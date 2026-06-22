"""PT web-page search fallback client.

Used when RSS/local cache returns no matches. It simulates a normal keyword search
against a tracker web page using the user's authenticated cookie.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from ...shared.config import get_settings
from ...shared.logging import get_logger
from ...shared.schemas import SearchQuery, TorrentResourceDTO

logger = get_logger(__name__)

_DOWNLOAD_HINTS = ("download.php", "action=download", "torrents.php?action=download", "dl.php")
_SIZE_RE = re.compile(r"([\d.]+)\s*(TB|GB|MB|KB)", re.IGNORECASE)
_SIZE_UNITS = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_RESOLUTION_RE = re.compile(r"\b(2160p|1080p|720p|480p)\b", re.IGNORECASE)
_QUALITY_RE = re.compile(r"\b(REMUX|BluRay|WEB-DL|WEBRip|HDTV)\b", re.IGNORECASE)

_CATEGORY_HINTS = {
    "movie": "Movie",
    "电影": "Movie",
    "tv": "TV",
    "series": "TV",
    "剧集": "TV",
    "综艺": "TV",
    "anime": "Anime",
    "动画": "Anime",
    "纪录": "Documentary",
    "documentary": "Documentary",
}


class WebPTSearchClient:
    """Perform best-effort search by parsing the PT website result page."""

    def __init__(self) -> None:
        settings = get_settings()
        self.site_name = settings.pt_site_name
        self.base_url = (settings.pt_base_url or "").rstrip("/")
        self.cookie = settings.pt_cookie
        self.max_pages = max(1, settings.pt_web_max_pages)
        self.query_template = (settings.pt_web_query_template or "").strip()
        self.keyword_param = (settings.pt_web_keyword_param or "search").strip()
        self.category_param = (settings.pt_web_category_param or "").strip()
        self.category_param_map = self._load_category_param_map(settings.pt_web_category_param_map)
        self.resolution_param = (settings.pt_web_resolution_param or "").strip()
        self.quality_param = (settings.pt_web_quality_param or "").strip()
        self.min_seeders_param = (settings.pt_web_min_seeders_param or "").strip()
        self.min_size_gb_param = (settings.pt_web_min_size_gb_param or "").strip()
        self.max_size_gb_param = (settings.pt_web_max_size_gb_param or "").strip()
        self.page_param = (settings.pt_web_page_param or "page").strip()
        parts = urlsplit(self.base_url)
        self.site_root = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""

    def configured(self) -> bool:
        return bool(self.base_url and self.cookie)

    def search(self, query: str | SearchQuery, limit: int = 100) -> list[TorrentResourceDTO]:
        if not self.configured():
            logger.info("PT web fallback skipped: PT_BASE_URL or PT_COOKIE missing")
            return []

        q = self._normalize_query(query)

        url = self._build_search_url(q, page=1)
        headers = {
            "Cookie": self.cookie,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36",
        }

        resources: list[TorrentResourceDTO] = []
        seen_download_urls: set[str] = set()
        visited_urls: set[str] = set()
        detail_cache: dict[str, dict[str, int | str | None]] = {}
        detail_budget = 8
        current_page = 1

        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                while current_page <= self.max_pages and len(resources) < limit and url and url not in visited_urls:
                    visited_urls.add(url)
                    resp = client.get(url, headers=headers)
                    resp.raise_for_status()
                    html = resp.text

                    page_results = self._parse_html(html, limit=limit)
                    added_this_page = 0
                    for item in page_results:
                        if detail_budget > 0 and self._needs_detail_enrich(item):
                            detail_meta = self._enrich_from_detail(
                                client=client,
                                headers=headers,
                                detail_url=item.detail_url,
                                cache=detail_cache,
                            )
                            if detail_meta:
                                item.category = item.category or detail_meta.get("category")
                                item.resolution = item.resolution or detail_meta.get("resolution")
                                item.quality = item.quality or detail_meta.get("quality")
                                item.seeders = item.seeders or int(detail_meta.get("seeders") or 0)
                                if not item.size_bytes:
                                    item.size_bytes = int(detail_meta.get("size_bytes") or 0)
                            detail_budget -= 1

                        key = item.download_url or ""
                        if key and key not in seen_download_urls:
                            seen_download_urls.add(key)
                            resources.append(item)
                            added_this_page += 1
                            if len(resources) >= limit:
                                break

                    if len(resources) >= limit:
                        break

                    soup = BeautifulSoup(html, "html.parser")
                    next_link = self._find_next_page_url(soup)
                    if next_link and next_link not in visited_urls:
                        url = next_link
                    elif added_this_page > 0:
                        # Fallback to explicit page parameter for trackers without a visible "next" anchor.
                        current_page += 1
                        url = self._build_search_url(q, page=current_page)
                    else:
                        break
        except Exception as exc:  # noqa: BLE001
            logger.warning("PT web fallback request failed: %s", exc)
            return []

        logger.info("PT web fallback search '%s' -> %d resources", q.keyword, len(resources))
        return resources[:limit]

    @staticmethod
    def _normalize_query(query: str | SearchQuery) -> SearchQuery:
        if isinstance(query, SearchQuery):
            return query
        return SearchQuery(keyword=(query or "").strip())

    def _build_search_url(self, query: SearchQuery, page: int = 1) -> str:
        if self.query_template:
            rendered = self.query_template
            tokens = {
                "keyword": query.keyword,
                "category": query.category,
                "resolution": query.resolution,
                "quality": query.quality,
                "min_seeders": query.min_seeders,
                "min_size_gb": query.min_size_gb,
                "max_size_gb": query.max_size_gb,
                "page": page,
            }
            for key, value in tokens.items():
                raw = "" if value is None else str(value)
                rendered = rendered.replace(f"{{{key}}}", quote(raw, safe=""))
            return rendered

        parts = urlsplit(self.base_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        if query.keyword:
            params[self.keyword_param] = query.keyword
        if query.category:
            self._apply_category_params(params, query.category)
        if query.resolution and self.resolution_param:
            params[self.resolution_param] = query.resolution
        if query.quality and self.quality_param:
            params[self.quality_param] = query.quality
        if query.min_seeders is not None and self.min_seeders_param:
            params[self.min_seeders_param] = str(query.min_seeders)
        if query.min_size_gb is not None and self.min_size_gb_param:
            params[self.min_size_gb_param] = str(query.min_size_gb)
        if query.max_size_gb is not None and self.max_size_gb_param:
            params[self.max_size_gb_param] = str(query.max_size_gb)
        if page > 1 and self.page_param:
            params[self.page_param] = str(page)
        new_query = urlencode(params)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

    def _apply_category_params(self, params: dict[str, str], category_raw: str) -> None:
        categories = self._split_categories(category_raw)
        if not categories:
            return

        # Preferred mode: map each category value to its dedicated parameter name
        # (for example 电影 -> cat401, 剧集 -> cat402), then set each to 1.
        if self.category_param_map:
            for c in categories:
                key = c.lower()
                mapped = self.category_param_map.get(key) or self.category_param_map.get(c)
                # Allow passing raw param names directly (e.g. "cat401").
                if not mapped and key.startswith("cat") and key[3:].isdigit():
                    mapped = c
                if mapped:
                    params[mapped] = "1"
            return

        # Backward-compatible mode for trackers with a single category parameter.
        if self.category_param:
            params[self.category_param] = ",".join(categories)

    @staticmethod
    def _split_categories(raw: str) -> list[str]:
        parts = re.split(r"[,，;/|\s]+", raw.strip())
        return [p for p in parts if p]

    @staticmethod
    def _load_category_param_map(raw: str) -> dict[str, str]:
        if not (raw or "").strip():
            return {}
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return {}
            out: dict[str, str] = {}
            for k, v in parsed.items():
                if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                    out[k.strip()] = v.strip()
                    out[k.strip().lower()] = v.strip()
            return out
        except Exception:  # noqa: BLE001
            logger.warning("Invalid PT_WEB_CATEGORY_PARAM_MAP, expected JSON object")
            return {}

    def _parse_html(self, html: str, limit: int) -> list[TorrentResourceDTO]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[TorrentResourceDTO] = []

        # Most trackers expose a download link per row.
        for a in soup.find_all("a", href=True):
            href = a.get("href") or ""
            if not any(h in href for h in _DOWNLOAD_HINTS):
                continue

            title, detail_url = self._extract_title_and_detail_url(a)
            if not title:
                continue

            download_url = self._abs_url(href)
            row_text = self._extract_row_text(a)
            merged_text = f"{title} {row_text}".strip()
            size = self._extract_size(row_text)
            seeders = self._extract_seeders(row_text)
            resolution = self._extract_resolution(merged_text)
            quality = self._extract_quality(merged_text)
            category = self._extract_category(merged_text)

            results.append(
                TorrentResourceDTO(
                    site_name=self.site_name,
                    title=title,
                    category=category,
                    resolution=resolution,
                    quality=quality,
                    size_bytes=size,
                    seeders=seeders,
                    leechers=0,
                    detail_url=detail_url,
                    download_url=download_url,
                )
            )
            if len(results) >= limit:
                break

        return results

    def _extract_title_and_detail_url(self, anchor) -> tuple[str, str | None]:  # noqa: ANN001
        # Download anchor text is often "下载本种". Try to resolve title from same row.
        title = (anchor.get("title") or anchor.get_text(" ", strip=True) or "").strip()
        detail_url = None

        row = anchor.find_parent("tr")
        scope = row if row is not None else anchor.parent
        if scope is not None:
            for link in scope.find_all("a", href=True):
                href = link.get("href") or ""
                text = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
                if not text:
                    continue
                # Prefer details-like links for the real resource title.
                if any(k in href for k in ("details", "torrents.php?id=", "id=")) and not any(
                    h in href for h in _DOWNLOAD_HINTS
                ):
                    title = text
                    detail_url = self._abs_url(href)
                    break

        if title in ("下载本种", "下载", "download", "dl") and scope is not None:
            # Last resort: pick the longest non-empty link text in the same row.
            candidates = [
                (link.get("title") or link.get_text(" ", strip=True) or "").strip()
                for link in scope.find_all("a", href=True)
            ]
            candidates = [c for c in candidates if c and c not in ("下载本种", "下载", "download", "dl")]
            if candidates:
                title = max(candidates, key=len)

        return title, detail_url

    def _find_next_page_url(self, soup: BeautifulSoup) -> str | None:
        for link in soup.find_all("a", href=True):
            text = (link.get_text(" ", strip=True) or "").lower()
            href = (link.get("href") or "").strip()
            if not href:
                continue
            if href.startswith(("javascript:", "mailto:", "#")):
                continue
            if any(token in text for token in ("next", "下一页", "下页", ">>", "›")):
                candidate = self._abs_url(href)
                if candidate:
                    return candidate
            # Some trackers use pagination links where only the href carries page=.
            if "page=" in href and any(token in href for token in ("search", "torrents", "browse")):
                rel = link.get("rel") or []
                if isinstance(rel, str):
                    rel = [rel]
                if any(r.lower() == "next" for r in rel):
                    candidate = self._abs_url(href)
                    if candidate:
                        return candidate
        return None

    def _abs_url(self, href: str) -> str:
        # Resolve tracker links against site root to avoid path artifacts like
        # ".../torrents.php/details.php?..." when PT_BASE_URL includes a page.
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            return ""
        if self.site_root:
            return urljoin(self.site_root + "/", href)
        return urljoin(self.base_url + "/", href)

    @staticmethod
    def _extract_row_text(anchor) -> str:  # noqa: ANN001
        row = anchor.find_parent("tr")
        if row is not None:
            return row.get_text(" ", strip=True)
        parent = anchor.parent
        return parent.get_text(" ", strip=True) if parent is not None else ""

    @staticmethod
    def _extract_resolution(text: str) -> str | None:
        m = _RESOLUTION_RE.search(text or "")
        return m.group(1).upper() if m else None

    @staticmethod
    def _extract_quality(text: str) -> str | None:
        m = _QUALITY_RE.search(text or "")
        return m.group(1).upper() if m else None

    @staticmethod
    def _extract_category(text: str) -> str | None:
        low = (text or "").lower()
        for hint, value in _CATEGORY_HINTS.items():
            if hint in low:
                return value
        return None

    @staticmethod
    def _needs_detail_enrich(item: TorrentResourceDTO) -> bool:
        return not (item.category and item.resolution and item.quality and item.size_bytes and item.seeders)

    def _enrich_from_detail(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        detail_url: str | None,
        cache: dict[str, dict[str, int | str | None]],
    ) -> dict[str, int | str | None]:
        if not detail_url:
            return {}
        if detail_url in cache:
            return cache[detail_url]

        try:
            resp = client.get(detail_url, headers=headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            meta: dict[str, int | str | None] = {
                "category": self._extract_category(text),
                "resolution": self._extract_resolution(text),
                "quality": self._extract_quality(text),
                "size_bytes": self._extract_size(text),
                "seeders": self._extract_seeders(text),
            }
            cache[detail_url] = meta
            return meta
        except Exception:  # noqa: BLE001
            cache[detail_url] = {}
            return {}

    @staticmethod
    def _extract_size(text: str) -> int:
        m = _SIZE_RE.search(text or "")
        if not m:
            return 0
        return int(float(m.group(1)) * _SIZE_UNITS[m.group(2).upper()])

    @staticmethod
    def _extract_seeders(text: str) -> int:
        # Heuristic: common "Seeders: 12" / "S 12" patterns.
        patterns = [
            r"Seeders?\s*[:：]?\s*(\d+)",
            r"\bS\s*(\d+)\b",
        ]
        for p in patterns:
            m = re.search(p, text or "", flags=re.IGNORECASE)
            if m:
                return int(m.group(1))
        return 0
