"""Agent framework.

Every agent is a small, single-purpose unit with a typed input and a validated
Pydantic output. Agents never call each other directly — the coordinator wires
them together — which is what lets a turn re-run only the agents it needs
instead of regenerating a whole deck.

Agents do not expose their reasoning. They emit user-facing *status* events
("Writing slide 4 of 12") and return structured data; the coordinator decides
what prose the user actually sees.
"""

from __future__ import annotations

import abc
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from deckforge.agents.prompts import density_from_request
from deckforge.config import Settings
from deckforge.core.errors import AgentError, ProviderError
from deckforge.core.events import EventStream, NullEventStream
from deckforge.core.logging import get_logger
from deckforge.layouts.engine import LayoutEngine
from deckforge.models.deck import Presentation
from deckforge.models.enums import ContentDensity
from deckforge.providers.base import ChatMessage, GenerationOptions, LLMProvider
from deckforge.themes.engine import ThemeEngine
from deckforge.utils import jsonx

log = get_logger(__name__)

InT = TypeVar("InT")
OutT = TypeVar("OutT", bound=BaseModel)


@dataclass(slots=True)
class AgentContext:
    """Everything an agent may read during a turn.

    One context object is built per user turn and shared by every agent, so
    research findings and deck state flow through the pipeline without a bespoke
    parameter list on each agent.
    """

    provider: LLMProvider
    settings: Settings
    themes: ThemeEngine
    layouts: LayoutEngine
    events: EventStream = field(default_factory=NullEventStream)

    conversation_id: str = ""
    history: list[ChatMessage] = field(default_factory=list)
    user_message: str = ""
    deck: Presentation | None = None
    memory: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    research: str = ""
    """Retrieved context, already condensed by the research agent."""
    retriever: Any = None
    """Anything implementing ``search(query, top_k)``; see :mod:`deckforge.retrieval`."""
    scratch: dict[str, Any] = field(default_factory=dict)
    """Per-turn shared state between agents (brief, outline, critique, …)."""

    temperature: float | None = None
    model: str | None = None
    max_tokens: int | None = None

    def options(
        self, *, temperature: float | None = None, json_mode: bool = False
    ) -> GenerationOptions:
        """Build provider options for a call, honouring conversation overrides."""
        return GenerationOptions(
            model=self.model,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=self.max_tokens or self.settings.max_output_tokens,
            json_mode=json_mode,
        )

    def recent_history(self, limit: int = 8) -> list[ChatMessage]:
        return self.history[-limit:]

    def density(self, request: str = "") -> ContentDensity:
        """How much prose this turn should produce.

        Density is the user's call, never the model's, so it is resolved from
        what they control: what they just asked for, then the conversation's
        saved preference, then the application default.
        """
        if explicit := density_from_request(request or self.user_message):
            return explicit
        saved = self.preferences.get("density")
        try:
            return ContentDensity(saved) if saved else self.settings.content_density
        except ValueError:
            return self.settings.content_density

    def deck_summary(self) -> str:
        """A compact description of the current deck for prompt context."""
        if self.deck is None or not self.deck.slides:
            return "There is no presentation yet."
        stats = self.deck.stats()
        return (
            f'Current deck: "{self.deck.title}" — {stats["slides"]} slides, '
            f"theme '{self.deck.theme}', audience: {self.deck.meta.audience or 'unspecified'}.\n"
            f"Outline:\n{self.deck.outline_text()}"
        )


class Agent(abc.ABC, Generic[InT, OutT]):
    """Base class for every agent."""

    #: Stable identifier used in logs and telemetry.
    name: str = "agent"
    #: One-line description shown in developer docs.
    description: str = ""
    #: Status line shown to the user while this agent runs.
    status_message: str = "Working"
    #: Sampling temperature; overridden per agent because a fact checker and a
    #: creative writer want very different behaviour.
    temperature: float = 0.6

    @abc.abstractmethod
    async def run(self, ctx: AgentContext, payload: InT) -> OutT:
        """Execute the agent."""

    # -- LLM helpers -------------------------------------------------------- #

    async def structured(
        self,
        ctx: AgentContext,
        schema: type[OutT],
        *,
        system: str,
        user: str,
        temperature: float | None = None,
        retries: int = 2,
    ) -> OutT:
        """Call the provider and validate the reply against ``schema``.

        Raises:
            AgentError: when the model cannot produce a valid object.
        """
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(
                role="user",
                content=(
                    f"{user}\n\n"
                    "Respond with a single JSON object and nothing else. "
                    f"It must validate against this JSON Schema:\n{jsonx.schema_hint(schema)}"
                ),
            ),
        ]
        started = time.perf_counter()
        try:
            result = await ctx.provider.structured(
                messages,
                schema,
                ctx.options(temperature=temperature or self.temperature, json_mode=True),
                retries=retries,
            )
        except ProviderError as exc:
            log.warning("agent.failed", agent=self.name, error=str(exc))
            raise AgentError(f"{self.name} could not complete: {exc.message}") from exc
        log.info(
            "agent.done",
            agent=self.name,
            schema=schema.__name__,
            ms=round((time.perf_counter() - started) * 1000),
        )
        return result

    async def converse(
        self,
        ctx: AgentContext,
        *,
        system: str,
        user: str,
        history: Sequence[ChatMessage] = (),
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Stream a natural-language reply."""
        messages = [
            ChatMessage(role="system", content=system),
            *history,
            ChatMessage(role="user", content=user),
        ]
        async for chunk in ctx.provider.stream(
            messages, ctx.options(temperature=temperature or self.temperature)
        ):
            yield chunk

    async def announce(
        self, ctx: AgentContext, message: str | None = None, *, progress: float | None = None
    ) -> None:
        """Emit a user-facing status update."""
        await ctx.events.status(message or self.status_message, phase=self.name, progress=progress)
