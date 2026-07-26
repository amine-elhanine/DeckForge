"""The LLM provider interface.

Everything above this module — agents, services, API — talks only to
:class:`LLMProvider`. Adding a new backend means writing one adapter and
registering it; no other file changes.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel

from deckforge.core.errors import ProviderError
from deckforge.core.logging import get_logger
from deckforge.utils import jsonx

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

Role = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class ChatMessage:
    """One message in a provider request."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class Usage:
    """Token accounting, when the backend reports it."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(slots=True)
class Completion:
    """A finished generation."""

    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GenerationOptions:
    """Per-call knobs, normalised across providers."""

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    stop: Sequence[str] | None = None
    json_mode: bool = False
    seed: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderCapabilities:
    streaming: bool = True
    json_mode: bool = True
    system_prompt: bool = True
    tools: bool = False
    vision: bool = False


@dataclass(slots=True)
class ProviderConfiguration:
    """Everything an adapter needs to reach its backend."""

    name: str
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    timeout: float = 300.0
    options: dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Abstract base for every LLM backend."""

    #: Registry key, e.g. ``"ollama"``.
    name: str = "base"
    #: Human readable name shown in the UI.
    label: str = "Base provider"
    #: ``"local"`` or ``"cloud"`` — the UI groups providers by this.
    kind: Literal["local", "cloud"] = "cloud"
    #: Whether an API key is mandatory.
    requires_api_key: bool = True
    capabilities: ProviderCapabilities = ProviderCapabilities()

    def __init__(self, config: ProviderConfiguration) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle --------------------------------------------------------- #

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazily created, reused HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=15.0),
                headers=self.default_headers(),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def default_headers(self) -> dict[str, str]:
        return {"content-type": "application/json"}

    # -- introspection ----------------------------------------------------- #

    @property
    def is_configured(self) -> bool:
        """Whether this provider can currently be used."""
        return not (self.requires_api_key and not self.config.api_key)

    @property
    def default_model(self) -> str:
        if not self.config.default_model:
            raise ProviderError(f"provider '{self.name}' has no default model configured")
        return self.config.default_model

    def resolve_model(self, options: GenerationOptions | None) -> str:
        if options and options.model:
            return options.model
        return self.default_model

    async def list_models(self) -> list[str]:
        """Return model ids the backend offers. Adapters override where supported."""
        return [self.config.default_model] if self.config.default_model else []

    async def health(self) -> bool:
        """Cheap reachability probe used by ``/providers``."""
        if not self.is_configured:
            return False
        try:
            await self.list_models()
            return True
        except Exception:  # pragma: no cover - network dependent
            return False

    # -- generation -------------------------------------------------------- #

    @abc.abstractmethod
    async def stream(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> AsyncIterator[str]:
        """Yield response text incrementally."""
        raise NotImplementedError
        yield ""  # pragma: no cover - makes the abstract method an async generator

    async def complete(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> Completion:
        """Return a full completion.

        The default implementation drains :meth:`stream`; adapters override it
        when the backend has a cheaper non-streaming endpoint.
        """
        chunks: list[str] = []
        async for chunk in self.stream(messages, options):
            chunks.append(chunk)
        return Completion(text="".join(chunks), model=self.resolve_model(options))

    async def structured(
        self,
        messages: Sequence[ChatMessage],
        schema: type[T],
        options: GenerationOptions | None = None,
        *,
        retries: int = 2,
    ) -> T:
        """Generate and validate a Pydantic object.

        The model is asked for JSON, the output is repaired if needed, and on a
        schema mismatch the error is fed back for up to ``retries`` attempts.

        Raises:
            ProviderError: if no attempt produced a valid object.
        """
        opts = options or GenerationOptions()
        opts.json_mode = self.capabilities.json_mode
        convo = list(messages)
        last_error = ""

        for attempt in range(retries + 1):
            completion = await self.complete(convo, opts)
            try:
                return jsonx.parse_model(completion.text, schema)
            except ValueError as exc:
                last_error = str(exc)
                log.warning(
                    "provider.structured_retry",
                    provider=self.name,
                    schema=schema.__name__,
                    attempt=attempt + 1,
                    error=last_error,
                )
                convo = [
                    *messages,
                    ChatMessage(role="assistant", content=completion.text[:4000]),
                    ChatMessage(
                        role="user",
                        content=(
                            f"That was not valid for the required schema ({last_error}). "
                            "Reply with the corrected JSON object only — no prose, no code fence."
                        ),
                    ),
                ]

        raise ProviderError(
            f"{self.name} could not produce valid {schema.__name__}: {last_error}",
            details={"schema": schema.__name__},
        )

    # -- helpers for adapters ---------------------------------------------- #

    @staticmethod
    def _split_system(messages: Sequence[ChatMessage]) -> tuple[str | None, list[ChatMessage]]:
        """Split leading system messages out, for APIs with a dedicated field."""
        systems = [m.content for m in messages if m.role == "system"]
        rest = [m for m in messages if m.role != "system"]
        return ("\n\n".join(systems) if systems else None), rest

    def _raise_for_status(self, response: httpx.Response, body: str = "") -> None:
        if response.status_code >= 400:
            detail = body or response.text
            raise ProviderError(
                f"{self.label} returned {response.status_code}: {detail[:500]}",
                details={"provider": self.name, "status": response.status_code},
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name} model={self.config.default_model}>"
