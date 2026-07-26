"""Saved LLM connections: CRUD, activation, health probing and resolution.

This is the single place that answers "which model am I about to talk to?".
Resolution order, highest first:

1. an explicit override on the conversation (``settings.provider`` / ``model``)
2. the active saved connection
3. the environment defaults (``DECKFORGE_DEFAULT_PROVIDER`` and friends)

The last rung keeps headless/server deployments working with nothing but a
``.env``, while the desktop app lives entirely on rung 2.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from deckforge.config import Settings
from deckforge.core.errors import ConflictError, DeckForgeError, NotFoundError, ValidationError
from deckforge.core.logging import get_logger
from deckforge.database.base import utcnow
from deckforge.database.entities import LlmProfile
from deckforge.database.repositories import UnitOfWork
from deckforge.models.llm import (
    LlmProbeRequest,
    LlmProbeResult,
    LlmProfileCreate,
    LlmProfileRead,
    LlmProfileUpdate,
    ProviderTemplate,
    mask_secret,
)
from deckforge.providers.base import LLMProvider
from deckforge.providers.registry import PROVIDERS, ProviderFactory

log = get_logger(__name__)

#: Sentinel used by the client to say "leave the stored key alone".
UNCHANGED_KEY = "__unchanged__"


class LlmService:
    """Manages the user's LLM connections."""

    def __init__(self, uow: UnitOfWork, settings: Settings, factory: ProviderFactory) -> None:
        self.uow = uow
        self.settings = settings
        self.factory = factory

    # -- reads ---------------------------------------------------------------- #

    async def list_all(self) -> list[LlmProfileRead]:
        """Every saved connection, oldest first, with keys masked."""
        return [self.to_read(p) for p in await self.uow.llm_profiles.all_profiles()]

    async def get(self, profile_id: str) -> LlmProfile:
        return await self.uow.llm_profiles.get_or_404(profile_id)

    async def active(self) -> LlmProfile | None:
        return await self.uow.llm_profiles.active()

    def to_read(self, profile: LlmProfile) -> LlmProfileRead:
        spec = PROVIDERS.try_get(profile.provider)
        return LlmProfileRead(
            id=profile.id,
            name=profile.name,
            provider=profile.provider,
            provider_label=spec.cls.label if spec else profile.provider,
            kind=spec.cls.kind if spec else "cloud",
            base_url=profile.base_url,
            model=profile.model,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            is_active=profile.is_active,
            has_api_key=bool(profile.api_key),
            api_key_hint=mask_secret(profile.api_key),
            options=profile.options or {},
            last_checked_at=profile.last_checked_at,
            last_error=profile.last_error,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def templates(self) -> list[ProviderTemplate]:
        """Prefill data for the "add a connection" form."""
        out: list[ProviderTemplate] = []
        for name in PROVIDERS.names():
            spec = PROVIDERS.get(name)
            try:
                probe = spec.build(self.settings, spec.default_model)
                base_url, configured = probe.config.base_url, probe.is_configured
            except Exception:  # pragma: no cover - defensive against bad plugins
                base_url, configured = None, False
            out.append(
                ProviderTemplate(
                    name=name,
                    label=spec.cls.label,
                    kind=spec.cls.kind,
                    requires_api_key=spec.cls.requires_api_key,
                    default_base_url=base_url,
                    default_model=spec.default_model,
                    suggested_models=spec.suggested_models,
                    configured_from_env=configured and spec.cls.requires_api_key,
                    note=spec.note,
                )
            )
        return out

    # -- writes --------------------------------------------------------------- #

    async def create(self, payload: LlmProfileCreate) -> LlmProfile:
        """Save a new connection.

        Raises:
            NotFoundError: unknown provider adapter.
            ConflictError: the label is already taken.
            ValidationError: the adapter needs an API key and none was given.
        """
        self._require_known_provider(payload.provider)
        if await self.uow.llm_profiles.by_name(payload.name):
            raise ConflictError(f"a connection named '{payload.name}' already exists")

        spec = PROVIDERS.get(payload.provider)
        if spec.cls.requires_api_key and not payload.api_key:
            raise ValidationError(f"{spec.cls.label} requires an API key")

        profile = LlmProfile(
            name=payload.name,
            provider=payload.provider,
            base_url=payload.base_url or None,
            api_key=payload.api_key or None,
            model=payload.model or spec.default_model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            options=payload.options,
        )
        await self.uow.llm_profiles.add(profile)

        # The first connection is always the active one; otherwise nothing would
        # be selected and the next turn would fall back to the environment.
        if payload.activate or len(await self.uow.llm_profiles.all_profiles()) == 1:
            await self.uow.llm_profiles.set_active(profile.id)
        log.info("llm.profile_created", profile=profile.id, provider=profile.provider)
        return profile

    async def update(self, profile_id: str, payload: LlmProfileUpdate) -> LlmProfile:
        profile = await self.get(profile_id)
        data = payload.model_dump(exclude_unset=True)

        if (new_name := data.get("name")) and new_name != profile.name:
            if await self.uow.llm_profiles.by_name(new_name):
                raise ConflictError(f"a connection named '{new_name}' already exists")
            profile.name = new_name
        if provider := data.get("provider"):
            self._require_known_provider(provider)
            profile.provider = provider
        if "base_url" in data:
            profile.base_url = data["base_url"] or None
        if "model" in data and data["model"] is not None:
            profile.model = data["model"]
        if "temperature" in data:
            profile.temperature = data["temperature"]
        if "max_tokens" in data:
            profile.max_tokens = data["max_tokens"]
        if "options" in data and data["options"] is not None:
            profile.options = data["options"]
        if "api_key" in data and data["api_key"] != UNCHANGED_KEY:
            profile.api_key = data["api_key"] or None

        profile.last_error = None
        await self.uow.flush()
        return profile

    async def activate(self, profile_id: str) -> LlmProfile:
        return await self.uow.llm_profiles.set_active(profile_id)

    async def delete(self, profile_id: str) -> None:
        """Delete a connection, promoting another if the active one goes away."""
        profile = await self.get(profile_id)
        was_active = profile.is_active
        await self.uow.llm_profiles.delete(profile_id)
        await self.uow.flush()
        if was_active:
            remaining = await self.uow.llm_profiles.all_profiles()
            if remaining:
                await self.uow.llm_profiles.set_active(remaining[0].id)

    # -- probing -------------------------------------------------------------- #

    async def probe(self, request: LlmProbeRequest) -> LlmProbeResult:
        """Check that a configuration can actually reach a model.

        Works for both saved and unsaved connections, so "Test" is usable before
        the user commits anything.
        """
        provider_name = request.provider
        base_url, api_key, model = request.base_url, request.api_key, request.model

        if request.profile_id:
            stored = await self.get(request.profile_id)
            provider_name = provider_name or stored.provider
            base_url = base_url or stored.base_url
            model = model or stored.model
            if not api_key or api_key == UNCHANGED_KEY:
                api_key = stored.api_key

        if not provider_name:
            raise ValidationError("a provider is required")

        started = time.perf_counter()
        try:
            provider = self.factory.build(
                provider_name, model=model, base_url=base_url, api_key=api_key
            )
            models = await provider.list_models()
        except DeckForgeError as exc:
            return self._failure(provider_name, exc.message, started)
        except Exception as exc:  # network, TLS, DNS…
            return self._failure(provider_name, str(exc), started)

        result = LlmProbeResult(
            ok=True,
            provider=provider_name,
            models=models,
            model_available=(model in models) if (model and models) else None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        if result.model_available is False:
            result.hint = f"'{model}' was not in the model list — check the name."

        if request.profile_id:
            stored = await self.get(request.profile_id)
            stored.last_checked_at = utcnow()
            stored.last_error = None
            await self.uow.flush()
        return result

    def _failure(self, provider: str, message: str, started: float) -> LlmProbeResult:
        return LlmProbeResult(
            ok=False,
            provider=provider,
            error=message,
            latency_ms=int((time.perf_counter() - started) * 1000),
            hint=self._hint_for(provider, message),
        )

    @staticmethod
    def _hint_for(provider: str, message: str) -> str | None:
        lowered = message.lower()
        if "unreachable" in lowered or "connect" in lowered or "refused" in lowered:
            spec = PROVIDERS.try_get(provider)
            if spec and spec.cls.kind == "local":
                return "Is the local server running? " + (spec.note or "")
            return "Check the base URL and your network connection."
        if "401" in lowered or "403" in lowered or "unauthor" in lowered:
            return "The API key was rejected."
        if "404" in lowered:
            return "The endpoint was not found — check the base URL path."
        return None

    async def record_failure(self, profile_id: str, message: str) -> None:
        """Remember why a connection failed so the settings screen can show it."""
        profile = await self.uow.llm_profiles.get(profile_id)
        if profile is not None:
            profile.last_error = message[:500]
            profile.last_checked_at = utcnow()
            await self.uow.flush()

    # -- resolution ------------------------------------------------------------ #

    async def resolve(
        self, overrides: dict[str, Any] | None = None
    ) -> tuple[LLMProvider, LlmProfile | None, dict[str, Any]]:
        """Return the provider to use for a turn, plus its generation defaults.

        Raises:
            ProviderNotConfiguredError: nothing usable is configured.
        """
        overrides = overrides or {}
        profile = await self.active()

        provider_name = overrides.get("provider") or (profile.provider if profile else None)
        model = overrides.get("model") or (profile.model if profile else None)

        if profile is not None and provider_name == profile.provider:
            provider = self.factory.build(
                provider_name,
                model=model,
                base_url=profile.base_url,
                api_key=profile.api_key,
                options=profile.options,
            )
            defaults = {
                "temperature": overrides.get("temperature") or profile.temperature,
                "max_tokens": overrides.get("max_tokens") or profile.max_tokens,
            }
            return provider, profile, defaults

        # No saved connection, or the conversation points at a different
        # adapter: fall back to the environment-configured provider.
        provider = self.factory.get(provider_name, model)
        return (
            provider,
            None,
            {
                "temperature": overrides.get("temperature"),
                "max_tokens": overrides.get("max_tokens"),
            },
        )

    async def bootstrap_from_env(self) -> LlmProfile | None:
        """Create a first connection from ``.env`` when none exists.

        Someone who already configured a key in the environment should not have
        to retype it in the UI on first launch.

        A *local* provider is only adopted if it actually answers: every install
        has a plausible-looking Ollama URL, and seeding a connection that cannot
        reach anything would suppress the "connect a model" prompt and leave a
        fresh install looking broken instead of unconfigured.
        """
        if await self.uow.llm_profiles.all_profiles():
            return None
        name = self.settings.default_provider
        spec = PROVIDERS.try_get(name)
        if spec is None:
            return None
        try:
            provider = spec.build(self.settings, self.settings.default_model)
        except Exception:  # pragma: no cover - defensive
            return None
        if not provider.is_configured:
            return None
        if spec.cls.kind == "local" and not await self._reachable(provider):
            log.info("llm.bootstrap_skipped_unreachable", provider=name)
            return None

        profile = LlmProfile(
            name=f"{spec.cls.label} (from .env)",
            provider=name,
            base_url=provider.config.base_url,
            api_key=provider.config.api_key,
            model=self.settings.default_model or spec.default_model,
            is_active=True,
        )
        await self.uow.llm_profiles.add(profile)
        log.info("llm.bootstrapped_from_env", provider=name)
        return profile

    #: How long a local server gets to answer before startup gives up on it.
    REACHABILITY_TIMEOUT = 2.0

    @classmethod
    async def _reachable(cls, provider: LLMProvider) -> bool:
        """Whether a local server actually answers, without stalling startup."""
        try:
            models = await asyncio.wait_for(
                provider.list_models(), timeout=cls.REACHABILITY_TIMEOUT
            )
        except Exception:
            return False
        return bool(models)

    @staticmethod
    def _require_known_provider(name: str) -> None:
        if name not in PROVIDERS:
            raise NotFoundError(
                f"unknown provider '{name}'", details={"available": PROVIDERS.names()}
            )
