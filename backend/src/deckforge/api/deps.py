"""FastAPI dependencies.

The container lives on ``app.state``; request-scoped units of work and services
are built per request from it. Route handlers never import the container module
directly, which keeps them trivially testable with a stub.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request

from deckforge.config import Settings
from deckforge.container import Container
from deckforge.database.repositories import UnitOfWork
from deckforge.services.chat_service import ChatService
from deckforge.services.conversation_service import ConversationService
from deckforge.services.export_service import ExportService
from deckforge.services.llm_service import LlmService
from deckforge.services.presentation_service import PresentationService


def get_container(request: Request) -> Container:
    """Return the application container."""
    return request.app.state.container  # type: ignore[no-any-return]


ContainerDep = Annotated[Container, Depends(get_container)]


def get_settings_dep(container: ContainerDep) -> Settings:
    return container.settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


async def get_uow(container: ContainerDep) -> AsyncIterator[UnitOfWork]:
    """Yield a request-scoped unit of work that commits on success."""
    async with container.database.session() as session:
        yield UnitOfWork.create(session)


UowDep = Annotated[UnitOfWork, Depends(get_uow)]


def get_conversation_service(container: ContainerDep, uow: UowDep) -> ConversationService:
    return ConversationService(uow, container.settings)


def get_presentation_service(uow: UowDep) -> PresentationService:
    return PresentationService(uow)


def get_export_service(container: ContainerDep, uow: UowDep) -> ExportService:
    return ExportService(
        uow, container.settings, container.themes, container.layouts, container.renderer
    )


def get_chat_service(container: ContainerDep, uow: UowDep) -> ChatService:
    return ChatService(container, uow)


def get_llm_service(container: ContainerDep, uow: UowDep) -> LlmService:
    return LlmService(uow, container.settings, container.providers)


ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
PresentationServiceDep = Annotated[PresentationService, Depends(get_presentation_service)]
ExportServiceDep = Annotated[ExportService, Depends(get_export_service)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
LlmServiceDep = Annotated[LlmService, Depends(get_llm_service)]
