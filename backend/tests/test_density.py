"""Content density: how much prose a deck carries, and whether it fits."""

from __future__ import annotations

import itertools
import json

import pytest
from tests.conftest import ScriptedProvider

from deckforge.agents.base import AgentContext
from deckforge.agents.outline import OutlineAgent
from deckforge.agents.planner import PlannerAgent
from deckforge.agents.prompts import density_clause, density_from_request
from deckforge.agents.writer import DeckAssembler, SlideWriterAgent
from deckforge.layouts import measure
from deckforge.layouts.builtin import MAX_GROWTH, stack
from deckforge.models.deck import (
    Box,
    BulletsElement,
    Card,
    CardsElement,
    ChartElement,
    ChartSeries,
    ChartSpec,
    TextElement,
)
from deckforge.models.enums import ContentDensity, TextRole
from deckforge.models.plan import DeckBrief, OutlineItem, SlideDraft
from deckforge.providers.base import ProviderConfiguration

LONG = (
    "An agent is not a bigger model — it is a model placed inside a loop that can act. "
    "The difference matters commercially: an assistant answers a question and stops, while an "
    "agent keeps going until the task is finished or it runs out of budget."
)


@pytest.fixture
def context(settings, themes, layouts) -> AgentContext:
    provider = ScriptedProvider(ProviderConfiguration(name="scripted", default_model="scripted-1"))
    return AgentContext(provider=provider, settings=settings, themes=themes, layouts=layouts)


# --------------------------------------------------------------------------- #
# Choosing a density
# --------------------------------------------------------------------------- #


def test_rich_is_the_default() -> None:
    """A deck nobody configured should still explain itself."""
    assert "45-80 words" in density_clause(None)
    assert "45-80 words" in density_clause(ContentDensity.RICH)


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("Make a detailed deck on retrieval augmentation", ContentDensity.RICH),
        ("I want paragraphs, not bullet fragments", ContentDensity.RICH),
        ("Write it as a handout people can read alone", ContentDensity.RICH),
        ("Keep it concise, I am presenting live", ContentDensity.CONCISE),
        ("Short keywords only please", ContentDensity.CONCISE),
        ("Build a deck about photosynthesis", None),
    ],
)
def test_the_request_can_set_the_density(
    request_text: str, expected: ContentDensity | None
) -> None:
    assert density_from_request(request_text) is expected


def test_precedence_request_then_preference_then_default(context: AgentContext) -> None:
    assert context.density("a deck about bees") is ContentDensity.RICH  # settings default

    context.preferences["density"] = "concise"
    assert context.density("a deck about bees") is ContentDensity.CONCISE, "preference applies"
    assert context.density("make it detailed") is ContentDensity.RICH, "the request wins"

    context.preferences["density"] = "nonsense"
    assert context.density("a deck about bees") is ContentDensity.RICH, "junk falls back"


async def test_the_brief_carries_the_density_not_the_model(context: AgentContext) -> None:
    """The model may guess anything; the user's choice is what ships."""
    context.preferences["density"] = "concise"
    brief = await PlannerAgent().run(context, "A deck about reinforcement learning")
    assert brief.density is ContentDensity.CONCISE


