"""Google Gemini adapter (``generativelanguage`` REST API)."""

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

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    """Gemini models. Roles map to ``user``/``model`` and system goes in ``system_instruction``."""

    name = "gemini"
    label = "Google Gemini"
    kind = "cloud"
    requires_api_key = True
    capabilities = ProviderCapabilities(streaming=True, json_mode=True, vision=True)

    def _base(self) -> str:
        return (self.config.base_url or DEFAULT_BASE).rstrip("/")

    def _url(self, model: str, *, stream: bool) -> str:
        verb = "streamGenerateContent" if stream else "generateContent"
        suffix = "&alt=sse" if stream else ""
        return f"{self._base()}/models/{model}:{verb}?key={self.config.api_key}{suffix}"

    def _payload(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None
    ) -> dict[str, Any]:
        opts = options or GenerationOptions()
        system, rest = self._split_system(messages)
        contents = [
            {
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            }
            for m in rest
        ] or [{"role": "user", "parts": [{"text": "Continue."}]}]

        generation_config: dict[str, Any] = {}
        if opts.temperature is not None:
            generation_config["temperature"] = opts.temperature
        if opts.max_tokens is not None:
            generation_config["maxOutputTokens"] = opts.max_tokens
        if opts.top_p is not None:
            generation_config["topP"] = opts.top_p
        if opts.stop:
            generation_config["stopSequences"] = list(opts.stop)
        if opts.json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload: dict[str, Any] = {"contents": contents}
        if generation_config:
            payload["generationConfig"] = generation_config
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        payload.update(opts.extra)
        return payload

    @staticmethod
    def _text_of(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for candidate in data.get("candidates", []):
            for part in (candidate.get("content") or {}).get("parts", []):
                if "text" in part:
                    parts.append(part["text"])
        return "".join(parts)

    async def stream(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> AsyncIterator[str]:
        model = self.resolve_model(options)
        payload = self._payload(messages, options)
        async with self.client.stream(
            "POST", self._url(model, stream=True), json=payload
        ) as response:
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
                if "error" in event:
                    raise ProviderError(f"Gemini error: {event['error']}")
                text = self._text_of(event)
                if text:
                    yield text

    async def complete(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> Completion:
        model = self.resolve_model(options)
        response = await self.client.post(
            self._url(model, stream=False), json=self._payload(messages, options)
        )
        self._raise_for_status(response)
        data = response.json()
        usage = data.get("usageMetadata") or {}
        return Completion(
            text=self._text_of(data),
            model=model,
            usage=Usage(
                prompt_tokens=int(usage.get("promptTokenCount", 0)),
                completion_tokens=int(usage.get("candidatesTokenCount", 0)),
            ),
            raw=data,
        )

    async def list_models(self) -> list[str]:
        try:
            response = await self.client.get(f"{self._base()}/models?key={self.config.api_key}")
            self._raise_for_status(response)
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - network dependent
            raise ProviderError(f"Gemini is unreachable: {exc}") from exc
        models = response.json().get("models", [])
        names = [
            m["name"].removeprefix("models/")
            for m in models
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]
        return sorted(names)
