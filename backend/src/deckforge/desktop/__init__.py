"""Desktop application shell.

Run it from source with::

    python -m deckforge.desktop

The packaged build calls the same entry point; see ``packaging/`` for the
PyInstaller spec and the Windows installer.
"""

from deckforge.desktop.app import main, run
from deckforge.desktop.server import EmbeddedServer, find_free_port
from deckforge.desktop.window import SingleInstance, WindowState

__all__ = ["EmbeddedServer", "SingleInstance", "WindowState", "find_free_port", "main", "run"]
