"""Anthropic Messages API adapter."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from deckforge.core.errors import ProviderError
from deckforge.providers.base import (
    ChatMessage,
    Completion,
    GenerationOptions,
    LLMProvider,
    ProviderCapabilities,
    Usage,
)

KNOWN_MODELS = [
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]


class AnthropicProvider(LLMProvider):
    """Claude models via the Messages API.

    Anthropic has no ``response_format`` switch, so JSON mode is emulated by
    prefilling an assistant turn with ``{`` — the model then has no choice but to
    continue a JSON object, and the brace is re-attached to the output.
    """

    name = "anthropic"
    label = "Anthropic"
    kind = "cloud"
    requires_api_key = True
    capabilities = ProviderCapabilities(streaming=True, json_mode=True, tools=True, vision=True)

    def default_headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": str(self.config.options.get("version", "2023-06-01")),
        }
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        return headers

    def _url(self) -> str:
        base = (self.config.base_url or "https://api.anthropic.com").rstrip("/")
        return f"{base}/v1/messages"

    def _payload(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None, *, stream: bool
    ) -> tuple[dict[str, Any], str]:
        opts = options or GenerationOptions()
        system, rest = self._split_system(messages)
        turns: list[dict[str, Any]] = [m.as_dict() for m in rest] or [
            {"role": "user", "content": "Continue."}
        ]

        prefill = ""
        if opts.json_mode:
            prefill = "{"
            turns.append({"role": "assistant", "content": prefill})

        payload: dict[str, Any] = {
            "model": self.resolve_model(opts),
            "messages": turns,
            "max_tokens": opts.max_tokens or 8192,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        if opts.temperature is not None:
            payload["temperature"] = opts.temperature
        if opts.top_p is not None:
            payload["top_p"] = opts.top_p
        if opts.stop:
            payload["stop_sequences"] = list(opts.stop)
        payload.update(opts.extra)
        return payload, prefill

    async def stream(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> AsyncIterator[str]:
        payload, prefill = self._payload(messages, options, stream=True)
        if prefill:
            yield prefill
        async with self.client.stream("POST", self._url(), json=payload) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")
                self._raise_for_status(response, body)
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                match event.get("type"):
                    case "content_block_delta":
                        text = (event.get("delta") or {}).get("text") or ""
                        if text:
                            yield text
                    case "error":
                        raise ProviderError(f"Anthropic error: {event.get('error')}")
                    case "message_stop":
                        return

    async def complete(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> Completion:
        payload, prefill = self._payload(messages, options, stream=False)
        response = await self.client.post(self._url(), json=payload)
        self._raise_for_status(response)
        data = response.json()
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        usage = data.get("usage") or {}
        return Completion(
            text=prefill + "".join(parts),
            model=data.get("model", payload["model"]),
            usage=Usage(
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
            ),
            finish_reason=data.get("stop_reason"),
            raw=data,
        )

    async def list_models(self) -> list[str]:
        base = (self.config.base_url or "https://api.anthropic.com").rstrip("/")
        try:
            response = await self.client.get(f"{base}/v1/models")
            if response.status_code == 404:  # older gateways
                return list(KNOWN_MODELS)
            self._raise_for_status(response)
            data = response.json().get("data", [])
            return sorted(m["id"] for m in data if m.get("id")) or list(KNOWN_MODELS)
        except ProviderError:
            raise
        except Exception:  # pragma: no cover - network dependent
            return list(KNOWN_MODELS)
