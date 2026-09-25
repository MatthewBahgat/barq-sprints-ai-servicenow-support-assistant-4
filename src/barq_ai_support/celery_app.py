"""
S3.6 — Celery application wiring.

STUB NOTICE: the real task body (claim the incident via Table API PATCH,
then run the ReAct agent loop over searchKB/addWorkNote/suggestAnswer/
requestHR) belongs to teammates' branches (the FastAPI receiver + Celery
consumer task, and the Celery worker + agent task) that aren't merged
yet. This version does real, meaningful work in the meantime so the
S3.6 "live end-to-end run" demo evidence is genuine rather than a bare
log line:

  1. incident fetch  -- STUB: uses the payload already sent by the
     webhook (real fetch is an authenticated Table API GET, owned by
     the not-yet-merged worker branch)
  2. retrieval        -- REAL: calls the actual retriever against Qdrant
  3. model/decision    -- STUB: threshold-gate, same logic as
     benchmark/pipeline_benchmark.py's stub_pipeline_agent, standing in
     for the real ReAct agent
  4. writeback         -- STUB: logs the exact PATCH payload that would
     be sent to ServiceNow. Field names below (ai_status, etc.) are
     PLACEHOLDERS -- the real scoped-app field names (e.g.
     x_<scope>_ai_status) come from the ServiceNow-side task (S3.1) and
     must be substituted before this can call the real Table API.

Swap each stubbed step for the real implementation as the corresponding
branch lands; the task name and payload shape are the seam other
services (the webhook) call against, so nothing else needs to change.
"""

import os

from celery import Celery

from .config import settings
from .retrieval.retriever import default_embedding_fn, gemini_embedding_fn, retrieve

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


def _litellm_proxy_embedding_fn(text: str) -> list[float]:
    """Real Gemini embeddings via the team's LiteLLM proxy (768-dim).
    Mirrors benchmark/run_benchmark.py's version; kept separate so the
    worker doesn't import a benchmark script into production code."""
    import json as _json
    import urllib.request as _urlreq

    base = os.environ.get("LITELLM_BASE_URL", "")
    key = os.environ.get("LITELLM_API_KEY", "")
    body = _json.dumps(
        {"model": "gemini/gemini-embedding-001", "input": text, "dimensions": 768}
    ).encode("utf-8")
    req = _urlreq.Request(
        base.rstrip("/") + "/embeddings",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with _urlreq.urlopen(req, timeout=120) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    return data["data"][0]["embedding"]


def _select_embedding_fn():
    """Same precedence as the benchmark harness: real Gemini key first,
    then the LiteLLM proxy, then the offline stub as a last resort."""
    if os.environ.get("GEMINI_API_KEY"):
        return gemini_embedding_fn
    if os.environ.get("LITELLM_BASE_URL") and os.environ.get("LITELLM_API_KEY"):
        return _litellm_proxy_embedding_fn
    return default_embedding_fn


@celery_app.task(name="barq_ai_support.process_incident_event")
def process_incident_event(incident_payload: dict) -> dict:
    number = incident_payload.get("number", "?")

    # --- step 1: fetch (STUB — see module docstring) ---
    short_description = incident_payload.get("short_description", "")
    description = incident_payload.get("description", "") or ""
    query = f"{short_description}\n{description}".strip()
    print(f"[worker] {number}: fetch (stub) — using payload already in hand")

    # --- step 2: retrieval (REAL) ---
    embedding_fn = _select_embedding_fn()
    result = retrieve(
        query=query,
        top_k=settings.retrieval_top_k,
        score_threshold=0.0,
        category=None,
        embedding_fn=embedding_fn,
    )
    retrieved = [c.article_number for c in result.chunks]
    best_score = result.best_score if result.best_score is not None else 0.0
    print(f"[worker] {number}: retrieval — top {len(retrieved)} articles {retrieved}, best_score={best_score:.4f}")

    # --- step 3: model/decision (STUB threshold gate) ---
    threshold = settings.retrieval_score_threshold
    outcome = "suggested" if (result.chunks and best_score >= threshold) else "escalated"
    print(f"[worker] {number}: decision (stub) — outcome={outcome}, confidence={best_score:.4f}")

    # --- step 4: writeback (STUB — placeholder field names, no real PATCH) ---
    writeback_payload = {
        "ai_status": outcome,  # PLACEHOLDER field name — real name pending S3.1 scoped fields
        "ai_suggested_response": retrieved if outcome == "suggested" else None,
        "ai_confidence": best_score,
        "human_review_required": True,
        "ai_processed": True,
    }
    print(f"[worker] {number}: writeback (stub, NOT sent to ServiceNow) — payload={writeback_payload}")

    return {
        "number": number,
        "outcome": outcome,
        "confidence": best_score,
        "matched_article_numbers": retrieved,
        "writeback_payload": writeback_payload,
    }
