"""The desktop application entry point.

Starts the embedded API server, then opens a native OS webview pointed at it —
WebView2 on Windows, WKWebView on macOS, WebKitGTK on Linux. No Chromium is
bundled and no Node process runs: the UI is a static bundle served by the same
Python process that does the work.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import webbrowser
from typing import Any

from deckforge import __version__, paths
from deckforge.core.logging import configure_logging, get_logger
from deckforge.desktop.bridge import DesktopApi
from deckforge.desktop.server import EmbeddedServer
from deckforge.desktop.streams import ensure_std_streams
from deckforge.desktop.window import (
    MIN_HEIGHT,
    MIN_WIDTH,
    SingleInstance,
    WindowState,
)

log = get_logger(__name__)

TITLE = "DeckForge"

STARTUP_FAILED = (
    "DeckForge could not start its local service.\n\nThe log file is at:\n{log_path}\n\n{detail}"
)


def _configure_logging() -> None:
    """Log to a file: a windowed application has no console to write to."""
    log_dir = paths.user_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    # Must happen before any logging is configured: in a windowed build the
    # standard streams are None, and uvicorn's log config resolves
    # `ext://sys.stdout`, which would raise before the server ever starts.
    ensure_std_streams(log_dir / "stdout.log")
    configure_logging("INFO", "json")

    import logging

    handler = logging.FileHandler(log_dir / "deckforge.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)


def _show_error(message: str) -> None:
    """Report a fatal startup problem without a console."""
    log.error("desktop.startup_failed", message=message)
    try:
        import webview

        webview.create_window(TITLE, html=_error_html(message), width=560, height=320)
        webview.start()
        return
    except Exception:  # pragma: no cover - the GUI itself is what failed
        pass
    print(message, file=sys.stderr)


def _error_html(message: str) -> str:
    from html import escape

    return (
        '<body style="font:14px system-ui;padding:24px;color:#111;background:#fff">'
        f"<h2 style='margin:0 0 12px'>DeckForge could not start</h2>"
        f"<pre style='white-space:pre-wrap;color:#444'>{escape(message)}</pre></body>"
    )


def run(*, dev_url: str | None = None, port: int | None = None) -> int:
    """Open the desktop window. Returns a process exit code."""
    _configure_logging()
    log.info("desktop.starting", version=__version__, **paths.describe())

    guard = SingleInstance()
    if (existing := guard.running_instance_url()) is not None:
        # Focusing another process's native window is not portable; opening the
        # running instance in the browser is the honest fallback.
        log.info("desktop.already_running", url=existing)
        webbrowser.open(existing)
        return 0

    server = EmbeddedServer(port=port)
    server.start()
    if not server.wait_until_ready():
        detail = str(server.error) if server.error else "The service did not respond in time."
        _show_error(STARTUP_FAILED.format(log_path=paths.user_log_dir(), detail=detail))
        server.stop()
        return 1

    guard.acquire(server.url)
    state = WindowState.load()

    try:
        import webview
    except ImportError:
        log.warning("desktop.webview_missing")
        webbrowser.open(dev_url or server.url)
        print(f"pywebview is not installed — opened {server.url} in your browser.")
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input("Press Enter to stop DeckForge…")
        server.stop()
        guard.release()
        return 0

    # An embedded webview does not download files on its own; the bridge gives
    # the page a way to ask Python to save one. See desktop/bridge.py.
    bridge = DesktopApi(server.url)

    # pywebview types create_window as optional; it only returns None on a
    # failure that also raises, so a local alias keeps the handlers readable.
    window: Any = webview.create_window(
        TITLE,
        url=dev_url or server.url,
        width=state.width,
        height=state.height,
        x=state.x,
        y=state.y,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        text_select=True,
        confirm_close=False,
        js_api=bridge,
    )
    bridge.attach(window)

    def remember(*_args: Any) -> None:
        try:
            state.width, state.height = int(window.width), int(window.height)
            state.x, state.y = int(window.x), int(window.y)
        except AttributeError, TypeError, ValueError:  # pragma: no cover - backend specific
            return
        state.save()

    window.events.resized += remember
    window.events.moved += remember
    window.events.closing += remember

    try:
        webview.start(
            debug=bool(dev_url),
            # Persist localStorage between launches: the appearance toggle and
            # the panel layout live there. pywebview defaults to private mode,
            # which would reset them on every start.
            private_mode=False,
            storage_path=str(paths.user_data_dir() / "webview"),
        )
    finally:
        state.save()
        server.stop()
        guard.release()
        log.info("desktop.stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deckforge-desktop", description="DeckForge desktop app")
    parser.add_argument("--version", action="version", version=f"DeckForge {__version__}")
    parser.add_argument(
        "--dev-url",
        help="Point the window at a running `npm run dev` server instead of the bundled UI.",
    )
    parser.add_argument("--port", type=int, help="Bind the embedded API to a fixed port.")
    args = parser.parse_args(argv)
    return run(dev_url=args.dev_url, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
