"""Shared fixtures.

The suite never talks to a real model. :class:`ScriptedProvider` implements the
:class:`~deckforge.providers.base.LLMProvider` interface and answers each agent
by recognising its system prompt, which exercises the real pipeline — including
JSON parsing, validation and retries — deterministically and offline.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from deckforge.config import Settings
from deckforge.container import Container
from deckforge.layouts.engine import LayoutEngine
from deckforge.providers.base import (
    ChatMessage,
    Completion,
    GenerationOptions,
    LLMProvider,
    ProviderConfiguration,
)
from deckforge.providers.registry import PROVIDERS, ProviderSpec
from deckforge.renderers.html import HtmlRenderer
from deckforge.samples import sample_deck
from deckforge.themes.engine import ThemeEngine

_KIND_RE = re.compile(r"^Kind:\s*(\w+)", re.MULTILINE)
_TITLE_RE = re.compile(r"^This slide:\s*(.+)$", re.MULTILINE)


class ScriptedProvider(LLMProvider):
    """A provider that answers by matching the agent's system prompt."""

    name = "scripted"
    label = "Scripted test provider"
    kind = "local"
    requires_api_key = False

    #: Overridable per test: prompt fragment -> payload (str or callable).
    overrides: dict[str, Any] = {}  # noqa: RUF012

    def __init__(self, config: ProviderConfiguration) -> None:
        super().__init__(config)
        self.calls: list[tuple[str, str]] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return ["scripted-1"]

    async def stream(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> AsyncIterator[str]:
        completion = await self.complete(messages, options)
        for token in completion.text.split(" "):
            yield token + " "

    async def complete(
        self, messages: Sequence[ChatMessage], options: GenerationOptions | None = None
    ) -> Completion:
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next((m.content for m in messages if m.role == "user"), "")
        self.calls.append((system[:60], user[:120]))
        return Completion(text=self._answer(system, user), model="scripted-1")

    def _answer(self, system: str, user: str) -> str:
        for fragment, payload in self.overrides.items():
            if fragment in system or fragment in user:
                return payload(user) if callable(payload) else payload

        if "You classify what a user wants" in system:
            return json.dumps(
                {
                    "intent": "edit" if "Slides (index" in user else "create",
                    "needs_research": "yes" in user.rsplit("available:", maxsplit=1)[-1][:6],
                    "needs_clarification": False,
                    "target_slides": [],
                    "export_formats": [],
                }
            )
        if "You are the planner" in system:
            return json.dumps(
                {
                    "title": "Reinforcement Learning",
                    "subtitle": "From bandits to RLHF",
                    "goal": "Give engineers a working mental model",
                    "audience": "software engineers",
                    "tone": "clear and concrete",
                    "language": "en",
                    "duration_minutes": 10,
                    "slide_count": 6,
                    "must_cover": ["the loop", "reward design"],
                    "key_questions": ["When is RL worth it?"],
                    "visual_direction": "restrained, technical",
                }
            )
        if "You are the outline architect" in system:
            return json.dumps(
                {
                    "title": "Reinforcement Learning",
                    "sections": ["Foundations", "Practice"],
                    "narrative_arc": "setup, tension, resolution",
                    "items": [
                        {
                            "title": "Reinforcement Learning",
                            "kind": "cover",
                            "section": "Foundations",
                            "intent": "Set the promise",
                        },
                        {
                            "title": "The core loop",
                            "kind": "content",
                            "section": "Foundations",
                            "intent": "Explain the mechanism",
                            "talking_points": ["state", "action", "reward", "update"],
                        },
                        {
                            "title": "Reward is the only supervision",
                            "kind": "quote",
                            "section": "Foundations",
                            "intent": "Land the key idea",
                        },
                        {
                            "title": "Sample efficiency, roughly",
                            "kind": "chart",
                            "section": "Practice",
                            "intent": "Ground it in numbers",
                        },
                        {
                            "title": "How a project usually goes",
                            "kind": "timeline",
                            "section": "Practice",
                            "intent": "Set expectations",
                        },
                        {
                            "title": "Start with the reward",
                            "kind": "ending",
                            "section": "Practice",
                            "intent": "Give them one action",
                        },
                    ],
                }
            )
        if "You write one slide at a time" in system:
            return self._slide_draft(user)
        if "You are the visual designer" in system:
            return json.dumps({"directives": []})
        if "You assign a layout" in system:
            return json.dumps({"choices": []})
        if "You pick a visual theme" in system:
            return json.dumps({"theme": "modern_dark", "reason": "engineering audience"})
        if "You extract what a presentation needs" in system:
            return json.dumps(
                {
                    "findings": ["The pilot reduced handling time by 23% over eight weeks."],
                    "open_questions": [],
                    "references": [],
                }
            )
        if "You audit a deck" in system:
            return json.dumps({"claims": []})
        if "You are a demanding presentation critic" in system:
            return json.dumps(
                {"score": 8.2, "strengths": ["clear arc"], "issues": [], "verdict": "ship"}
            )
        if "You edit an existing presentation" in system:
            return json.dumps({"summary": "No change needed.", "operations": []})
        return "Done. Want me to tighten the ending?"

    @staticmethod
    def _slide_draft(user: str) -> str:
        kind = (_KIND_RE.search(user).group(1) if _KIND_RE.search(user) else "content").strip()
        title = (_TITLE_RE.search(user).group(1) if _TITLE_RE.search(user) else "Slide").strip()
        draft: dict[str, Any] = {
            "title": title,
            "kind": kind,
            "notes": f"Say the point of {title}.",
        }
        match kind:
            case "cover":
                draft["subtitle"] = "From bandits to RLHF"
                draft["eyebrow"] = "Engineering primer"
            case "quote":
                draft["quote"] = "Reward is enough."
                draft["quote_attribution"] = "Silver et al."
            case "chart":
                draft["chart"] = {
                    "kind": "column",
                    "categories": ["DQN", "PPO", "SAC"],
                    "series": [{"name": "steps (M)", "values": [10, 6, 4]}],
                }
            case "timeline":
                draft["timeline"] = [
                    {"label": "Week 1", "title": "Environment", "body": "Make it deterministic."},
                    {"label": "Week 2", "title": "Reward", "body": "Expect to rewrite it."},
                ]
            case "ending":
                draft["subtitle"] = "Instrument the reward first."
            case _:
                draft["bullets"] = [
                    "The agent observes a state",
                    "It selects an action",
                    "The environment returns a reward",
                    "The policy updates",
                ]
        return json.dumps(draft)


@pytest.fixture(scope="session", autouse=True)
def register_scripted_provider() -> Iterator[None]:
    """Make ``scripted`` selectable through the normal provider factory."""
    if "scripted" not in PROVIDERS:
        PROVIDERS.register(
            "scripted", ProviderSpec(cls=ScriptedProvider, default_model="scripted-1")
        )
    yield


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated settings backed by a temporary SQLite file."""
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        default_provider="scripted",
        default_model="scripted-1",
        environment="local",
        log_level="WARNING",
        worker_concurrency=4,
    )


@pytest.fixture
def themes() -> ThemeEngine:
    return ThemeEngine([Settings().builtin_theme_dir])


@pytest.fixture
def layouts() -> LayoutEngine:
    return LayoutEngine()


@pytest.fixture
def renderer(layouts: LayoutEngine) -> HtmlRenderer:
    return HtmlRenderer(layouts)


@pytest.fixture
def deck():
    """The built-in sample deck."""
    return sample_deck("modern_dark")


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[Container]:
    instance = Container.create(settings)
    await instance.startup()
    try:
        yield instance
    finally:
        await instance.shutdown()


@pytest.fixture
async def app(container: Container):
    """A FastAPI app wired to the test container (no lifespan re-entry)."""
    from deckforge.main import create_app

    return create_app(container.settings, container=container)


@pytest.fixture
async def client(app) -> AsyncIterator[Any]:
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
