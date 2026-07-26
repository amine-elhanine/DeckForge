"""Repositories for uploaded assets and their retrievable chunks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update

from deckforge.database.entities import Asset, AssetChunk, LlmProfile, Setting, ThemeRecord
from deckforge.database.repositories.base import Repository


class AssetRepository(Repository[Asset]):
    model = Asset

    async def list_for_conversation(self, conversation_id: str) -> Sequence[Asset]:
        stmt = (
            select(Asset)
            .where(Asset.conversation_id == conversation_id)
            .order_by(Asset.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().all()


class ChunkRepository(Repository[AssetChunk]):
    model = AssetChunk

    async def for_conversation(
        self, conversation_id: str, limit: int = 5000
    ) -> Sequence[AssetChunk]:
        stmt = (
            select(AssetChunk)
            .where(AssetChunk.conversation_id == conversation_id)
            .order_by(AssetChunk.asset_id, AssetChunk.position)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def for_assets(self, asset_ids: list[str]) -> Sequence[AssetChunk]:
        if not asset_ids:
            return []
        stmt = (
            select(AssetChunk)
            .where(AssetChunk.asset_id.in_(asset_ids))
            .order_by(AssetChunk.asset_id, AssetChunk.position)
        )
        return (await self.session.execute(stmt)).scalars().all()


class ThemeRepository(Repository[ThemeRecord]):
    model = ThemeRecord

    async def by_name(self, name: str) -> ThemeRecord | None:
        stmt = select(ThemeRecord).where(ThemeRecord.name == name)
        return (await self.session.execute(stmt)).scalars().first()

    async def all_records(self) -> Sequence[ThemeRecord]:
        return (await self.session.execute(select(ThemeRecord))).scalars().all()


class LlmProfileRepository(Repository[LlmProfile]):
    """Saved LLM connections. Exactly one may be active at a time."""

    model = LlmProfile

    async def all_profiles(self) -> Sequence[LlmProfile]:
        stmt = select(LlmProfile).order_by(LlmProfile.created_at.asc())
        return (await self.session.execute(stmt)).scalars().all()

    async def by_name(self, name: str) -> LlmProfile | None:
        stmt = select(LlmProfile).where(LlmProfile.name == name)
        return (await self.session.execute(stmt)).scalars().first()

    async def active(self) -> LlmProfile | None:
        stmt = select(LlmProfile).where(LlmProfile.is_active.is_(True)).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def set_active(self, profile_id: str) -> LlmProfile:
        """Activate one profile and deactivate every other, atomically."""
        profile = await self.get_or_404(profile_id)
        await self.session.execute(
            update(LlmProfile)
            .where(LlmProfile.id != profile_id, LlmProfile.is_active.is_(True))
            .values(is_active=False)
        )
        profile.is_active = True
        await self.session.flush()
        return profile


class SettingRepository(Repository[Setting]):
    model = Setting

    async def get_value(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        row = await self.get(key)
        return row.value if row else (default or {})

    async def set_value(self, key: str, value: dict[str, Any]) -> Setting:
        row = await self.get(key)
        if row is None:
            row = Setting(key=key, value=value)
            await self.add(row)
        else:
            row.value = value
            await self.session.flush()
        return row
