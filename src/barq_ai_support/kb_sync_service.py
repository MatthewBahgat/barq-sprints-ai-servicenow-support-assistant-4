"""
S3.3 — KB sync orchestration. Implements all four sync paths, reusing the
existing chunker/embedding/qdrant_store code from Sprint 2 rather than
duplicating it.

Also runnable standalone for a single article:
    uv run python -m src.barq_ai_support.kb_sync_service <sys_id> <insert|update|delete>
"""
import asyncio
import hashlib
import json
import sys

from qdrant_client.models import Filter, FieldCondition, MatchValue, PointIdsList

from .ingestion.chunker import chunk_article
from .ingestion import qdrant_store  # reuse client, COLLECTION_NAME, generate_point_id, upsert_chunks
from .ingestion.embedding import get_embedding_provider
from .servicenow_client import ServiceNowClient
from . import kb_state_store as state_store


def _hash_body(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _article_filter(sys_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="sys_id", match=MatchValue(value=sys_id))])


def _ensure_sys_id_index() -> None:
    """
    Qdrant requires a payload index before filtering by a field. Idempotent —
    safe to call on every sync, only actually creates the index once.
    """
    try:
        qdrant_store.client.create_payload_index(
            collection_name=qdrant_store.COLLECTION_NAME,
            field_name="sys_id",
            field_schema="keyword",
        )
    except Exception:
        pass  # index already exists — safe to ignore


def _delete_points_for_article(sys_id: str) -> None:
    qdrant_store.client.delete(
        collection_name=qdrant_store.COLLECTION_NAME,
        points_selector=_article_filter(sys_id),
    )


def _delete_stale_points_for_article(sys_id: str, chunks: list[dict]) -> None:
    """Remove old chunk IDs only after replacement chunks were upserted."""
    current_ids = {
        qdrant_store.generate_point_id(chunk)
        for chunk in chunks
    }
    stale_ids = []
    offset = None

    while True:
        points, offset = qdrant_store.client.scroll(
            collection_name=qdrant_store.COLLECTION_NAME,
            scroll_filter=_article_filter(sys_id),
            limit=100,
            offset=offset,
            with_payload=["sys_id"],
        )
        stale_ids.extend(point.id for point in points if str(point.id) not in current_ids)
        if offset is None:
            break

    if stale_ids:
        qdrant_store.client.delete(
            collection_name=qdrant_store.COLLECTION_NAME,
            points_selector=PointIdsList(points=stale_ids),
        )


def _article_points_are_current(sys_id: str) -> bool:
    """Return whether all stored chunks have text and use the active embedder."""
    offset = None
    found_points = False

    while True:
        points, offset = qdrant_store.client.scroll(
            collection_name=qdrant_store.COLLECTION_NAME,
            scroll_filter=_article_filter(sys_id),
            limit=100,
            offset=offset,
            with_payload=["text", "embedding_provider"],
        )
        if not points:
            return found_points

        found_points = True
        if any(
            not point.payload
            or not point.payload.get("text")
            or point.payload.get("embedding_provider") != get_embedding_provider()
            for point in points
        ):
            return False
        if offset is None:
            return True


def _indexed_article_sys_ids() -> list[str]:
    """Collect distinct ServiceNow article IDs from every Qdrant page."""
    sys_ids: set[str] = set()
    offset = None

    while True:
        points, offset = qdrant_store.client.scroll(
            collection_name=qdrant_store.COLLECTION_NAME,
            limit=100,
            offset=offset,
            with_payload=["sys_id"],
        )
        sys_ids.update(
            point.payload["sys_id"]
            for point in points
            if point.payload and point.payload.get("sys_id")
        )
        if offset is None:
            return sorted(sys_ids)


