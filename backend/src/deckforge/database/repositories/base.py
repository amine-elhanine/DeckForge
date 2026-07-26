"""Generic repository implementing the shared CRUD surface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deckforge.core.errors import NotFoundError
from deckforge.database.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """Data access for a single entity type.

    Services depend on repositories, never on SQLAlchemy directly, which keeps
    the business layer swappable and trivially mockable in tests.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get(self, entity_id: Any) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def get_or_404(self, entity_id: Any) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            raise NotFoundError(f"{self.model.__name__} '{entity_id}' not found")
        return entity

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        order_by: Any | None = None,
        **filters: Any,
    ) -> Sequence[ModelT]:
        stmt = select(self.model).limit(limit).offset(offset)
        for field, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, field) == value)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        for field, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, field) == value)
        return int((await self.session.execute(stmt)).scalar_one())

    async def delete(self, entity_id: Any) -> bool:
        result = await self.session.execute(
            delete(self.model).where(self.model.__mapper__.primary_key[0] == entity_id)
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def flush(self) -> None:
        await self.session.flush()
