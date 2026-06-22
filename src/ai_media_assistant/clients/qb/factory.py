"""qBittorrent client factory — mock or real based on configuration."""

from __future__ import annotations

from functools import lru_cache

from ...shared.config import get_settings
from .base import QBClient


@lru_cache
def get_qb_client() -> QBClient:
    settings = get_settings()
    if settings.qb_mock:
        from .mock import MockQBClient

        return MockQBClient()

    from .real import RealQBClient

    return RealQBClient()
