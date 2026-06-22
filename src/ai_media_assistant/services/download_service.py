"""Download service — adds resources to qBittorrent and tracks tasks."""

from __future__ import annotations

from ..clients.qb import get_qb_client
from ..database import session_scope
from ..database import repositories as repo
from ..shared.config import get_settings
from ..shared.errors import DownloadError, GuardrailError, ResourceNotFoundError
from ..shared.logging import get_logger
from ..shared.schemas import DownloadStatus, DownloadTaskDTO

logger = get_logger(__name__)


class DownloadService:
    """Start and monitor downloads via qBittorrent."""

    def __init__(self) -> None:
        self._qb_client = None
        self._settings = get_settings()

    @property
    def _qb(self):
        # Lazy: connect to qBittorrent only when a download is actually needed,
        # so importing the service never fails if qBittorrent is offline.
        if self._qb_client is None:
            self._qb_client = get_qb_client()
        return self._qb_client

    def download(
        self,
        resource_id: int,
        confirm: bool = False,
        save_path: str | None = None,
    ) -> DownloadTaskDTO:
        """Add a resource to the download client.

        Guardrail: when ``AGENT_REQUIRE_DOWNLOAD_CONFIRM`` is enabled, the caller
        must pass ``confirm=True`` (an explicit human-in-the-loop approval).
        """
        if self._settings.agent_require_download_confirm and not confirm:
            raise GuardrailError(
                "Download requires explicit confirmation (set confirm=true)."
            )

        with session_scope() as session:
            resource = repo.get_resource(session, resource_id)
            if resource is None:
                raise ResourceNotFoundError(f"Resource {resource_id} not found")
            if not resource.download_url:
                raise DownloadError(f"Resource {resource_id} has no download URL")

            target_save_path = (save_path or "").strip() or self._settings.download_save_path

            torrent_hash = self._qb.add(
                resource.download_url,
                save_path=target_save_path,
                name=resource.title,
            )
            task = repo.create_download_task(
                session,
                resource_id=resource.id,
                qb_hash=torrent_hash,
                save_path=target_save_path,
            )
            dto = DownloadTaskDTO(
                id=task.id,
                resource_id=resource.id,
                qb_hash=torrent_hash,
                task_status=DownloadStatus.queued,
                progress=0.0,
                save_path=task.save_path,
                title=resource.title,
            )
        logger.info("Download started: resource=%s hash=%s", resource_id, torrent_hash)
        return dto

    def refresh(self, task_id: int) -> DownloadTaskDTO | None:
        """Poll qBittorrent and update a download task's progress/status."""
        with session_scope() as session:
            task = session.get(repo.DownloadTask, task_id)
            if task is None or not task.qb_hash:
                return None
            info = self._qb.status(task.qb_hash)
            if info is not None:
                task.task_status = info.state
                task.progress = round(info.progress * 100, 2)
                session.flush()
            return DownloadTaskDTO(
                id=task.id,
                resource_id=task.resource_id,
                qb_hash=task.qb_hash,
                task_status=DownloadStatus(task.task_status),
                progress=float(task.progress),
                save_path=task.save_path,
            )

    def list_tasks(self) -> list[DownloadTaskDTO]:
        with session_scope() as session:
            tasks = repo.list_download_tasks(session)
            return [
                DownloadTaskDTO(
                    id=t.id,
                    resource_id=t.resource_id,
                    qb_hash=t.qb_hash,
                    task_status=DownloadStatus(t.task_status),
                    progress=float(t.progress),
                    save_path=t.save_path,
                )
                for t in tasks
            ]
