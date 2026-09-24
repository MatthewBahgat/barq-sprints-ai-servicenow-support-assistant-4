"""
S3.6 — Celery application wiring.

STUB NOTICE: the real task body (claim the incident via Table API PATCH,
then hand off to the ReAct agent) belongs to teammates' branches (the
FastAPI receiver + Celery consumer task, and the Celery worker + agent
task) that aren't merged yet. This file wires up a real, connected Celery
app so `docker-compose.yml`'s worker service has something to actually
start and consume from, and defines one placeholder task with the name
and payload shape the real consumer is expected to enqueue against.

Swap `process_incident_event`'s body for the real claim + agent hand-off
once those branches land; the task name is the seam other services call
against, so nothing else needs to change.
"""

from celery import Celery

from .config import settings

celery_app = Celery(
    "barq_ai_support",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="barq_ai_support.process_incident_event")
def process_incident_event(incident_payload: dict) -> dict:
    """STUB — see module docstring. Logs receipt; does not claim or process."""
    number = incident_payload.get("number", "?")
    print(f"[STUB worker] received incident {number} — real claim/agent hand-off not yet wired.")
    return {"number": number, "status": "stub_not_implemented"}
