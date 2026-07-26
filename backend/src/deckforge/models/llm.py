"""Schemas for saved LLM connections.

An API key is never returned to the client in full — only a masked hint, so the
settings screen can show *which* key is stored without being able to exfiltrate
it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def mask_secret(value: str | None) -> str | None:
    """Return a display-safe hint such as ``sk-…f8149b``."""
    if not value:
        return None
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:3]}…{value[-6:]}"


class LlmModel(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)


class LlmProfileCreate(LlmModel):
    """A new saved connection."""

    name: str = Field(min_length=1, max_length=120, description="Label shown in the picker.")
    provider: str = Field(description="Adapter key, e.g. 'openai', 'ollama', 'deepseek'.")
    base_url: str | None = None
    api_key: str | None = None
    model: str = ""
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    options: dict[str, Any] = Field(default_factory=dict)
    activate: bool = Field(default=True, description="Make this the connection in use.")

    @field_validator("name", "model", "base_url", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class LlmProfileUpdate(LlmModel):
    """A partial edit. Omitted fields keep their stored value.

    ``api_key`` is three-state on purpose: absent leaves the stored key alone,
    a string replaces it, and an empty string clears it. Without that, opening
    the edit form and saving would wipe the key the user cannot see.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    options: dict[str, Any] | None = None


class LlmProfileRead(LlmModel):
    id: str
    name: str
    provider: str
    provider_label: str = ""
    kind: str = "cloud"
    base_url: str | None = None
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    is_active: bool = False
    has_api_key: bool = False
    api_key_hint: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    last_checked_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class LlmProbeRequest(LlmModel):
    """Test a configuration that has not been saved yet.

    ``profile_id`` lets the client test an existing connection without
    re-sending the key it never received.
    """

    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    profile_id: str | None = None


class LlmProbeResult(LlmModel):
    ok: bool
    provider: str
    models: list[str] = Field(default_factory=list)
    model_available: bool | None = None
    latency_ms: int | None = None
    error: str | None = None
    hint: str | None = None


class ProviderTemplate(LlmModel):
    """What the "add a connection" form needs to prefill itself."""

    name: str
    label: str
    kind: str
    requires_api_key: bool
    default_base_url: str | None = None
    default_model: str = ""
    suggested_models: list[str] = Field(default_factory=list)
    configured_from_env: bool = False
    note: str | None = None
