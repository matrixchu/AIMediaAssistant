"""Search service — queries PT sites, caches resources, applies preferences."""

from __future__ import annotations

import re
from time import monotonic

from ..clients.pt import get_pt_client
from ..clients.pt.web import WebPTSearchClient
from ..database import session_scope
from ..database import repositories as repo
from ..shared.logging import get_logger
from ..shared.schemas import SearchQuery, SearchResult, TorrentResourceDTO

logger = get_logger(__name__)

# Ranking weights for resolution / quality preferences.
_RESOLUTION_RANK = {"2160P": 4, "1080P": 3, "720P": 2, "480P": 1}
_QUALITY_RANK = {"REMUX": 5, "BLURAY": 4, "WEB-DL": 3, "WEBRIP": 2, "HDTV": 1}
_CATEGORY_ALIAS = {
    "movie": "movie",
    "电影": "movie",
    "film": "movie",
    "tv": "tv",
    "series": "tv",
    "show": "tv",
    "剧集": "tv",
    "电视剧": "tv",
    "综艺": "tv",
    "anime": "anime",
    "动画": "anime",
    "documentary": "documentary",
    "纪录片": "documentary",
    "纪录": "documentary",
    "music": "music",
    "音乐": "music",
}


class SearchService:
    """Search for media resources and persist them for later download."""

    def __init__(self) -> None:
        self._pt_client = None
        self._pt_web_client = WebPTSearchClient()
        # Cache repeated identical queries in short windows. This reduces model
        # re-tries and repeated planner calls from hammering the PT backend.
        self._search_cache: dict[tuple[str, int], tuple[float, SearchResult]] = {}
        self._search_cache_ttl_seconds = 20.0
        self._pref_cache: dict[str, str] | None = None
        self._pref_cache_at = 0.0
        self._pref_cache_ttl_seconds = 30.0

    @property
    def _pt(self):
        # Lazy: only build the PT client (which may hit the network) on first use,
        # so importing the service never fails if a backend is misconfigured.
        if self._pt_client is None:
            self._pt_client = get_pt_client()
        return self._pt_client

    def search(self, query: str | SearchQuery, limit: int = 20) -> SearchResult:
        q = self._normalize_query(query)
        cache_key = (
            q.keyword.lower(),
            (q.category or "").lower(),
            (q.resolution or "").lower(),
            (q.quality or "").lower(),
            q.min_seeders or 0,
            q.min_size_gb or 0.0,
            q.max_size_gb or 0.0,
            limit,
        )
        now = monotonic()
        cached = self._search_cache.get(cache_key)
        if cached and (now - cached[0]) <= self._search_cache_ttl_seconds:
            logger.debug("Search cache hit for '%s'", q.keyword)
            return cached[1].model_copy(deep=True)

        min_size_bytes = int(q.min_size_gb * (1024**3)) if q.min_size_gb is not None else None
        max_size_bytes = int(q.max_size_gb * (1024**3)) if q.max_size_gb is not None else None

        # Try local catalog first so queries can hit previously synced RSS items.
        with session_scope() as session:
            local_rows = repo.search_resources(
                session,
                q.keyword,
                category=q.category,
                resolution=q.resolution,
                quality=q.quality,
                min_seeders=q.min_seeders,
                min_size_bytes=min_size_bytes,
                max_size_bytes=max_size_bytes,
                limit=limit,
            )
        if local_rows:
            results = [
                TorrentResourceDTO(
                    id=row.id,
                    site_name=row.site_name or self._pt.site_name,
                    title=row.title,
                    category=row.category,
                    resolution=row.resolution,
                    quality=row.quality,
                    size_bytes=row.size_bytes or 0,
                    seeders=row.seeders or 0,
                    leechers=row.leechers or 0,
                    detail_url=row.detail_url,
                    download_url=row.download_url,
                    publish_time=row.publish_time,
                )
                for row in local_rows
            ]
            logger.info("Search '%s' -> %d resources (from local buffer)", q.keyword, len(results))
            result = SearchResult(keyword=q.keyword, resources=results)
            self._search_cache[cache_key] = (now, result.model_copy(deep=True))
            return result

        # ============================================================
        # Fallback: Query live PT API
        # ============================================================
        live_keyword = q.keyword or q.category or q.quality or q.resolution or ""
        resources = self._pt.search(live_keyword, limit=limit) if live_keyword else []

        # Fallback: simulate a normal tracker web search with cookie auth.
        if not resources and live_keyword:
            resources = self._pt_web_client.search(q, limit=limit)

        resources = self._apply_filters(resources, q)

        prefs = self._load_preferences()
        resources = self._rank(resources, prefs)

        # Persist resources so they receive stable IDs for downloading.
        with session_scope() as session:
            stored: list[TorrentResourceDTO] = []
            for dto in resources:
                row = repo.upsert_resource(session, dto)
                dto.id = row.id
                stored.append(dto)
            logger.info("Search '%s' -> %d resources (from live PT API)", q.keyword, len(stored))
            result = SearchResult(keyword=q.keyword, resources=stored)
        self._search_cache[cache_key] = (now, result.model_copy(deep=True))
        # Keep cache bounded.
        if len(self._search_cache) > 32:
            oldest_key = min(self._search_cache, key=lambda k: self._search_cache[k][0])
            self._search_cache.pop(oldest_key, None)
        return result

    def best_match(self, keyword: str) -> TorrentResourceDTO | None:
        """Return the single best resource for a keyword (used by agents)."""
        result = self.search(keyword)
        return result.resources[0] if result.resources else None

    @staticmethod
    def _normalize_query(query: str | SearchQuery) -> SearchQuery:
        if isinstance(query, SearchQuery):
            return query
        return SearchQuery(keyword=query.strip())

    @staticmethod
    def _apply_filters(
        resources: list[TorrentResourceDTO],
        query: SearchQuery,
    ) -> list[TorrentResourceDTO]:
        wanted_categories = {
            c
            for c in (
                SearchService._normalize_category_token(token)
                for token in re.split(r"[,，;/|\s]+", query.category or "")
            )
            if c
        }
        out: list[TorrentResourceDTO] = []
        for item in resources:
            if wanted_categories:
                item_cat = SearchService._normalize_category_token(item.category or "")
                # Keep records with unknown category metadata; PT-side filtering
                # may already be applied at query URL level.
                if item_cat and item_cat not in wanted_categories:
                    continue
            if query.resolution and query.resolution.lower() not in (item.resolution or "").lower():
                continue
            if query.quality and query.quality.lower() not in (item.quality or "").lower():
                continue
            if query.min_seeders is not None and item.seeders < query.min_seeders:
                continue

            size_gb = item.size_bytes / (1024**3) if item.size_bytes else 0.0
            if query.min_size_gb is not None and size_gb < query.min_size_gb:
                continue
            if query.max_size_gb is not None and size_gb > query.max_size_gb:
                continue
            out.append(item)
        return out

    @staticmethod
    def _normalize_category_token(value: str) -> str:
        token = (value or "").strip().lower()
        return _CATEGORY_ALIAS.get(token, token)

    # ------------------------------------------------------------------ #
    def _load_preferences(self) -> dict[str, str]:
        now = monotonic()
        if self._pref_cache is not None and (now - self._pref_cache_at) <= self._pref_cache_ttl_seconds:
            return dict(self._pref_cache)

        with session_scope() as session:
            memories = repo.list_memories(session, memory_type="preference")
            prefs = {m.memory_key: (m.memory_value or "") for m in memories}
        self._pref_cache = prefs
        self._pref_cache_at = now
        return dict(prefs)

    def _rank(
        self, resources: list[TorrentResourceDTO], prefs: dict[str, str]
    ) -> list[TorrentResourceDTO]:
        pref_res = (prefs.get("preferred_resolution") or "").upper()
        pref_qual = (prefs.get("preferred_quality") or "").upper()

        def score(r: TorrentResourceDTO) -> tuple:
            res_score = _RESOLUTION_RANK.get((r.resolution or "").upper(), 0)
            qual_score = _QUALITY_RANK.get((r.quality or "").upper(), 0)
            pref_bonus = 0
            if pref_res and (r.resolution or "").upper() == pref_res:
                pref_bonus += 10
            if pref_qual and (r.quality or "").upper() == pref_qual:
                pref_bonus += 10
            return (pref_bonus, res_score, qual_score, r.seeders)

        return sorted(resources, key=score, reverse=True)
