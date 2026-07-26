"""The stdio MCP server.

Run it with ``deckforge-mcp`` (or ``deckforge mcp``). It speaks JSON-RPC on
stdin/stdout and exits when the client closes the connection, so an MCP client
can spawn it on demand — the desktop app never has to be open.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from deckforge import __version__
from deckforge.core.errors import DeckForgeError
from deckforge.core.logging import get_logger
from deckforge.mcp import tools
from deckforge.mcp.runtime import Runtime, configure_process

log = get_logger(__name__)

SERVER_NAME = "deckforge"

INSTRUCTIONS = """\
DeckForge builds presentation decks locally.

A normal sequence is `create_deck` to generate one, `refine_deck` as many times \
as needed, then `export_deck` to write a .pptx or .pdf and get its path.

`create_deck` and `refine_deck` call a language model and take one to four \
minutes; they report progress while they work. `export_deck` and `get_deck` are \
fast and offline.

If nothing works, call `deckforge_capabilities` — it reports whether a model is \
configured and how to fix it if not."""


def build_server(runtime: Runtime) -> Server[Any, Any]:
    """Wire the tool handlers onto a server bound to ``runtime``."""
    server: Server[Any, Any] = Server(SERVER_NAME, version=__version__, instructions=INSTRUCTIONS)

    # The SDK's registration decorators are untyped, so mypy cannot see through
    # them to the handlers below. The handlers themselves are fully annotated.
    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        return tools.tool_definitions()

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        progress = _progress_reporter(server)
        try:
            payload = await tools.dispatch(runtime, name, arguments, progress)
        except DeckForgeError as exc:
            # Expected failures: no model configured, unknown deck, export
            # refused. The agent gets the sentence it needs, not a traceback.
            log.info("mcp.tool_failed", tool=name, code=exc.code, error=exc.message)
            raise ValueError(exc.message) from exc
        except Exception as exc:
            log.exception("mcp.tool_crashed", tool=name)
            raise ValueError(f"{name} failed: {exc}") from exc
        return tools.to_content(payload)

    return server


def _progress_reporter(server: Server[Any, Any]) -> tools.ProgressFn | None:
    """Forward pipeline status to the client, when it asked to be told.

    Progress is optional in MCP: without a token from the client there is
    nowhere to send it, and a four-minute silence is the price. Reporting is
    also best-effort — a client that has stopped listening must not take the
    generation down with it.
    """
    try:
        context = server.request_context
    except LookupError:  # pragma: no cover - only outside a request
        return None

    token = context.meta.progressToken if context.meta else None
    if token is None:
        return None
    session = context.session

    async def report(value: float, message: str) -> None:
        try:
            await session.send_progress_notification(
                progress_token=token,
                progress=value,
                total=1.0,
                message=message or None,
                related_request_id=str(context.request_id),
            )
        except Exception as exc:  # pragma: no cover - transport hiccup
            log.debug("mcp.progress_dropped", error=str(exc))

    return report


async def serve() -> None:
    """Run the server until the client disconnects."""
    runtime = await Runtime.start()
    server = build_server(runtime)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
                raise_exceptions=False,
            )
    finally:
        await runtime.stop()


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point.

    Nothing here may write to stdout: it is the transport.
    """
    parser = argparse.ArgumentParser(
        prog="deckforge-mcp",
        description="Serve DeckForge to other agents over MCP (stdio).",
    )
    parser.add_argument("--version", action="version", version=f"DeckForge {__version__}")
    parser.parse_args(argv)

    configure_process()
    try:
        anyio.run(serve)
    except KeyboardInterrupt, asyncio.CancelledError:  # pragma: no cover - normal shutdown
        return 0
    except Exception as exc:  # pragma: no cover - startup failure
        log.exception("mcp.startup_failed")
        print(f"deckforge-mcp failed to start: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
