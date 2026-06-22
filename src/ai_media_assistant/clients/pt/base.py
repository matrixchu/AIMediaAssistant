"""PT client interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...shared.schemas import TorrentResourceDTO


class PTClient(ABC):
    """Abstract private-tracker search client.

    Implementations must be read-only with respect to the tracker: this project
    only *searches* and reads torrent metadata. Honour each site's terms of
    service and rate limits.
    """

    @abstractmethod
    def search(self, keyword: str, limit: int = 20) -> list[TorrentResourceDTO]:
        """Search the tracker and return candidate resources."""
        raise NotImplementedError
