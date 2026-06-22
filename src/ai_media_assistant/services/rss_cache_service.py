"""RSS sync service that caches the latest PT feed into the local catalog."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from ..clients.pt import get_pt_client
from ..database import session_scope
from ..database import repositories as repo
from ..shared.logging import get_logger

logger = get_logger(__name__)

CACHE_REFRESH_INTERVAL = 600  # 10 minutes


class RssCacheService:
    """Synchronise RSS resources into the local torrent catalog."""

    @staticmethod
    def refresh_latest_resources(limit: int = 50) -> dict[str, Any]:
        """Fetch the latest RSS items and upsert them into torrent_resource."""
        client = get_pt_client()
        resources = client.fetch_latest_resources(limit=limit)
        stored = 0
        with session_scope() as session:
            for dto in resources:
                row = repo.upsert_resource(session, dto)
                dto.id = row.id
                stored += 1
        summary = {
            "fetched": len(resources),
            "stored": stored,
            "synced_at": datetime.utcnow().isoformat(),
        }
        logger.info("RSS sync complete: %s", summary)
        return summary

    @staticmethod
    def get_cache_age() -> int | None:
        """Return the age of the latest cached catalog resource in seconds."""
        with session_scope() as session:
            latest = repo.list_recent_resources(session, limit=1)
            if not latest:
                return None
            latest_time = latest[0].created_time
            if latest_time is None:
                return None
            return int((datetime.utcnow() - latest_time).total_seconds())

    @staticmethod
    def is_cache_valid() -> bool:
        age = RssCacheService.get_cache_age()
        return age is not None and age < CACHE_REFRESH_INTERVAL

    @staticmethod
    async def background_refresh_loop() -> None:
        logger.info("RSS sync background task started (interval: %ss)", CACHE_REFRESH_INTERVAL)
        while True:
            try:
                await asyncio.sleep(CACHE_REFRESH_INTERVAL)
                RssCacheService.refresh_latest_resources()
            except asyncio.CancelledError:
                logger.info("RSS sync background task cancelled")
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error in RSS sync background loop: %s", exc)
                await asyncio.sleep(60)
