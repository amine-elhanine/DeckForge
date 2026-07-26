"""Ollama adapter using the native ``/api/chat`` endpoint.

The native endpoint is preferred over Ollama's OpenAI shim because it exposes
``format: json`` (constrained decoding) and per-request ``options``, both of
which matter a lot for small local models producing structured deck output.
"""

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


class OllamaProvider(LLMProvider):
    """Local models served by Ollama."""

    name = "ollama"
    label = "Ollama"
    kind = "local"
    requires_api_key = False
    capabilities = ProviderCapabilities(streaming=True, json_mode=True, vision=True)

    def _url(self, path: str) -> str:
        base = (self.config.base_url or "http://localhost:11434").rstrip("/")
        return f"{base}{path}"

    def _payload(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None, *, stream: bool
    ) -> dict[str, Any]:
        opts = options or GenerationOptions()
        model_options: dict[str, Any] = {}
        if opts.temperature is not None:
            model_options["temperature"] = opts.temperature
        if opts.max_tokens is not None:
            model_options["num_predict"] = opts.max_tokens
        if opts.top_p is not None:
            model_options["top_p"] = opts.top_p
        if opts.stop:
            model_options["stop"] = list(opts.stop)
        if opts.seed is not None:
            model_options["seed"] = opts.seed
        model_options.update(self.config.options.get("model_options", {}))

        payload: dict[str, Any] = {
            "model": self.resolve_model(opts),
            "messages": [m.as_dict() for m in messages],
            "stream": stream,
        }
        if model_options:
            payload["options"] = model_options
        if opts.json_mode:
            payload["format"] = "json"
        payload.update(opts.extra)
        return payload

    async def stream(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, options, stream=True)
        async with self.client.stream("POST", self._url("/api/chat"), json=payload) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")
                self._raise_for_status(response, body)
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("error"):
                    raise ProviderError(f"Ollama error: {event['error']}")
                chunk = (event.get("message") or {}).get("content") or ""
                if chunk:
                    yield chunk
                if event.get("done"):
                    return

    async def complete(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> Completion:
        payload = self._payload(messages, options, stream=False)
        response = await self.client.post(self._url("/api/chat"), json=payload)
        self._raise_for_status(response)
        data = response.json()
        if data.get("error"):
            raise ProviderError(f"Ollama error: {data['error']}")
        return Completion(
            text=(data.get("message") or {}).get("content") or "",
            model=data.get("model", payload["model"]),
            usage=Usage(
                prompt_tokens=int(data.get("prompt_eval_count", 0)),
                completion_tokens=int(data.get("eval_count", 0)),
            ),
            finish_reason=data.get("done_reason"),
            raw=data,
        )

    async def list_models(self) -> list[str]:
        try:
            response = await self.client.get(self._url("/api/tags"))
            self._raise_for_status(response)
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - network dependent
            raise ProviderError(f"Ollama is unreachable at {self.config.base_url}: {exc}") from exc
        models = response.json().get("models", [])
        return sorted(m["name"] for m in models if m.get("name"))

    @property
    def is_configured(self) -> bool:
        return bool(self.config.base_url)
