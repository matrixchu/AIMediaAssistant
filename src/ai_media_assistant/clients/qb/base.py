"""qBittorrent client interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TorrentInfo:
    hash: str
    name: str
    state: str  # queued | downloading | completed | error | paused
    progress: float  # 0.0 - 1.0


class QBClient(ABC):
    """Abstract qBittorrent download manager."""

    @abstractmethod
    def add(self, download_url: str, save_path: str | None = None, name: str | None = None) -> str:
        """Add a torrent/magnet and return its info-hash."""

    @abstractmethod
    def status(self, torrent_hash: str) -> TorrentInfo | None:
        """Return current status for a torrent hash."""

    @abstractmethod
    def list(self) -> list[TorrentInfo]:
        """List all tracked torrents."""
