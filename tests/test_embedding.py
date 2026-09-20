from unittest.mock import MagicMock, patch

import barq_ai_support.ingestion.embedding as embedding_module
from barq_ai_support.ingestion.embedding import create_embedding


@patch("barq_ai_support.ingestion.embedding.get_client")
def test_create_embedding_returns_vector(mock_get_client):
    mock_response = MagicMock()
    mock_response.embeddings = [MagicMock(values=[0.1] * 768)]

    mock_client = MagicMock()
    mock_client.models.embed_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    vector = create_embedding("How do I reset my password?")

    assert vector == [0.1] * 768

    mock_client.models.embed_content.assert_called_once_with(
        model="gemini-embedding-001",
        contents="How do I reset my password?",
        config={"output_dimensionality": 768},
    )


@patch("barq_ai_support.ingestion.embedding.genai.Client")
def test_get_client_is_created_once_and_cached(mock_genai_client):
    # Reset the module-level cache so this test doesn't depend
    # on ordering with other tests.
    embedding_module._client = None

    mock_genai_client.return_value = MagicMock()

    first = embedding_module.get_client()
    second = embedding_module.get_client()

    assert first is second
    mock_genai_client.assert_called_once()

    embedding_module._client = None
