"""Server-Sent Events.

Implemented directly on Starlette's ``StreamingResponse`` rather than pulling in
an SSE library: the framing is a dozen lines, and owning it means the headers
that actually matter for streaming (no caching, no proxy buffering) are explicit
rather than dependent on a third party tracking Starlette releases.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from starlette.responses import StreamingResponse

from deckforge.core.events import RunEvent

SSE_HEADERS = {
    "cache-control": "no-cache, no-transform",
    "connection": "keep-alive",
    # Tells nginx and friends not to buffer the response.
    "x-accel-buffering": "no",
}


def format_sse(event: str, data: Any) -> str:
    """Encode one SSE frame.

    Newlines inside the payload must each get their own ``data:`` line, which is
    why the JSON is serialised without indentation.
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    lines = "".join(f"data: {line}\n" for line in payload.split("\n"))
    return f"event: {event}\n{lines}\n"


async def event_stream(events: AsyncIterator[RunEvent]) -> AsyncIterator[bytes]:
    """Turn a stream of :class:`RunEvent` into SSE frames."""
    # A leading comment flushes response headers immediately, so the client's
    # `fetch` resolves before the first real event is produced.
    yield b": stream open\n\n"
    async for event in events:
        yield format_sse(event.type.value, event.data).encode("utf-8")


def sse_response(events: AsyncIterator[RunEvent]) -> StreamingResponse:
    """Wrap an event iterator in a streaming HTTP response."""
    return StreamingResponse(
        event_stream(events),
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )
