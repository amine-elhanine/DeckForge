"""Repositories for presentations, versions, slide index and exports."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select

from deckforge.database.entities import (
    ExportRecord,
    Presentation,
    PresentationVersion,
    Slide,
)
from deckforge.database.repositories.base import Repository
from deckforge.models.deck import Presentation as DeckModel


class PresentationRepository(Repository[Presentation]):
    model = Presentation

    async def list_for_conversation(self, conversation_id: str) -> Sequence[Presentation]:
        stmt = (
            select(Presentation)
            .where(Presentation.conversation_id == conversation_id)
            .order_by(Presentation.created_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def latest_for_conversation(self, conversation_id: str) -> Presentation | None:
        stmt = (
            select(Presentation)
            .where(Presentation.conversation_id == conversation_id)
            .order_by(Presentation.updated_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def recent(self, limit: int = 20) -> Sequence[Presentation]:
        """Most recently touched decks across every conversation.

        The UI browses by conversation; an MCP client has no conversation of its
        own and needs a flat list to pick an earlier deck back up.
        """
        stmt = select(Presentation).order_by(Presentation.updated_at.desc()).limit(limit)
        return (await self.session.execute(stmt)).scalars().all()


class VersionRepository(Repository[PresentationVersion]):
    model = PresentationVersion

    async def list_for_presentation(self, presentation_id: str) -> Sequence[PresentationVersion]:
        stmt = (
            select(PresentationVersion)
            .where(PresentationVersion.presentation_id == presentation_id)
            .order_by(PresentationVersion.version.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_version(self, presentation_id: str, version: int) -> PresentationVersion | None:
        stmt = select(PresentationVersion).where(
            PresentationVersion.presentation_id == presentation_id,
            PresentationVersion.version == version,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def next_version_number(self, presentation_id: str) -> int:
        stmt = select(func.max(PresentationVersion.version)).where(
            PresentationVersion.presentation_id == presentation_id
        )
        current = (await self.session.execute(stmt)).scalar()
        return int(current or 0) + 1


class SlideIndexRepository(Repository[Slide]):
    """Keeps the denormalised slide table in sync with the deck JSON."""

    model = Slide

    async def reindex(self, presentation_id: str, deck: DeckModel) -> None:
        await self.session.execute(delete(Slide).where(Slide.presentation_id == presentation_id))
        for position, slide in enumerate(deck.slides):
            self.session.add(
                Slide(
                    presentation_id=presentation_id,
                    slide_id=slide.id,
                    position=position,
                    kind=str(slide.kind),
                    layout=slide.layout,
                    title=slide.title[:500],
                    search_text=slide.text_content()[:20000],
                )
            )
        await self.session.flush()

    async def search(self, conversation_id: str, query: str, limit: int = 20) -> Sequence[Slide]:
        pattern = f"%{query.lower()}%"
        stmt = (
            select(Slide)
            .join(Presentation, Presentation.id == Slide.presentation_id)
            .where(
                Presentation.conversation_id == conversation_id,
                func.lower(Slide.search_text).like(pattern),
            )
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()


class ExportRepository(Repository[ExportRecord]):
    model = ExportRecord

    async def history(self, presentation_id: str, limit: int = 50) -> Sequence[ExportRecord]:
        stmt = (
            select(ExportRecord)
            .where(ExportRecord.presentation_id == presentation_id)
            .order_by(ExportRecord.created_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()


__all__ = [
    "ExportRepository",
    "PresentationRepository",
    "SlideIndexRepository",
    "VersionRepository",
]
