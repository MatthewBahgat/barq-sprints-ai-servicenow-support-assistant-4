"""
S3.6 — Distributed tracing via Langfuse.

Provides `traced_incident_run()`: wraps one incident's handling in a
single Langfuse trace containing four child spans, matching the sprint
spec's required shape exactly: incident fetch, retrieval, model call,
writeback.

STUB NOTICE: the fetch and writeback spans are stubs. The real Table API
fetch belongs to the Celery worker task (teammate branch, not merged),
and the real ServiceNow writeback PATCH isn't implemented anywhere yet
either. Both spans are still real, meaningful trace entries -- they log
exactly what the real call's input/output would look like -- they just
don't make a network call. The retrieval span calls the REAL retrieval
code (retriever.retrieve) against the live Qdrant collection. Swap the
fetch/writeback span bodies for real API calls once available; the span
names and structure are the seam -- nothing else needs to change.

Requires LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST in
.env (see .env.example). If unset, get_langfuse_client() will construct
a client that fails silently on flush -- check your Langfuse project's
Traces tab if nothing shows up.
"""

from __future__ import annotations

from typing import Any, Callable

from langfuse import Langfuse

from .config import settings

_langfuse: Langfuse | None = None


def get_langfuse_client() -> Langfuse:
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse


def traced_incident_run(
    incident: dict[str, Any],
    query: str,
    category: str | None,
    retrieve_fn: Callable[..., Any],
    decide_fn: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    """
    Run one incident through fetch -> retrieval -> model -> writeback,
    all nested under a single trace named after the incident number.

    retrieve_fn(query, category) -> RetrievalResult (e.g. retriever.retrieve)
    decide_fn(RetrievalResult) -> dict with at least {"outcome", "confidence"}
    """
    lf = get_langfuse_client()
    number = incident.get("number", "UNKNOWN")

    with lf.start_as_current_observation(
        name=f"incident-run-{number}", as_type="chain", input=incident
    ) as trace:

        # --- span 1: incident fetch (STUB) ---
        with lf.start_as_current_observation(
            name="incident-fetch", as_type="tool", input={"number": number}
        ) as fetch_span:
            # STUB: real fetch is an authenticated Table API GET owned by
            # the Celery worker task. The incident is already in hand
            # here (benchmark dataset / demo payload), so this span
            # documents the step's shape without a real network call.
            fetch_span.update(output=incident)

        # --- span 2: retrieval (REAL) ---
        with lf.start_as_current_observation(
            name="kb-retrieval",
            as_type="retriever",
            input={"query": query, "category": category},
        ) as retrieval_span:
            result = retrieve_fn(query=query, category=category)
            retrieval_span.update(
                output={
                    "retrieved_articles": [c.article_number for c in result.chunks],
                    "best_score": result.best_score,
                }
            )

        # --- span 3: model / agent decision ---
        with lf.start_as_current_observation(
            name="agent-decision",
            as_type="generation",
            model="stub-threshold-gate",
            input={"retrieved_articles": [c.article_number for c in result.chunks]},
        ) as model_span:
            decision = decide_fn(result)
            model_span.update(output=decision)

        # --- span 4: writeback (STUB) ---
        writeback_payload = {
            "ai_status": decision["outcome"],
            "ai_confidence": decision["confidence"],
            "human_review_required": True,
            "ai_processed": True,
        }
        with lf.start_as_current_observation(
            name="servicenow-writeback",
            as_type="tool",
            input={"incident_number": number, "fields": writeback_payload},
        ) as writeback_span:
            # STUB: real writeback is an authenticated Table API PATCH
            # scoped to the AI fields (ai_status, ai_suggested_response,
            # ai_confidence, human_review_required, ai_processed), per
            # the sprint spec. Not implemented anywhere yet -- this span
            # logs the exact payload shape that call will send.
            writeback_span.update(output=writeback_payload)

        trace.update(output=decision)

    lf.flush()
    return decision
