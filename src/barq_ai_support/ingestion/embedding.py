import os
import json
import urllib.request

from dotenv import load_dotenv
from google import genai

load_dotenv()

_client = None


def get_embedding_provider() -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini-direct:gemini-embedding-001"
    if os.environ.get("LITELLM_BASE_URL") and os.environ.get("LITELLM_API_KEY"):
        return "litellm:gemini/gemini-embedding-001"
    return "unconfigured"


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required for direct Gemini embedding ingestion."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def create_embedding(text: str) -> list[float]:
    if os.environ.get("GEMINI_API_KEY"):
        response = _get_client().models.embed_content(
            model="gemini-embedding-001",
            contents=text,
            config={"output_dimensionality": 768},
        )
        return response.embeddings[0].values

    base_url = os.environ.get("LITELLM_BASE_URL", "").strip()
    api_key = os.environ.get("LITELLM_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError(
            "Configure GEMINI_API_KEY or both LITELLM_BASE_URL and LITELLM_API_KEY "
            "to generate knowledge-base embeddings."
        )

    request_body = json.dumps(
        {
            "model": "gemini/gemini-embedding-001",
            "input": text,
            "dimensions": 768,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/embeddings",
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result["data"][0]["embedding"]


if __name__ == "__main__":
    vector = create_embedding(
        "How do I reset my ServiceNow password?"
    )

    print("Vector length:", len(vector))
    print("First 5 values:", vector[:5])