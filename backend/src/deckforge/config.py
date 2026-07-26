"""Application configuration.

All configuration is environment driven (``.env`` file or process environment) so the
same image can run in lightweight local mode (SQLite, Ollama) or production mode
(PostgreSQL, Redis, cloud provider) without code changes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from deckforge import paths
from deckforge.models.enums import ContentDensity

PACKAGE_ROOT = paths.PACKAGE_ROOT


class Settings(BaseSettings):
    """Runtime settings for the DeckForge backend."""

    model_config = SettingsConfigDict(
        # From source: the repository .env. Frozen: the per-user config dir,
        # since the install directory is read-only.
        env_file=paths.env_files(),
        env_prefix="DECKFORGE_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- application ---------------------------------------------------------
    app_name: str = "DeckForge"
    environment: Literal["local", "development", "production"] = "local"
    debug: bool = True
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    api_prefix: str = "/api/v1"
    # ``NoDecode`` stops pydantic-settings from JSON-parsing the raw environment
    # value, so ``A,B`` works as well as ``["A","B"]``.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # -- storage -------------------------------------------------------------
    # Empty means "derive from data_dir", which is what the desktop build needs:
    # the database belongs beside the user's uploads, not in Program Files.
    database_url: str = ""
    data_dir: Path = Field(default_factory=paths.user_data_dir)
    redis_url: str | None = None

    # -- default LLM ---------------------------------------------------------
    default_provider: str = "ollama"
    default_model: str = "qwen3:8b"
    default_temperature: float = 0.7
    request_timeout_seconds: float = 300.0
    max_output_tokens: int = 8192

    # -- provider credentials / endpoints ------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    lmstudio_base_url: str = "http://localhost:1234/v1"
    llamacpp_base_url: str = "http://localhost:8080/v1"
    vllm_base_url: str = "http://localhost:8000/v1"

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    openrouter_api_key: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    together_api_key: str | None = None
    deepseek_api_key: str | None = None
    mistral_api_key: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"

    # -- engine tuning -------------------------------------------------------
    theme_paths: Annotated[list[Path], NoDecode] = Field(default_factory=list)
    plugin_paths: Annotated[list[Path], NoDecode] = Field(default_factory=list)
    max_upload_bytes: int = 50 * 1024 * 1024
    retrieval_top_k: int = 8
    enable_fact_checker: bool = True
    enable_critic: bool = True
    max_slides: int = 60
    worker_concurrency: int = 4
    content_density: ContentDensity = ContentDensity.RICH
    """Default prose depth. A conversation setting or the request itself overrides it."""

    @field_validator("cors_origins", "theme_paths", "plugin_paths", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept ``a,b``, ``["a","b"]`` or a real list from the environment."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                import json

                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _resolve_storage(self) -> Settings:
        """Make ``data_dir`` absolute and derive the database from it.

        A relative data directory resolves against the current working
        directory, which is wherever the user happened to double-click the app —
        so it is pinned here. Deriving the database URL in the same place keeps
        the two consistent when only ``DECKFORGE_DATA_DIR`` is overridden, which
        is the common case for the desktop build and for tests.
        """
        self.data_dir = self.data_dir.expanduser().resolve()
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{(self.data_dir / 'deckforge.db').as_posix()}"
        return self

    @property
    def builtin_theme_dir(self) -> Path:
        return paths.builtin_theme_dir()

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def ensure_directories(self) -> None:
        """Create every directory the application writes to."""
        for path in (self.data_dir, self.uploads_dir, self.exports_dir, self.assets_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
