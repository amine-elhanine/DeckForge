"""ORM entities.

The persistence model mirrors the workspace: a *user* owns *conversations*;
each conversation holds *messages*, *assets* and *presentations*; each
presentation keeps an append-only chain of *versions* which powers undo, redo,
compare and fork.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deckforge.database.base import Base, IdMixin, TimestampMixin, gen_id


class User(Base, IdMixin, TimestampMixin):
    """A workspace owner. Local mode auto-creates a single ``local`` user."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("usr"))
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), default="Local user")
    preferences: Mapped[dict[str, Any]] = mapped_column(default=dict)

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class Conversation(Base, IdMixin, TimestampMixin):
    """A never-ending collaboration thread around a topic."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("conv"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="New conversation")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    memory: Mapped[dict[str, Any]] = mapped_column(
        default=dict, doc="Distilled long-term facts and user preferences for this thread."
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    presentations: Mapped[list[Presentation]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    assets: Mapped[list[Asset]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base, IdMixin, TimestampMixin):
    """One chat turn. Assistant turns may point at the deck version they produced."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conv_created", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("msg"))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    message_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)
    presentation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    presentation_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict[str, Any]] = mapped_column(default=dict)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Presentation(Base, IdMixin, TimestampMixin):
    """A deck inside a conversation. The deck JSON lives on the current version."""

    __tablename__ = "presentations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("pres"))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="Untitled presentation")
    theme: Mapped[str] = mapped_column(String(80), default="minimal")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    deck: Mapped[dict[str, Any]] = mapped_column(default=dict, doc="Current deck JSON snapshot.")
    forked_from_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="presentations")
    versions: Mapped[list[PresentationVersion]] = relationship(
        back_populates="presentation",
        cascade="all, delete-orphan",
        order_by="PresentationVersion.version",
    )
    exports: Mapped[list[ExportRecord]] = relationship(
        back_populates="presentation", cascade="all, delete-orphan"
    )


class PresentationVersion(Base, IdMixin, TimestampMixin):
    """An immutable deck snapshot — the unit of undo/redo/compare/fork."""

    __tablename__ = "presentation_versions"
    __table_args__ = (
        UniqueConstraint("presentation_id", "version"),
        Index("ix_versions_pres", "presentation_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("ver"))
    presentation_id: Mapped[str] = mapped_column(
        ForeignKey("presentations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(300), default="")
    deck: Mapped[dict[str, Any]] = mapped_column(default=dict)
    change_log: Mapped[list[str]] = mapped_column(default=list)
    created_by_message_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    presentation: Mapped[Presentation] = relationship(back_populates="versions")


class Slide(Base, IdMixin, TimestampMixin):
    """Denormalised slide row.

    The deck JSON stays authoritative; this table exists so the UI can list and
    search slides cheaply without loading every deck snapshot.
    """

    __tablename__ = "slides"
    __table_args__ = (Index("ix_slides_pres_pos", "presentation_id", "position"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("sl"))
    presentation_id: Mapped[str] = mapped_column(
        ForeignKey("presentations.id", ondelete="CASCADE"), index=True
    )
    slide_id: Mapped[str] = mapped_column(String(40), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(40), default="content")
    layout: Mapped[str] = mapped_column(String(60), default="auto")
    title: Mapped[str] = mapped_column(String(500), default="")
    search_text: Mapped[str] = mapped_column(Text, default="")


class Asset(Base, IdMixin, TimestampMixin):
    """An uploaded or generated file (documents, images, diagrams, exports)."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("ast"))
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(160), default="application/octet-stream")
    kind: Mapped[str] = mapped_column(String(40), default="document")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(1000))
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)

    conversation: Mapped[Conversation | None] = relationship(back_populates="assets")
    chunks: Mapped[list[AssetChunk]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class AssetChunk(Base, IdMixin, TimestampMixin):
    """A retrievable passage extracted from an asset."""

    __tablename__ = "asset_chunks"
    __table_args__ = (Index("ix_chunks_asset_pos", "asset_id", "position"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("chk"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)

    asset: Mapped[Asset] = relationship(back_populates="chunks")


class ExportRecord(Base, IdMixin, TimestampMixin):
    """History of rendered files."""

    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("exp"))
    presentation_id: Mapped[str] = mapped_column(
        ForeignKey("presentations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    format: Mapped[str] = mapped_column(String(30))
    filename: Mapped[str] = mapped_column(String(500))
    path: Mapped[str] = mapped_column(String(1000))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    options: Mapped[dict[str, Any]] = mapped_column(default=dict)

    presentation: Mapped[Presentation] = relationship(back_populates="exports")


class ThemeRecord(Base, IdMixin, TimestampMixin):
    """A user-authored theme, stored in the database instead of on disk."""

    __tablename__ = "themes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("thm"))
    name: Mapped[str] = mapped_column(String(80), unique=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    definition: Mapped[dict[str, Any]] = mapped_column(default=dict)
    based_on: Mapped[str | None] = mapped_column(String(80), nullable=True)


class LlmProfile(Base, IdMixin, TimestampMixin):
    """A saved, named LLM connection.

    Users keep several — "DeepSeek", "Local Qwen", "Work Azure" — and switch the
    active one from the settings screen. Several profiles may share a provider
    adapter with different endpoints, models or keys, which is why this is its
    own entity rather than one row per provider.

    The API key is stored as given. This is a single-user local application and
    the database sits in the user's own profile directory; it is not a secrets
    vault, and the UI says so.
    """

    __tablename__ = "llm_profiles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("llm"))
    name: Mapped[str] = mapped_column(String(120), unique=True, doc="User-facing label.")
    provider: Mapped[str] = mapped_column(String(60), doc="Adapter key, e.g. 'openai'.")
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model: Mapped[str] = mapped_column(String(200), default="")
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    options: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base, TimestampMixin):
    """Global key/value settings editable from the UI."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)


__all__ = [
    "Asset",
    "AssetChunk",
    "Conversation",
    "ExportRecord",
    "LlmProfile",
    "Message",
    "Presentation",
    "PresentationVersion",
    "Setting",
    "Slide",
    "ThemeRecord",
    "User",
]
