"""Real qBittorrent client backed by the qbittorrent-api package."""

from __future__ import annotations

import os
import re
import tempfile
import time
from typing import Callable, TypeVar
from urllib.parse import urlsplit

import httpx

from ...shared.config import get_settings
from ...shared.errors import DownloadError
from ...shared.logging import get_logger
from .base import QBClient, TorrentInfo

logger = get_logger(__name__)

# Map qBittorrent states to our simplified vocabulary.
_STATE_MAP = {
    "downloading": "downloading",
    "stalledDL": "downloading",
    "metaDL": "downloading",
    "forcedDL": "downloading",
    "checkingDL": "downloading",
    "queuedDL": "queued",
    "pausedDL": "paused",
    "stoppedDL": "paused",
    "uploading": "completed",
    "stalledUP": "completed",
    "pausedUP": "completed",
    "stoppedUP": "completed",
    "queuedUP": "completed",
    "forcedUP": "completed",
    "checkingUP": "completed",
    "error": "error",
    "missingFiles": "error",
}

_MAGNET_BTIH = re.compile(r"btih:([0-9a-fA-F]{40}|[A-Za-z2-7]{32})")
_T = TypeVar("_T")


class RealQBClient(QBClient):
    def __init__(self) -> None:
        import qbittorrentapi  # imported lazily so the package is optional

        settings = get_settings()
        self._category = settings.qb_category
        self._client = qbittorrentapi.Client(
            host=settings.qb_host,
            username=settings.qb_username,
            password=settings.qb_password,
        )
        self._connect_or_raise(initial=True)

    def _connect_or_raise(self, initial: bool = False) -> None:
        import qbittorrentapi

        attempts = 3
        last_exc: Exception | None = None
        for idx in range(attempts):
            try:
                self._client.auth_log_in()
                if initial:
                    logger.info("Connected to qBittorrent %s", self._client.app.version)
                return
            except qbittorrentapi.APIError as exc:  # pragma: no cover - network
                last_exc = exc
                if idx < attempts - 1:
                    time.sleep(0.5)
        raise DownloadError(f"qBittorrent login failed: {last_exc}") from last_exc

    def _call_with_reconnect(self, fn: Callable[[], _T]) -> _T:
        import qbittorrentapi

        for idx in range(2):
            try:
                return fn()
            except qbittorrentapi.APIConnectionError as exc:  # pragma: no cover - network
                if idx == 1:
                    raise DownloadError(
                        "Failed to connect to qBittorrent. "
                        f"Connection Error: {exc}"
                    ) from exc
                logger.warning("qB connection dropped; trying to re-login and retry once")
                self._connect_or_raise()
            except qbittorrentapi.APIError as exc:  # pragma: no cover - network
                raise DownloadError(f"qBittorrent API error: {exc}") from exc
        raise DownloadError("qBittorrent request failed unexpectedly")

    def add(self, download_url: str, save_path: str | None = None, name: str | None = None) -> str:
        import qbittorrentapi

        # Ensure our category exists so downloads are organised and findable.
        try:
            self._call_with_reconnect(
                lambda: self._client.torrents_create_category(name=self._category)
            )
        except qbittorrentapi.Conflict409Error:
            pass  # already exists
        except DownloadError as exc:  # pragma: no cover - network
            logger.warning("Could not ensure category '%s': %s", self._category, exc)

        # If we have a magnet, the info-hash is known up front (most reliable).
        known_hash = _hash_from_magnet(download_url)
        existing = {t.hash for t in self.list()}

        payload: dict[str, str] = {
            "category": self._category,
        }
        if save_path:
            payload["save_path"] = save_path
        if name:
            # Hint qB with a deterministic display name so post-add lookup can
            # resolve the hash even for .torrent URLs where btih is unknown.
            payload["rename"] = name

        split = urlsplit(download_url or "")
        is_http = split.scheme in {"http", "https"}

        if is_http and not known_hash:
            torrent_path = self._download_torrent_to_temp(download_url)
            try:
                result = self._call_with_reconnect(
                    lambda: self._client.torrents_add(
                        torrent_files=[torrent_path],
                        **payload,
                    )
                )
            finally:
                try:
                    os.unlink(torrent_path)
                except OSError:
                    pass
        else:
            result = self._call_with_reconnect(
                lambda: self._client.torrents_add(
                    urls=download_url,
                    **payload,
                )
            )

        if isinstance(result, str) and result.lower() != "ok.":
            raise DownloadError(f"qBittorrent rejected the torrent: {result}")

        if known_hash:
            return known_hash

        # Otherwise resolve by polling (qB may register new torrents slightly
        # after the add call returns), then by name for duplicate adds.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            infos = self.list()
            for info in infos:
                if info.hash not in existing:
                    return info.hash
            if name:
                # Duplicate .torrent adds may return OK without a new hash.
                for info in infos:
                    if (info.name or "").strip() == name.strip():
                        return info.hash
            time.sleep(0.35)

        raise DownloadError(
            "Torrent add acknowledged by qBittorrent, but hash could not be resolved; "
            "please verify the torrent appears in qB Web UI and retry get_download_status."
        )

    def _download_torrent_to_temp(self, download_url: str) -> str:
        settings = get_settings()
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36",
        }
        if settings.pt_cookie:
            headers["Cookie"] = settings.pt_cookie

        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(download_url, headers=headers)
                resp.raise_for_status()
                content = resp.content
        except Exception as exc:  # noqa: BLE001
            raise DownloadError(f"Failed to download torrent file from PT: {exc}") from exc

        # A valid .torrent file is bencoded and starts with a dictionary marker 'd'.
        if not content or content[:1] != b"d":
            ctype = resp.headers.get("content-type", "")
            raise DownloadError(
                "PT download URL did not return a valid .torrent file "
                f"(content-type={ctype or 'unknown'})."
            )

        with tempfile.NamedTemporaryFile(prefix="ai_media_", suffix=".torrent", delete=False) as fp:
            fp.write(content)
            return fp.name

    def status(self, torrent_hash: str) -> TorrentInfo | None:
        torrents = self._call_with_reconnect(
            lambda: self._client.torrents_info(torrent_hashes=torrent_hash)
        )
        if not torrents:
            return None
        return self._map(torrents[0])

    def list(self) -> list[TorrentInfo]:
        torrents = self._call_with_reconnect(lambda: self._client.torrents_info())
        return [self._map(t) for t in torrents]

    @staticmethod
    def _map(t) -> TorrentInfo:  # noqa: ANN001 - qbittorrentapi dynamic object
        return TorrentInfo(
            hash=t.hash,
            name=t.name,
            state=_STATE_MAP.get(t.state, "downloading"),
            progress=round(float(t.progress), 2),
        )


def _hash_from_magnet(url: str) -> str | None:
    m = _MAGNET_BTIH.search(url or "")
    return m.group(1).lower() if m and len(m.group(1)) == 40 else None

