"""Embeddings provider factory with an offline deterministic fallback.

The fallback embedding hashes token n-grams into a fixed-size vector. It needs
no model download or network access, so RAG features run in any environment
(CI, tests, air-gapped) while still giving useful lexical similarity.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from ..shared.config import get_settings
from ..shared.logging import get_logger

logger = get_logger(__name__)

_DIM = 256
_TOKEN = re.compile(r"[a-z0-9\u4e00-\u9fff]+")


class HashingEmbeddings(Embeddings):
    """Deterministic, dependency-free embedding using the hashing trick."""

    def __init__(self, dim: int = _DIM) -> None:
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN.findall(text.lower())
        # Unigrams + bigrams for a little word-order sensitivity.
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for gram in grams:
            h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@lru_cache
def get_embeddings() -> Embeddings:
    settings = get_settings()
    provider = settings.embed_provider.lower()

    if provider == "ollama":
        try:
            from langchain_ollama import OllamaEmbeddings

            logger.info("Using Ollama embeddings: %s", settings.embed_model)
            return OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_base_url)
        except Exception as exc:  # noqa: BLE001 - graceful fallback
            logger.warning("Ollama embeddings unavailable (%s); using fallback.", exc)

    elif provider == "openai" and settings.openai_api_key:
        from langchain_openai import OpenAIEmbeddings

        logger.info("Using OpenAI embeddings")
        return OpenAIEmbeddings(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    logger.info("Using deterministic hashing embeddings (offline).")
    return HashingEmbeddings()
