"""Standard streams for a windowed application.

A PyInstaller build with ``console=False`` starts with ``sys.stdout`` and
``sys.stderr`` set to ``None``. Anything that writes to them then fails — and
the failures are invisible, because there is nowhere to report them.

The one that actually killed startup was uvicorn: its default logging
configuration names ``ext://sys.stdout``, so ``dictConfig`` raised before the
server ever bound a port. Pointing the streams at the log file makes the
windowed build behave like the console one.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import TextIO


def ensure_std_streams(log_path: Path | None = None) -> None:
    """Guarantee ``sys.stdout`` and ``sys.stderr`` are writable.

    Args:
        log_path: file to append stray output to. Output is discarded if it is
            ``None`` or cannot be opened.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return

    sink = _open_sink(log_path)
    if sys.stdout is None:
        sys.stdout = sink
    if sys.stderr is None:
        sys.stderr = sink


def _open_sink(log_path: Path | None) -> TextIO:
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            return open(log_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    # Never let logging setup be the thing that crashes the app.
    return io.StringIO()
