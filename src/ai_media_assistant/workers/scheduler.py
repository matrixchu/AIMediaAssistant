"""Standalone scheduler process for RSS sync and download refresh jobs."""

from __future__ import annotations

from ..database import init_db
from ..services.scheduler_service import get_scheduler_manager
from ..shared.logging import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    setup_logging()
    init_db()

    scheduler = get_scheduler_manager()
    scheduler.start()

    logger.info("Scheduler started (RSS sync every 10m, downloads every 30s). Ctrl+C to stop.")
    try:
        import time

        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
