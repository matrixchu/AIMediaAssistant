"""Pytest fixtures: isolated SQLite database + offline configuration."""

from __future__ import annotations

import os

import pytest

# Force a fully offline, deterministic configuration BEFORE importing the app.
os.environ["PT_BACKEND"] = "mock"
os.environ["PT_MOCK"] = "true"
os.environ["QB_MOCK"] = "true"
os.environ["EMBED_PROVIDER"] = "fallback"
os.environ["DB_HOST"] = ""  # -> SQLite fallback
# Use the deterministic rule-based agent path so tests don't require a running
# LLM (Ollama/OpenAI) and stay fast and reproducible.
os.environ.setdefault("LLM_PROVIDER", "none")


@pytest.fixture(scope="session", autouse=True)
def _use_temp_db(tmp_path_factory):
    """Point the database at a throwaway SQLite file for the test session."""
    db_file = tmp_path_factory.mktemp("db") / "test.db"

    import ai_media_assistant.shared.config as config

    config.get_settings.cache_clear()
    settings = config.get_settings()
    # Override the database_url by monkeypatching the property result.
    url = f"sqlite:///{db_file}"

    import ai_media_assistant.database.base as base

    base.get_engine.cache_clear()
    base._session_factory.cache_clear()

    # Patch settings.database_url to our temp file.
    type(settings).database_url = property(lambda self: url)  # type: ignore[assignment]

    from ai_media_assistant.database import init_db

    init_db()
    yield
