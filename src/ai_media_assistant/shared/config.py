"""Centralised application configuration using pydantic-settings.

All settings are read from environment variables (or a local ``.env`` file).
Every value has a safe default so the project runs fully offline for learning.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# Project root = three parents up from this file (src/ai_media_assistant/shared/).
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # ---- Database ----
    db_host: str = ""
    db_port: int = 3306
    db_name: str = "ai_media_assistant"
    db_user: str = ""
    db_password: str = ""

    # ---- LLM ----
    llm_provider: str = "ollama"  # "ollama" | "openai"
    llm_model: str = "qwen3:8b"
    llm_temperature: float = 0.2
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # ---- Embeddings / RAG ----
    embed_provider: str = "fallback"  # "ollama" | "openai" | "fallback"
    embed_model: str = "nomic-embed-text"
    vector_store_dir: str = "data/chroma"

    # ---- qBittorrent ----
    qb_host: str = "http://localhost:8080"
    qb_username: str = "admin"
    qb_password: str = "adminadmin"
    qb_mock: bool = True
    download_save_path: str = "/downloads"
    qb_category: str = "ai-media"

    # ---- PT site ----
    # Backend: "mock" (offline sample catalog), "rss" (your member tracker's
    # personal RSS feed — easiest for a single private site), "torznab"
    # (Jackett/Prowlarr), or "json" (a custom JSON search API).
    pt_backend: str = "mock"
    pt_mock: bool = True  # kept for backward compatibility (mock when true)
    pt_site_name: str = "demo-pt"
    pt_base_url: str = ""
    pt_api_key: str = ""
    pt_cookie: str = ""
    pt_min_seeders: int = 1
    pt_web_max_pages: int = 5
    # Optional tracker-specific query template for web fallback search.
    # Supports placeholders: {keyword}, {category}, {resolution}, {quality},
    # {min_seeders}, {min_size_gb}, {max_size_gb}, {page}.
    pt_web_query_template: str = ""
    # Parameter names when no template is provided.
    pt_web_keyword_param: str = "search"
    pt_web_category_param: str = ""
    # JSON map for tracker category multi-select, e.g.
    # {"电影":"cat401","剧集":"cat402","综艺":"cat403"}
    pt_web_category_param_map: str = ""
    pt_web_resolution_param: str = ""
    pt_web_quality_param: str = ""
    pt_web_min_seeders_param: str = ""
    pt_web_min_size_gb_param: str = ""
    pt_web_max_size_gb_param: str = ""
    pt_web_page_param: str = "page"
    # Personal RSS feed URL for a member PT site. May contain a {keyword}
    # placeholder for searchable feeds. Contains your passkey — keep it secret.
    pt_rss_url: str = ""

    # ---- Agent safety ----
    agent_require_download_confirm: bool = False
    agent_max_iterations: int = 12

    # ---- Derived helpers ----
    @property
    def database_url(self) -> str:
        """Return a SQLAlchemy URL.

        Falls back to a local SQLite database when no MySQL host is configured,
        so the project is runnable with zero external services.
        """
        if self.db_host:
            # Build via SQLAlchemy to safely escape reserved URL characters
            # in credentials (for example '@' or ':').
            return URL.create(
                drivername="mysql+pymysql",
                username=self.db_user or None,
                password=self.db_password or None,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                query={"charset": "utf8mb4"},
            ).render_as_string(hide_password=False)
        sqlite_path = PROJECT_ROOT / "data" / "app.db"
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{sqlite_path}"

    @property
    def vector_store_path(self) -> Path:
        path = PROJECT_ROOT / self.vector_store_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def effective_pt_backend(self) -> str:
        """Resolve the PT backend, honouring the legacy ``pt_mock`` flag.

        Returns one of ``"mock"``, ``"rss"``, ``"torznab"`` or ``"json"``.
        """
        backend = (self.pt_backend or "mock").lower()
        # Explicit non-mock backend always wins.
        if backend in ("rss", "torznab", "json"):
            return backend
        if self.pt_mock:
            return "mock"
        # pt_mock disabled but no explicit backend -> infer from what's set.
        if self.pt_rss_url:
            return "rss"
        if self.pt_base_url:
            return "torznab"
        return "mock"


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
