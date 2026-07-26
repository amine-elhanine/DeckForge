"""Progress events emitted by the agent pipeline and streamed to the client.

Agents never expose their internal reasoning. They emit *user facing* status
events ("Researching your documents", "Writing slide 4 of 12") plus content
tokens for the assistant reply and deck snapshots for live preview.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    """Types of events on the run stream."""

    STATUS = "status"
    """Human readable progress update."""
    TOKEN = "token"
    """A chunk of the assistant's natural-language reply."""
    DECK = "deck"
    """A full deck snapshot for the preview pane."""
    SLIDE = "slide"
    """A single finished slide, for incremental rendering."""
    ARTIFACT = "artifact"
    """A produced file (export, asset)."""
    MESSAGE = "message"
    """The persisted assistant message record."""
    ERROR = "error"
    DONE = "done"


class RunEvent(BaseModel):
    """A single event on the streaming channel."""

    model_config = ConfigDict(extra="forbid")

    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def status(
        cls, message: str, *, phase: str | None = None, progress: float | None = None
    ) -> Self:
        payload: dict[str, Any] = {"message": message}
        if phase is not None:
            payload["phase"] = phase
        if progress is not None:
            payload["progress"] = round(progress, 4)
        return cls(type=EventType.STATUS, data=payload)

    @classmethod
    def token(cls, text: str) -> Self:
        return cls(type=EventType.TOKEN, data={"text": text})

    @classmethod
    def error(cls, message: str, *, code: str = "error") -> Self:
        return cls(type=EventType.ERROR, data={"message": message, "code": code})


class EventStream:
    """An in-memory async channel between the agent pipeline and the HTTP layer."""

    _SENTINEL = object()

    def __init__(self, maxsize: int = 512) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def emit(self, event: RunEvent) -> None:
        if self._closed:
            return
        await self._queue.put(event)

    async def status(self, message: str, **kwargs: Any) -> None:
        await self.emit(RunEvent.status(message, **kwargs))

    async def token(self, text: str) -> None:
        await self.emit(RunEvent.token(text))

    async def push(self, type_: EventType, **data: Any) -> None:
        await self.emit(RunEvent(type=type_, data=data))

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._queue.put(self._SENTINEL)

    async def __aiter__(self) -> AsyncIterator[RunEvent]:
        while True:
            item = await self._queue.get()
            if item is self._SENTINEL:
                return
            yield item


class NullEventStream(EventStream):
    """A stream that discards everything — used for non-streaming invocations."""

    async def emit(self, event: RunEvent) -> None:
        return
