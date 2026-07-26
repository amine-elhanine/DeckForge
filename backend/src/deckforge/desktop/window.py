"""Native window state: geometry persistence and the single-instance guard."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from deckforge import paths
from deckforge.core.logging import get_logger

log = get_logger(__name__)

MIN_WIDTH, MIN_HEIGHT = 1024, 700
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1440, 900


@dataclass(slots=True)
class WindowState:
    """Remembered window geometry."""

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    x: int | None = None
    y: int | None = None
    maximized: bool = False

    @classmethod
    def load(cls) -> WindowState:
        path = _state_path()
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            return cls()
        state = cls(
            width=max(MIN_WIDTH, int(data.get("width", DEFAULT_WIDTH))),
            height=max(MIN_HEIGHT, int(data.get("height", DEFAULT_HEIGHT))),
            x=data.get("x"),
            y=data.get("y"),
            maximized=bool(data.get("maximized", False)),
        )
        # A monitor that has since been unplugged would put the window off-screen.
        if state.x is not None and (state.x < -10_000 or state.y is None or state.y < -10_000):
            state.x = state.y = None
        return state

    def save(self) -> None:
        try:
            path = _state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - best effort
            log.debug("desktop.window_state_not_saved", error=str(exc))


def _state_path() -> Path:
    return paths.user_data_dir() / "window.json"


def _lock_path() -> Path:
    return paths.user_data_dir() / "instance.json"


class SingleInstance:
    """Prevents a second window from opening on the same data directory.

    Two processes on one SQLite file is the failure this avoids. The lock is a
    small file naming the running instance's port; it is validated by actually
    calling that port, so a stale file left by a crash never blocks startup.
    """

    def __init__(self) -> None:
        self._socket: socket.socket | None = None

    def running_instance_url(self) -> str | None:
        """Return the URL of a live instance, or ``None``."""
        path = _lock_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            url = str(data["url"])
        except OSError, json.JSONDecodeError, KeyError:
            return None
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1.5) as response:
                if response.status == 200:
                    return url
        except urllib.error.URLError, OSError, TimeoutError:
            pass
        # Stale: the recorded process is gone.
        path.unlink(missing_ok=True)
        return None

    def acquire(self, url: str) -> None:
        path = _lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")

    def release(self) -> None:
        _lock_path().unlink(missing_ok=True)
