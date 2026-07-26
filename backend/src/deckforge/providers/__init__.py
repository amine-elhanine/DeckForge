"""LLM provider abstraction.

Usage::

    factory = ProviderFactory(settings)
    provider = factory.get("ollama", model="qwen3:8b")
    async for chunk in provider.stream([ChatMessage(role="user", content="Hi")]):
        ...
"""

from deckforge.providers.base import (
    ChatMessage,
    Completion,
    GenerationOptions,
    LLMProvider,
    ProviderCapabilities,
    ProviderConfiguration,
    Usage,
)
from deckforge.providers.registry import PROVIDERS, ProviderFactory, ProviderSpec, register_provider

__all__ = [
    "PROVIDERS",
    "ChatMessage",
    "Completion",
    "GenerationOptions",
    "LLMProvider",
    "ProviderCapabilities",
    "ProviderConfiguration",
    "ProviderFactory",
    "ProviderSpec",
    "Usage",
    "register_provider",
]
