"""Agent pipeline, driven by the scripted provider."""

from __future__ import annotations

import json

import pytest
from tests.conftest import ScriptedProvider

from deckforge.agents.base import AgentContext
from deckforge.agents.coordinator import CoordinatorAgent
from deckforge.agents.intent import IntentRouter, detect_export_formats
from deckforge.agents.reviewers import PresentationCriticAgent
from deckforge.agents.reviser import RevisionAgent
from deckforge.config import Settings
from deckforge.core.events import EventStream, EventType
from deckforge.models.deck import BulletsElement, Presentation, Slide
from deckforge.models.enums import Intent, SlideKind
from deckforge.providers.base import ProviderConfiguration


def make_context(settings: Settings, themes, layouts, **kwargs) -> AgentContext:
    provider = ScriptedProvider(ProviderConfiguration(name="scripted", default_model="scripted-1"))
    return AgentContext(
        provider=provider,
        settings=settings,
        themes=themes,
        layouts=layouts,
        events=EventStream(maxsize=4096),
        conversation_id="conv_test",
        **kwargs,
    )


async def drain(stream: EventStream) -> list:
    await stream.close()
    return [event async for event in stream]


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


def test_export_format_detection() -> None:
    assert detect_export_formats("give me the pptx") == ["pptx"]
    assert set(detect_export_formats("export as pdf and markdown")) == {"pdf", "markdown"}
    assert detect_export_formats("make it prettier") == []


async def test_router_picks_create_without_a_deck(settings, themes, layouts) -> None:
    ctx = make_context(settings, themes, layouts, user_message="Make a deck about RL")
    decision = await IntentRouter().run(ctx, ctx.user_message)
    assert decision.intent is Intent.CREATE


async def test_router_prefers_edit_when_a_deck_exists(settings, themes, layouts, deck) -> None:
    ctx = make_context(settings, themes, layouts, user_message="make it more modern", deck=deck)
    decision = await IntentRouter().run(ctx, ctx.user_message)
    assert decision.intent in (Intent.EDIT, Intent.RESTYLE)


async def test_router_short_circuits_export(settings, themes, layouts, deck) -> None:
    ctx = make_context(
        settings, themes, layouts, user_message="download the pptx please", deck=deck
    )
    decision = await IntentRouter().run(ctx, ctx.user_message)
    assert decision.intent is Intent.EXPORT
    assert decision.export_formats == ["pptx"]
    assert ctx.provider.calls == [], "an unambiguous export should not cost a model call"


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


async def test_full_creation_pipeline(settings, themes, layouts) -> None:
    ctx = make_context(
        settings, themes, layouts, user_message="Create a presentation about reinforcement learning"
    )
    result = await CoordinatorAgent().handle(ctx)

    assert result.intent is Intent.CREATE
    assert result.changed
    deck = result.deck
    assert deck is not None
    assert len(deck.slides) == 6
    assert deck.slides[0].kind is SlideKind.COVER
    assert deck.slides[-1].kind is SlideKind.ENDING
    assert deck.theme == "modern_dark"
    assert all(s.layout != "auto" for s in deck.slides)
    assert any(s.notes for s in deck.slides)
    assert result.reply

    events = await drain(ctx.events)
    kinds = {e.type for e in events}
    assert EventType.STATUS in kinds
    assert EventType.DECK in kinds
    assert EventType.SLIDE in kinds
    # Progress is monotonic and never exposes internal reasoning.
    progress = [e.data.get("progress") for e in events if e.type is EventType.STATUS]
    progress = [p for p in progress if p is not None]
    assert progress == sorted(progress)


async def test_generated_deck_renders_and_exports(settings, themes, layouts, renderer) -> None:
    from deckforge.exporters.base import EXPORTERS, ExportContext

    ctx = make_context(settings, themes, layouts, user_message="Deck about RL")
    result = await CoordinatorAgent().handle(ctx)
    assert result.deck is not None

    context = ExportContext(theme=themes.for_deck(result.deck), layouts=layouts, renderer=renderer)
    for name in ("html", "pptx", "pdf", "markdown"):
        assert EXPORTERS.get(name).export(result.deck, context).size > 500


async def test_slide_writer_failure_does_not_lose_the_deck(settings, themes, layouts) -> None:
    """One bad slide must not take the whole generation down."""
    ctx = make_context(settings, themes, layouts, user_message="Deck about RL")
    ctx.provider.overrides = {"You write one slide at a time": "not json at all"}
    try:
        result = await CoordinatorAgent().handle(ctx)
    finally:
        ctx.provider.overrides = {}

    assert result.deck is not None
    assert len(result.deck.slides) == 6
    assert all(s.title for s in result.deck.slides)


# --------------------------------------------------------------------------- #
# Editing
# --------------------------------------------------------------------------- #


async def test_edit_applies_operations(settings, themes, layouts) -> None:
    deck = Presentation(title="Deck", theme="minimal")
    for i in range(8):
        deck.add_slide(Slide(title=f"S{i + 1}", elements=[BulletsElement(items=["a"])]))
    seventh = deck.slides[6].id

    ctx = make_context(
        settings, themes, layouts, user_message="move slide 7 before slide 4", deck=deck
    )
    ctx.provider.overrides = {
        "You edit an existing presentation": json.dumps(
            {
                "summary": "Moved slide 7 before slide 4.",
                "operations": [{"op": "move_slide", "slide_id": seventh, "to_index": 3}],
            }
        )
    }
    try:
        result = await CoordinatorAgent().handle(ctx)
    finally:
        ctx.provider.overrides = {}

    assert result.changed
    assert [s.title for s in result.deck.slides][:5] == ["S1", "S2", "S3", "S7", "S4"]


