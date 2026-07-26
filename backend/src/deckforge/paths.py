"""Filesystem layout, for both source checkouts and frozen desktop builds.

A PyInstaller bundle breaks two assumptions the rest of the codebase would
otherwise make:

* ``Path(__file__).parent`` no longer points at readable package data — bundled
  resources live under ``sys._MEIPASS`` in a temporary extraction directory.
* The install directory is read-only (Program Files), so the database, uploads
  and exports must live in a per-user data directory instead.

Every path decision is centralised here so no other module has to know whether
it is running frozen.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

APP_NAME = "DeckForge"
APP_SLUG = "deckforge"

PACKAGE_ROOT = Path(__file__).resolve().parent


def is_frozen() -> bool:
    """Whether we are running from a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


@lru_cache(maxsize=1)
def resource_root() -> Path:
    """Directory containing read-only bundled resources.

    Frozen builds extract data files to ``sys._MEIPASS``; from source this is
    simply the installed package directory.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / APP_SLUG
        return bundled if bundled.is_dir() else Path(meipass)
    return PACKAGE_ROOT


@lru_cache(maxsize=1)
def repo_root() -> Path | None:
    """The source checkout root, or ``None`` when running frozen.

    Used only for developer conveniences (reading the repository's ``.env`` and
    ``plugins/`` folder); nothing at runtime may depend on it existing.
    """
    if is_frozen():
        return None
    candidate = PACKAGE_ROOT.parents[2]  # …/backend
    return candidate.parent if (candidate.parent / "backend").is_dir() else candidate


@lru_cache(maxsize=1)
def user_data_dir() -> Path:
    """Writable per-user directory for the database, uploads and exports.

    Honours ``DECKFORGE_DATA_DIR`` when set, so a portable build or a test can
    redirect everything with one variable.
    """
    override = os.environ.get("DECKFORGE_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if not is_frozen():
        root = repo_root()
        if root is not None:
            return root / "data"

    return _platform_data_dir()


def shared_data_dir() -> Path:
    """The data directory the *installed* application uses.

    :func:`user_data_dir` deliberately resolves to ``<repo>/data`` from a source
    checkout, which keeps development and the test suite isolated. That is wrong
    for a process whose whole job is to reach the user's real state: the MCP
    server must find the LLM connection they configured in the desktop app's
    settings, and write decks the desktop app will then list. Running from
    source it would otherwise open a different, empty database and fail every
    request with "no LLM configured".

    ``DECKFORGE_DATA_DIR`` still wins, so a test or a portable install can
    redirect it.
    """
    override = os.environ.get("DECKFORGE_DATA_DIR")
    return Path(override).expanduser() if override else _platform_data_dir()


def _platform_data_dir() -> Path:
    """Per-platform application data directory."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base or Path.home() / "AppData" / "Local") / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg or Path.home() / ".local" / "share") / APP_SLUG


@lru_cache(maxsize=1)
def user_config_dir() -> Path:
    """Directory holding the user-editable ``.env``.

    From source this is the checkout root, so the developer workflow is
    unchanged. Frozen, it sits beside the data directory — one folder per app is
    friendlier than scattering config elsewhere.
    """
    if not is_frozen():
        root = repo_root()
        if root is not None:
            return root
    if sys.platform.startswith("linux"):
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / APP_SLUG
    return user_data_dir()


@lru_cache(maxsize=1)
def user_log_dir() -> Path:
    return user_data_dir() / "logs"


def env_files() -> tuple[Path, ...]:
    """``.env`` locations, lowest precedence first.

    A frozen app reads only the user config directory. From source the
    repository's ``.env`` is also honoured so developers keep their current
    workflow.
    """
    files: list[Path] = []
    root = repo_root()
    if root is not None:
        files.extend([root / ".env", root / "backend" / ".env"])
    files.append(user_config_dir() / ".env")
    return tuple(files)


def builtin_theme_dir() -> Path:
    """Directory of shipped theme packages."""
    return resource_root() / "themes" / "packages"


def bundled_web_dir() -> Path | None:
    """The exported frontend bundled with the app, if present."""
    candidates = [
        resource_root() / "web",
        resource_root().parent / "web",
    ]
    root = repo_root()
    if root is not None:
        candidates.append(root / "frontend" / "out")
    return next((c for c in candidates if (c / "index.html").is_file()), None)


def bundled_plugin_dirs() -> list[Path]:
    """Plugin directories that always exist: shipped examples plus the user's."""
    dirs: list[Path] = []
    root = repo_root()
    if root is not None:
        dirs.append(root / "plugins")
    bundled = resource_root() / "plugins"
    if bundled.is_dir():
        dirs.append(bundled)
    dirs.append(user_data_dir() / "plugins")
    return dirs


def describe() -> dict[str, str | bool | None]:
    """Diagnostics for the health endpoint and the CLI doctor."""
    web = bundled_web_dir()
    return {
        "frozen": is_frozen(),
        "resource_root": str(resource_root()),
        "data_dir": str(user_data_dir()),
        "config_dir": str(user_config_dir()),
        "themes": str(builtin_theme_dir()),
        "web": str(web) if web else None,
        "repo_root": str(repo_root()) if repo_root() else None,
    }
