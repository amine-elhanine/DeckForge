"""Chat service — one user turn, end to end.

Owns the boundary between the agent pipeline and persistence: it builds the
agent context, streams progress to the caller while the coordinator works, then
commits the resulting deck version, assistant message and any exports as a
single unit.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from deckforge.agents.base import AgentContext
from deckforge.agents.coordinator import CoordinatorAgent, TurnResult
from deckforge.container import Container
from deckforge.core.errors import DeckForgeError, ProviderNotConfiguredError
from deckforge.core.events import EventStream, EventType, RunEvent
from deckforge.core.logging import get_logger
from deckforge.database.entities import Conversation, Message
from deckforge.database.repositories import UnitOfWork
from deckforge.memory.service import MemoryService
from deckforge.models.chat import MessageCreate
from deckforge.models.deck import Presentation
from deckforge.models.enums import Intent, MessageRole
from deckforge.providers.base import ChatMessage
from deckforge.retrieval.service import ConversationRetriever, RetrievalService
from deckforge.services.conversation_service import ConversationService
from deckforge.services.export_service import ExportService
from deckforge.services.llm_service import LlmService
from deckforge.services.presentation_service import PresentationService

log = get_logger(__name__)


class ChatService:
    """Runs conversational turns."""

    def __init__(self, container: Container, uow: UnitOfWork) -> None:
        self.container = container
        self.uow = uow
        self.settings = container.settings
        self.conversations = ConversationService(uow, container.settings)
        self.presentations = PresentationService(uow)
        self.exports = ExportService(
            uow, container.settings, container.themes, container.layouts, container.renderer
        )
        self.memory = MemoryService(uow)
        self.llm = LlmService(uow, container.settings, container.providers)
        self.coordinator = CoordinatorAgent()
        self._active_profile_id: str | None = None

    # -- public API ------------------------------------------------------------ #

    async def stream(self, conversation_id: str, payload: MessageCreate) -> AsyncIterator[RunEvent]:
        """Run a turn, yielding progress events as they happen."""
        events = EventStream()
        prepared = await self._prepare(conversation_id, payload, events)
        if isinstance(prepared, RunEvent):
            yield prepared
            yield RunEvent(type=EventType.DONE)
            return

        ctx, conversation, deck_row = prepared

        async def work() -> TurnResult:
            """Run the pipeline, always closing the stream so the consumer ends."""
            try:
                return await self.coordinator.handle(ctx)
            finally:
                await events.close()

        task = asyncio.create_task(work())
        try:
            async for event in events:
                yield event
            result = await task
        except BaseException:
            task.cancel()
            raise

        async for event in self._finalise(conversation, deck_row, result, payload):
            yield event
        yield RunEvent(type=EventType.DONE)

    async def run(self, conversation_id: str, payload: MessageCreate) -> dict[str, Any]:
        """Non-streaming variant, for scripting and tests."""
        final: dict[str, Any] = {"events": []}
        async for event in self.stream(conversation_id, payload):
            if event.type in (EventType.MESSAGE, EventType.ERROR):
                final[event.type.value] = event.data
            elif event.type == EventType.DECK:
                final["deck"] = event.data.get("deck")
            else:
                final["events"].append(event.model_dump(mode="json"))
        return final

    # -- turn setup ------------------------------------------------------------- #

    async def _prepare(
        self, conversation_id: str, payload: MessageCreate, events: EventStream
    ) -> tuple[AgentContext, Conversation, Any] | RunEvent:
        conversation = await self.conversations.get(conversation_id)
        await self.conversations.autotitle(conversation, payload.content)
        await self.conversations.add_message(
            conversation_id,
            MessageRole.USER,
            payload.content,
            metadata={"attachments": payload.attachments} if payload.attachments else None,
        )
        await self.memory.observe_message(conversation, payload.content)
        preferences = await self.memory.preferences(conversation)

        try:
            provider, profile, generation = await self.llm.resolve(preferences)
        except ProviderNotConfiguredError as exc:
            return RunEvent.error(exc.message, code="no_llm_configured")
        except DeckForgeError as exc:
            return RunEvent.error(exc.message, code=exc.code)

        deck_row = await self._resolve_deck_row(conversation_id, payload.presentation_id)
        deck = Presentation.model_validate(deck_row.deck) if deck_row else None

        retrieval = RetrievalService(self.uow, top_k=self.settings.retrieval_top_k)
        retriever = (
            ConversationRetriever(retrieval, conversation_id)
            if await retrieval.has_documents(conversation_id)
            else None
        )

        ctx = AgentContext(
            provider=provider,
            settings=self.settings,
            themes=self.container.themes,
            layouts=self.container.layouts,
            events=events,
            conversation_id=conversation_id,
            history=await self._history_messages(conversation_id),
            user_message=payload.content,
            deck=deck,
            memory=dict(conversation.memory or {}),
            preferences=preferences,
            retriever=retriever,
            # The saved connection supplies sampling defaults; a conversation
            # override still wins, and the global default is the last resort.
            temperature=generation.get("temperature") or self.settings.default_temperature,
            model=provider.config.default_model,
            max_tokens=generation.get("max_tokens"),
        )
        self._active_profile_id = profile.id if profile else None
        return ctx, conversation, deck_row

    async def _resolve_deck_row(self, conversation_id: str, presentation_id: str | None) -> Any:
        if presentation_id:
            return await self.presentations.get_row(presentation_id)
        return await self.presentations.latest_for_conversation(conversation_id)

    async def _history_messages(self, conversation_id: str, limit: int = 12) -> list[ChatMessage]:
        rows = await self.uow.messages.recent(conversation_id, limit)
        return [
            ChatMessage(role=row.role, content=row.content)  # type: ignore[arg-type]
            for row in rows
            if row.role in ("user", "assistant") and row.content.strip()
        ][:-1]  # drop the message we just stored; it is passed separately

    # -- persistence ------------------------------------------------------------ #

    async def _finalise(
        self,
        conversation: Conversation,
        deck_row: Any,
        result: TurnResult,
        payload: MessageCreate,
    ) -> AsyncIterator[RunEvent]:
        """Commit whatever the turn produced and emit the closing events."""
        presentation_id = deck_row.id if deck_row else None
        version: int | None = deck_row.current_version if deck_row else None
        artifacts: list[dict[str, Any]] = []

        if result.deck is not None and result.intent is not Intent.EXPORT:
            deck_row, version = await self._persist_deck(
                conversation, deck_row, result, payload.content
            )
            presentation_id = deck_row.id
            await self.memory.note_deck(conversation, result.deck)

        if result.intent is Intent.EXPORT and deck_row is not None:
            artifacts = await self._run_exports(deck_row.id, result)
            if artifacts:
                names = ", ".join(a["format"].upper() for a in artifacts)
                result.reply = result.reply or f"Exported your deck as {names}."
            else:
                result.reply = result.reply or "I could not produce that export."
            for artifact in artifacts:
                yield RunEvent(type=EventType.ARTIFACT, data=artifact)

        # Surface a failing connection in the settings screen rather than only
        # in the transcript, where it scrolls away.
        if result.error and self._active_profile_id:
            await self.llm.record_failure(self._active_profile_id, result.error)

        message = await self.conversations.add_message(
            conversation.id,
            MessageRole.ASSISTANT,
            result.reply,
            metadata=self._message_metadata(result, artifacts),
            presentation_id=presentation_id,
            presentation_version=version,
        )
        await self.uow.conversations.touch(conversation)
        await self.uow.commit()

        yield RunEvent(type=EventType.MESSAGE, data=self._message_payload(message))

    async def _persist_deck(
        self, conversation: Conversation, deck_row: Any, result: TurnResult, prompt: str
    ) -> tuple[Any, int]:
        deck = result.deck
        assert deck is not None
        label = result.changelog[0] if result.changelog else prompt
        if deck_row is None:
            deck_row = await self.presentations.create(
                conversation.id, deck, label="Initial version", change_log=result.changelog
            )
        elif result.changed:
            await self.presentations.commit_version(
                deck_row, deck, label=label, change_log=result.changelog
            )
        else:
            await self.presentations.save_working_copy(deck_row, deck)
        return deck_row, deck_row.current_version

    async def _run_exports(self, presentation_id: str, result: TurnResult) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for fmt in result.export_formats:
            try:
                record = await self.exports.export(presentation_id, fmt)
            except DeckForgeError as exc:
                log.warning("chat.export_failed", format=fmt, error=exc.message)
                continue
            artifacts.append(
                {
                    "id": record.id,
                    "format": record.format,
                    "filename": record.filename,
                    "size_bytes": record.size_bytes,
                    "download_url": f"{self.settings.api_prefix}/exports/{record.id}/download",
                }
            )
        return artifacts

    @staticmethod
    def _message_metadata(result: TurnResult, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        metadata: dict[str, Any] = {"intent": str(result.intent), "changed": result.changed}
        if result.changelog:
            metadata["changelog"] = result.changelog[:20]
        if result.clarifying_questions:
            metadata["questions"] = result.clarifying_questions
        if artifacts:
            metadata["artifacts"] = artifacts
        if result.critique is not None:
            metadata["review"] = {
                "score": result.critique.score,
                "verdict": result.critique.verdict,
                "issues": len(result.critique.issues),
            }
        if result.error:
            metadata["error"] = result.error
        return metadata

    @staticmethod
    def _message_payload(message: Message) -> dict[str, Any]:
        return {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
            "metadata": message.message_metadata,
            "presentation_id": message.presentation_id,
            "presentation_version": message.presentation_version,
        }
