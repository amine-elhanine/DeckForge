"""Conversation, message and upload endpoints (including the SSE chat stream)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, File, Query, UploadFile, status
from starlette.responses import StreamingResponse

from deckforge.api.deps import ChatServiceDep, ConversationServiceDep, PresentationServiceDep
from deckforge.api.sse import sse_response
from deckforge.core.events import EventType, RunEvent
from deckforge.core.logging import get_logger
from deckforge.models.chat import (
    AssetRead,
    ConversationCreate,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
)

log = get_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _to_read(
    service: ConversationServiceDep, presentations: PresentationServiceDep, conversation: Any
) -> ConversationRead:
    latest = await presentations.latest_for_conversation(conversation.id)
    return ConversationRead(
        id=conversation.id,
        title=conversation.title,
        archived=conversation.archived,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        settings=conversation.settings or {},
        message_count=await service.uow.messages.count(conversation_id=conversation.id),
        presentation_count=await service.uow.presentations.count(conversation_id=conversation.id),
        latest_presentation_id=latest.id if latest else None,
    )


@router.get("", response_model=list[ConversationRead], summary="List conversations")
async def list_conversations(
    service: ConversationServiceDep,
    presentations: PresentationServiceDep,
    include_archived: bool = Query(False),
) -> list[ConversationRead]:
    conversations = await service.list_all(include_archived=include_archived)
    return [await _to_read(service, presentations, c) for c in conversations]


@router.post(
    "",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation",
)
async def create_conversation(
    payload: ConversationCreate,
    service: ConversationServiceDep,
    presentations: PresentationServiceDep,
) -> ConversationRead:
    conversation = await service.create(
        title=payload.title, settings=payload.settings.model_dump(exclude_none=True)
    )
    return await _to_read(service, presentations, conversation)


@router.get("/{conversation_id}", response_model=ConversationRead, summary="Get a conversation")
async def get_conversation(
    conversation_id: str,
    service: ConversationServiceDep,
    presentations: PresentationServiceDep,
) -> ConversationRead:
    conversation = await service.get(conversation_id)
    return await _to_read(service, presentations, conversation)


@router.patch(
    "/{conversation_id}", response_model=ConversationRead, summary="Update a conversation"
)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    service: ConversationServiceDep,
    presentations: PresentationServiceDep,
) -> ConversationRead:
    conversation = await service.update(
        conversation_id,
        title=payload.title,
        settings=payload.settings.model_dump(exclude_none=True) if payload.settings else None,
        archived=payload.archived,
    )
    return await _to_read(service, presentations, conversation)


@router.delete(
    "/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a conversation"
)
async def delete_conversation(conversation_id: str, service: ConversationServiceDep) -> None:
    await service.delete(conversation_id)


@router.get(
    "/{conversation_id}/messages", response_model=list[MessageRead], summary="Message history"
)
async def list_messages(
    conversation_id: str, service: ConversationServiceDep, limit: int = Query(200, ge=1, le=1000)
) -> list[MessageRead]:
    rows = await service.history(conversation_id, limit)
    return [
        MessageRead(
            id=row.id,
            conversation_id=row.conversation_id,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
            metadata=row.message_metadata or {},
            presentation_id=row.presentation_id,
            presentation_version=row.presentation_version,
        )
        for row in rows
    ]


@router.post(
    "/{conversation_id}/messages",
    summary="Send a message (streams progress over SSE)",
    response_class=StreamingResponse,
)
async def send_message(
    conversation_id: str, payload: MessageCreate, chat: ChatServiceDep
) -> StreamingResponse:
    """Run one turn of the agent pipeline.

    Emits Server-Sent Events: ``status`` (progress), ``token`` (assistant reply),
    ``slide``/``deck`` (live preview), ``artifact`` (exports), ``message`` (the
    persisted turn) and ``done``.
    """

    async def events() -> AsyncIterator[RunEvent]:
        try:
            async for event in chat.stream(conversation_id, payload):
                yield event
        except Exception as exc:  # pragma: no cover - transport level safety net
            log.exception("chat.stream_failed", conversation=conversation_id)
            yield RunEvent.error(str(exc))
            yield RunEvent(type=EventType.DONE)

    return sse_response(events())


@router.post(
    "/{conversation_id}/messages/sync",
    summary="Send a message and wait for the result (no streaming)",
)
async def send_message_sync(
    conversation_id: str, payload: MessageCreate, chat: ChatServiceDep
) -> dict[str, Any]:
    return await chat.run(conversation_id, payload)


@router.post(
    "/{conversation_id}/uploads",
    response_model=list[AssetRead],
    status_code=status.HTTP_201_CREATED,
    summary="Upload source documents",
)
async def upload_files(
    conversation_id: str,
    service: ConversationServiceDep,
    files: list[UploadFile] = File(...),
) -> list[AssetRead]:
    """Store and index files the agent may draw on (PDF, DOCX, PPTX, MD, CSV, XLSX, images)."""
    stored = []
    for upload in files:
        content = await upload.read()
        asset = await service.store_upload(
            conversation_id,
            upload.filename or "upload",
            content,
            upload.content_type or "application/octet-stream",
        )
        stored.append(_asset_read(asset))
    return stored


@router.get("/{conversation_id}/assets", response_model=list[AssetRead], summary="List assets")
async def list_assets(conversation_id: str, service: ConversationServiceDep) -> list[AssetRead]:
    return [_asset_read(a) for a in await service.assets(conversation_id)]


def _asset_read(asset: Any) -> AssetRead:
    return AssetRead(
        id=asset.id,
        conversation_id=asset.conversation_id,
        filename=asset.filename,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        kind=asset.kind,
        created_at=asset.created_at,
        indexed=asset.indexed,
        excerpt=asset.excerpt,
    )
