"""Frozen application entry point.

A dedicated module rather than ``-m deckforge.desktop`` because PyInstaller
analyses a script path, and because the frozen process needs multiprocessing
support installed before anything else runs.
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    # Without this, any library that spawns a process would relaunch the whole
    # application instead — a classic frozen-app failure that shows up as
    # windows multiplying on screen.
    multiprocessing.freeze_support()

    from deckforge.desktop.app import main as run_desktop

    return run_desktop([])


if __name__ == "__main__":
    sys.exit(main())
