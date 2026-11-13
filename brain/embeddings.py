"""384-dimensional local embedding generator using all-MiniLM-L6-v2."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from functools import lru_cache
from typing import Protocol

EMBEDDING_DIM = 384
DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Protocol for text-to-384-dim vector embedders."""

    def embed(self, text: str) -> list[float]:
        ...


class SentenceTransformerEmbedder:
    """Local MiniLM-L6-v2 embedder via sentence-transformers."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        vec = self._model.encode(
            text or "",
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [float(x) for x in vec.tolist()]


class HashingFallbackEmbedder:
    """Deterministic 384-dim token/trigram projection for offline/lightweight tests."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        normalized = (text or "").lower()
        tokens = re.findall(r"[a-z0-9_]+", normalized)
        features: list[tuple[str, float]] = []
        for tok in tokens:
            features.append((f"w:{tok}", 2.0))
            if len(tok) >= 3:
                for idx in range(len(tok) - 2):
                    features.append((f"c:{tok[idx:idx + 3]}", 0.5))

        if not features:
            return vec

        for feat, weight in features:
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self._dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[bucket] += sign * weight

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        return vec


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Return the configured embedder (defaults to all-MiniLM-L6-v2 with safe fallback)."""
    backend = os.environ.get("KNOWLEDGE_BRAIN_EMBEDDING_BACKEND", "auto").lower()
    if backend == "hash":
        return HashingFallbackEmbedder()

    model_name = os.environ.get("KNOWLEDGE_BRAIN_EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
    try:
        return SentenceTransformerEmbedder(model_name=model_name)
    except Exception as exc:
        if backend == "sentence_transformers":
            raise
        logger.warning(
            "Falling back to HashingFallbackEmbedder because %s could not load: %s",
            model_name,
            exc,
        )
        return HashingFallbackEmbedder()


def embed_text(text: str) -> list[float]:
    """Generate a normalized 384-dim float vector for the given text."""
    return get_embedder().embed(text)
