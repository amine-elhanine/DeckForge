"""The embedded API server that backs the desktop window.

Uvicorn runs on a background thread bound to loopback on an ephemeral port. A
fixed port would collide with whatever else the user is running and would also
expose the app to anything on the machine that guesses it; an ephemeral port
that only the window knows about is both safer and quieter.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from deckforge.core.logging import get_logger

log = get_logger(__name__)

HOST = "127.0.0.1"

#: Everything a not-yet-listening server can raise at a health probe.
NOT_READY_ERRORS = (urllib.error.URLError, OSError, TimeoutError)


def find_free_port() -> int:
    """Ask the OS for a free loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


class EmbeddedServer:
    """Runs the FastAPI application in this process, on its own thread."""

    def __init__(self, port: int | None = None, *, log_level: str = "warning") -> None:
        self.port = port or find_free_port()
        self._log_level = log_level
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def start(self) -> None:
        """Launch the server thread."""
        import uvicorn

        from deckforge.main import create_app

        config = uvicorn.Config(
            create_app(),
            host=HOST,
            port=self.port,
            log_level=self._log_level,
            access_log=False,
            # Keep our structlog setup: uvicorn's default dictConfig points at
            # `ext://sys.stdout`, which does not exist in a windowed build.
            log_config=None,
            # The window owns the lifecycle; uvicorn must not install its own
            # signal handlers on a non-main thread (it would raise).
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None

        def run() -> None:
            try:
                self._server.run()
            except BaseException as exc:  # reported to the caller via .error
                self._error = exc
                log.exception("desktop.server_crashed")

        self._thread = threading.Thread(target=run, name="deckforge-server", daemon=True)
        self._thread.start()

    def wait_until_ready(self, timeout: float = 60.0) -> bool:
        """Poll ``/health`` until the app answers.

        Returns:
            True once the server is serving; False if it never came up.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._error is not None:
                return False
            if self._probe():
                log.info("desktop.server_ready", port=self.port)
                return True
            time.sleep(0.15)
        return False

    def _probe(self) -> bool:
        """One health request. Any failure just means "not yet"."""
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=2) as response:
                return bool(response.status == 200)
        except NOT_READY_ERRORS:
            return False

    @property
    def error(self) -> BaseException | None:
        return self._error

    def stop(self, timeout: float = 8.0) -> None:
        """Ask uvicorn to shut down and wait briefly for the thread to finish."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        log.info("desktop.server_stopped")
