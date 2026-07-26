"""SQLAlchemy declarative base and shared column types."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONVariant = JSON().with_variant(JSONB(), "postgresql")
"""Portable JSON column: JSONB on PostgreSQL, plain JSON on SQLite."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    """Declarative base for every ORM entity."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012
        dict[str, Any]: JSONVariant,
        list[str]: JSONVariant,
    }


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` to an entity."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IdMixin:
    """String primary key with a readable prefix."""

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
