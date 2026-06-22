"""Follow service — subscriptions, episode tracking and auto-completion."""

from __future__ import annotations

import re

from ..database import session_scope
from ..database import repositories as repo
from ..shared.logging import get_logger
from ..shared.schemas import EpisodeDTO, SubscriptionDTO, SubscriptionStatus
from .download_service import DownloadService
from .search_service import SearchService

logger = get_logger(__name__)


class FollowService:
    """Manage TV-show subscriptions and automatic episode downloads."""

    def __init__(self) -> None:
        self._search = SearchService()
        self._download = DownloadService()

    def follow_show(
        self,
        title: str,
        season: int | None = None,
        quality: str | None = None,
        confirm: bool = False,
    ) -> dict:
        """Create/return a subscription and download all available episodes."""
        with session_scope() as session:
            sub = repo.find_subscription(session, title, season)
            if sub is None:
                sub = repo.create_subscription(
                    session, title=title, media_type="tv", season_no=season, quality=quality
                )
            sub_id = sub.id

        # Search for currently available episodes and download them.
        keyword = f"{title} S{season:02d}" if season else title
        result = self._search.search(keyword)
        downloaded: list[int] = []
        for res in result.resources:
            parsed = _parse_se(res.title)
            if not parsed:
                continue
            s_no, e_no = parsed
            if season is not None and s_no != season:
                continue
            try:
                task = self._download.download(res.id, confirm=confirm)
            except Exception as exc:  # noqa: BLE001 - keep following other episodes
                logger.warning("Episode download failed (%s): %s", res.title, exc)
                continue
            with session_scope() as session:
                repo.upsert_episode(
                    session,
                    subscription_id=sub_id,
                    season_no=s_no,
                    episode_no=e_no,
                    downloaded=True,
                    torrent_resource_id=res.id,
                )
            downloaded.append(e_no)
            logger.info("Followed %s S%02dE%02d (task=%s)", title, s_no, e_no, task.id)

        return {
            "subscription_id": sub_id,
            "title": title,
            "season": season,
            "episodes_downloaded": sorted(set(downloaded)),
        }

    def handle_release(
        self, show_title: str, season: int, episode: int, confirm: bool = False
    ) -> dict | None:
        """Auto-complete an episode discovered via RSS, if it matches a sub."""
        with session_scope() as session:
            sub = _match_subscription(session, show_title, season)
            if sub is None:
                logger.debug("No subscription matches '%s' S%02d", show_title, season)
                return None
            sub_id, sub_title = sub.id, sub.title
            already = any(
                ep.episode_no == episode and ep.season_no == season and ep.downloaded
                for ep in sub.episodes
            )
        if already:
            return None

        best = self._search.best_match(f"{show_title} S{season:02d}E{episode:02d}")
        if best is None:
            return None
        task = self._download.download(best.id, confirm=confirm)
        with session_scope() as session:
            repo.upsert_episode(
                session,
                subscription_id=sub_id,
                season_no=season,
                episode_no=episode,
                downloaded=True,
                torrent_resource_id=best.id,
            )
        logger.info("Auto-completed %s S%02dE%02d", sub_title, season, episode)
        return {"subscription_id": sub_id, "season": season, "episode": episode, "task_id": task.id}

    def list_subscriptions(self) -> list[SubscriptionDTO]:
        with session_scope() as session:
            subs = repo.list_subscriptions(session)
            return [
                SubscriptionDTO(
                    id=s.id,
                    title=s.title,
                    original_title=s.original_title,
                    media_type=s.media_type or "tv",
                    season_no=s.season_no,
                    quality=s.quality,
                    follow_enabled=bool(s.follow_enabled),
                    status=SubscriptionStatus(s.status or "active"),
                )
                for s in subs
            ]

    def list_episodes(self, subscription_id: int) -> list[EpisodeDTO]:
        with session_scope() as session:
            sub = session.get(repo.MediaSubscription, subscription_id)
            if not sub:
                return []
            return [
                EpisodeDTO(
                    id=e.id,
                    subscription_id=e.subscription_id,
                    season_no=e.season_no,
                    episode_no=e.episode_no,
                    downloaded=bool(e.downloaded),
                    torrent_resource_id=e.torrent_resource_id,
                )
                for e in sub.episodes
            ]


def _parse_se(title: str) -> tuple[int, int] | None:
    m = re.search(r"S(\d{1,2})E(\d{1,3})", title, re.IGNORECASE)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _match_subscription(session, show_title: str, season: int):  # noqa: ANN001
    norm = re.sub(r"[^a-z0-9]+", "", show_title.lower())
    for sub in repo.list_active_subscriptions(session):
        sub_norm = re.sub(r"[^a-z0-9]+", "", sub.title.lower())
        if (norm in sub_norm or sub_norm in norm) and (
            sub.season_no is None or sub.season_no == season
        ):
            return sub
    return None
