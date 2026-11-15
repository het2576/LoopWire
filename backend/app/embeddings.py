"""Embeddings for personalization.

gemini-embedding-001 truncated to EMBEDDING_DIMENSIONS via its Matryoshka
output_dimensionality. Truncated Matryoshka vectors are NOT unit-norm, so
cosine (not raw dot product) is used everywhere. Vectors live in a Postgres
float array; cosine is computed with numpy - fine for a personal library of
thousands of items (a 1k x 768 matrix is ~3MB and scores in well under 1ms).
"""

import numpy as np

from app.llm import embed
from app.models import EMBEDDING_DIMENSIONS

EMBEDDING_MODEL = "gemini-embedding-001"


def compute_embedding(text: str) -> list[float]:
    return embed(text, task_type="SEMANTIC_SIMILARITY", dimensions=EMBEDDING_DIMENSIONS, model=EMBEDDING_MODEL)


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    if a is None or b is None or len(a) == 0 or len(a) != len(b):
        return 0.0
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))
