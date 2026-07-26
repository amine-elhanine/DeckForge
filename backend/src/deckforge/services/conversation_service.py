"""Conversation and upload management."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from deckforge.config import Settings
from deckforge.core.errors import ValidationError
from deckforge.core.logging import get_logger
from deckforge.database.entities import Asset, Conversation, Message
from deckforge.database.repositories import UnitOfWork
from deckforge.database.repositories.conversation import LOCAL_USER_ID
from deckforge.models.enums import MessageRole
from deckforge.retrieval.extractors import supported_extensions
from deckforge.retrieval.service import RetrievalService
from deckforge.utils.text import truncate

log = get_logger(__name__)

_TITLE_STRIP = re.compile(
    r"^\s*(please\s+)?(can you\s+)?(create|make|build|generate|write|design|prepare)\s+"
    r"(me\s+)?(a|an|the)?\s*(presentation|deck|slides?)?\s*(about|on|for|covering)?\s*",
    re.IGNORECASE,
)


class ConversationService:
    """Creates conversations, records messages and stores uploads."""

    def __init__(self, uow: UnitOfWork, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    # -- conversations --------------------------------------------------------- #

    async def create(
        self, *, title: str | None = None, settings: dict[str, Any] | None = None
    ) -> Conversation:
        user = await self.uow.users.get_or_create_local()
        conversation = Conversation(
            user_id=user.id,
            title=title or "New conversation",
            settings=settings or {},
            memory={},
        )
        await self.uow.conversations.add(conversation)
        return conversation

    async def get(self, conversation_id: str) -> Conversation:
        return await self.uow.conversations.get_or_404(conversation_id)

    async def list_all(self, *, include_archived: bool = False) -> list[Conversation]:
        """List the local user's conversations, most recently updated first."""
        return list(
            await self.uow.conversations.list_for_user(
                LOCAL_USER_ID, include_archived=include_archived
            )
        )

    async def update(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        settings: dict[str, Any] | None = None,
        archived: bool | None = None,
    ) -> Conversation:
        conversation = await self.get(conversation_id)
        if title is not None:
            conversation.title = truncate(title, 300)
        if settings is not None:
            conversation.settings = {**(conversation.settings or {}), **settings}
        if archived is not None:
            conversation.archived = archived
        await self.uow.flush()
        return conversation

    async def delete(self, conversation_id: str) -> bool:
        return await self.uow.conversations.delete(conversation_id)

    async def autotitle(self, conversation: Conversation, first_message: str) -> None:
        """Name a fresh conversation from its opening message."""
        if conversation.title not in ("New conversation", "", None):
            return
        cleaned = _TITLE_STRIP.sub("", first_message.strip()).strip(" .:\n")
        if not cleaned:
            return
        conversation.title = truncate(cleaned[:1].upper() + cleaned[1:], 80)
        await self.uow.flush()

    # -- messages -------------------------------------------------------------- #

    async def add_message(
        self,
        conversation_id: str,
        role: MessageRole,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        presentation_id: str | None = None,
        presentation_version: int | None = None,
        usage: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=str(role),
            content=content,
            message_metadata=metadata or {},
            presentation_id=presentation_id,
            presentation_version=presentation_version,
            token_usage=usage or {},
        )
        await self.uow.messages.add(message)
        return message

    async def history(self, conversation_id: str, limit: int = 200) -> list[Message]:
        return list(await self.uow.messages.history(conversation_id, limit))

    # -- uploads --------------------------------------------------------------- #

    async def store_upload(
        self,
        conversation_id: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> Asset:
        """Persist an uploaded file and index it for retrieval."""
        if len(content) > self.settings.max_upload_bytes:
            raise ValidationError(
                f"'{filename}' exceeds the {self.settings.max_upload_bytes // 1_048_576} MB limit"
            )
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension not in supported_extensions():
            raise ValidationError(
                f"unsupported file type '.{extension}'",
                details={"supported": supported_extensions()},
            )

        safe_name = Path(filename).name
        directory = self.settings.uploads_dir / conversation_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{uuid.uuid4().hex[:8]}-{safe_name}"
        target.write_bytes(content)

        asset = Asset(
            conversation_id=conversation_id,
            filename=safe_name,
            content_type=content_type,
            size_bytes=len(content),
            path=str(target),
        )
        await self.uow.assets.add(asset)

        retrieval = RetrievalService(self.uow, top_k=self.settings.retrieval_top_k)
        try:
            await retrieval.ingest(asset, target)
        except ValidationError as exc:
            log.info("upload.not_indexed", file=safe_name, reason=exc.message)

        # Images double as slide assets, so mirror them into the asset library.
        if asset.kind == "image":
            library = self.settings.assets_dir / conversation_id
            library.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, library / target.name)
            asset.asset_metadata = {
                **asset.asset_metadata,
                "src": f"{conversation_id}/{target.name}",
            }
        await self.uow.flush()
        return asset

    async def assets(self, conversation_id: str) -> list[Asset]:
        return list(await self.uow.assets.list_for_conversation(conversation_id))