async def test_restyle_only_touches_the_theme(settings, themes, layouts, deck) -> None:
    before = [s.text_content() for s in deck.slides]
    ctx = make_context(settings, themes, layouts, user_message="use dark colours", deck=deck)
    ctx.provider.overrides = {
        "You edit an existing presentation": json.dumps(
            {
                "summary": "Switched to a dark theme.",
                "operations": [{"op": "set_theme", "theme": "minimal_dark"}],
            }
        )
    }
    try:
        result = await CoordinatorAgent().handle(ctx)
    finally:
        ctx.provider.overrides = {}

    assert result.deck.theme == "minimal_dark"
    assert [s.text_content() for s in result.deck.slides] == before


async def test_revision_ignores_operations_on_missing_slides(
    settings, themes, layouts, deck
) -> None:
    ctx = make_context(settings, themes, layouts, user_message="delete slide 99", deck=deck)
    batch_json = json.dumps(
        {"summary": "x", "operations": [{"op": "delete_slide", "slide_id": "sl_nope"}]}
    )
    ctx.provider.overrides = {"You edit an existing presentation": batch_json}
    try:
        agent = RevisionAgent()
        batch = await agent.run(ctx, ctx.user_message)
        result = agent.apply(deck, batch)
    finally:
        ctx.provider.overrides = {}
    assert not result.changed
    assert result.skipped


async def test_conversation_intent_leaves_the_deck_alone(settings, themes, layouts, deck) -> None:
    ctx = make_context(
        settings, themes, layouts, user_message="what is this deck about?", deck=deck
    )
    ctx.provider.overrides = {"You classify what a user wants": json.dumps({"intent": "question"})}
    try:
        result = await CoordinatorAgent().handle(ctx)
    finally:
        ctx.provider.overrides = {}
    assert not result.changed
    assert result.reply


# --------------------------------------------------------------------------- #
# Review
# --------------------------------------------------------------------------- #


def _dense_deck(words_per_bullet: int) -> Presentation:
    deck = Presentation(title="Dense")
    deck.add_slide(
        Slide(
            title="Everything",
            elements=[
                BulletsElement(items=[" ".join(["word"] * words_per_bullet) for _ in range(5)])
            ],
        )
    )
    return deck


async def test_critic_flags_walls_of_text(settings, themes, layouts) -> None:
    deck = _dense_deck(70)  # 350 words: too much at any density
    ctx = make_context(settings, themes, layouts, deck=deck)
    critique = await PresentationCriticAgent().run(ctx, deck)
    assert any(i.category == "density" and i.severity == "high" for i in critique.issues)
    assert critique.verdict == "revise"


async def test_the_wall_of_text_threshold_follows_the_density(settings, themes, layouts) -> None:
    """200 words is a wall in a spoken deck and normal in a reading deck.

    Without this the critic would flag every rich slide and the reviser would
    cut back exactly the prose the user asked for.
    """
    deck = _dense_deck(40)  # 200 words

    ctx = make_context(settings, themes, layouts, deck=deck, preferences={"density": "concise"})
    critique = await PresentationCriticAgent().run(ctx, deck)
    assert any(i.category == "density" for i in critique.issues)

    ctx = make_context(settings, themes, layouts, deck=deck, preferences={"density": "rich"})
    critique = await PresentationCriticAgent().run(ctx, deck)
    assert not any(i.category == "density" for i in critique.issues)


async def test_critic_flags_repeated_layouts(settings, themes, layouts) -> None:
    deck = Presentation(title="Same")
    for i in range(6):
        deck.add_slide(Slide(title=f"S{i}", layout="bullets", notes="say something"))
    ctx = make_context(settings, themes, layouts, deck=deck)
    critique = await PresentationCriticAgent().run(ctx, deck)
    assert any(i.category == "variety" for i in critique.issues)


async def test_critic_flags_near_duplicate_slides(settings, themes, layouts) -> None:
    deck = Presentation(title="Dup")
    body = ["reward shaping matters", "credit assignment is hard", "start simple"]
    for i in range(2):
        deck.add_slide(Slide(title=f"Point {i}", notes="n", elements=[BulletsElement(items=body)]))
    ctx = make_context(settings, themes, layouts, deck=deck)
    critique = await PresentationCriticAgent().run(ctx, deck)
    assert any(i.category == "repetition" for i in critique.issues)


async def test_critic_can_be_disabled(settings, themes, layouts, deck) -> None:
    settings.enable_critic = False
    ctx = make_context(settings, themes, layouts, deck=deck)
    critique = await PresentationCriticAgent().run(ctx, deck)
    assert critique.verdict == "ship" and not critique.issues


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "garbage",
    [
        'Sure! Here is the JSON:\n```json\n{"intent": "create"}\n```',
        "{'intent': 'create',}",
        '{"intent": "create",}\ntrailing prose',
    ],
)
async def test_router_tolerates_messy_model_output(settings, themes, layouts, garbage) -> None:
    ctx = make_context(settings, themes, layouts, user_message="build a deck")
    ctx.provider.overrides = {"You classify what a user wants": garbage}
    try:
        decision = await IntentRouter().run(ctx, ctx.user_message)
    finally:
        ctx.provider.overrides = {}
    assert decision.intent is Intent.CREATE


async def test_pipeline_survives_a_totally_broken_model(settings, themes, layouts) -> None:
    """Everything returns junk: the turn must fail cleanly, not hang or crash."""
    ctx = make_context(settings, themes, layouts, user_message="build a deck")
    ctx.provider.overrides = {"": "this is not json"}
    try:
        result = await CoordinatorAgent().handle(ctx)
    finally:
        ctx.provider.overrides = {}
    assert result.error or result.reply
