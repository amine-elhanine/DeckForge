"""Settings parsing.

Environment variables are strings; getting list fields wrong here breaks startup
with an opaque error, so every accepted spelling is pinned down.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
        ('["http://a.test","http://b.test"]', ["http://a.test", "http://b.test"]),
        ("http://a.test", ["http://a.test"]),
        (" http://a.test , http://b.test ", ["http://a.test", "http://b.test"]),
    ],
)
def test_cors_origins_accepts_csv_and_json(monkeypatch, raw: str, expected: list[str]) -> None:
    monkeypatch.setenv("DECKFORGE_CORS_ORIGINS", raw)
    assert Settings().cors_origins == expected


def test_path_lists_accept_csv(monkeypatch, tmp_path: Path) -> None:
    a, b = tmp_path / "one", tmp_path / "two"
    monkeypatch.setenv("DECKFORGE_PLUGIN_PATHS", f"{a},{b}")
    monkeypatch.setenv("DECKFORGE_THEME_PATHS", str(a))
    settings = Settings()
    assert settings.plugin_paths == [a, b]
    assert settings.theme_paths == [a]


def test_defaults_are_local_first() -> None:
    """Shipped defaults, ignoring whatever the developer has in their own .env."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.is_sqlite
    assert settings.default_provider == "ollama"
    assert settings.builtin_theme_dir.is_dir()


def test_derived_directories(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert settings.uploads_dir == tmp_path / "uploads"
    settings.ensure_directories()
    assert settings.exports_dir.is_dir() and settings.assets_dir.is_dir()


def test_database_defaults_into_the_data_directory(tmp_path: Path) -> None:
    """The desktop build sets only DECKFORGE_DATA_DIR; the database must follow."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "store")  # type: ignore[call-arg]
    assert settings.database_url.endswith("store/deckforge.db")
    assert settings.is_sqlite


def test_relative_data_dir_is_pinned_to_an_absolute_path(tmp_path: Path, monkeypatch) -> None:
    """A double-clicked app inherits an arbitrary working directory."""
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, data_dir=Path("./store"))  # type: ignore[call-arg]
    assert settings.data_dir.is_absolute()
    assert settings.data_dir == (tmp_path / "store").resolve()
