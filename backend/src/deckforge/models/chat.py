"""API-facing chat and workspace schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from deckforge.models.enums import ContentDensity, ExportFormat, MessageRole


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)


class ConversationSettings(ApiModel):
    """Per-conversation overrides of the global defaults."""

    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    theme: str | None = None
    language: str | None = None
    audience: str | None = None
    tone: str | None = None
    density: ContentDensity | None = None
    default_slide_count: int | None = Field(default=None, ge=1, le=60)
    enable_research: bool = True
    enable_critic: bool = True
    enable_fact_check: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class ConversationCreate(ApiModel):
    title: str | None = None
    settings: ConversationSettings = Field(default_factory=ConversationSettings)


class ConversationUpdate(ApiModel):
    title: str | None = None
    settings: ConversationSettings | None = None
    archived: bool | None = None


class ConversationRead(ApiModel):
    id: str
    title: str
    archived: bool
    created_at: datetime
    updated_at: datetime
    settings: dict[str, Any] = Field(default_factory=dict)
    message_count: int = 0
    presentation_count: int = 0
    latest_presentation_id: str | None = None


class MessageCreate(ApiModel):
    content: str = Field(min_length=1)
    attachments: list[str] = Field(default_factory=list, description="Asset ids to attach.")
    presentation_id: str | None = Field(
        default=None, description="Deck to edit; defaults to the conversation's latest."
    )
    stream: bool = True


class MessageRead(ApiModel):
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    presentation_id: str | None = None
    presentation_version: int | None = None


class PresentationSummary(ApiModel):
    id: str
    conversation_id: str
    title: str
    theme: str
    slide_count: int
    version: int
    created_at: datetime
    updated_at: datetime


class PresentationRead(PresentationSummary):
    deck: dict[str, Any]
    versions: list[VersionSummary] = Field(default_factory=list)


class VersionSummary(ApiModel):
    id: str
    version: int
    label: str
    created_at: datetime
    slide_count: int


class ExportRequest(ApiModel):
    format: ExportFormat = ExportFormat.PPTX
    version: int | None = Field(default=None, description="Defaults to the current version.")
    options: dict[str, Any] = Field(default_factory=dict)


class ExportRead(ApiModel):
    id: str
    presentation_id: str
    format: ExportFormat
    filename: str
    size_bytes: int
    created_at: datetime
    download_url: str


class AssetRead(ApiModel):
    id: str
    conversation_id: str | None
    filename: str
    content_type: str
    size_bytes: int
    kind: str
    created_at: datetime
    indexed: bool = False
    excerpt: str | None = None


class ProviderInfo(ApiModel):
    name: str
    label: str
    kind: str
    configured: bool
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)
    supports_streaming: bool = True
    supports_json_mode: bool = True
    note: str | None = None


class ThemeInfo(ApiModel):
    name: str
    label: str
    description: str
    tags: list[str] = Field(default_factory=list)
    mode: str = "light"
    palette: dict[str, str] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)
    source: str = "builtin"


class LayoutInfo(ApiModel):
    name: str
    label: str
    description: str
    slots: list[str] = Field(default_factory=list)
    suits: list[str] = Field(default_factory=list)


class PluginInfo(ApiModel):
    name: str
    version: str
    description: str
    provides: dict[str, list[str]] = Field(default_factory=dict)
    source: str = "local"


PresentationRead.model_rebuild()
