"""In-memory mock PT client with a small sample catalog.

This lets the whole system run end-to-end without access to a real private
tracker, which is ideal for learning and respects tracker terms of service.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ...shared.schemas import TorrentResourceDTO

_GB = 1024**3

# A curated catalogue covering the scenarios in Design.md.
_CATALOG: list[dict] = [
    {
        "title": "Dune Part Two 2024 2160p UHD BluRay REMUX HDR",
        "aliases": ["沙丘2", "dune part two", "dune 2"],
        "category": "Movie",
        "resolution": "2160P",
        "quality": "REMUX",
        "size_bytes": int(78.5 * _GB),
        "seeders": 312,
        "leechers": 12,
    },
    {
        "title": "Dune Part Two 2024 1080p BluRay x265",
        "aliases": ["沙丘2", "dune part two", "dune 2"],
        "category": "Movie",
        "resolution": "1080P",
        "quality": "BluRay",
        "size_bytes": int(12.3 * _GB),
        "seeders": 540,
        "leechers": 30,
    },
    {
        "title": "Blade Runner 2049 2017 2160p UHD BluRay REMUX",
        "aliases": ["blade runner", "银翼杀手2049"],
        "category": "Movie",
        "resolution": "2160P",
        "quality": "REMUX",
        "size_bytes": int(60.1 * _GB),
        "seeders": 210,
        "leechers": 8,
    },
    {
        "title": "Arrival 2016 2160p UHD BluRay REMUX HDR",
        "aliases": ["arrival", "降临"],
        "category": "Movie",
        "resolution": "2160P",
        "quality": "REMUX",
        "size_bytes": int(54.0 * _GB),
        "seeders": 150,
        "leechers": 5,
    },
    {
        "title": "Interstellar 2014 2160p UHD BluRay REMUX",
        "aliases": ["interstellar", "星际穿越"],
        "category": "Movie",
        "resolution": "2160P",
        "quality": "REMUX",
        "size_bytes": int(70.0 * _GB),
        "seeders": 420,
        "leechers": 15,
    },
]

# TV shows: episodes generated on demand.
_TV_SHOWS: list[dict] = [
    {
        "title": "The Last of Us",
        "aliases": ["the last of us", "最后生还者", "最后的生还者"],
        "seasons": {2: 7},  # season 2 has 7 episodes available
        "resolution": "2160P",
        "quality": "WEB-DL",
    },
    {
        "title": "Foundation",
        "aliases": ["foundation", "基地"],
        "seasons": {2: 10},
        "resolution": "2160P",
        "quality": "WEB-DL",
    },
]


class MockPTClient:
    """A deterministic, offline PT client used for development and tests."""

    def __init__(self, site_name: str = "demo-pt") -> None:
        self.site_name = site_name

    def search(self, keyword: str, limit: int = 20) -> list[TorrentResourceDTO]:
        kw = keyword.strip().lower()
        season = _extract_season(keyword)
        results: list[TorrentResourceDTO] = []

        # Movies & generic catalogue items.
        for entry in _CATALOG:
            if self._matches(kw, entry):
                results.append(self._to_dto(entry["title"], entry))

        # TV shows -> expand into episode resources.
        for show in _TV_SHOWS:
            if not self._matches(kw, show):
                continue
            for s_no, ep_count in show["seasons"].items():
                if season is not None and s_no != season:
                    continue
                for ep in range(1, ep_count + 1):
                    title = (
                        f"{show['title']} S{s_no:02d}E{ep:02d} "
                        f"{show['resolution']} {show['quality']}"
                    )
                    results.append(
                        self._to_dto(
                            title,
                            {
                                "category": "TV",
                                "resolution": show["resolution"],
                                "quality": show["quality"],
                                "size_bytes": int(4.5 * _GB),
                                "seeders": 120,
                                "leechers": 6,
                            },
                        )
                    )

        results.sort(key=lambda r: r.seeders, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------ #
    @staticmethod
    def _matches(kw: str, entry: dict) -> bool:
        if not kw:
            return True
        haystack = [entry["title"].lower(), *[a.lower() for a in entry.get("aliases", [])]]
        return any(kw in h or h in kw for h in haystack)

    def _to_dto(self, title: str, entry: dict) -> TorrentResourceDTO:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return TorrentResourceDTO(
            site_name=self.site_name,
            title=title,
            category=entry.get("category"),
            resolution=entry.get("resolution"),
            quality=entry.get("quality"),
            size_bytes=entry.get("size_bytes", 0),
            seeders=entry.get("seeders", 0),
            leechers=entry.get("leechers", 0),
            detail_url=f"https://{self.site_name}.example/torrent/{slug}",
            # A magnet placeholder — never points at real infringing content.
            download_url=f"magnet:?xt=urn:btih:{abs(hash(title)) & ((1 << 160) - 1):040x}",
            publish_time=datetime.now(timezone.utc) - timedelta(days=abs(hash(title)) % 30),
        )


def _extract_season(keyword: str) -> int | None:
    m = re.search(r"(?:s|season|第)\s*0*(\d+)\s*季?", keyword, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None
