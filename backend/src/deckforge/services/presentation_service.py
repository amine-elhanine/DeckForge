"""Presentation lifecycle: versions, undo/redo, compare and fork.

The deck JSON on the ``presentations`` row is the working copy; every accepted
change also appends an immutable ``PresentationVersion``. Undo is therefore a
pointer move, not a destructive rewrite, and history is never lost.
"""

from __future__ import annotations

from typing import Any

from deckforge.core.errors import NotFoundError, ValidationError
from deckforge.core.logging import get_logger
from deckforge.database.entities import Presentation as PresentationRow
from deckforge.database.entities import PresentationVersion
from deckforge.database.repositories import UnitOfWork
from deckforge.models.deck import Presentation
from deckforge.utils.text import truncate

log = get_logger(__name__)


class PresentationService:
    """CRUD and version control for decks."""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    # -- loading -------------------------------------------------------------- #

    async def get_row(self, presentation_id: str) -> PresentationRow:
        return await self.uow.presentations.get_or_404(presentation_id)

    async def load(self, presentation_id: str) -> Presentation:
        """Load the working copy of a deck."""
        row = await self.get_row(presentation_id)
        return Presentation.model_validate(row.deck)

    async def load_version(self, presentation_id: str, version: int) -> Presentation:
        record = await self.uow.versions.get_version(presentation_id, version)
        if record is None:
            raise NotFoundError(f"version {version} of '{presentation_id}' not found")
        return Presentation.model_validate(record.deck)

    async def latest_for_conversation(self, conversation_id: str) -> PresentationRow | None:
        return await self.uow.presentations.latest_for_conversation(conversation_id)

    # -- writing -------------------------------------------------------------- #

    async def create(
        self,
        conversation_id: str,
        deck: Presentation,
        *,
        label: str = "Initial version",
        message_id: str | None = None,
        change_log: list[str] | None = None,
    ) -> PresentationRow:
        """Persist a brand-new deck plus its first version."""
        row = PresentationRow(
            conversation_id=conversation_id,
            title=deck.title,
            theme=deck.theme,
            deck=deck.model_dump(mode="json"),
            current_version=0,
        )
        await self.uow.presentations.add(row)
        await self.commit_version(
            row, deck, label=label, message_id=message_id, change_log=change_log
        )
        return row

    async def commit_version(
        self,
        row: PresentationRow,
        deck: Presentation,
        *,
        label: str,
        message_id: str | None = None,
        change_log: list[str] | None = None,
    ) -> PresentationVersion:
        """Append a new immutable version and make it current."""
        number = await self.uow.versions.next_version_number(row.id)
        deck.version = number
        record = PresentationVersion(
            presentation_id=row.id,
            version=number,
            label=truncate(label, 280),
            deck=deck.model_dump(mode="json"),
            change_log=change_log or [],
            created_by_message_id=message_id,
        )
        await self.uow.versions.add(record)

        row.deck = record.deck
        row.title = deck.title
        row.theme = deck.theme
        row.current_version = number
        await self.uow.slides.reindex(row.id, deck)
        await self.uow.flush()
        log.info("presentation.version", presentation=row.id, version=number, label=label)
        return record

    async def save_working_copy(self, row: PresentationRow, deck: Presentation) -> None:
        """Update the working copy without creating a version (autosave)."""
        row.deck = deck.model_dump(mode="json")
        row.title = deck.title
        row.theme = deck.theme
        await self.uow.slides.reindex(row.id, deck)
        await self.uow.flush()

    # -- history -------------------------------------------------------------- #

    async def versions(self, presentation_id: str) -> list[dict[str, Any]]:
        records = await self.uow.versions.list_for_presentation(presentation_id)
        return [
            {
                "id": r.id,
                "version": r.version,
                "label": r.label,
                "created_at": r.created_at,
                "slide_count": len(r.deck.get("slides", [])),
                "change_log": r.change_log,
            }
            for r in records
        ]

    async def restore(self, presentation_id: str, version: int) -> Presentation:
        """Undo/redo: make an earlier version current by appending it again.

        Restoring forward-appends rather than truncating, so "undo, then undo the
        undo" is always possible and no history is ever discarded.
        """
        row = await self.get_row(presentation_id)
        deck = await self.load_version(presentation_id, version)
        await self.commit_version(row, deck, label=f"Restored version {version}")
        return deck

    async def undo(self, presentation_id: str) -> Presentation:
        row = await self.get_row(presentation_id)
        records = await self.uow.versions.list_for_presentation(presentation_id)
        if len(records) < 2:
            raise ValidationError("there is nothing to undo yet")
        target = records[-2]
        return await self.restore(row.id, target.version)

    async def fork(
        self, presentation_id: str, *, version: int | None = None, title: str | None = None
    ) -> PresentationRow:
        """Branch a deck into an independent presentation."""
        row = await self.get_row(presentation_id)
        deck = (
            await self.load_version(presentation_id, version)
            if version is not None
            else await self.load(presentation_id)
        )
        deck.title = title or f"{deck.title} (copy)"
        forked = PresentationRow(
            conversation_id=row.conversation_id,
            title=deck.title,
            theme=deck.theme,
            deck=deck.model_dump(mode="json"),
            forked_from_id=row.id,
        )
        await self.uow.presentations.add(forked)
        await self.commit_version(forked, deck, label=f"Forked from {row.title}")
        return forked

    async def compare(self, presentation_id: str, left: int, right: int) -> dict[str, Any]:
        """Diff two versions at slide granularity."""
        a = await self.load_version(presentation_id, left)
        b = await self.load_version(presentation_id, right)
        a_by_id = {s.id: s for s in a.slides}
        b_by_id = {s.id: s for s in b.slides}

        added = [s.id for s in b.slides if s.id not in a_by_id]
        removed = [s.id for s in a.slides if s.id not in b_by_id]
        changed = [
            s.id
            for s in b.slides
            if s.id in a_by_id
            and a_by_id[s.id].model_dump(mode="json") != s.model_dump(mode="json")
        ]
        moved = [
            s.id
            for i, s in enumerate(b.slides)
            if s.id in a_by_id and a.index_of(s.id) != i and s.id not in changed
        ]
        return {
            "left": left,
            "right": right,
            "added": added,
            "removed": removed,
            "changed": changed,
            "moved": moved,
            "left_stats": a.stats(),
            "right_stats": b.stats(),
        }

    async def delete(self, presentation_id: str) -> bool:
        return await self.uow.presentations.delete(presentation_id)
