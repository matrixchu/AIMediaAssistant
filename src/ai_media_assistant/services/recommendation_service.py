"""Recommendation service — RAG over media knowledge + recent resources.

Pipeline (Retrieval-Augmented Generation):
    1. Build a corpus from cached PT resources + a curated media knowledge base.
    2. Embed and index the corpus (vector store).
    3. Retrieve the most relevant entries for the user's query + preferences.
    4. Ask the LLM to synthesise a recommendation list grounded in the retrieved
       context. If the LLM is unavailable, fall back to the ranked retrieval.
"""

from __future__ import annotations

import json
import re
from time import monotonic

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from ..agent.memory import AgentMemoryStore
from ..agent.rag import SimpleVectorIndex
from ..database import session_scope
from ..database import repositories as repo
from ..shared.logging import get_logger
from ..shared.schemas import RecommendationDTO, TorrentResourceDTO
from .search_service import SearchService

logger = get_logger(__name__)

class RecommendationService:
    """Generate personalised media recommendations using RAG."""

    def __init__(self) -> None:
        self._memory = AgentMemoryStore()
        self._search = SearchService()
        self._index_cache: SimpleVectorIndex | None = None
        self._index_cache_at = 0.0
        self._index_cache_ttl_seconds = 30.0

    def recommend(self, query: str = "", k: int = 5) -> list[RecommendationDTO]:
        # Fast path: when the user is asking "what can I download", return
        # a live PT resource list (with ids) instead of content-style recs.
        if _is_download_listing_query(query):
            return self._recommend_downloadable_resources(query, k=k)

        index = self._get_cached_index()
        prefs = self._memory.get_preferences()
        enriched_query = self._build_query(query, prefs)
        retrieved = index.similarity_search(enriched_query, k=k)
        context = [s.document for s in retrieved]

        recommendations = self._synthesize(enriched_query, context)
        if recommendations:
            return recommendations

        # Fallback: turn retrieved docs directly into recommendations.
        return [
            RecommendationDTO(
                title=doc.metadata.get("title", "Unknown"),
                reason=doc.page_content,
                score=round(s.score, 3),
            )
            for s, doc in zip(retrieved, context)
        ]

    def _recommend_downloadable_resources(self, query: str, k: int) -> list[RecommendationDTO]:
        keyword = _extract_listing_keyword(query)
        result = self._search.search(keyword, limit=max(k, 5))
        return [
            RecommendationDTO(
                title=r.title,
                reason=(
                    f"实时 PT 可下载资源（id={r.id}, "
                    f"resolution={r.resolution or 'N/A'}, quality={r.quality or 'N/A'}, "
                    f"size={r.size_gb}GB, seeders={r.seeders}）"
                ),
                score=_download_score(r),
                resource=r,
            )
            for r in result.resources[:k]
        ]

    def _get_cached_index(self) -> SimpleVectorIndex:
        now = monotonic()
        if self._index_cache is not None and (now - self._index_cache_at) <= self._index_cache_ttl_seconds:
            return self._index_cache
        index = self._build_index()
        self._index_cache = index
        self._index_cache_at = now
        return index

    # ------------------------------------------------------------------ #
    def _build_index(self) -> SimpleVectorIndex:
        index = SimpleVectorIndex()
        docs: list[Document] = []
        with session_scope() as session:
            for res in repo.list_recent_resources(session, limit=100):
                docs.append(
                    Document(
                        page_content=(
                            f"{res.title} ({res.category or 'uncategorized'}) "
                            f"{res.resolution or ''} {res.quality or ''}"
                        ),
                        metadata={
                            "title": res.title,
                            "genre": (res.category or "").lower(),
                            "source": "catalog",
                            "resource_id": res.id,
                        },
                    )
                )
        index.add(docs)
        catalog_count = len(docs)
        logger.info("Recommendation RAG index built from %d cached resources", catalog_count)
        return index

    def _build_query(self, query: str, prefs: dict[str, str]) -> str:
        parts = [query] if query else []
        if genre := prefs.get("favorite_genre"):
            parts.append(f"genre {genre}")
        if res := prefs.get("preferred_resolution"):
            parts.append(res)
        return " ".join(parts) or "popular highly rated movies"

    def _synthesize(self, query: str, context: list[Document]) -> list[RecommendationDTO]:
        if not context:
            return []
        try:
            from ..agent.llm import get_llm

            llm = get_llm()
            context_text = "\n".join(f"- {d.page_content}" for d in context)
            system = SystemMessage(
                content=(
                    "You are a media recommendation assistant. Recommend titles ONLY "
                    "from the provided context. Respond with a JSON array of objects "
                    "with keys: title, reason, score (0-1). No prose outside JSON."
                )
            )
            human = HumanMessage(content=f"User request: {query}\n\nContext:\n{context_text}")
            reply = llm.invoke([system, human])
            data = json.loads(_extract_json(reply.content))
            return [
                RecommendationDTO(
                    title=item["title"],
                    reason=item.get("reason", ""),
                    score=float(item.get("score", 0.0)),
                )
                for item in data
            ]
        except Exception as exc:  # noqa: BLE001 - fall back gracefully when no LLM
            logger.info("LLM synthesis unavailable (%s); using retrieval fallback.", exc)
            return []


def _extract_json(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    return text[start : end + 1] if start != -1 and end != -1 else "[]"


def _is_download_listing_query(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    low = q.lower()
    has_resource = any(t in q for t in ("资源", "版本", "清单")) or "resource" in low
    has_download = any(t in q for t in ("下载", "可下", "可下载")) or "download" in low
    has_listing = any(t in q for t in ("有哪些", "有什么", "哪些", "有啥")) or "what" in low
    return has_resource and (has_download or has_listing)


def _extract_listing_keyword(query: str) -> str:
    cleaned = query
    phrases = [
        "有哪些资源可以下载",
        "有哪些资源可下载",
        "有什么资源可以下载",
        "有什么资源可下载",
        "这个综艺",
        "这个电影",
        "这个剧",
        "这个节目",
        "有哪些资源",
        "有什么资源",
        "可以下载",
        "可下载",
        "下载资源",
        "资源清单",
        "资源",
        "版本",
        "请帮我",
        "帮我",
        "请",
    ]
    for phrase in phrases:
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"[？?，,。.!！:：;；\n\t]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or query.strip()


def _download_score(resource: TorrentResourceDTO) -> float:
    # Keep score bounded to [0, 1] while heavily rewarding active seeders.
    score = min(resource.seeders / 100.0, 1.0)
    if (resource.resolution or "").upper() == "2160P":
        score = min(score + 0.1, 1.0)
    if (resource.quality or "").upper() == "REMUX":
        score = min(score + 0.1, 1.0)
    return round(score, 3)
