"""Provider registry and factory.

A :class:`ProviderSpec` binds an adapter class to the settings keys that
configure it. Plugins call :func:`register_provider` with their own spec; nothing
else in the codebase needs to know the provider exists.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from deckforge.config import Settings
from deckforge.core.errors import ProviderNotConfiguredError
from deckforge.core.logging import get_logger
from deckforge.core.registry import Registry
from deckforge.providers.anthropic import AnthropicProvider
from deckforge.providers.base import LLMProvider, ProviderConfiguration
from deckforge.providers.gemini import GeminiProvider
from deckforge.providers.ollama import OllamaProvider
from deckforge.providers.openai_compatible import (
    AzureOpenAIProvider,
    DeepSeekProvider,
    GroqProvider,
    LlamaCppProvider,
    LMStudioProvider,
    MistralProvider,
    OpenAICompatibleProvider,
    OpenRouterProvider,
    TogetherProvider,
    VLLMProvider,
)

log = get_logger(__name__)


@dataclass(slots=True)
class ProviderSpec:
    """Describes how to build one provider from application settings."""

    cls: type[LLMProvider]
    base_url: Callable[[Settings], str | None] = lambda _s: None
    api_key: Callable[[Settings], str | None] = lambda _s: None
    default_model: str = ""
    suggested_models: list[str] = field(default_factory=list)
    note: str | None = None

    def build(self, settings: Settings, model: str | None = None) -> LLMProvider:
        config = ProviderConfiguration(
            name=self.cls.name,
            base_url=self.base_url(settings),
            api_key=self.api_key(settings),
            default_model=model or self.default_model or settings.default_model,
            timeout=settings.request_timeout_seconds,
        )
        if self.cls.name == "azure":
            config.options["api_version"] = settings.azure_openai_api_version
        return self.cls(config)


PROVIDERS: Registry[ProviderSpec] = Registry("provider")
"""The global provider registry. Plugins mutate this at import time."""


def register_provider(spec: ProviderSpec, *, override: bool = False) -> ProviderSpec:
    """Register a provider spec under its adapter's ``name``."""
    return PROVIDERS.register(spec.cls.name, spec, override=override)


