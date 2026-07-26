"""Adapter for every backend that speaks the OpenAI ``/chat/completions`` API.

That covers OpenAI itself plus LM Studio, llama.cpp's server, vLLM, OpenRouter,
Groq, Together, DeepSeek, Mistral and Azure OpenAI. Vendors differ only in base
URL, auth header and a couple of quirks, so each is a five-line subclass.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

from deckforge.core.errors import ProviderError
from deckforge.providers.base import (
    ChatMessage,
    Completion,
    GenerationOptions,
    LLMProvider,
    ProviderCapabilities,
    Usage,
)


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible chat provider."""

    name = "openai"
    label = "OpenAI"
    kind: Literal["local", "cloud"] = "cloud"
    requires_api_key = True
    capabilities = ProviderCapabilities(streaming=True, json_mode=True, tools=True, vision=True)

    #: Set False for servers that reject ``response_format``.
    supports_response_format = True
    #: Some gateways want extra headers (OpenRouter's referer, Azure's api-key).
    extra_headers: dict[str, str] = {}  # noqa: RUF012

    def default_headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json", **self.extra_headers}
        if self.config.api_key:
            headers["authorization"] = f"Bearer {self.config.api_key}"
        return headers

    # -- request building --------------------------------------------------- #

    def chat_url(self) -> str:
        base = (self.config.base_url or "").rstrip("/")
        if not base:
            raise ProviderError(f"provider '{self.name}' has no base_url")
        return f"{base}/chat/completions"

    def models_url(self) -> str:
        return f"{(self.config.base_url or '').rstrip('/')}/models"

    def build_payload(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None, *, stream: bool
    ) -> dict[str, Any]:
        opts = options or GenerationOptions()
        payload: dict[str, Any] = {
            "model": self.resolve_model(opts),
            "messages": [m.as_dict() for m in messages],
            "stream": stream,
        }
        if opts.temperature is not None:
            payload["temperature"] = opts.temperature
        if opts.max_tokens is not None:
            payload["max_tokens"] = opts.max_tokens
        if opts.top_p is not None:
            payload["top_p"] = opts.top_p
        if opts.stop:
            payload["stop"] = list(opts.stop)
        if opts.seed is not None:
            payload["seed"] = opts.seed
        if opts.json_mode and self.supports_response_format:
            payload["response_format"] = {"type": "json_object"}
        payload.update(opts.extra)
        payload.update(self.config.options.get("payload", {}))
        return payload

    # -- generation --------------------------------------------------------- #

    async def stream(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> AsyncIterator[str]:
        payload = self.build_payload(messages, options, stream=True)
        async with self.client.stream("POST", self.chat_url(), json=payload) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")
                self._raise_for_status(response, body)
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data in ("", "[DONE]"):
                    if data == "[DONE]":
                        return
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in event.get("choices", []):
                    delta = choice.get("delta") or {}
                    text = delta.get("content") or ""
                    if text:
                        yield text

    async def complete(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> Completion:
        payload = self.build_payload(messages, options, stream=False)
        response = await self.client.post(self.chat_url(), json=payload)
        self._raise_for_status(response)
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return Completion(
            text=(choice.get("message") or {}).get("content") or "",
            model=data.get("model", payload["model"]),
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            finish_reason=choice.get("finish_reason"),
            raw=data,
        )

    async def list_models(self) -> list[str]:
        try:
            response = await self.client.get(self.models_url())
            self._raise_for_status(response)
            data = response.json()
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - network dependent
            raise ProviderError(f"{self.label} is unreachable: {exc}") from exc
        items = data.get("data", data if isinstance(data, list) else [])
        names = [str(m["id"]) for m in items if isinstance(m, dict) and m.get("id")]
        return sorted(names)


# --------------------------------------------------------------------------- #
# Local servers exposing the OpenAI API
# --------------------------------------------------------------------------- #


class LMStudioProvider(OpenAICompatibleProvider):
    name = "lmstudio"
    label = "LM Studio"
    kind = "local"
    requires_api_key = False
    supports_response_format = False


class LlamaCppProvider(OpenAICompatibleProvider):
    name = "llamacpp"
    label = "llama.cpp server"
    kind = "local"
    requires_api_key = False
    supports_response_format = False


class VLLMProvider(OpenAICompatibleProvider):
    name = "vllm"
    label = "vLLM"
    kind = "local"
    requires_api_key = False


# --------------------------------------------------------------------------- #
# Cloud gateways
# --------------------------------------------------------------------------- #


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    label = "OpenRouter"
    extra_headers = {  # noqa: RUF012
        "http-referer": "https://github.com/deckforge/deckforge",
        "x-title": "DeckForge",
    }


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    label = "Groq"


class TogetherProvider(OpenAICompatibleProvider):
    name = "together"
    label = "Together AI"


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"
    label = "DeepSeek"


class MistralProvider(OpenAICompatibleProvider):
    name = "mistral"
    label = "Mistral AI"


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure routes per-deployment and authenticates with ``api-key``."""

    name = "azure"
    label = "Azure OpenAI"

    def default_headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.config.api_key:
            headers["api-key"] = self.config.api_key
        return headers

    @property
    def _api_version(self) -> str:
        return str(self.config.options.get("api_version", "2024-10-21"))

    def chat_url(self) -> str:
        base = (self.config.base_url or "").rstrip("/")
        deployment = self.config.default_model or "gpt-4o"
        return (
            f"{base}/openai/deployments/{deployment}/chat/completions"
            f"?api-version={self._api_version}"
        )

    def models_url(self) -> str:
        base = (self.config.base_url or "").rstrip("/")
        return f"{base}/openai/models?api-version={self._api_version}"