def _patch_metadata_only(sys_id: str, metadata: dict) -> None:
    """Path 3: update payload fields on existing points, no embedding calls."""
    patch_fields = {
        "short_description": state_store._flatten(metadata.get("short_description")),
        "kb_category": state_store._flatten(metadata.get("kb_category")),
        "workflow_state": state_store._flatten(metadata.get("workflow_state")),
    }
    qdrant_store.client.set_payload(
        collection_name=qdrant_store.COLLECTION_NAME,
        payload=patch_fields,
        points=_article_filter(sys_id),
    )

def sync_article(sys_id: str, operation: str) -> dict:
    state_store.init_db()
    qdrant_store.create_collection()
    _ensure_sys_id_index()

    if operation == "delete":
        _delete_points_for_article(sys_id)
        state_store.delete_article_state(sys_id)
        return {"sys_id": sys_id, "action": "deleted"}
    
    # insert or update: pull full current article via Table API
    client = ServiceNowClient()
    article = asyncio.run(client.get_kb_article(sys_id))

    body = article.get("text", "")
    new_hash = _hash_body(body)
    existing = state_store.get_article_state(sys_id)

    body_changed = existing is None or existing.body_hash != new_hash
    chunks_are_current = True if body_changed else _article_points_are_current(sys_id)

    if body_changed or not chunks_are_current:
        chunks = chunk_article(article, chunk_size=1000, overlap=100)
        if not qdrant_store.upsert_chunks(chunks):
            return {
                "sys_id": sys_id,
                "status": "error",
                "error": "Embedding failed; retry the article sync.",
            }
        _delete_stale_points_for_article(sys_id, chunks)
        state_store.upsert_article_state(sys_id, new_hash, article)
        action = "re_embedded" if body_changed else "re_embedded_stale_embeddings"
        return {"sys_id": sys_id, "action": action, "chunk_count": len(chunks)}

    # Body unchanged — check if metadata actually differs
    metadata_changed = (
        existing.short_description != article.get("short_description")
        or existing.kb_category != article.get("kb_category")
        or existing.workflow_state != article.get("workflow_state")
    )

    if metadata_changed:
        # Path 3: metadata-only -> patch payloads, no embedding calls
        _patch_metadata_only(sys_id, article)
        state_store.upsert_article_state(sys_id, new_hash, article)
        return {"sys_id": sys_id, "action": "metadata_patched"}

    # Path 4: unchanged -> no-op
    return {"sys_id": sys_id, "action": "skipped_unchanged"}


def reindex_all_indexed_articles() -> dict:
    """Re-sync every distinct article currently represented in Qdrant."""
    qdrant_store.create_collection()
    _ensure_sys_id_index()
    sys_ids = _indexed_article_sys_ids()
    failures = []
    reembedded = 0
    skipped = 0

    for index, sys_id in enumerate(sys_ids, start=1):
        print(f"Reindexing article {index}/{len(sys_ids)}: {sys_id}")
        try:
            result = sync_article(sys_id, "update")
        except Exception as error:
            failures.append({"sys_id": sys_id, "error": str(error)})
            print(f"Failed article {sys_id}: {error}")
            continue

        if result.get("status") == "error":
            failures.append({"sys_id": sys_id, "error": result["error"]})
        elif result.get("action", "").startswith("re_embedded"):
            reembedded += 1
        else:
            skipped += 1

    return {
        "total": len(sys_ids),
        "reembedded": reembedded,
        "skipped": skipped,
        "failed": len(failures),
        "failures": failures,
    }


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--reindex-all":
        summary = reindex_all_indexed_articles()
        print(json.dumps(summary, indent=2))
        sys.exit(1 if summary["failed"] else 0)

    if len(sys.argv) != 3 or sys.argv[2] not in ("insert", "update", "delete"):
        print(
            "Usage: uv run python -m src.barq_ai_support.kb_sync_service "
            "<sys_id> <insert|update|delete> | --reindex-all"
        )
        sys.exit(1)

    result = sync_article(sys.argv[1], sys.argv[2])
    print(result)