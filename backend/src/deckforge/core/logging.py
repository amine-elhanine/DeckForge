"""Structured logging setup built on :mod:`structlog`."""

from __future__ import annotations

import logging
import sys
from typing import Any, TextIO

import structlog

_CONFIGURED = False


def configure_logging(
    level: str = "INFO", fmt: str = "console", stream: TextIO | None = None
) -> None:
    """Configure stdlib logging and structlog once per process.

    Args:
        level: threshold name, e.g. ``"INFO"``.
        fmt: ``"console"`` for human output, ``"json"`` for machine output.
        stream: where log records go. Defaults to stdout. The stdio MCP server
            passes stderr, because on that transport stdout carries JSON-RPC and
            a single log line silently corrupts the protocol.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    stream = stream if stream is not None else sys.stdout
    logging.basicConfig(
        format="%(message)s",
        stream=stream,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    for noisy in ("httpx", "httpcore", "python_multipart", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=_supports_colour(stream))
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def _supports_colour(stream: TextIO) -> bool:
    """Whether ANSI colour is worth emitting on ``stream``.

    A redirected or closed stream has no ``isatty``, and a windowed build can
    hand us a file object standing in for a missing console.
    """
    try:
        return bool(stream.isatty())
    except AttributeError, ValueError:
        return False


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
