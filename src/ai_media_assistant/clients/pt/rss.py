"""RSS-based PT client for a single private tracker you're a member of.

Most private trackers expose a **personal RSS feed** (the URL embeds your
passkey/secret). The feed lists the latest torrents and—crucially—each item's
download link already contains your passkey, so qBittorrent can fetch the
.torrent without any extra authentication.

This client supports two modes, controlled by how you configure ``PT_RSS_URL``:

1. **Searchable feed** — if your tracker's RSS URL accepts a search term, put a
   ``{keyword}`` placeholder in the URL and we substitute the query, e.g.::

       PT_RSS_URL=https://pt.example/torrentrss.php?passkey=XXlike&search={keyword}

2. **Latest-only feed** — if the feed just lists newest torrents, omit the
   placeholder. We fetch the feed and filter items locally by your keyword::

       PT_RSS_URL=https://pt.example/torrentrss.php?passkey=XX&cat=movies

Because the passkey lives in the URL, treat ``PT_RSS_URL`` as a secret (it stays
in your local ``.env``, which is git-ignored).
"""

from __future__ import annotations

import re
from datetime import datetime
from time import mktime
from urllib.parse import quote

import feedparser

from ...shared.config import get_settings
from ...shared.logging import get_logger
from ...shared.schemas import TorrentResourceDTO

logger = get_logger(__name__)

_SIZE_RE = re.compile(r"([\d.]+)\s*(TB|GB|MB|KB)", re.IGNORECASE)
_SIZE_UNITS = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


class RssPTClient:
    """Search a member PT site via its personal RSS feed."""

    def __init__(self) -> None:
        settings = get_settings()
        self.site_name = settings.pt_site_name
        self.feed_url = settings.pt_rss_url
        self.min_seeders = settings.pt_min_seeders

    def search(self, keyword: str, limit: int = 20) -> list[TorrentResourceDTO]:
        if not self.feed_url:
            logger.warning("PT_RSS_URL not configured; RSS PT search returns nothing.")
            return []

        searchable = "{keyword}" in self.feed_url
        kw = keyword.strip().lower()
        results = []
        for dto in self.fetch_latest_resources(limit=max(limit, 50)):
            # If the feed isn't searchable, filter locally by keyword.
            if not searchable and kw and kw not in dto.title.lower():
                continue
            if kw and kw not in dto.title.lower() and kw not in (dto.category or "").lower():
                continue
            results.append(dto)

        results.sort(key=lambda r: (r.seeders, r.publish_time or datetime.min), reverse=True)
        logger.info("PT RSS search '%s' -> %d resources", keyword, len(results))
        return results[:limit]

    def fetch_latest_resources(self, limit: int = 50) -> list[TorrentResourceDTO]:
        """Fetch the latest resources from the RSS feed without applying keyword filters."""
        if not self.feed_url:
            logger.warning("PT_RSS_URL not configured; RSS PT fetch returns nothing.")
            return []

        url = self._build_url("")
        parsed = feedparser.parse(url)
        if parsed.bozo and not parsed.entries:
            logger.error("PT RSS parse failed for %s: %s", _redact(url), parsed.bozo_exception)
            return []

        results: list[TorrentResourceDTO] = []
        for entry in parsed.entries:
            dto = self._to_dto(entry)
            if dto is None:
                continue
            if dto.seeders and dto.seeders < self.min_seeders:
                continue
            results.append(dto)

        results.sort(key=lambda r: (r.seeders, r.publish_time or datetime.min), reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------ #
    def _build_url(self, keyword: str) -> str:
        if "{keyword}" in self.feed_url:
            return self.feed_url.replace("{keyword}", quote(keyword))
        return self.feed_url

    def _to_dto(self, entry) -> TorrentResourceDTO | None:  # noqa: ANN001 - feedparser obj
        title = getattr(entry, "title", "").strip()
        if not title:
            return None

        download_url = _download_link(entry)
        if not download_url:
            return None

        published = None
        if getattr(entry, "published_parsed", None):
            published = datetime.fromtimestamp(mktime(entry.published_parsed))

        return TorrentResourceDTO(
            site_name=self.site_name,
            title=title,
            category=_first_category(entry),
            resolution=_guess(title, ("2160p", "1080p", "720p", "480p")),
            quality=_guess(title, ("remux", "bluray", "web-dl", "webrip", "hdtv")),
            size_bytes=_extract_size(entry),
            seeders=_int_attr(entry, ("seeders", "nyaa_seeders")),
            leechers=_int_attr(entry, ("leechers", "peers", "nyaa_leechers")),
            detail_url=getattr(entry, "link", None),
            download_url=download_url,
            publish_time=published,
        )


def _download_link(entry) -> str | None:  # noqa: ANN001
    """Pick the actual torrent/magnet URL from an RSS item.

    Order of preference: explicit enclosure (most PT feeds), then any magnet in
    the link, then the item link itself.
    """
    for enc in getattr(entry, "enclosures", []) or []:
        href = enc.get("href") or enc.get("url")
        if href:
            return href
    for link in getattr(entry, "links", []) or []:
        if link.get("rel") == "enclosure" and link.get("href"):
            return link["href"]
    link = getattr(entry, "link", None)
    return link


def _first_category(entry) -> str | None:  # noqa: ANN001
    tags = getattr(entry, "tags", None)
    if tags:
        return tags[0].get("term")
    return getattr(entry, "category", None)


def _extract_size(entry) -> int:  # noqa: ANN001
    # Some feeds expose enclosure length (bytes); otherwise parse from text.
    for enc in getattr(entry, "enclosures", []) or []:
        length = enc.get("length")
        if length and str(length).isdigit():
            return int(length)
    text = f"{getattr(entry, 'title', '')} {getattr(entry, 'summary', '')}"
    m = _SIZE_RE.search(text)
    if m:
        return int(float(m.group(1)) * _SIZE_UNITS[m.group(2).upper()])
    return 0


def _int_attr(entry, names: tuple[str, ...]) -> int:  # noqa: ANN001
    for name in names:
        value = getattr(entry, name, None)
        if value is not None and str(value).isdigit():
            return int(value)
    return 0


def _guess(title: str, candidates: tuple[str, ...]) -> str | None:
    low = title.lower()
    for c in candidates:
        if c in low:
            return c.upper()
    return None


def _redact(url: str) -> str:
    return re.sub(r"(passkey|apikey|secret|rss_?key)=[^&]+", r"\1=***", url, flags=re.IGNORECASE)
