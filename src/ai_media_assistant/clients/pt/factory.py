"""PT client factory — selects mock, Torznab, or custom JSON based on config."""

from __future__ import annotations

from functools import lru_cache

from ...shared.config import get_settings
from ...shared.logging import get_logger
from .base import PTClient

logger = get_logger(__name__)


@lru_cache
def get_pt_client() -> PTClient:
    settings = get_settings()
    backend = settings.effective_pt_backend

    if backend == "rss":
        from .rss import RssPTClient

        logger.info("PT backend: member RSS feed (%s)", settings.pt_site_name)
        return RssPTClient()  # type: ignore[return-value]

    if backend == "torznab":
        from .torznab import TorznabPTClient

        logger.info("PT backend: Torznab (%s)", settings.pt_base_url or "unconfigured")
        return TorznabPTClient()  # type: ignore[return-value]

    if backend == "json":
        from .http import HTTPPTClient

        logger.info("PT backend: custom JSON (%s)", settings.pt_base_url or "unconfigured")
        return HTTPPTClient()  # type: ignore[return-value]

    from .mock import MockPTClient

    logger.info("PT backend: mock (offline sample catalog)")
    return MockPTClient(site_name=settings.pt_site_name)  # type: ignore[return-value]
