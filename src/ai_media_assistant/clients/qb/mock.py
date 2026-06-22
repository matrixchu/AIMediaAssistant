"""In-memory mock qBittorrent client.

Simulates download progress deterministically so the full workflow runs without
a real qBittorrent server. Each ``status()`` call advances progress a little.
"""

from __future__ import annotations

import hashlib
import re

from .base import QBClient, TorrentInfo


class MockQBClient(QBClient):
    def __init__(self) -> None:
        self._torrents: dict[str, TorrentInfo] = {}

    def add(self, download_url: str, save_path: str | None = None, name: str | None = None) -> str:
        torrent_hash = _hash_from_url(download_url)
        self._torrents[torrent_hash] = TorrentInfo(
            hash=torrent_hash,
            name=name or _name_from_url(download_url),
            state="downloading",
            progress=0.0,
        )
        return torrent_hash

    def status(self, torrent_hash: str) -> TorrentInfo | None:
        info = self._torrents.get(torrent_hash)
        if info is None:
            return None
        # Advance simulated progress by 20% per poll until complete.
        if info.state == "downloading":
            info.progress = min(1.0, round(info.progress + 0.2, 2))
            if info.progress >= 1.0:
                info.state = "completed"
        return info

    def list(self) -> list[TorrentInfo]:
        return list(self._torrents.values())


def _hash_from_url(url: str) -> str:
    magnet = re.search(r"btih:([0-9a-fA-F]{40})", url)
    if magnet:
        return magnet.group(1).lower()
    return hashlib.sha1(url.encode()).hexdigest()


def _name_from_url(url: str) -> str:
    dn = re.search(r"[?&]dn=([^&]+)", url)
    return dn.group(1) if dn else url[:60]
