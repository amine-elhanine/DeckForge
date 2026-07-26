"""The JavaScript bridge exposed to the page as ``window.pywebview.api``.

An embedded WebView2 does not download files the way a browser does: an
``<a download>`` click is handed to the host application, and if the host does
not act on it, nothing happens at all — no file, no error, no prompt. That is
why the export menu appeared to do nothing.

So the desktop build saves files itself: the page asks Python for a download,
Python fetches the bytes from its own API, shows a native save dialog and writes
the file. Browsers keep using the ordinary blob download in ``lib/desktop.ts``.
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from deckforge.core.logging import get_logger

log = get_logger(__name__)

#: Only the app's own API may be fetched through the bridge.
ALLOWED_PREFIX = "/api/v1/"

_FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)

#: Save-dialog filters, by file extension.
FILE_TYPES = {
    "pptx": "PowerPoint presentation (*.pptx)",
    "pdf": "PDF document (*.pdf)",
    "html": "Web page (*.html)",
    "md": "Markdown (*.md)",
    "json": "JSON (*.json)",
    "zip": "Archive (*.zip)",
}


def downloads_dir() -> Path:
    """The user's Downloads folder, falling back to home."""
    candidate = Path.home() / "Downloads"
    return candidate if candidate.is_dir() else Path.home()


class DesktopApi:
    """Python methods callable from the page.

    Every method returns a plain dict so the page can branch on the outcome
    rather than catching exceptions across the bridge.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._window: Any = None
        self._saved: set[str] = set()

    def attach(self, window: Any) -> None:
        """Give the bridge the window it must open dialogs on."""
        self._window = window

    # -- exposed to JavaScript ------------------------------------------------ #

    def is_desktop(self) -> bool:
        """Lets the page detect the desktop shell without sniffing user agents."""
        return True

    def save_download(self, api_path: str, suggested_name: str = "") -> dict[str, Any]:
        """Fetch an API download and write it wherever the user chooses.

        Args:
            api_path: path under ``/api/v1/`` on this app's own server.
            suggested_name: filename to prefill; the server's own name wins if
                it sends one.

        Returns:
            ``{"ok": True, "path": ...}``, ``{"cancelled": True}`` or
            ``{"ok": False, "error": ...}``.
        """
        if not api_path.startswith(ALLOWED_PREFIX):
            # The page is local, but a bridge that fetches arbitrary URLs on
            # request is a confused-deputy waiting to happen.
            log.warning("desktop.download_rejected", path=api_path[:120])
            return {"ok": False, "error": "That download is not allowed."}

        try:
            content, server_name = self._fetch(api_path)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            log.warning("desktop.download_failed", path=api_path, error=str(exc))
            return {"ok": False, "error": f"Could not produce the file: {exc}"}

        filename = server_name or suggested_name or "deckforge-export"
        target = self._ask_where_to_save(filename)
        if target is None:
            return {"cancelled": True}

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        except OSError as exc:
            log.warning("desktop.write_failed", path=str(target), error=str(exc))
            return {"ok": False, "error": f"Could not write the file: {exc}"}

        self._saved.add(str(target))
        log.info("desktop.download_saved", path=str(target), bytes=len(content))
        return {"ok": True, "path": str(target), "name": target.name, "bytes": len(content)}

    def reveal(self, path: str) -> dict[str, Any]:
        """Show a saved file in the system file manager.

        Only files this session wrote can be revealed, so the page cannot use
        the bridge to browse the disk.
        """
        if path not in self._saved:
            return {"ok": False, "error": "Unknown file."}
        target = Path(path)
        if not target.is_file():
            return {"ok": False, "error": "The file has moved."}
        try:
            self._reveal_in_file_manager(target)
        except OSError as exc:  # pragma: no cover - platform dependent
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    # -- internals ------------------------------------------------------------ #

    def _fetch(self, api_path: str) -> tuple[bytes, str]:
        """Download from the app's own server, returning bytes and filename."""
        url = f"{self._base_url}{api_path}"
        # Exports render synchronously and a large deck takes a moment.
        with urllib.request.urlopen(url, timeout=180) as response:
            content = response.read()
            disposition = response.headers.get("content-disposition", "")
        match = _FILENAME_RE.search(disposition)
        name = urllib.parse.unquote(match.group(1)) if match else ""
        return content, Path(name).name

    def _ask_where_to_save(self, filename: str) -> Path | None:
        if self._window is None:  # pragma: no cover - only before attach()
            return downloads_dir() / filename

        import webview

        extension = Path(filename).suffix.lstrip(".").lower()
        file_types = (FILE_TYPES.get(extension, f"{extension.upper()} file (*.{extension})"),)
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(downloads_dir()),
            save_filename=filename,
            file_types=file_types,
        )
        if not result:
            return None
        # Backends return either a string or a one-element sequence.
        chosen = result if isinstance(result, str) else result[0]
        return Path(chosen)

    @staticmethod
    def _reveal_in_file_manager(target: Path) -> None:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(target)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent)])
