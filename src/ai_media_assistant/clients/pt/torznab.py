"""Torznab PT search client (Jackett / Prowlarr / any Torznab indexer).

Torznab is the de-facto standard exposed by indexer aggregators such as
**Jackett** and **Prowlarr**. Pointing this client at a Torznab endpoint makes
the whole pipeline real: it searches your configured private trackers and
returns magnet/.torrent links that qBittorrent can download.

Endpoint shape (Torznab):
    {base_url}?t=search&q={keyword}&apikey={api_key}
returns an RSS/XML document whose <item>s carry the title, size, a magnet or
.torrent enclosure, and torznab:attr seeders/peers metadata.

Typical setup:
    * Jackett:  PT_BASE_URL=http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab/api
    * Prowlarr: PT_BASE_URL=http://127.0.0.1:9696/{indexerId}/api
"""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree as ET

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ...shared.config import get_settings
from ...shared.logging import get_logger
from ...shared.schemas import TorrentResourceDTO

logger = get_logger(__name__)

_TORZNAB_NS = "{http://torznab.com/schemas/2015/feed}"


class TorznabPTClient:
    """A real PT search client speaking the Torznab protocol."""

    def __init__(self) -> None:
        settings = get_settings()
        self.site_name = settings.pt_site_name
        self.base_url = settings.pt_base_url.rstrip("?")
        self.api_key = settings.pt_api_key
        self.min_seeders = settings.pt_min_seeders

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=6))
    def search(self, keyword: str, limit: int = 20) -> list[TorrentResourceDTO]:
        if not self.base_url:
            logger.warning("PT_BASE_URL not configured; Torznab search returns nothing.")
            return []

        params = {"t": "search", "q": keyword, "limit": str(limit)}
        if self.api_key:
            params["apikey"] = self.api_key

        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(self.base_url, params=params)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
        except httpx.HTTPError as exc:
            logger.error("Torznab request failed: %s", exc)
            return []
        except ET.ParseError as exc:
            logger.error("Torznab returned invalid XML: %s", exc)
            return []

        resources: list[TorrentResourceDTO] = []
        for item in root.iter("item"):
            dto = self._parse_item(item)
            if dto and dto.seeders >= self.min_seeders:
                resources.append(dto)

        resources.sort(key=lambda r: r.seeders, reverse=True)
        logger.info("Torznab search '%s' -> %d resources", keyword, len(resources))
        return resources[:limit]

    # ------------------------------------------------------------------ #
    def _parse_item(self, item: ET.Element) -> TorrentResourceDTO | None:
        title = _text(item, "title")
        if not title:
            return None

        attrs = self._torznab_attrs(item)
        download_url = (
            attrs.get("magneturl")
            or _enclosure_url(item)
            or _text(item, "link")
        )
        if not download_url:
            return None

        size = _to_int(attrs.get("size") or _enclosure_length(item))
        return TorrentResourceDTO(
            site_name=attrs.get("indexer") or self.site_name,
            title=title,
            category=attrs.get("category"),
            resolution=_guess(title, ("2160p", "1080p", "720p", "480p")),
            quality=_guess(title, ("remux", "bluray", "web-dl", "webrip", "hdtv")),
            size_bytes=size,
            seeders=_to_int(attrs.get("seeders")),
            leechers=_to_int(attrs.get("peers") or attrs.get("leechers")),
            detail_url=_text(item, "comments") or _text(item, "guid"),
            download_url=download_url,
            publish_time=_parse_dt(_text(item, "pubDate")),
        )

    @staticmethod
    def _torznab_attrs(item: ET.Element) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for attr in item.iter(f"{_TORZNAB_NS}attr"):
            name = attr.get("name")
            value = attr.get("value")
            if name and value is not None:
                attrs[name] = value
        return attrs


def _text(item: ET.Element, tag: str) -> str | None:
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else None


def _enclosure_url(item: ET.Element) -> str | None:
    enc = item.find("enclosure")
    return enc.get("url") if enc is not None else None


def _enclosure_length(item: ET.Element) -> str | None:
    enc = item.find("enclosure")
    return enc.get("length") if enc is not None else None


def _to_int(value: str | None) -> int:
    try:
        return int(value) if value is not None else 0
    except (ValueError, TypeError):
        return 0


def _guess(title: str, candidates: tuple[str, ...]) -> str | None:
    low = title.lower()
    for c in candidates:
        if c in low:
            return c.upper()
    return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
