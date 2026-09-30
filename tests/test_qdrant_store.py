from unittest.mock import patch
import pytest

from barq_ai_support.ingestion.qdrant_store import (
    generate_point_id,
    upsert_chunks,
)
from barq_ai_support.ingestion import embedding
from barq_ai_support.kb_sync_service import (
    _article_points_are_current,
    _delete_stale_points_for_article,
    _indexed_article_sys_ids,
)


def test_generate_point_id_is_deterministic():
    chunk = {
        "text": "Password is not working.",
        "metadata": {
            "sys_id": "article-001",
            "chunk_index": 0,
        },
    }

    first_id = generate_point_id(chunk)
    second_id = generate_point_id(chunk)

    assert first_id == second_id


def test_different_chunks_have_different_ids():
    chunk_1 = {
        "text": "Password is not working.",
        "metadata": {
            "sys_id": "article-001",
            "chunk_index": 0,
        },
    }

    chunk_2 = {
        "text": "Reset the password.",
        "metadata": {
            "sys_id": "article-001",
            "chunk_index": 1,
        },
    }

    assert generate_point_id(chunk_1) != generate_point_id(chunk_2)


def test_embedding_client_is_deferred_until_embedding_is_requested(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.setattr(embedding, "_client", None)

    with pytest.raises(RuntimeError, match="Configure GEMINI_API_KEY"):
        embedding.create_embedding("test text")


def test_kb_sync_marks_points_stale_when_embedding_provider_is_missing(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "https://proxy.example")
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    point = SimpleNamespace(payload={"text": "Article body"})
    monkeypatch.setattr(
        "barq_ai_support.kb_sync_service.qdrant_store.client.scroll",
        lambda **kwargs: ([point], None),
    )

    assert not _article_points_are_current("article-sys-id")


def test_indexed_article_sys_ids_collects_all_pages_and_deduplicates(monkeypatch):
    from types import SimpleNamespace

    pages = iter(
        [
            (
                [SimpleNamespace(payload={"sys_id": "article-a"})],
                "next-page",
            ),
            (
                [
                    SimpleNamespace(payload={"sys_id": "article-a"}),
                    SimpleNamespace(payload={"sys_id": "article-b"}),
                ],
                None,
            ),
        ]
    )
    monkeypatch.setattr(
        "barq_ai_support.kb_sync_service.qdrant_store.client.scroll",
        lambda **kwargs: next(pages),
    )

    assert _indexed_article_sys_ids() == ["article-a", "article-b"]


def test_kb_sync_deletes_stale_chunks_after_replacement(monkeypatch):
    from types import SimpleNamespace

    stale_point = SimpleNamespace(id="old-point")
    monkeypatch.setattr(
        "barq_ai_support.kb_sync_service.qdrant_store.client.scroll",
        lambda **kwargs: ([stale_point], None),
    )
    delete = patch(
        "barq_ai_support.kb_sync_service.qdrant_store.client.delete"
    )
    mocked_delete = delete.start()
    try:
        _delete_stale_points_for_article(
            "article-001",
            [{"metadata": {"sys_id": "article-001", "chunk_index": 0}}],
        )
    finally:
        delete.stop()

    assert mocked_delete.call_args.kwargs["points_selector"].points == ["old-point"]


@patch(
    "barq_ai_support.ingestion.qdrant_store.create_embedding"
)
@patch(
    "barq_ai_support.ingestion.qdrant_store.client.upsert"
)
def test_upsert_chunks(
    mock_upsert,
    mock_create_embedding,
):
    mock_create_embedding.return_value = [0.1] * 768

    chunks = [
        {
            "text": "Cause > Password is not working.",
            "metadata": {
                "sys_id": "article-001",
                "number": "KB001",
                "workflow_state": "published",
                "category": "Password",
                "heading_path": ["Cause"],
                "chunk_index": 0,
            },
        }
    ]

    upsert_chunks(chunks)

    mock_create_embedding.assert_called_once_with(
        "Cause > Password is not working."
    )

    mock_upsert.assert_called_once()

    call_kwargs = mock_upsert.call_args.kwargs

    assert call_kwargs["collection_name"] == "barq_kb_chunks"

    points = call_kwargs["points"]

    assert len(points) == 1

    assert len(points[0].vector) == 768

    assert points[0].payload["sys_id"] == "article-001"
    assert points[0].payload["number"] == "KB001"
    assert points[0].payload["workflow_state"] == "published"
    assert points[0].payload["category"] == "Password"
    assert points[0].payload["heading_path"] == ["Cause"]
    assert points[0].payload["chunk_index"] == 0
    assert points[0].payload["text"] == "Cause > Password is not working."
    assert "embedding_provider" in points[0].payload