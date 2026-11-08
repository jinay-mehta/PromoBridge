from __future__ import annotations

from functools import lru_cache
from typing import Sequence

import numpy as np


@lru_cache(maxsize=2)
def _load_model(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Optional package not installed. Run: pip install -r requirements-semantic.txt") from exc
    return SentenceTransformer(model_name)


def semantic_similarities(query: str, documents: Sequence[str], model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> list[float]:
    if not query or not documents:
        return [0.0] * len(documents)
    model = _load_model(model_name)
    vectors = model.encode([query, *documents], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    query_vector = vectors[0]
    scores = np.dot(vectors[1:], query_vector)
    return [float(max(0.0, min(1.0, (x + 1.0) / 2.0))) for x in scores]
