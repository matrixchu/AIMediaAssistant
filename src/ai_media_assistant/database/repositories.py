"""Repository helpers — thin data-access functions over the ORM models.

Each function takes an explicit :class:`Session` so callers control transactions.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..shared.schemas import TorrentResourceDTO
from .models import (
    AgentExecutionLog,
    AgentMemory,
    AgentTask,
    DownloadTask,
    MediaEpisode,
    MediaSubscription,
    SchedulerJob,
    SchedulerJobRun,
    RssFeed,
    RssItem,
    TorrentResource,
)


# --------------------------------------------------------------------------- #
# Torrent resources
# --------------------------------------------------------------------------- #
def upsert_resource(session: Session, dto: TorrentResourceDTO) -> TorrentResource:
    """Insert a resource (or return an existing one matching site + title)."""
    existing = session.scalar(
        select(TorrentResource).where(
            TorrentResource.site_name == dto.site_name,
            TorrentResource.title == dto.title,
        )
    )
    if existing:
        return existing
    row = TorrentResource(
        site_name=dto.site_name,
        title=dto.title,
        category=dto.category,
        resolution=dto.resolution,
        quality=dto.quality,
        size_bytes=dto.size_bytes,
        seeders=dto.seeders,
        leechers=dto.leechers,
        detail_url=dto.detail_url,
        download_url=dto.download_url,
        publish_time=dto.publish_time,
    )
    session.add(row)
    session.flush()
    return row


def get_resource(session: Session, resource_id: int) -> TorrentResource | None:
    return session.get(TorrentResource, resource_id)


def find_resource_by_site_title(
    session: Session,
    site_name: str | None,
    title: str,
) -> TorrentResource | None:
    return session.scalar(
        select(TorrentResource).where(
            TorrentResource.site_name == site_name,
            TorrentResource.title == title,
        )
    )


def list_recent_resources(session: Session, limit: int = 50) -> list[TorrentResource]:
    return list(
        session.scalars(
            select(TorrentResource).order_by(TorrentResource.created_time.desc()).limit(limit)
        )
    )


def search_resources(
    session: Session,
    keyword: str = "",
    *,
    category: str | None = None,
    resolution: str | None = None,
    quality: str | None = None,
    min_seeders: int | None = None,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
    limit: int = 20,
) -> list[TorrentResource]:
    stmt = select(TorrentResource)

    clean_keyword = keyword.strip()
    if clean_keyword:
        pattern = f"%{clean_keyword}%"
        stmt = stmt.where(
            TorrentResource.title.ilike(pattern)
            | TorrentResource.category.ilike(pattern)
            | TorrentResource.resolution.ilike(pattern)
            | TorrentResource.quality.ilike(pattern)
        )

    if category:
        stmt = stmt.where(TorrentResource.category.ilike(f"%{category.strip()}%"))
    if resolution:
        stmt = stmt.where(TorrentResource.resolution.ilike(f"%{resolution.strip()}%"))
    if quality:
        stmt = stmt.where(TorrentResource.quality.ilike(f"%{quality.strip()}%"))
    if min_seeders is not None:
        stmt = stmt.where(TorrentResource.seeders >= min_seeders)
    if min_size_bytes is not None:
        stmt = stmt.where(TorrentResource.size_bytes >= min_size_bytes)
    if max_size_bytes is not None:
        stmt = stmt.where(TorrentResource.size_bytes <= max_size_bytes)

    stmt = stmt.order_by(TorrentResource.seeders.desc(), TorrentResource.created_time.desc()).limit(limit)
    return list(session.scalars(stmt))


# --------------------------------------------------------------------------- #
# Download tasks
# --------------------------------------------------------------------------- #
def create_download_task(
    session: Session, resource_id: int, qb_hash: str | None, save_path: str | None
) -> DownloadTask:
    task = DownloadTask(
        resource_id=resource_id,
        qb_hash=qb_hash,
        task_status="queued",
        progress=0,
        save_path=save_path,
    )
    session.add(task)
    session.flush()
    return task


def update_download_task(
    session: Session, task_id: int, *, status: str | None = None, progress: float | None = None
) -> DownloadTask | None:
    task = session.get(DownloadTask, task_id)
    if not task:
        return None
    if status is not None:
        task.task_status = status
    if progress is not None:
        task.progress = progress
    session.flush()
    return task


def list_download_tasks(session: Session, limit: int = 50) -> list[DownloadTask]:
    return list(
        session.scalars(
            select(DownloadTask).order_by(DownloadTask.created_time.desc()).limit(limit)
        )
    )


# --------------------------------------------------------------------------- #
# Subscriptions & episodes
# --------------------------------------------------------------------------- #
def create_subscription(
    session: Session,
    *,
    title: str,
    media_type: str = "tv",
    season_no: int | None = None,
    quality: str | None = None,
    original_title: str | None = None,
) -> MediaSubscription:
    sub = MediaSubscription(
        title=title,
        original_title=original_title,
        media_type=media_type,
        season_no=season_no,
        quality=quality,
        follow_enabled=True,
        status="active",
    )
    session.add(sub)
    session.flush()
    return sub


def find_subscription(session: Session, title: str, season_no: int | None) -> MediaSubscription | None:
    stmt = select(MediaSubscription).where(MediaSubscription.title == title)
    if season_no is not None:
        stmt = stmt.where(MediaSubscription.season_no == season_no)
    return session.scalar(stmt)


def list_subscriptions(session: Session) -> list[MediaSubscription]:
    return list(session.scalars(select(MediaSubscription).order_by(MediaSubscription.id.desc())))


def list_active_subscriptions(session: Session) -> list[MediaSubscription]:
    return list(
        session.scalars(
            select(MediaSubscription).where(
                MediaSubscription.follow_enabled.is_(True),
                MediaSubscription.status == "active",
            )
        )
    )


def upsert_episode(
    session: Session,
    *,
    subscription_id: int,
    season_no: int,
    episode_no: int,
    downloaded: bool = False,
    torrent_resource_id: int | None = None,
) -> MediaEpisode:
    existing = session.scalar(
        select(MediaEpisode).where(
            MediaEpisode.subscription_id == subscription_id,
            MediaEpisode.season_no == season_no,
            MediaEpisode.episode_no == episode_no,
        )
    )
    if existing:
        if downloaded:
            existing.downloaded = True
        if torrent_resource_id:
            existing.torrent_resource_id = torrent_resource_id
        session.flush()
        return existing
    ep = MediaEpisode(
        subscription_id=subscription_id,
        season_no=season_no,
        episode_no=episode_no,
        downloaded=downloaded,
        torrent_resource_id=torrent_resource_id,
    )
    session.add(ep)
    session.flush()
    return ep


# --------------------------------------------------------------------------- #
# RSS
# --------------------------------------------------------------------------- #
def list_enabled_feeds(session: Session) -> list[RssFeed]:
    return list(session.scalars(select(RssFeed).where(RssFeed.enabled.is_(True))))


def rss_item_exists(session: Session, guid: str) -> bool:
    return session.scalar(select(RssItem.id).where(RssItem.guid == guid)) is not None


def create_rss_item(
    session: Session,
    *,
    feed_id: int,
    guid: str,
    title: str,
    link: str | None,
    publish_time: datetime | None,
) -> RssItem:
    item = RssItem(
        feed_id=feed_id,
        guid=guid,
        title=title,
        link=link,
        publish_time=publish_time,
        processed=False,
    )
    session.add(item)
    session.flush()
    return item


def mark_rss_item_processed(session: Session, item_id: int) -> None:
    item = session.get(RssItem, item_id)
    if item:
        item.processed = True
        session.flush()


def get_rss_item_by_link(session: Session, link: str) -> RssItem | None:
    """Get RssItem by download link (used for deduplication)."""
    return session.scalar(select(RssItem).where(RssItem.link == link))


def get_latest_rss_cache_time(session: Session) -> datetime | None:
    """Get timestamp of the most recent RSS cache entry."""
    latest = session.scalar(
        select(RssItem.created_time).order_by(RssItem.created_time.desc()).limit(1)
    )
    return latest


def list_cached_rss_items(session: Session, keyword: str = "", limit: int = 100) -> list[RssItem]:
    """List cached RSS items, optionally filtered by keyword."""
    query = select(RssItem).order_by(RssItem.created_time.desc()).limit(limit)
    if keyword:
        query = query.where(RssItem.title.ilike(f"%{keyword}%"))
    return list(session.scalars(query))


# --------------------------------------------------------------------------- #
# Scheduler monitoring
# --------------------------------------------------------------------------- #
def get_scheduler_job(session: Session, job_name: str) -> SchedulerJob | None:
    return session.scalar(select(SchedulerJob).where(SchedulerJob.job_name == job_name))


def list_scheduler_jobs(session: Session) -> list[SchedulerJob]:
    return list(session.scalars(select(SchedulerJob).order_by(SchedulerJob.job_name.asc())))


def upsert_scheduler_job(
    session: Session,
    *,
    job_name: str,
    job_type: str,
    interval_seconds: int,
) -> SchedulerJob:
    job = get_scheduler_job(session, job_name)
    if job:
        job.job_type = job_type
        job.interval_seconds = interval_seconds
        job.enabled = True
        session.flush()
        return job
    job = SchedulerJob(
        job_name=job_name,
        job_type=job_type,
        interval_seconds=interval_seconds,
        enabled=True,
        job_status="idle",
    )
    session.add(job)
    session.flush()
    return job


def update_scheduler_job(
    session: Session,
    job_name: str,
    **fields,
) -> SchedulerJob | None:
    job = get_scheduler_job(session, job_name)
    if not job:
        return None
    for key, value in fields.items():
        if hasattr(job, key):
            setattr(job, key, value)
    session.flush()
    return job


def create_scheduler_run(
    session: Session,
    *,
    job_name: str,
    payload: object | None = None,
) -> SchedulerJobRun:
    run = SchedulerJobRun(job_name=job_name, payload=_to_text(payload), run_status="running")
    session.add(run)
    session.flush()
    return run


def update_scheduler_run(
    session: Session,
    run_id: int,
    *,
    status: str | None = None,
    summary: object | None = None,
    error_message: str | None = None,
    finished_time: datetime | None = None,
) -> SchedulerJobRun | None:
    run = session.get(SchedulerJobRun, run_id)
    if not run:
        return None
    if status is not None:
        run.run_status = status
    if summary is not None:
        run.summary = _to_text(summary)
    if error_message is not None:
        run.error_message = error_message
    if finished_time is not None:
        run.finished_time = finished_time
    session.flush()
    return run


def list_scheduler_runs(session: Session, job_name: str | None = None, limit: int = 50) -> list[SchedulerJobRun]:
    stmt = select(SchedulerJobRun)
    if job_name:
        stmt = stmt.where(SchedulerJobRun.job_name == job_name)
    stmt = stmt.order_by(SchedulerJobRun.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def create_rss_item_cached(
    session: Session,
    *,
    title: str,
    link: str,
    raw_entry: str = "",
    cached_at: datetime | None = None,
) -> RssItem:
    """Create an RSS item without feed_id (used for cache entries)."""
    item = RssItem(
        feed_id=None,  # Cache entries don't belong to a specific feed
        guid=link,  # Use link as unique identifier for cache
        title=title,
        link=link,
        raw_data=raw_entry,
        publish_time=cached_at or datetime.utcnow(),
        processed=False,
    )
    session.add(item)
    session.flush()
    return item


# --------------------------------------------------------------------------- #
# Agent memory
# --------------------------------------------------------------------------- #
def set_memory(
    session: Session, *, memory_type: str, key: str, value: str, importance: int = 1
) -> AgentMemory:
    existing = session.scalar(
        select(AgentMemory).where(
            AgentMemory.memory_type == memory_type, AgentMemory.memory_key == key
        )
    )
    if existing:
        existing.memory_value = value
        existing.importance = importance
        session.flush()
        return existing
    mem = AgentMemory(
        memory_type=memory_type, memory_key=key, memory_value=value, importance=importance
    )
    session.add(mem)
    session.flush()
    return mem


def list_memories(session: Session, memory_type: str | None = None) -> list[AgentMemory]:
    stmt = select(AgentMemory).order_by(AgentMemory.importance.desc())
    if memory_type:
        stmt = stmt.where(AgentMemory.memory_type == memory_type)
    return list(session.scalars(stmt))


# --------------------------------------------------------------------------- #
# Agent tasks & execution trace
# --------------------------------------------------------------------------- #
def create_agent_task(session: Session, *, task_type: str, content: str) -> AgentTask:
    task = AgentTask(task_type=task_type, task_status="running", task_content=content)
    session.add(task)
    session.flush()
    return task


def finish_agent_task(session: Session, task_id: int, status: str = "completed") -> None:
    task = session.get(AgentTask, task_id)
    if task:
        task.task_status = status
        session.flush()


def log_execution(
    session: Session,
    *,
    task_id: int | None,
    step_name: str,
    tool_name: str | None,
    request_data: object | None = None,
    response_data: object | None = None,
) -> AgentExecutionLog:
    log = AgentExecutionLog(
        task_id=task_id,
        step_name=step_name,
        tool_name=tool_name,
        request_data=_to_text(request_data),
        response_data=_to_text(response_data),
    )
    session.add(log)
    session.flush()
    return log


def list_execution_logs(session: Session, task_id: int) -> list[AgentExecutionLog]:
    return list(
        session.scalars(
            select(AgentExecutionLog)
            .where(AgentExecutionLog.task_id == task_id)
            .order_by(AgentExecutionLog.id.asc())
        )
    )


def _to_text(data: object | None) -> str | None:
    if data is None:
        return None
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except TypeError:
        return str(data)
