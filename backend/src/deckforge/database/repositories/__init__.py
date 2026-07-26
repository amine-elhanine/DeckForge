"""Repository layer — the only module that talks to SQLAlchemy sessions."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from deckforge.database.repositories.asset import (
    AssetRepository,
    ChunkRepository,
    LlmProfileRepository,
    SettingRepository,
    ThemeRepository,
)
from deckforge.database.repositories.base import Repository
from deckforge.database.repositories.conversation import (
    ConversationRepository,
    MessageRepository,
    UserRepository,
)
from deckforge.database.repositories.presentation import (
    ExportRepository,
    PresentationRepository,
    SlideIndexRepository,
    VersionRepository,
)


@dataclass(slots=True)
class UnitOfWork:
    """Bundles every repository bound to one session.

    Services receive a ``UnitOfWork`` instead of a bag of repositories, so adding
    a repository does not ripple through every constructor.
    """

    session: AsyncSession
    users: UserRepository
    conversations: ConversationRepository
    messages: MessageRepository
    presentations: PresentationRepository
    versions: VersionRepository
    slides: SlideIndexRepository
    exports: ExportRepository
    assets: AssetRepository
    chunks: ChunkRepository
    themes: ThemeRepository
    llm_profiles: LlmProfileRepository
    settings: SettingRepository

    @classmethod
    def create(cls, session: AsyncSession) -> UnitOfWork:
        return cls(
            session=session,
            users=UserRepository(session),
            conversations=ConversationRepository(session),
            messages=MessageRepository(session),
            presentations=PresentationRepository(session),
            versions=VersionRepository(session),
            slides=SlideIndexRepository(session),
            exports=ExportRepository(session),
            assets=AssetRepository(session),
            chunks=ChunkRepository(session),
            themes=ThemeRepository(session),
            llm_profiles=LlmProfileRepository(session),
            settings=SettingRepository(session),
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def flush(self) -> None:
        await self.session.flush()


__all__ = [
    "AssetRepository",
    "ChunkRepository",
    "ConversationRepository",
    "ExportRepository",
    "MessageRepository",
    "PresentationRepository",
    "ProviderConfigRepository",
    "Repository",
    "SettingRepository",
    "SlideIndexRepository",
    "ThemeRepository",
    "UnitOfWork",
    "UserRepository",
    "VersionRepository",
]
