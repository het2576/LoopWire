"""Embeddings for adaptive personalization (Phase B, prdv2.md).

Uses Gemini's embedding model, truncated to EMBEDDING_DIMENSIONS via the
API's native Matryoshka support (output_dimensionality) - smaller vectors
are cheaper to store and compare at this scale without a meaningful quality
loss, and there's no dedicated vector DB here (plain Postgres ARRAY column +
cosine similarity computed in Python, per prdv2.md B.2 - fine at this scale).
"""

import math

from google import genai
from google.genai import types

from app.config import get_settings
from app.models import EMBEDDING_DIMENSIONS

EMBEDDING_MODEL = "gemini-embedding-001"

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set - see SETUP.md")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def compute_embedding(text: str) -> list[float]:
    """Embeds a piece of text (an item's summary, or a static interest
    profile) into a fixed-size vector for cosine-similarity comparisons."""
    client = _get_client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            output_dimensionality=EMBEDDING_DIMENSIONS,
            task_type="SEMANTIC_SIMILARITY",
        ),
    )
    return list(response.embeddings[0].values)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
