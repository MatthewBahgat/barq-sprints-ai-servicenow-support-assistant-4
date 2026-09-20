import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

_client = None


def get_client() -> genai.Client:
    """
    Lazily create the Gemini client on first use, so importing
    this module doesn't require GEMINI_API_KEY to already be set.
    """

    global _client

    if _client is None:
        _client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"]
        )

    return _client


def create_embedding(text: str) -> list[float]:
    response = get_client().models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config={
            "output_dimensionality": 768,
        },
    )

    return response.embeddings[0].values


if __name__ == "__main__":
    vector = create_embedding(
        "How do I reset my ServiceNow password?"
    )

    print("Vector length:", len(vector))
    print("First 5 values:", vector[:5])