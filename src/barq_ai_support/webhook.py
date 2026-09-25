"""
S1.4 — ServiceNow Business Rule webhook receiver.

Moved here from the old root-level main.py so the webhook and the
knowledge-base endpoints live in ONE FastAPI app instead of two
disconnected ones.

Also fixes a real gap found during review: the Business Rule
(businessRule/business_rule.js) sends an "X-ServiceNow-Secret" header,
but the original webhook never checked it. Anyone who found the ngrok
URL could POST fake incidents. This version validates that header.

S3.6 UPDATE: handle_event() now enqueues the real Celery task instead of
just printing. This is a stub standing in for the real FastAPI receiver +
Redis dedup + Celery consumer task (a teammate's not-yet-merged branch,
which also owns claiming the incident via ai_status=in_progress before
this point). No dedup gate here yet -- every webhook call enqueues a new
task. Swap this for the real dedup+claim consumer once that branch
lands; the Celery task name/payload shape is the seam.
"""

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

from .celery_app import process_incident_event
from .config import settings

router = APIRouter()


class IncidentEvent(BaseModel):
    incident_sys_id: str
    number: str
    short_description: str
    description: str | None = ""


def _verify_webhook_secret(x_servicenow_secret: str | None) -> None:
    """Reject the request if the shared secret header is missing or wrong."""
    if not settings.servicenow_webhook_secret:
        # No secret configured yet — fail closed rather than silently open.
        raise HTTPException(
            status_code=500,
            detail="SERVICENOW_WEBHOOK_SECRET is not configured on the server.",
        )
    if x_servicenow_secret != settings.servicenow_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret.")


@router.post("/webhook", status_code=202)
async def webhook(
    payload: IncidentEvent,
    background_tasks: BackgroundTasks,
    x_servicenow_secret: str | None = Header(default=None),
):
    _verify_webhook_secret(x_servicenow_secret)

    print(f"Received event for {payload.number} (sys_id: {payload.incident_sys_id})")
    background_tasks.add_task(handle_event, payload)
    return {"status": "accepted", "number": payload.number}


def handle_event(payload: IncidentEvent) -> None:
    # STUB (see module docstring): enqueues the Celery task directly, no
    # dedup gate, no claim PATCH. Real receiver logic is a teammate's task.
    task = process_incident_event.delay(payload.model_dump())
    print(f"Enqueued Celery task {task.id} for {payload.number}: {payload.short_description}")
