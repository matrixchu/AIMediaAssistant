"""Pydantic DTOs shared across services, API and agent tools."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    movie = "movie"
    tv = "tv"


class DownloadStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    completed = "completed"
    error = "error"
    paused = "paused"


class SubscriptionStatus(str, Enum):
    active = "active"
    paused = "paused"
    completed = "completed"


# --------------------------------------------------------------------------- #
# Resources / search
# --------------------------------------------------------------------------- #
class TorrentResourceDTO(BaseModel):
    id: int | None = None
    site_name: str
    title: str
    category: str | None = None
    resolution: str | None = None
    quality: str | None = None
    size_bytes: int = 0
    seeders: int = 0
    leechers: int = 0
    detail_url: str | None = None
    download_url: str | None = None
    publish_time: datetime | None = None

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / (1024**3), 2)


class SearchResult(BaseModel):
    keyword: str
    resources: list[TorrentResourceDTO] = Field(default_factory=list)


class SearchQuery(BaseModel):
    keyword: str = ""
    category: str | None = None
    resolution: str | None = None
    quality: str | None = None
    min_seeders: int | None = None
    min_size_gb: float | None = None
    max_size_gb: float | None = None


# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #
class DownloadTaskDTO(BaseModel):
    id: int | None = None
    resource_id: int | None = None
    qb_hash: str | None = None
    task_status: DownloadStatus = DownloadStatus.queued
    progress: float = 0.0
    save_path: str | None = None
    title: str | None = None


# --------------------------------------------------------------------------- #
# Subscriptions / episodes
# --------------------------------------------------------------------------- #
class SubscriptionDTO(BaseModel):
    id: int | None = None
    title: str
    original_title: str | None = None
    media_type: MediaType = MediaType.tv
    season_no: int | None = None
    quality: str | None = None
    follow_enabled: bool = True
    status: SubscriptionStatus = SubscriptionStatus.active


class EpisodeDTO(BaseModel):
    id: int | None = None
    subscription_id: int
    season_no: int
    episode_no: int
    downloaded: bool = False
    torrent_resource_id: int | None = None


# --------------------------------------------------------------------------- #
# Recommendations
# --------------------------------------------------------------------------- #
class RecommendationDTO(BaseModel):
    title: str
    reason: str
    score: float = 0.0
    resource: TorrentResourceDTO | None = None


# --------------------------------------------------------------------------- #
# Agent interaction
# --------------------------------------------------------------------------- #
class AgentRequest(BaseModel):
    message: str
    confirm: bool = False  # explicit confirmation for sensitive actions


class AgentStep(BaseModel):
    step_name: str
    tool_name: str | None = None
    detail: str | None = None


class AgentResponse(BaseModel):
    reply: str
    steps: list[AgentStep] = Field(default_factory=list)
    task_id: int | None = None
