"""LangChain tools that expose the application's services to the agent.

These same capabilities are also published over MCP (see ``mcp/server.py``),
so the agent can call them either in-process (LangGraph) or as remote MCP tools.
Tool docstrings are written carefully — they are the agent-computer interface.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from ..services.download_service import DownloadService
from ..services.follow_service import FollowService
from ..services.recommendation_service import RecommendationService
from ..services.search_service import SearchService
from ..shared.errors import AIMediaError

_search = SearchService()
_download = DownloadService()
_follow = FollowService()
_recommend = RecommendationService()


def _ok(data: object) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


@tool
def search_media(keyword: str) -> str:
    """Search private trackers for a movie or TV show.

    Args:
        keyword: Title to search for, e.g. "Dune Part Two" or "The Last of Us S02".

    Returns a JSON list of resources. Each has: id, title, resolution, quality,
    size_gb, seeders. Use the ``id`` with ``download_media`` to start a download.
    """
    try:
        result = _search.search(keyword)
        return _ok(
            [
                {
                    "id": r.id,
                    "title": r.title,
                    "resolution": r.resolution,
                    "quality": r.quality,
                    "size_gb": r.size_gb,
                    "seeders": r.seeders,
                }
                for r in result.resources
            ]
        )
    except AIMediaError as exc:
        return _err(str(exc))


@tool
def download_media(resource_id: int, confirm: bool = False) -> str:
    """Add a previously-searched resource to qBittorrent for download.

    Args:
        resource_id: The ``id`` returned by ``search_media``.
        confirm: Set true to approve the download when confirmation is required.

    Returns the created download task (task_id, status, qb_hash).
    """
    try:
        task = _download.download(resource_id, confirm=confirm)
        return _ok(
            {
                "task_id": task.id,
                "title": task.title,
                "status": task.task_status.value,
                "qb_hash": task.qb_hash,
            }
        )
    except AIMediaError as exc:
        return _err(str(exc))


@tool
def follow_show(title: str, season: int | None = None, quality: str | None = None) -> str:
    """Subscribe to a TV show and download all currently-available episodes.

    Args:
        title: Show title, e.g. "The Last of Us".
        season: Season number to follow (optional).
        quality: Preferred quality, e.g. "2160P" (optional).

    Returns the subscription id and the list of episodes downloaded.
    """
    try:
        return _ok(_follow.follow_show(title, season=season, quality=quality))
    except AIMediaError as exc:
        return _err(str(exc))


@tool
def list_subscriptions() -> str:
    """List all TV-show subscriptions and their status."""
    subs = _follow.list_subscriptions()
    return _ok([s.model_dump() for s in subs])


@tool
def get_download_status(task_id: int | None = None) -> str:
    """Get download progress.

    Args:
        task_id: A specific task id, or omit to list all tasks.
    """
    if task_id is not None:
        task = _download.refresh(task_id)
        return _ok(task.model_dump() if task else None)
    return _ok([t.model_dump() for t in _download.list_tasks()])


@tool
def get_recommendations(query: str = "") -> str:
    """Recommend media using RAG over the catalogue and learned preferences.

    Args:
        query: Optional free-text request, e.g. "recent sci-fi movies".
    """
    recs = _recommend.recommend(query)
    return _ok([r.model_dump() for r in recs])


ALL_TOOLS = [
    search_media,
    download_media,
    follow_show,
    list_subscriptions,
    get_download_status,
    get_recommendations,
]
