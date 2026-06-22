"""Generic HTTP PT client.

This is a *template* for integrating a real private tracker. PT sites vary
widely (HTML scraping, JSON APIs, Jackett/Prowlarr proxies, etc.), so this
client targets a Jackett/Torznab-style JSON endpoint as a sensible default and
is intentionally easy to subclass.

Only search/read operations are performed. Configure credentials via the
PT_* environment variables. If not configured, an empty result is returned.
"""

from __future__ import annotations

from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ...shared.config import get_settings
from ...shared.logging import get_logger
from ...shared.schemas import TorrentResourceDTO

logger = get_logger(__name__)


class HTTPPTClient:
    """A Torznab/JSON-style PT search client."""

    def __init__(self) -> None:
        settings = get_settings()
        self.site_name = settings.pt_site_name
        self.base_url = settings.pt_base_url.rstrip("/")
        self.api_key = settings.pt_api_key
        self.cookie = settings.pt_cookie

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=5))
    def search(self, keyword: str, limit: int = 20) -> list[TorrentResourceDTO]:
        if not self.base_url:
            logger.warning("PT_BASE_URL not configured; returning no results.")
            return []

        params = {"q": keyword, "limit": limit}
        if self.api_key:
            params["apikey"] = self.api_key
        headers = {"Cookie": self.cookie} if self.cookie else {}

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(f"{self.base_url}/api/search", params=params, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("PT search failed: %s", exc)
            return []

        items = payload.get("results", payload if isinstance(payload, list) else [])
        return [self._parse(item) for item in items][:limit]

    def _parse(self, item: dict) -> TorrentResourceDTO:
        return TorrentResourceDTO(
            site_name=self.site_name,
            title=item.get("title", "unknown"),
            category=item.get("category"),
            resolution=item.get("resolution"),
            quality=item.get("quality"),
            size_bytes=int(item.get("size", 0) or 0),
            seeders=int(item.get("seeders", 0) or 0),
            leechers=int(item.get("leechers", 0) or 0),
            detail_url=item.get("details") or item.get("detail_url"),
            download_url=item.get("link") or item.get("download_url"),
            publish_time=_parse_dt(item.get("publishDate")),
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
