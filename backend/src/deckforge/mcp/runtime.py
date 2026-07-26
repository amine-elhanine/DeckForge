"""Process setup and shared state for the MCP server.

Two things here matter more than the rest of this package put together.

**stdout belongs to the protocol.** On a stdio transport every byte of stdout is
JSON-RPC. :func:`configure_process` therefore points logging at stderr *before*
anything else can configure it, and nothing in this package may ``print``.

**The data directory must be the one the installed app uses.**
:func:`deckforge.paths.user_data_dir` resolves to ``<repo>/data`` from a source
checkout, which is right for development and wrong here: the LLM connection the
user configured in the desktop app lives in the per-user database, and without
it every request fails with "no LLM configured".
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from deckforge import paths
from deckforge.config import Settings
from deckforge.container import Container
from deckforge.core.logging import configure_logging, get_logger
from deckforge.database.repositories import UnitOfWork
from deckforge.services.chat_service import ChatService
from deckforge.services.conversation_service import ConversationService
from deckforge.services.export_service import ExportService
from deckforge.services.llm_service import LlmService
from deckforge.services.presentation_service import PresentationService

log = get_logger(__name__)


def configure_process() -> Settings:
    """Prepare the process for stdio and return the settings to build on.

    Call this before importing anything that logs. Returns :class:`Settings`
    already pointed at the shared data directory.
    """
    # Pin the data directory through the environment rather than by passing a
    # Settings instance around: `Settings` reads `.env` files relative to it,
    # and `paths` caches its answers, so the variable is the one lever that
    # every later lookup agrees on.
    os.environ.setdefault("DECKFORGE_DATA_DIR", str(paths.shared_data_dir()))

    settings = Settings()
    # Ahead of Container.create(), whose own call then becomes a no-op. Passing
    # the stream explicitly rather than relying on that ordering, because the
    # failure mode if it ever changes is a corrupted protocol stream and a
    # client-side parse error that points nowhere near this line.
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    return settings


@dataclass(slots=True)
class Runtime:
    """The container plus per-request service construction.

    One container per process, built once at server start. Services are
    request-scoped and built per call from a fresh unit of work, exactly as
    :mod:`deckforge.api.deps` does for HTTP.
    """

    container: Container

    @classmethod
    async def start(cls, settings: Settings | None = None) -> Runtime:
        container = Container.create(settings or configure_process())
        await container.startup()
        log.info("mcp.ready", data_dir=str(container.settings.data_dir))
        return cls(container=container)

    async def stop(self) -> None:
        await self.container.shutdown()

    @asynccontextmanager
    async def services(self) -> AsyncIterator[Services]:
        """Yield services bound to one transaction, committed on success."""
        async with self.container.database.session() as session:
            uow = UnitOfWork.create(session)
            yield Services(container=self.container, uow=uow)


@dataclass(slots=True)
class Services:
    """The service objects a single tool call needs."""

    container: Container
    uow: UnitOfWork

    @property
    def conversations(self) -> ConversationService:
        return ConversationService(self.uow, self.container.settings)

    @property
    def presentations(self) -> PresentationService:
        return PresentationService(self.uow)

    @property
    def exports(self) -> ExportService:
        return ExportService(
            self.uow,
            self.container.settings,
            self.container.themes,
            self.container.layouts,
            self.container.renderer,
        )

    @property
    def chat(self) -> ChatService:
        return ChatService(self.container, self.uow)

    @property
    def llm(self) -> LlmService:
        return LlmService(self.uow, self.container.settings, self.container.providers)
