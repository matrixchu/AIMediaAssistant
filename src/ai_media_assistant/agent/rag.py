"""Retrieval-Augmented Generation (RAG) building blocks.

A small, dependency-light vector index over media knowledge. It uses the
configured embeddings (Ollama / OpenAI / offline hashing fallback) and cosine
similarity, so retrieval works in any environment. A Chroma-backed index can be
swapped in via :func:`build_chroma_index` when persistence is desired.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.documents import Document

from ..shared.config import get_settings
from ..shared.logging import get_logger
from .embeddings import get_embeddings

logger = get_logger(__name__)


@dataclass
class ScoredDocument:
    document: Document
    score: float


class SimpleVectorIndex:
    """In-memory cosine-similarity vector index."""

    def __init__(self) -> None:
        self._embeddings = get_embeddings()
        self._docs: list[Document] = []
        self._vectors: list[list[float]] = []

    def add(self, documents: list[Document]) -> None:
        if not documents:
            return
        vectors = self._embeddings.embed_documents([d.page_content for d in documents])
        self._docs.extend(documents)
        self._vectors.extend(vectors)

    def similarity_search(self, query: str, k: int = 5) -> list[ScoredDocument]:
        if not self._docs:
            return []
        q = self._embeddings.embed_query(query)
        scored = [
            ScoredDocument(doc, _cosine(q, vec))
            for doc, vec in zip(self._docs, self._vectors)
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self._docs)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)


def build_chroma_index(documents: list[Document]):  # pragma: no cover - optional path
    """Build a persistent Chroma vector store (optional)."""
    from langchain_chroma import Chroma

    settings = get_settings()
    store = Chroma(
        collection_name="media_knowledge",
        embedding_function=get_embeddings(),
        persist_directory=str(settings.vector_store_path),
    )
    if documents:
        store.add_documents(documents)
    return store
