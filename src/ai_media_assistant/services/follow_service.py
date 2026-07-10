"""Follow service — subscriptions, episode tracking and auto-completion."""

from __future__ import annotations

import re
from time import monotonic

from ..clients.rss import parse_episode
from ..database import session_scope
from ..database import repositories as repo
from ..shared.config import get_settings
from ..shared.logging import get_logger
from ..shared.schemas import EpisodeDTO, SubscriptionDTO, SubscriptionStatus, TorrentResourceDTO
from .download_service import DownloadService
from .search_service import SearchService

logger = get_logger(__name__)


class FollowService:
    """Manage TV-show subscriptions and automatic episode downloads."""

    # Keep follow_show responsive for MCP callers: do partial initial backfill,
    # then let scheduler auto-follow handle later/new episodes.
    _INITIAL_DOWNLOAD_LIMIT = 6
    _INITIAL_DOWNLOAD_BUDGET_SECONDS = 8.0
    _LEGACY_TV_BASE_PATH = "/downloads/newvideo/tv"
    _DEFAULT_TV_BASE_PATH = "/downloads/video/tv"

    def __init__(self) -> None:
        self._search = SearchService()
        self._download = DownloadService()
        self._settings = get_settings()

    def follow_show(
        self,
        title: str,
        season: int | None = None,
        quality: str | None = None,
        confirm: bool = False,
        initial_sync: bool = True,
    ) -> dict:
        """Create/return a subscription and download all available episodes."""
        with session_scope() as session:
            sub = repo.find_subscription(session, title, season)
            if sub is None:
                sub = repo.create_subscription(
                    session, title=title, media_type="tv", season_no=season, quality=quality
                )
            sub_id = sub.id

        if not initial_sync:
            return {
                "subscription_id": sub_id,
                "title": title,
                "season": season,
                "episodes_downloaded": [],
                "initial_sync_skipped": True,
                "detail": "Subscription created. Scheduler will auto-follow new releases.",
            }

        # Search for currently available episodes and download them.
        started_at = monotonic()
        keyword = f"{title} S{season:02d}" if season else title
        result = self._search.search(keyword, limit=30)
        downloaded: list[int] = []
        timed_out = False
        capped = False
        candidates = _pick_best_per_episode(result.resources, season=season, quality=quality)
        for res in candidates:
            if len(downloaded) >= self._INITIAL_DOWNLOAD_LIMIT:
                capped = True
                break
            if (monotonic() - started_at) >= self._INITIAL_DOWNLOAD_BUDGET_SECONDS:
                timed_out = True
                break

            parsed = _parse_se(res.title)
            if not parsed:
                continue
            s_no, e_no = parsed
            save_path = self._episode_save_path(title, s_no, resource_title=res.title)
            try:
                task = self._download.download(res.id, confirm=confirm, save_path=save_path)
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

        payload = {
            "subscription_id": sub_id,
            "title": title,
            "season": season,
            "episodes_downloaded": sorted(set(downloaded)),
        }
        if timed_out or capped:
            payload["initial_sync_partial"] = True
            payload["detail"] = (
                "Initial follow sync stopped early to keep response fast; "
                "scheduler will continue auto-following new releases."
            )
        return payload

    def handle_release(
        self,
        show_title: str,
        season: int,
        episode: int,
        confirm: bool = False,
        release_title: str | None = None,
    ) -> dict | None:
        """Auto-complete an episode discovered via RSS, if it matches a sub."""
        with session_scope() as session:
            sub = _match_subscription(session, show_title, season, release_title=release_title)
            if sub is None:
                logger.debug("No subscription matches '%s' S%02d", show_title, season)
                return None
            sub_id, sub_title, preferred_variant = sub.id, sub.title, (sub.quality or "")
            already = any(
                ep.episode_no == episode and ep.season_no == season and ep.downloaded
                for ep in sub.episodes
            )
        if already:
            return None

        query_title = sub_title or show_title
        result = self._search.search(f"{query_title} S{season:02d}E{episode:02d}", limit=30)
        candidates = result.resources
        if preferred_variant:
            candidates = [r for r in candidates if _matches_variant(preferred_variant, r)]
        best = candidates[0] if candidates else None
        if best is None:
            logger.info(
                "No matching release for %s S%02dE%02d (preferred_variant=%s)",
                show_title,
                season,
                episode,
                preferred_variant or "any",
            )
            return None
        save_path = self._episode_save_path(sub_title or show_title, season, resource_title=best.title)
        task = self._download.download(best.id, confirm=confirm, save_path=save_path)
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

    def reconcile_subscription(self, subscription_id: int, confirm: bool = False) -> dict:
        """Backfill missing episodes for an existing subscription."""
        with session_scope() as session:
            sub = session.get(repo.MediaSubscription, subscription_id)
            if not sub:
                return {"subscription_id": subscription_id, "checked": 0, "downloaded": []}

            title = sub.title
            season = sub.season_no
            quality = sub.quality
            downloaded_keys = {
                (ep.season_no, ep.episode_no)
                for ep in sub.episodes
                if ep.downloaded
            }

        keyword = f"{title} S{season:02d}" if season else title
        result = self._search.search(keyword, limit=30)
        candidates = _pick_best_per_episode(result.resources, season=season, quality=quality)

        checked = 0
        downloaded: list[int] = []
        for res in candidates:
            parsed = _parse_se(res.title)
            if not parsed:
                continue
            s_no, e_no = parsed
            checked += 1
            if (s_no, e_no) in downloaded_keys:
                continue

            save_path = self._episode_save_path(title, s_no, resource_title=res.title)
            try:
                self._download.download(res.id, confirm=confirm, save_path=save_path)
            except Exception as exc:  # noqa: BLE001 - keep reconciliation resilient
                logger.warning("Subscription reconcile download failed (%s): %s", res.title, exc)
                continue

            with session_scope() as session:
                repo.upsert_episode(
                    session,
                    subscription_id=subscription_id,
                    season_no=s_no,
                    episode_no=e_no,
                    downloaded=True,
                    torrent_resource_id=res.id,
                )
            downloaded.append(e_no)
            downloaded_keys.add((s_no, e_no))

        return {
            "subscription_id": subscription_id,
            "checked": checked,
            "downloaded": sorted(set(downloaded)),
        }

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

    def _episode_save_path(self, show_title: str, season: int, resource_title: str | None = None) -> str:
        configured_base = (
            self._settings.follow_tv_base_path
            or self._settings.download_save_path
            or self._DEFAULT_TV_BASE_PATH
        ).rstrip("/")
        # Keep old configs compatible but migrate to the new standard TV path.
        base = (
            self._DEFAULT_TV_BASE_PATH
            if configured_base == self._LEGACY_TV_BASE_PATH
            else configured_base
        )
        show = _episode_show_dir_name(show_title, resource_title=resource_title)
        return f"{base}/{show}/Season {season:02d}/"