async def test_writing_agents_are_told_the_density(context: AgentContext, monkeypatch) -> None:
    seen: list[str] = []

    async def capture(self, ctx, model, *, system, user, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(system)
        return model()

    monkeypatch.setattr(SlideWriterAgent, "structured", capture, raising=False)
    monkeypatch.setattr(OutlineAgent, "structured", capture, raising=False)

    brief = DeckBrief(title="Agents", density=ContentDensity.RICH)
    await OutlineAgent().run(context, brief)
    context.scratch["brief"] = brief
    await SlideWriterAgent().run(context, OutlineItem(title="The loop"))

    assert len(seen) == 2
    for system in seen:
        assert "Density: rich" in system


# --------------------------------------------------------------------------- #
# Turning prose into elements
# --------------------------------------------------------------------------- #


def test_paragraphs_become_one_lead_block() -> None:
    draft = SlideDraft(title="Why", paragraphs=["First para.", "Second para."])
    elements = DeckAssembler()._elements_for(draft)
    lead = next(e for e in elements if isinstance(e, TextElement))
    assert lead.role is TextRole.LEAD
    assert lead.text == "First para.\n\nSecond para."


def test_body_and_paragraphs_merge_without_repeating() -> None:
    """Models often emit the first paragraph in both fields."""
    draft = SlideDraft(title="Why", body="First para.", paragraphs=["First para.", "Second para."])
    elements = DeckAssembler()._elements_for(draft)
    lead = next(e for e in elements if isinstance(e, TextElement))
    assert lead.text == "First para.\n\nSecond para."


def test_prose_keeps_its_markdown() -> None:
    """Bold labels are the whole point of a rich bullet."""
    draft = SlideDraft(
        title="Trade-offs",
        body="**Cost:** the index rebuilds nightly.",
        bullets=["**Latency:** 210 ms at the 95th percentile once the cache is warm."],
    )
    elements = DeckAssembler()._elements_for(draft)
    lead = next(e for e in elements if isinstance(e, TextElement))
    bullets = next(e for e in elements if isinstance(e, BulletsElement))
    assert lead.markdown is True
    assert "**Cost:**" in lead.text
    assert "**Latency:**" in bullets.items[0].text


def test_rich_bullets_survive_the_writer(themes, renderer) -> None:
    """End to end: a bold label reaches the rendered slide as bold."""
    from deckforge.models.deck import Slide

    slide = Slide(
        title="Trade-offs",
        layout="bullets",
        elements=[BulletsElement(items=["**Latency:** 210 ms once the cache is warm."])],
    )
    html = renderer.render_slide(slide, themes.get("minimal"))
    assert "<strong>Latency:</strong>" in html
    assert "**" not in html


@pytest.mark.parametrize(
    "card",
    [
        {"title": "Planning", "body": "It decomposes the goal."},
        {"heading": "Planning", "description": "It decomposes the goal."},
        {"name": "Planning", "text": "It decomposes the goal."},
        {"term": "Planning", "definition": "It decomposes the goal."},
    ],
)
def test_cards_survive_the_synonyms_models_use(card: dict[str, str]) -> None:
    """A card read through the wrong key draws as an empty box on the slide."""
    elements = DeckAssembler()._elements_for(SlideDraft(title="Capabilities", cards=[card]))
    cards = next(e for e in elements if isinstance(e, CardsElement))
    assert cards.cards[0].title == "Planning"
    assert cards.cards[0].body == "It decomposes the goal."


def test_empty_cards_are_dropped_not_drawn() -> None:
    draft = SlideDraft(
        title="Spectrum",
        cards=[{"title": "Reactive", "body": "Answers one query."}, {}, {"icon": "zap"}],
    )
    elements = DeckAssembler()._elements_for(draft)
    cards = next(e for e in elements if isinstance(e, CardsElement))
    assert len(cards.cards) == 1, "blank cards render as empty boxes"


def test_a_slide_of_only_empty_cards_has_no_cards_element() -> None:
    elements = DeckAssembler()._elements_for(SlideDraft(title="Nothing", cards=[{}, {}]))
    assert not any(isinstance(e, CardsElement) for e in elements)


def test_timeline_and_metric_synonyms_too() -> None:
    from deckforge.models.deck import MetricElement, TimelineElement

    draft = SlideDraft(
        title="Rollout",
        timeline=[{"phase": "Q1", "milestone": "Pilot", "description": "Ten teams."}],
        metrics=[{"figure": "23%", "name": "handling time"}],
    )
    elements = DeckAssembler()._elements_for(draft)
    entry = next(e for e in elements if isinstance(e, TimelineElement)).entries[0]
    metric = next(e for e in elements if isinstance(e, MetricElement))
    assert (entry.label, entry.title, entry.body) == ("Q1", "Pilot", "Ten teams.")
    assert (metric.value, metric.label) == ("23%", "handling time")


def test_a_diagram_slide_without_a_diagram_falls_back(themes, layouts) -> None:
    """Better an honest text layout than a title over empty space."""
    from deckforge.models.deck import Slide
    from deckforge.models.enums import SlideKind

    theme = themes.get("minimal")
    described = Slide(
        kind=SlideKind.DIAGRAM,
        title="The agent loop",
        elements=[TextElement(text=LONG, role=TextRole.LEAD)],
    )
    assert layouts.choose(described, theme) != "diagram"

    from deckforge.models.deck import DiagramElement

    drawn = Slide(
        kind=SlideKind.DIAGRAM,
        title="The agent loop",
        elements=[DiagramElement(source="flowchart LR\n A --> B")],
    )
    assert layouts.choose(drawn, theme) in {"diagram", "architecture", "flow"}


@pytest.mark.parametrize("key", ["source", "mermaid", "code", "definition"])
def test_the_diagram_is_found_whatever_the_model_calls_it(key: str) -> None:
    """Reading only `source` drops the picture the slide exists for."""
    from deckforge.models.deck import DiagramElement

    draft = SlideDraft(title="The loop", diagram={key: "flowchart LR\n  A --> B"})
    element = next(e for e in DeckAssembler()._elements_for(draft) if isinstance(e, DiagramElement))
    assert element.source.startswith("flowchart LR")


def test_a_fenced_diagram_is_unwrapped() -> None:
    from deckforge.models.deck import DiagramElement

    draft = SlideDraft(
        title="The loop", diagram={"mermaid": "```mermaid\nflowchart LR\n A --> B\n```"}
    )
    element = next(e for e in DeckAssembler()._elements_for(draft) if isinstance(e, DiagramElement))
    assert element.source == "flowchart LR\n A --> B"
    assert "```" not in element.source


def test_a_diagram_the_model_emitted_reaches_the_slide_as_shapes(themes) -> None:
    """End to end: `mermaid` key in, drawn nodes out."""
    from deckforge.models.deck import DiagramElement
    from deckforge.renderers import diagrams
    from deckforge.renderers.primitives import Label

    draft = SlideDraft(
        title="The loop",
        diagram={"mermaid": "flowchart LR\n  P[Perceive] --> R[Reason]"},
    )
    element = next(e for e in DeckAssembler()._elements_for(draft) if isinstance(e, DiagramElement))
    drawing = diagrams.render_diagram(element, 900, 400, themes.get("minimal"))
    assert drawing is not None
    labels = {i.text for i in drawing.items if isinstance(i, Label)}
    assert {"Perceive", "Reason"} <= labels


def test_the_writer_is_told_what_its_slide_kind_requires() -> None:
    from deckforge.agents.writer import REQUIRED_FIELD
    from deckforge.models.enums import SlideKind

    assert "flowchart" in REQUIRED_FIELD[SlideKind.DIAGRAM]
    assert "chart" in REQUIRED_FIELD[SlideKind.CHART]
    assert SlideKind.CONTENT not in REQUIRED_FIELD, "a content slide is free to choose"


def test_a_scripted_run_still_produces_a_deck(context: AgentContext) -> None:
    """The density knob must not break the draft-to-JSON mapping."""
    draft = SlideDraft(title="The loop", body=LONG, bullets=["**One:** a point.", "**Two:** more."])
    slide = DeckAssembler().to_slide(draft, OutlineItem(title="The loop"), {})
    assert [e.type for e in slide.elements] == ["text", "bullets"]
    assert json.loads(slide.model_dump_json())["title"] == "The loop"


# --------------------------------------------------------------------------- #
# Making it fit
# --------------------------------------------------------------------------- #


def test_long_copy_shrinks_the_type_instead_of_overflowing(themes) -> None:
    theme = themes.get("minimal")
    elements = [
        TextElement(text=LONG * 2, role=TextRole.LEAD),
        BulletsElement(items=[LONG[:120]] * 5),
    ]
    box = Box(x=84, y=180, width=1112, height=420)

    placements = stack(elements, box, theme)
    scale = placements[0].scale
    assert scale < 1.0, "the type must give way"
    assert scale >= measure.MIN_TYPE_SCALE, "but never below the readable floor"

    bottom = max(p.box.y + p.box.height for p in placements)
    assert bottom <= box.y + box.height + 1, "nothing may run past the box"

    fitted = theme.type_scaled(scale)
    total = measure.total_height(elements, box.width, fitted, theme.spacing.gap)
    assert total <= box.height + 1


def test_a_visual_gives_up_its_room_before_the_text_does(themes) -> None:
    """Prose, bullets and a diagram together must not overlap.

    The diagram's height does not follow the type scale, so squeezing every box
    proportionally leaves the paragraph shorter than its own words and the
    bullets get painted over its last line.
    """
    from deckforge.layouts.builtin import MIN_VISUAL
    from deckforge.models.deck import DiagramElement

    theme = themes.get("minimal")
    elements = [
        TextElement(text=LONG, role=TextRole.LEAD),
        BulletsElement(items=[LONG[:150]] * 4),
        DiagramElement(source="flowchart LR\n  A[One] --> B[Two] --> C[Three]"),
    ]
    box = Box(x=84, y=180, width=1112, height=430)
    placements = stack(elements, box, theme)

    for first, second in itertools.pairwise(placements):
        assert first.box.y + first.box.height <= second.box.y + 1, "blocks must not overlap"
    assert placements[-1].box.y + placements[-1].box.height <= box.y + box.height + 1

    fitted = theme.type_scaled(placements[0].scale)
    for placement in placements[:2]:
        needed = measure.element_height(placement.element, box.width, fitted)
        assert placement.box.height >= needed - 1, "text keeps the height its words need"
    assert placements[2].box.height >= MIN_VISUAL - 1, "the diagram is still worth drawing"


def test_short_copy_keeps_full_size_type(themes) -> None:
    theme = themes.get("minimal")
    elements = [TextElement(text="One short line.", role=TextRole.LEAD)]
    placements = stack(elements, Box(x=84, y=180, width=1112, height=420), theme)
    assert placements[0].scale == 1.0


def test_type_is_not_shrunk_for_a_chart(themes) -> None:
    """A chart keeps its aspect whatever the type does, so shrinking buys nothing."""
    theme = themes.get("minimal")
    chart = ChartElement(
        chart=ChartSpec(categories=["a", "b"], series=[ChartSeries(name="s", values=[1.0, 2.0])])
    )
    placements = stack([chart], Box(x=84, y=180, width=1112, height=200), theme)
    assert placements[0].scale == 1.0


def test_spare_room_goes_to_the_elements_that_can_use_it(themes) -> None:
    theme = themes.get("minimal")
    cards = CardsElement(
        columns=3,
        cards=[Card(title=f"Card {i}", body="A sentence of explanation.") for i in range(3)],
    )
    box = Box(x=84, y=180, width=1112, height=460)
    natural = measure.element_height(cards, box.width, theme)

    placement = stack([cards], box, theme, valign="center")[0]
    assert placement.box.height > natural, "cards grow into the space"
    assert placement.box.height <= natural * MAX_GROWTH + 1, "but only so far"
    assert placement.box.y >= box.y, "and stay inside the body"


def test_text_does_not_stretch_into_dead_space(themes) -> None:
    """A taller box for a paragraph is just trailing whitespace."""
    theme = themes.get("minimal")
    text = TextElement(text="One short line.", role=TextRole.LEAD)
    box = Box(x=84, y=180, width=1112, height=460)
    placement = stack([text], box, theme)[0]
    assert placement.box.height < box.height / 2


def test_exports_survive_a_dense_slide(themes, layouts, renderer) -> None:
    from deckforge.exporters.base import EXPORTERS, ExportContext
    from deckforge.models.deck import Presentation, Slide

    deck = Presentation(title="Dense", theme="minimal")
    deck.add_slide(
        Slide(
            title="Everything at once",
            layout="bullets",
            elements=[
                TextElement(text=LONG * 2, role=TextRole.LEAD),
                BulletsElement(items=[LONG[:140]] * 5),
            ],
        )
    )
    theme = themes.for_deck(deck)
    context = ExportContext(theme=theme, layouts=layouts, renderer=renderer)
    for name in ("pptx", "pdf"):
        assert EXPORTERS.get(name).export(deck, context).size > 1000
