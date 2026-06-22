"""MCP server publishing the six media tools from the design.

Tools: search_media, download_media, download_media_default, follow_show,
list_subscriptions, get_download_status, get_recommendations.

Run with:  python -m ai_media_assistant.mcp.server   (stdio transport)

An OpenClaw / Claude-Desktop style client can then connect and call these tools
via natural language. Tool descriptions double as the agent-computer interface.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..database import init_db
from ..services.download_service import DownloadService
from ..services.follow_service import FollowService
from ..services.recommendation_service import RecommendationService
from ..services.search_service import SearchService
from ..shared.errors import AIMediaError
from ..shared.logging import get_logger
from ..shared.schemas import SearchQuery

logger = get_logger(__name__)

mcp = FastMCP("ai-media-assistant")

_search = SearchService()
_download = DownloadService()
_follow = FollowService()
_recommend = RecommendationService()


@mcp.tool()
def search_media(
    keyword: str = "",
    category: str = "",
    resolution: str = "",
    quality: str = "",
    min_seeders: int = 0,
    min_size_gb: float = 0.0,
    max_size_gb: float = 0.0,
) -> dict:
    """Search private trackers and return downloadable resource candidates.

    Use this when the user asks things like "有哪些资源" / "哪些版本" /
    "有哪些资源可以下载".
    The returned ``id`` is required by ``download_media``.
    """
    query = SearchQuery(
        keyword=keyword,
        category=category or None,
        resolution=resolution or None,
        quality=quality or None,
        min_seeders=min_seeders if min_seeders > 0 else None,
        min_size_gb=min_size_gb if min_size_gb > 0 else None,
        max_size_gb=max_size_gb if max_size_gb > 0 else None,
    )
    result = _search.search(query)
    return {
        "keyword": result.keyword,
        "query": query.model_dump(),
        "resources": [
            {
                "id": r.id,
                "title": r.title,
                "resolution": r.resolution,
                "quality": r.quality,
                "size_gb": r.size_gb,
                "seeders": r.seeders,
            }
            for r in result.resources
        ],
    }


@mcp.tool()
def download_media(resource_id: int, save_path: str, confirm: bool = False) -> dict:
    """Add a searched resource (by id) to qBittorrent for download.

    This tool requires an explicit save_path. If the user says "保存到...",
    pass that directory as save_path.
    """
    path = (save_path or "").strip()
    if not path:
        return {"error": "save_path is required for download_media."}
    try:
        task = _download.download(resource_id, confirm=confirm, save_path=path)
        return {
            "task_id": task.id,
            "status": task.task_status.value,
            "title": task.title,
            "save_path": task.save_path,
        }
    except AIMediaError as exc:
        return {"error": str(exc)}


@mcp.tool()
def download_media_default(resource_id: int, confirm: bool = False) -> dict:
    """Add a searched resource to qBittorrent using DOWNLOAD_SAVE_PATH."""
    try:
        task = _download.download(resource_id, confirm=confirm)
        return {
            "task_id": task.id,
            "status": task.task_status.value,
            "title": task.title,
            "save_path": task.save_path,
        }
    except AIMediaError as exc:
        return {"error": str(exc)}


@mcp.tool()
def follow_show(title: str, season: int = 0, quality: str = "") -> dict:
    """Subscribe to a TV show and download currently-available episodes.

    Pass season=0 to follow the whole show, or a season number to scope it.
    """
    try:
        return _follow.follow_show(title, season=season or None, quality=quality or None)
    except AIMediaError as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_subscriptions() -> list[dict]:
    """List all TV-show subscriptions."""
    return [s.model_dump() for s in _follow.list_subscriptions()]


@mcp.tool()
def get_download_status(task_id: int = 0) -> dict | list[dict]:
    """Get progress for one download task, or all tasks when task_id=0."""
    if task_id:
        task = _download.refresh(task_id)
        return task.model_dump() if task else {"error": "task not found"}
    return [t.model_dump() for t in _download.list_tasks()]


@mcp.tool()
def get_recommendations(query: str = "") -> list[dict]:
    """Recommend titles using RAG (not the primary tool for download listing).

    For "what resources can I download" requests, prefer ``search_media``.
    """
    return [r.model_dump() for r in _recommend.recommend(query)]


@mcp.tool()
def get_system_status() -> dict:
    """Report whether the search/download chain is running in real or mock mode.

    Use this to confirm the pipeline is fully wired (PT indexer reachable,
    qBittorrent connected) before downloading.
    """
    from ..shared.config import get_settings

    settings = get_settings()
    status: dict = {
        "pt_backend": settings.effective_pt_backend,
        "pt_base_url": settings.pt_base_url or None,
        "pt_rss_configured": bool(settings.pt_rss_url),
        "qb_mock": settings.qb_mock,
        "qb_host": settings.qb_host,
        "db_backend": "mysql" if settings.db_host else "sqlite",
        "db_target": settings.db_host or "data/app.db",
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
    }
    if not settings.qb_mock:
        try:
            from ..clients.qb import get_qb_client

            torrents = get_qb_client().list()
            status["qb_connected"] = True
            status["qb_active_torrents"] = len(torrents)
        except Exception as exc:  # noqa: BLE001 - report rather than crash
            status["qb_connected"] = False
            status["qb_error"] = str(exc)
    return status


def main() -> None:
    init_db()
    logger.info("Starting AI Media Assistant MCP server (stdio)…")
    mcp.run()


if __name__ == "__main__":
    main()
