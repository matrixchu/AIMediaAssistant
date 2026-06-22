"""Diagnostics: verify the real integrations (MySQL, qBittorrent, PT source).

Run after editing ``.env`` to confirm the full chain is wired:

    python -m ai_media_assistant.doctor

It checks, in order:
    1. Database  — connects and ensures tables exist (MySQL or SQLite).
    2. qBittorrent — logs in to the (possibly remote/NAS) Web UI.
    3. PT source — runs a sample search through the configured backend.
    4. LLM / Ollama — checks the model endpoint is reachable (optional).

Nothing here downloads anything; it only probes connectivity.
"""

from __future__ import annotations

import sys

from .shared.config import get_settings
from .shared.logging import setup_logging


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def _info(msg: str) -> None:
    print(f"  • {msg}")


def check_database() -> bool:
    from sqlalchemy import text

    from .database import get_engine, init_db

    settings = get_settings()
    backend = "MySQL" if settings.db_host else "SQLite"
    target = settings.db_host or "data/app.db (local file)"
    print(f"[1/4] Database — {backend} @ {target}")
    try:
        init_db()  # creates tables if missing
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        _ok(f"Connected and tables ensured ({backend}).")
        if backend == "SQLite":
            _info("Tip: set DB_HOST/DB_USER/DB_PASSWORD/DB_NAME to use your MySQL server.")
        return True
    except Exception as exc:  # noqa: BLE001
        _fail(f"Database error: {exc}")
        return False


def check_qbittorrent() -> bool:
    settings = get_settings()
    print(f"[2/4] qBittorrent — {'MOCK' if settings.qb_mock else settings.qb_host}")
    if settings.qb_mock:
        _info("QB_MOCK=true (simulated). Set QB_MOCK=false and QB_HOST=<nas-ip:port> to go live.")
        return True
    try:
        from .clients.qb import get_qb_client

        client = get_qb_client()
        torrents = client.list()
        _ok(f"Connected to qBittorrent; {len(torrents)} torrent(s) currently tracked.")
        _info(f"Downloads will be saved to: {settings.download_save_path} (path on the NAS).")
        return True
    except Exception as exc:  # noqa: BLE001
        _fail(f"qBittorrent error: {exc}")
        _info("Check QB_HOST/QB_USERNAME/QB_PASSWORD and that the NAS Web UI is reachable.")
        return False


def check_pt() -> bool:
    settings = get_settings()
    backend = settings.effective_pt_backend
    print(f"[3/4] PT source — backend '{backend}'")
    if backend == "mock":
        _info("Using the offline sample catalog. Set PT_BACKEND=rss (or torznab) to go live.")
    try:
        from .clients.pt import get_pt_client

        client = get_pt_client()
        sample = "Dune" if backend == "mock" else "1080p"
        results = client.search(sample, limit=5)
        if results:
            _ok(f"Search returned {len(results)} result(s). Example: {results[0].title[:60]}")
        else:
            _info("Search returned 0 results (feed reachable but no matches for the sample query).")
        return True
    except Exception as exc:  # noqa: BLE001
        _fail(f"PT search error: {exc}")
        return False


def check_llm() -> bool:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    print(f"[4/4] LLM — provider '{provider}', model '{settings.llm_model}'")
    if provider in ("none", "off", "disabled"):
        _info("LLM disabled; the rule-based agent path will be used.")
        return True
    if provider == "ollama":
        try:
            import httpx

            r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if settings.llm_model in models:
                _ok(f"Ollama reachable; model '{settings.llm_model}' is installed.")
            else:
                _info(f"Ollama reachable but '{settings.llm_model}' not pulled. Have: {models}")
            return True
        except Exception as exc:  # noqa: BLE001
            _fail(f"Ollama not reachable at {settings.ollama_base_url}: {exc}")
            return False
    _info("Non-Ollama provider; skipping live check.")
    return True


def main() -> int:
    setup_logging("WARNING")
    print("AI Media Assistant — integration doctor\n")
    results = [check_database(), check_qbittorrent(), check_pt(), check_llm()]
    print()
    passed = sum(results)
    if all(results):
        print(f"\033[32mAll {passed}/4 checks passed. The chain is ready.\033[0m")
        return 0
    print(f"\033[33m{passed}/4 checks passed. Fix the ✗ items in your .env.\033[0m")
    return 1


if __name__ == "__main__":
    sys.exit(main())
