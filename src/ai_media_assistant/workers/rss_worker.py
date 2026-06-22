"""RSS worker — syncs the latest PT RSS items into the local catalog."""

from __future__ import annotations

from ..services.rss_cache_service import RssCacheService
from ..shared.logging import get_logger

logger = get_logger(__name__)


class RssWorker:
    def run_once(self) -> dict:
        """Sync the latest RSS feed into the local catalog and return a summary."""
        summary = RssCacheService.refresh_latest_resources()
        logger.info("RSS run complete: %s", summary)
        return summary


def main() -> None:
    from ..database import init_db

    init_db()
    RssWorker().run_once()


if __name__ == "__main__":
    main()
