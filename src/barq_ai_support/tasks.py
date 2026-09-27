"""
S3.3/S3.6 — Celery tasks. All ServiceNow API calls happen here, never on the
FastAPI request thread.

servicenow_client's methods are async (httpx.AsyncClient), but Celery tasks
run synchronously by default, so we bridge with asyncio.run().
"""
import asyncio

from .celery_app import celery_app
from .servicenow_client import ServiceNowClient
from .kb_sync_service import sync_article
from .agent.s3_worker import process_incident_event as run_real_agent


async def _claim_and_run_agent(sys_id: str) -> dict:
    """
    Claim the incident (S3.3), then hand it to the real S3.4 ReAct agent.
    Both run under one event loop so the LLM/HTTP clients created inside
    the agent stay valid for their full lifetime.
    """
    client = ServiceNowClient()

    await client.claim_incident(sys_id, status_value="in_progress")

    return await run_real_agent(
        {"sys_id": sys_id},
        sn_client=client,
    )


@celery_app.task(name="process_incident", bind=True, max_retries=3, default_retry_delay=10)
def process_incident(self, incident_payload: dict) -> dict:
    """
    Entry point for a first-seen incident event.
      1. Claim the incident in ServiceNow (PATCH ai_status=in_progress).
      2. Run the real S3.4 agent (searchKB / addWorkNote / suggestAnswer / requestHR).
    """
    sys_id = incident_payload.get("incident_sys_id")
    if not sys_id:
        print(f"process_incident called without incident_sys_id: {incident_payload}")
        return {"status": "error", "reason": "missing incident_sys_id"}

    try:
        result = asyncio.run(_claim_and_run_agent(sys_id))
    except Exception as exc:  # noqa: BLE001 - retry on any transient failure
        print(f"process_incident failed for {sys_id}, retrying: {exc}")
        raise self.retry(exc=exc)

    print(f"Processed incident {sys_id}: {result.get('status', 'unknown')}")
    return result


@celery_app.task(name="process_kb_event", bind=True, max_retries=3, default_retry_delay=10)
def process_kb_event(self, sys_id: str, operation: str) -> dict:
    """
    Entry point for a KB change event (insert/update/delete on kb_knowledge).
    Runs the diff-and-sync logic against Qdrant, never on the request thread.
    """
    try:
        result = sync_article(sys_id, operation)
    except Exception as exc:  # noqa: BLE001 - retry on any transient failure
        print(f"KB sync failed for sys_id={sys_id}, retrying: {exc}")
        raise self.retry(exc=exc)

    print(f"KB sync complete for sys_id={sys_id}: {result}")
    return result