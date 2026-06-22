"""ORM models mapping the schema defined in Design.md.

Tables: media_subscription, media_episode, torrent_resource, download_task,
rss_feed, rss_item, agent_memory, agent_task, agent_execution_log.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# BigInteger maps to MySQL BIGINT, but SQLite only autoincrements INTEGER PRIMARY
# KEY. This variant keeps BIGINT on MySQL while letting SQLite autoincrement.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class TimestampMixin:
    created_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_time: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- #
# Subscriptions & episodes
# --------------------------------------------------------------------------- #
class MediaSubscription(Base, TimestampMixin):
    __tablename__ = "media_subscription"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(20))
    season_no: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[str | None] = mapped_column(String(50))
    follow_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str | None] = mapped_column(String(20), default="active")

    episodes: Mapped[list["MediaEpisode"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )


class MediaEpisode(Base):
    __tablename__ = "media_episode"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("media_subscription.id"), nullable=False
    )
    season_no: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_no: Mapped[int] = mapped_column(Integer, nullable=False)
    downloaded: Mapped[bool] = mapped_column(Boolean, default=False)
    torrent_resource_id: Mapped[int | None] = mapped_column(BigInteger)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    subscription: Mapped[MediaSubscription] = relationship(back_populates="episodes")


# --------------------------------------------------------------------------- #
# Resources & downloads
# --------------------------------------------------------------------------- #
class TorrentResource(Base):
    __tablename__ = "torrent_resource"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    site_name: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(50))
    resolution: Mapped[str | None] = mapped_column(String(20))
    quality: Mapped[str | None] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    seeders: Mapped[int] = mapped_column(Integer, default=0)
    leechers: Mapped[int] = mapped_column(Integer, default=0)
    detail_url: Mapped[str | None] = mapped_column(Text)
    download_url: Mapped[str | None] = mapped_column(Text)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class DownloadTask(Base, TimestampMixin):
    __tablename__ = "download_task"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    resource_id: Mapped[int | None] = mapped_column(BigInteger)
    qb_hash: Mapped[str | None] = mapped_column(String(100))
    task_status: Mapped[str] = mapped_column(String(50), default="queued")
    progress: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    save_path: Mapped[str | None] = mapped_column(String(500))


# --------------------------------------------------------------------------- #
# RSS
# --------------------------------------------------------------------------- #
class RssFeed(Base):
    __tablename__ = "rss_feed"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    feed_name: Mapped[str | None] = mapped_column(String(100))
    feed_url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class RssItem(Base):
    __tablename__ = "rss_item"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    feed_id: Mapped[int | None] = mapped_column(BigInteger)
    guid: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(Text)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# --------------------------------------------------------------------------- #
# Agent memory / tasks / execution trace
# --------------------------------------------------------------------------- #
class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    memory_type: Mapped[str | None] = mapped_column(String(50))
    memory_key: Mapped[str | None] = mapped_column(String(100))
    memory_value: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(Integer, default=1)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AgentTask(Base):
    __tablename__ = "agent_task"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    task_type: Mapped[str | None] = mapped_column(String(50))
    task_status: Mapped[str | None] = mapped_column(String(50), default="pending")
    task_content: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AgentExecutionLog(Base):
    __tablename__ = "agent_execution_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(BigInteger)
    step_name: Mapped[str | None] = mapped_column(String(100))
    tool_name: Mapped[str | None] = mapped_column(String(100))
    request_data: Mapped[str | None] = mapped_column(Text)
    response_data: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())



# --------------------------------------------------------------------------- #
# Scheduler / monitoring
# --------------------------------------------------------------------------- #
class SchedulerJob(Base, TimestampMixin):
     __tablename__ = "scheduler_job"

     id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
     job_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
     job_type: Mapped[str] = mapped_column(String(50), nullable=False)
     enabled: Mapped[bool] = mapped_column(Boolean, default=True)
     job_status: Mapped[str] = mapped_column(String(50), default="idle")
     interval_seconds: Mapped[int] = mapped_column(Integer, default=600)
     last_started_time: Mapped[datetime | None] = mapped_column(DateTime)
     last_finished_time: Mapped[datetime | None] = mapped_column(DateTime)
     last_success_time: Mapped[datetime | None] = mapped_column(DateTime)
     next_run_time: Mapped[datetime | None] = mapped_column(DateTime)
     total_runs: Mapped[int] = mapped_column(Integer, default=0)
     success_runs: Mapped[int] = mapped_column(Integer, default=0)
     failure_runs: Mapped[int] = mapped_column(Integer, default=0)
     last_summary: Mapped[str | None] = mapped_column(Text)
     last_error: Mapped[str | None] = mapped_column(Text)


class SchedulerJobRun(Base):
     __tablename__ = "scheduler_job_run"

     id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
     job_name: Mapped[str] = mapped_column(String(100), nullable=False)
     run_status: Mapped[str] = mapped_column(String(50), default="running")
     started_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())
     finished_time: Mapped[datetime | None] = mapped_column(DateTime)
     duration_seconds: Mapped[int | None] = mapped_column(Integer)
     summary: Mapped[str | None] = mapped_column(Text)
     error_message: Mapped[str | None] = mapped_column(Text)
     payload: Mapped[str | None] = mapped_column(Text)
