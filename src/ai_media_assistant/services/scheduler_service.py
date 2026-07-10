"""Scheduler management for RSS sync and download refresh jobs."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
import json
from threading import Lock
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from ..database import session_scope
from ..database import repositories as repo
from ..shared.logging import get_logger
from .download_service import DownloadService
from .follow_service import FollowService, parse_release_title
from .rss_cache_service import RssCacheService

logger = get_logger(__name__)


@dataclass(slots=True)
class JobControlResult:
    job_name: str
    status: str
    detail: str


class SchedulerManager:
    """Owns the application scheduler and persists run state in MySQL/SQLite."""

    _AUTO_FOLLOW_RECENT_SCAN_LIMIT = 200

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._download = DownloadService()
        self._follow = FollowService()
        self._lock = Lock()
        self._started = False
        self._registered = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._register_jobs()
            self._scheduler.start()
            self._started = True
            logger.info("Scheduler manager started")

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            if not self._started:
                return
            self._scheduler.shutdown(wait=wait)
            self._started = False
            logger.info("Scheduler manager stopped")

    def is_running(self) -> bool:
        return self._started and self._scheduler.running

    # ------------------------------------------------------------------ #
    # Public controls
    # ------------------------------------------------------------------ #
    def pause_job(self, job_name: str) -> JobControlResult:
        self._scheduler.pause_job(job_name)
        with session_scope() as session:
            repo.update_scheduler_job(session, job_name, enabled=False, job_status="paused")
        return JobControlResult(job_name=job_name, status="paused", detail="job paused")

    def resume_job(self, job_name: str) -> JobControlResult:
        self._scheduler.resume_job(job_name)
        with session_scope() as session:
            repo.update_scheduler_job(session, job_name, enabled=True, job_status="idle")
        return JobControlResult(job_name=job_name, status="running", detail="job resumed")

    def restart_job(self, job_name: str) -> JobControlResult:
        with suppress(Exception):
            self._scheduler.remove_job(job_name)
        self._register_jobs(force=True)
        with session_scope() as session:
            repo.update_scheduler_job(session, job_name, enabled=True, job_status="idle")
        return JobControlResult(job_name=job_name, status="restarted", detail="job rescheduled")

    def run_job_now(self, job_name: str) -> JobControlResult:
        if job_name == "rss_sync":
            self._run_rss_sync()
            return JobControlResult(job_name=job_name, status="triggered", detail="rss sync executed")
        if job_name == "download_refresh":
            self._refresh_downloads()
            return JobControlResult(job_name=job_name, status="triggered", detail="download refresh executed")
        raise ValueError(f"unknown job: {job_name}")

    def pause_all(self) -> None:
        self._scheduler.pause()
        with session_scope() as session:
            for job in repo.list_scheduler_jobs(session):
                repo.update_scheduler_job(session, job.job_name, enabled=False, job_status="paused")

    def resume_all(self) -> None:
        self._scheduler.resume()
        with session_scope() as session:
            for job in repo.list_scheduler_jobs(session):
                repo.update_scheduler_job(session, job.job_name, enabled=True, job_status="idle")

    # ------------------------------------------------------------------ #
    # Status / history
    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict[str, Any]:
        with session_scope() as session:
            jobs = []
            for job in repo.list_scheduler_jobs(session):
                aps_job = self._scheduler.get_job(job.job_name) if self._started else None
                jobs.append(
                    {
                        "job_name": job.job_name,
                        "job_type": job.job_type,
                        "enabled": job.enabled,
                        "job_status": job.job_status,
                        "interval_seconds": job.interval_seconds,
                        "last_started_time": self._fmt(job.last_started_time),
                        "last_finished_time": self._fmt(job.last_finished_time),
                        "last_success_time": self._fmt(job.last_success_time),
                        "next_run_time": self._fmt(getattr(aps_job, "next_run_time", None) or job.next_run_time),
                        "total_runs": job.total_runs,
                        "success_runs": job.success_runs,
                        "failure_runs": job.failure_runs,
                        "last_summary": job.last_summary,
                        "last_error": job.last_error,
                    }
                )
            recent_runs = [
                {
                    "id": run.id,
                    "job_name": run.job_name,
                    "run_status": run.run_status,
                    "started_time": self._fmt(run.started_time),
                    "finished_time": self._fmt(run.finished_time),
                    "duration_seconds": run.duration_seconds,
                    "summary": run.summary,
                    "error_message": run.error_message,
                }
                for run in repo.list_scheduler_runs(session, limit=20)
            ]
        return {
            "running": self.is_running(),
            "jobs": jobs,
            "recent_runs": recent_runs,
        }

    # ------------------------------------------------------------------ #
    # Job registration / execution
    # ------------------------------------------------------------------ #
    def _register_jobs(self, force: bool = False) -> None:
        if self._registered and not force:
            return

        self._ensure_job(
            "rss_sync",
            "interval",
            minutes=10,
            func=self._run_rss_sync,
        )
        self._ensure_job(
            "download_refresh",
            "interval",
            seconds=30,
            func=self._refresh_downloads,
        )
        self._registered = True

    def _ensure_job(self, job_name: str, trigger: str, func, **trigger_kwargs: Any) -> None:
        self._scheduler.add_job(
            func,
            trigger,
            id=job_name,
            replace_existing=True,
            **trigger_kwargs,
        )
        interval_seconds = trigger_kwargs.get("minutes", 0) * 60 + trigger_kwargs.get("seconds", 0)
        if trigger_kwargs.get("hours"):
            interval_seconds += trigger_kwargs["hours"] * 3600
        with session_scope() as session:
            job = repo.upsert_scheduler_job(
                session,
                job_name=job_name,
                job_type=job_name,
                interval_seconds=interval_seconds or 600,
            )
            job.next_run_time = self._job_next_run_time(job_name)

    def _run_rss_sync(self) -> None:
        def _runner() -> dict[str, Any]:
            summary = RssCacheService.refresh_latest_resources()
            auto_follow_downloads = 0
            considered_releases = 0
            reconcile_downloads = 0
            reconciled_subscriptions = 0
            releases: list[dict[str, Any]] = []
            releases.extend(summary.get("new_resources", []))

            # Backfill recent cached rows too, so episodes missed in a prior run
            # can still be auto-followed after parser/matching improvements.
            with session_scope() as session:
                for row in repo.list_recent_resources(session, limit=self._AUTO_FOLLOW_RECENT_SCAN_LIMIT):
                    releases.append({"id": row.id, "title": row.title})

            seen_ids: set[int] = set()
            seen_titles: set[str] = set()
            for item in releases:
                item_id = item.get("id")
                title = str(item.get("title") or "")
                if not title:
                    continue
                if isinstance(item_id, int):
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                elif title in seen_titles:
                    continue
                seen_titles.add(title)

                parsed = parse_release_title(str(item.get("title") or ""))
                if not parsed:
                    continue
                show_title, season, episode = parsed
                considered_releases += 1
                try:
                    result = self._follow.handle_release(
                        show_title,
                        season,
                        episode,
                        confirm=True,
                        release_title=title,
                    )
                    if result:
                        auto_follow_downloads += 1
                except Exception as exc:  # noqa: BLE001 - keep job resilient
                    logger.warning(
                        "Auto-follow release handling failed for '%s' S%02dE%02d: %s",
                        show_title,
                        season,
                        episode,
                        exc,
                    )

            with session_scope() as session:
                active_subs = [s.id for s in repo.list_active_subscriptions(session)]
            for sub_id in active_subs:
                try:
                    r = self._follow.reconcile_subscription(sub_id, confirm=True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Subscription reconcile failed for sub=%s: %s", sub_id, exc)
                    continue
                reconciled_subscriptions += 1
                reconcile_downloads += len(r.get("downloaded", []))

            summary["auto_follow_scan_total"] = len(releases)
            summary["considered_releases"] = considered_releases
            summary["auto_follow_downloads"] = auto_follow_downloads
            summary["reconciled_subscriptions"] = reconciled_subscriptions
            summary["reconcile_downloads"] = reconcile_downloads
            return summary

        self._execute_job("rss_sync", _runner)

    def _refresh_downloads(self) -> None:
        def _runner() -> dict[str, Any]:
            refreshed = 0
            failed = 0
            with session_scope() as session:
                task_ids = [
                    t.id
                    for t in repo.list_download_tasks(session)
                    if t.task_status in ("queued", "downloading")
                ]
            for task_id in task_ids:
                try:
                    self._download.refresh(task_id)
                    refreshed += 1
                except Exception as exc:  # noqa: BLE001 - per-task isolation
                    failed += 1
                    logger.warning("Download refresh failed for task %s: %s", task_id, exc)
            return {
                "refreshed_download_tasks": refreshed,
                "failed_download_tasks": failed,
            }

        self._execute_job("download_refresh", _runner)

    def _execute_job(self, job_name: str, runner) -> None:
        started_at = datetime.utcnow()
        with session_scope() as session:
            job = repo.upsert_scheduler_job(
                session,
                job_name=job_name,
                job_type=job_name,
                interval_seconds=self._interval_seconds(job_name),
            )
            job.job_status = "running"
            job.last_started_time = started_at
            job.total_runs += 1
            run = repo.create_scheduler_run(session, job_name=job_name)
            run_id = run.id

        try:
            payload = runner()
            finished_at = datetime.utcnow()
            summary = payload if isinstance(payload, dict) else {"result": payload}
            next_run = self._job_next_run_time(job_name)
            with session_scope() as session:
                repo.update_scheduler_run(
                    session,
                    run_id,
                    status="success",
                    summary=summary,
                    finished_time=finished_at,
                )
                current = repo.get_scheduler_job(session, job_name)
                job = repo.update_scheduler_job(
                    session,
                    job_name,
                    job_status="idle",
                    last_finished_time=finished_at,
                    last_success_time=finished_at,
                    last_summary=json.dumps(summary, ensure_ascii=False, default=str),
                    last_error=None,
                    next_run_time=next_run,
                    success_runs=(current.success_runs + 1) if current else 1,
                    failure_runs=current.failure_runs if current else 0,
                )
            logger.info("Scheduler job '%s' completed: %s", job_name, summary)
        except Exception as exc:  # noqa: BLE001
            finished_at = datetime.utcnow()
            next_run = self._job_next_run_time(job_name)
            with session_scope() as session:
                repo.update_scheduler_run(
                    session,
                    run_id,
                    status="failed",
                    error_message=str(exc),
                    finished_time=finished_at,
                )
                current = repo.get_scheduler_job(session, job_name)
                repo.update_scheduler_job(
                    session,
                    job_name,
                    job_status="error",
                    last_finished_time=finished_at,
                    last_error=str(exc),
                    failure_runs=(current.failure_runs + 1) if current else 1,
                    next_run_time=next_run,
                )
            logger.exception("Scheduler job '%s' failed", job_name)

    def _interval_seconds(self, job_name: str) -> int:
        if job_name == "rss_sync":
            return 600
        if job_name == "download_refresh":
            return 30
        return 600

    def _job_next_run_time(self, job_name: str):
        job = self._scheduler.get_job(job_name)
        if not job:
            return None
        # APScheduler may return different job objects before scheduler start;
        # use getattr for compatibility across states/versions.
        return getattr(job, "next_run_time", None)

    @staticmethod
    def _fmt(value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value


_scheduler_manager: SchedulerManager | None = None


def get_scheduler_manager() -> SchedulerManager:
    global _scheduler_manager
    if _scheduler_manager is None:
        _scheduler_manager = SchedulerManager()
    return _scheduler_manager