def _parse_se(title: str) -> tuple[int, int] | None:
    m = re.search(r"S(\d{1,2})E(\d{1,3})", title, re.IGNORECASE)
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_release_title(title: str) -> tuple[str, int, int] | None:
    parsed = parse_episode(title or "")
    if not parsed:
        return None
    show = re.sub(r"\s+", " ", (parsed.show_title or "").strip())
    if not show:
        return None
    return show, int(parsed.season), int(parsed.episode)


def _matches_variant(preferred: str, resource) -> bool:  # noqa: ANN001
    token = (preferred or "").strip().upper()
    if not token:
        return True
    alias = {
        "4K": "2160P",
        "UHD": "2160P",
    }
    token = alias.get(token, token)

    title = (resource.title or "").upper()
    resolution = (resource.resolution or "").upper()
    quality = (resource.quality or "").upper()
    return token in title or token in resolution or token in quality


def _match_subscription(
    session,
    show_title: str,
    season: int,
    *,
    release_title: str | None = None,
):  # noqa: ANN001
    norm = _normalize_title(show_title)
    raw_norm = _normalize_title(release_title or "")
    if not norm and not raw_norm:
        return None
    for sub in repo.list_active_subscriptions(session):
        sub_norm = _normalize_title(sub.title)
        if not sub_norm:
            continue
        if (
            _title_matches_subscription(norm, sub_norm)
            or _title_matches_subscription(raw_norm, sub_norm)
        ) and (
            sub.season_no is None or sub.season_no == season
        ):
            return sub
    return None


def _normalize_title(text: str) -> str:
    # Keep latin/digits and CJK chars, remove separators and punctuation.
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (text or "").lower())


def _title_matches_subscription(show_norm: str, sub_norm: str) -> bool:
    # Guard against accidental universal matches like empty strings.
    if not show_norm or not sub_norm:
        return False
    return show_norm in sub_norm or sub_norm in show_norm


def _safe_dir_name(text: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    # Use dotted style to avoid spaces in NAS paths.
    cleaned = cleaned.replace(" ", ".")
    cleaned = re.sub(r"\.+", ".", cleaned).strip(".")
    return cleaned or "Unknown.Show"


def _episode_show_dir_name(show_title: str, resource_title: str | None = None) -> str:
    english = _extract_english_show_name(show_title)
    if not english and resource_title:
        english = _extract_english_show_name(resource_title)
    chosen = english or show_title
    return _safe_dir_name(chosen)


def _extract_english_show_name(text: str) -> str | None:
    candidate = re.sub(r"^\[[^\]]+\]\s*", "", text or "").strip()
    if not candidate:
        return None

    # Prefer titles before SxxEyy / Season xx markers.
    patterns = (
        r"(?P<name>[A-Za-z][A-Za-z0-9 '&.\-]{2,}?)\s+S\d{1,2}(?:[ ._\-]*E\d{1,3})\b",
        r"(?P<name>[A-Za-z][A-Za-z0-9 '&.\-]{2,}?)\s+Season\s+\d{1,2}\b",
    )
    for pattern in patterns:
        m = re.search(pattern, candidate, re.IGNORECASE)
        if m:
            name = re.sub(r"\s+", " ", (m.group("name") or "").strip())
            return name.strip("-._ ") or None

    # If the text starts with latin words, take the leading latin chunk.
    m = re.match(r"(?P<name>[A-Za-z][A-Za-z0-9 '&.\-]{2,})", candidate)
    if m:
        name = re.sub(r"\s+", " ", (m.group("name") or "").strip())
        return name.strip("-._ ") or None
    return None


def _pick_best_per_episode(
    resources: list[TorrentResourceDTO],
    *,
    season: int | None,
    quality: str | None,
) -> list[TorrentResourceDTO]:
    picked: list[TorrentResourceDTO] = []
    seen: set[tuple[int, int]] = set()
    for res in resources:
        parsed = _parse_se(res.title)
        if not parsed:
            continue
        s_no, e_no = parsed
        if season is not None and s_no != season:
            continue
        if quality and not _matches_variant(quality, res):
            continue
        key = (s_no, e_no)
        if key in seen:
            continue
        seen.add(key)
        picked.append(res)
    return picked
