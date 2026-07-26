"""DeckForge as an MCP server.

A third entry point onto the same service layer the REST API and the desktop
shell use, so another agent can build, refine and export a deck over stdio
without DeckForge itself being open.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point. Imported lazily to keep startup cheap."""
    from deckforge.mcp.server import main as _main

    return _main(argv)