def _register_builtins() -> None:
    register_provider(
        ProviderSpec(
            cls=OllamaProvider,
            base_url=lambda s: s.ollama_base_url,
            default_model="qwen3:8b",
            suggested_models=["qwen3:8b", "llama3.1:8b", "mistral-nemo", "gemma3:12b"],
            note="Fully offline. Pull a model first: `ollama pull qwen3:8b`.",
        )
    )
    register_provider(
        ProviderSpec(
            cls=LMStudioProvider,
            base_url=lambda s: s.lmstudio_base_url,
            default_model="local-model",
            note="Start the LM Studio local server, then pick a loaded model.",
        )
    )
    register_provider(
        ProviderSpec(
            cls=LlamaCppProvider,
            base_url=lambda s: s.llamacpp_base_url,
            default_model="local-model",
            note="Run `llama-server --host 0.0.0.0 --port 8080`.",
        )
    )
    register_provider(
        ProviderSpec(
            cls=VLLMProvider,
            base_url=lambda s: s.vllm_base_url,
            default_model="local-model",
            note="Self-hosted vLLM OpenAI-compatible server.",
        )
    )
    register_provider(
        ProviderSpec(
            cls=OpenAICompatibleProvider,
            base_url=lambda s: s.openai_base_url,
            api_key=lambda s: s.openai_api_key,
            default_model="gpt-4o-mini",
            suggested_models=["gpt-4o", "gpt-4o-mini", "o4-mini"],
        )
    )
    register_provider(
        ProviderSpec(
            cls=AnthropicProvider,
            base_url=lambda s: s.anthropic_base_url,
            api_key=lambda s: s.anthropic_api_key,
            default_model="claude-sonnet-4-5",
            suggested_models=["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
        )
    )
    register_provider(
        ProviderSpec(
            cls=OpenRouterProvider,
            base_url=lambda _s: "https://openrouter.ai/api/v1",
            api_key=lambda s: s.openrouter_api_key,
            default_model="anthropic/claude-sonnet-4.5",
        )
    )
    register_provider(
        ProviderSpec(
            cls=GeminiProvider,
            api_key=lambda s: s.gemini_api_key,
            default_model="gemini-2.5-flash",
        )
    )
    register_provider(
        ProviderSpec(
            cls=GroqProvider,
            base_url=lambda _s: "https://api.groq.com/openai/v1",
            api_key=lambda s: s.groq_api_key,
            default_model="llama-3.3-70b-versatile",
        )
    )
    register_provider(
        ProviderSpec(
            cls=TogetherProvider,
            base_url=lambda _s: "https://api.together.xyz/v1",
            api_key=lambda s: s.together_api_key,
            default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        )
    )
    register_provider(
        ProviderSpec(
            cls=DeepSeekProvider,
            base_url=lambda _s: "https://api.deepseek.com/v1",
            api_key=lambda s: s.deepseek_api_key,
            default_model="deepseek-v4-flash",
            suggested_models=["deepseek-v4-pro", "deepseek-v4-flash"],
            note="`deepseek-chat` and `deepseek-reasoner` were retired; use a v4 name.",
        )
    )
    register_provider(
        ProviderSpec(
            cls=MistralProvider,
            base_url=lambda _s: "https://api.mistral.ai/v1",
            api_key=lambda s: s.mistral_api_key,
            default_model="mistral-large-latest",
        )
    )
    register_provider(
        ProviderSpec(
            cls=AzureOpenAIProvider,
            base_url=lambda s: s.azure_openai_endpoint,
            api_key=lambda s: s.azure_openai_api_key,
            default_model="gpt-4o",
            note="`default_model` must be your Azure *deployment* name.",
        )
    )


_register_builtins()


class ProviderFactory:
    """Creates and caches provider instances.

    Instances are cached per ``(name, model)`` so the underlying HTTP connection
    pool is shared across requests.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[tuple[str, ...], LLMProvider] = {}
        self._overrides: dict[str, ProviderConfiguration] = {}

    def apply_override(self, config: ProviderConfiguration) -> None:
        """Install a stored configuration as the default for one provider."""
        self._overrides[config.name] = config
        for key in [k for k in self._cache if k[0] == config.name]:
            self._cache.pop(key, None)

    def build(
        self,
        provider: str,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> LLMProvider:
        """Construct a provider from an explicit configuration.

        This is how saved LLM connections are used: the endpoint, key and model
        come from the user's profile rather than from the environment. Instances
        are cached on the full configuration so the HTTP connection pool is
        reused, and a changed key produces a new instance rather than a stale one.

        Raises:
            NotFoundError: if the adapter name is unknown.
            ProviderNotConfiguredError: if the adapter still lacks credentials.
        """
        spec = PROVIDERS.get(provider)
        resolved_model = model or spec.default_model or self._settings.default_model
        cache_key = (
            provider,
            resolved_model,
            base_url or "",
            # Fingerprint rather than the key itself: cache keys end up in logs
            # and debugger views.
            hashlib.sha256((api_key or "").encode()).hexdigest()[:16],
        )
        if cache_key not in self._cache:
            instance = spec.build(self._settings, resolved_model)
            if base_url:
                instance.config.base_url = base_url
            if api_key:
                instance.config.api_key = api_key
            if options:
                instance.config.options |= options
            self._cache[cache_key] = instance

        instance = self._cache[cache_key]
        if not instance.is_configured:
            raise ProviderNotConfiguredError(
                f"{instance.label} needs an API key.",
                details={"provider": provider},
            )
        return instance

    def get(self, name: str | None = None, model: str | None = None) -> LLMProvider:
        """Return a provider instance, creating it on first use.

        Raises:
            NotFoundError: if the provider name is unknown.
            ProviderNotConfiguredError: if credentials or endpoint are missing.
        """
        provider_name = (name or self._settings.default_provider).lower()
        spec = PROVIDERS.get(provider_name)
        resolved_model = model or self._resolved_default_model(provider_name, spec)
        cache_key: tuple[str, ...] = (provider_name, resolved_model)

        if cache_key not in self._cache:
            provider = spec.build(self._settings, resolved_model)
            override = self._overrides.get(provider_name)
            if override is not None:
                provider.config.base_url = override.base_url or provider.config.base_url
                provider.config.api_key = override.api_key or provider.config.api_key
                provider.config.options |= override.options
            self._cache[cache_key] = provider

        provider = self._cache[cache_key]
        if not provider.is_configured:
            raise ProviderNotConfiguredError(
                f"{provider.label} is not configured. "
                f"Set DECKFORGE_{provider_name.upper()}_API_KEY or configure it in Settings.",
                details={"provider": provider_name},
            )
        return provider

    def _resolved_default_model(self, name: str, spec: ProviderSpec) -> str:
        override = self._overrides.get(name)
        if override and override.default_model:
            return override.default_model
        if name == self._settings.default_provider:
            return self._settings.default_model or spec.default_model
        return spec.default_model

    def describe(self) -> list[dict[str, object]]:
        """Return UI-facing metadata for every registered provider."""
        out: list[dict[str, object]] = []
        for name in PROVIDERS.names():
            spec = PROVIDERS.get(name)
            try:
                provider = spec.build(self._settings, self._resolved_default_model(name, spec))
                configured = provider.is_configured
                base_url = provider.config.base_url
            except Exception:  # pragma: no cover - defensive
                configured, base_url = False, None
            out.append(
                {
                    "name": name,
                    "label": spec.cls.label,
                    "kind": spec.cls.kind,
                    "configured": configured,
                    "base_url": base_url,
                    "models": spec.suggested_models,
                    "supports_streaming": spec.cls.capabilities.streaming,
                    "supports_json_mode": spec.cls.capabilities.json_mode,
                    "note": spec.note,
                }
            )
        return out

    async def aclose(self) -> None:
        for provider in self._cache.values():
            await provider.aclose()
        self._cache.clear()
