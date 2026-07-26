"""Theme engine and layout engine."""

from __future__ import annotations

import json

import pytest

from deckforge.core.errors import ValidationError
from deckforge.layouts.engine import LayoutEngine
from deckforge.models.deck import (
    BulletsElement,
    ChartElement,
    ChartSeries,
    ChartSpec,
    ImageElement,
    Presentation,
    Slide,
)
from deckforge.models.enums import SlideKind
from deckforge.themes.engine import ThemeEngine
from deckforge.themes.model import Theme
from deckforge.utils import colors


def test_every_builtin_theme_resolves(themes: ThemeEngine) -> None:
    assert len(themes.names()) >= 20
    for name in themes.names():
        theme = themes.get(name)
        assert theme.name == name
        assert theme.palette.background.startswith("#")
        assert theme.css_variables()["--df-primary"]


def test_theme_body_text_meets_contrast(themes: ThemeEngine) -> None:
    """Every shipped theme must be readable — accessibility is not optional."""
    failures = []
    for name in themes.names():
        theme = themes.get(name)
        ratio = colors.contrast_ratio(theme.palette.text, theme.palette.background)
        if ratio < 4.5:
            failures.append((name, round(ratio, 2)))
    assert not failures, f"themes below WCAG AA for body text: {failures}"


def test_partial_type_override_keeps_the_other_properties(tmp_path) -> None:
    """`{"display": {"weight": 800}}` means "heavier", not "reset to defaults".

    Pydantic would otherwise build a fresh TypeStyle from that dict alone and
    every unstated field would fall back to the class default — which turned
    68pt display headings into 20pt body text in six shipped themes.
    """
    (tmp_path / "partial").mkdir()
    (tmp_path / "partial" / "theme.json").write_text(
        json.dumps(
            {
                "name": "partial",
                "type_scale": {
                    "display": {"weight": 800},
                    "eyebrow": {"letter_spacing": 3.0},
                    "quote": {"font": "heading"},
                },
            }
        ),
        encoding="utf-8",
    )
    scale = ThemeEngine([tmp_path], fallback="partial").get("partial").type_scale
    defaults = Theme(name="defaults").type_scale

    assert scale.display.weight == 800, "the override must apply"
    assert scale.display.size == defaults.display.size, "and everything else must survive"
    assert scale.display.font == defaults.display.font
    assert scale.eyebrow.letter_spacing == 3.0
    assert scale.eyebrow.size == defaults.eyebrow.size
    assert scale.eyebrow.transform == defaults.eyebrow.transform
    assert scale.quote.size == defaults.quote.size


def test_every_theme_keeps_a_readable_hierarchy(themes: ThemeEngine) -> None:
    """Headings must actually outrank body text in every shipped theme."""
    problems = []
    for name in themes.names():
        ts = themes.get(name).type_scale
        if not (ts.display.size > ts.title.size > ts.body.size):
            problems.append((name, ts.display.size, ts.title.size, ts.body.size))
        if ts.eyebrow.size >= ts.title.size:
            problems.append((name, "eyebrow", ts.eyebrow.size, ts.title.size))
    assert not problems, f"broken type hierarchy: {problems}"


def test_unknown_theme_falls_back(themes: ThemeEngine) -> None:
    assert themes.get("does-not-exist").name == "minimal"


def test_theme_inheritance(tmp_path) -> None:
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "theme.json").write_text(
        json.dumps({"name": "base", "palette": {"primary": "#123456", "text": "#000000"}}),
        encoding="utf-8",
    )
    (tmp_path / "child").mkdir()
    (tmp_path / "child" / "theme.json").write_text(
        json.dumps({"name": "child", "extends": "base", "palette": {"primary": "#abcdef"}}),
        encoding="utf-8",
    )
    engine = ThemeEngine([tmp_path], fallback="base")
    child = engine.get("child")
    assert child.palette.primary == "#abcdef"
    assert child.palette.text == "#000000"


def test_circular_inheritance_is_rejected(tmp_path) -> None:
    for name, extends in (("a", "b"), ("b", "a")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "theme.json").write_text(
            json.dumps({"name": name, "extends": extends}), encoding="utf-8"
        )
    engine = ThemeEngine([tmp_path], fallback="a")
    with pytest.raises(ValidationError, match="circular"):
        engine.get("a")


def test_theme_overrides_merge_deeply(themes: ThemeEngine) -> None:
    deck = Presentation(
        title="x", theme="minimal", theme_overrides={"palette": {"primary": "#ff0000"}}
    )
    theme = themes.for_deck(deck)
    assert theme.palette.primary == "#ff0000"
    assert theme.palette.background == themes.get("minimal").palette.background


def test_missing_theme_directory_is_harmless(tmp_path) -> None:
    engine = ThemeEngine([tmp_path / "nope"])
    assert engine.get("minimal").name == "minimal"


# --------------------------------------------------------------------------- #
# Layouts
# --------------------------------------------------------------------------- #


def test_all_layouts_render_every_slide_kind(themes: ThemeEngine, layouts: LayoutEngine) -> None:
    theme = themes.get("minimal")
    for kind in SlideKind:
        slide = Slide(
            kind=kind,
            title="A title that is long enough to wrap onto two lines comfortably",
            subtitle="A subtitle",
            elements=[BulletsElement(items=["one", "two", "three"])],
        )
        for name in layouts.names():
            slide.layout = name
            frame = layouts.resolve(slide, theme)
            assert frame.canvas == (1280.0, 720.0)
            for box in frame.all_boxes():
                assert box.width > 0 and box.height > 0


def test_layout_boxes_stay_on_canvas(themes: ThemeEngine, layouts: LayoutEngine, deck) -> None:
    theme = themes.for_deck(deck)
    for frame in layouts.resolve_deck(deck, theme):
        for box in frame.all_boxes():
            assert box.x >= -1 and box.y >= -1
            assert box.right <= 1281 and box.bottom <= 721, f"{frame.layout} overflows"


LONG_COVER_TITLE = "Agentic AI: The Next Frontier in Autonomous Systems"


def _overlaps(a, b) -> bool:
    """Whether two boxes intersect."""
    return not (a.right <= b.x or b.right <= a.x or a.bottom <= b.y or b.bottom <= a.y)


@pytest.mark.parametrize("theme_name", ["technology", "minimal", "apple", "startup", "editorial"])
def test_header_text_never_overlaps(themes: ThemeEngine, layouts: LayoutEngine, theme_name) -> None:
    """A long wrapping title must not be drawn on top of its subtitle.

    Header blocks are stacked using the measured height of the block above, so
    an under-measured title silently collides with whatever follows.
    """
    theme = themes.get(theme_name)
    slide = Slide(
        kind=SlideKind.COVER,
        eyebrow="THE NEXT SHIFT",
        title=LONG_COVER_TITLE,
        subtitle="From answering prompts to taking action — AI that pursues goals, "
        "makes plans, and executes autonomously.",
        elements=[ImageElement(src="", alt="Abstract network graphic")],
    )
    for layout in ("hero", "hero_centered", "bullets", "split", "section_divider"):
        slide.layout = layout
        frame = layouts.resolve(slide, theme)
        for i, first in enumerate(frame.texts):
            for second in frame.texts[i + 1 :]:
                assert not _overlaps(first.box, second.box), (
                    f"{theme_name}/{layout}: '{first.key}' overlaps '{second.key}'"
                )


def test_generated_decks_keep_text_apart(themes: ThemeEngine, layouts: LayoutEngine, deck) -> None:
    """The same invariant across the whole sample deck, in every theme."""
    for name in ("modern_dark", "minimal", "academic", "neon"):
        deck.theme = name
        theme = themes.for_deck(deck)
        for index, frame in enumerate(layouts.resolve_deck(deck, theme)):
            for i, first in enumerate(frame.texts):
                for second in frame.texts[i + 1 :]:
                    assert not _overlaps(first.box, second.box), (
                        f"{name} slide {index + 1} ({frame.layout}): "
                        f"'{first.key}' overlaps '{second.key}'"
                    )


def test_overflow_hiding_elements_get_enough_room(
    themes: ThemeEngine, layouts: LayoutEngine, deck
) -> None:
    """Cards and code panels hide their overflow, so a short box loses content.

    Their resolved boxes must be at least as tall as the measured content on a
    normally-filled deck. (``stack`` deliberately shrinks on genuine overflow;
    this asserts the sample deck is not in that regime.)
    """
    from deckforge.layouts import measure
    from deckforge.models.enums import ElementType

    theme = themes.for_deck(deck)
    fragile = {ElementType.CARDS, ElementType.CODE}
    checked = 0
    for frame in layouts.resolve_deck(deck, theme):
        for placement in frame.elements:
            if placement.element.type not in fragile:
                continue
            checked += 1
            needed = measure.element_height(placement.element, placement.box.width, theme)
            assert placement.box.height >= needed, (
                f"{placement.element.type} box {placement.box.height:.0f} < needed {needed:.0f}"
            )
    assert checked >= 2, "sample deck should exercise both cards and code"


def test_auto_layout_avoids_repetition(themes: ThemeEngine, layouts: LayoutEngine) -> None:
    deck = Presentation(title="Repetition", theme="minimal")
    for i in range(8):
        deck.add_slide(Slide(title=f"Point {i}", elements=[BulletsElement(items=["a", "b", "c"])]))
    plan = layouts.plan(deck, themes.get("minimal"))
    chosen = list(plan.values())
    assert len(set(chosen)) > 1, "auto layout produced eight identical slides"
    for i in range(len(chosen) - 2):
        assert not (chosen[i] == chosen[i + 1] == chosen[i + 2]), "three in a row"


def test_layout_selection_matches_content(themes: ThemeEngine, layouts: LayoutEngine) -> None:
    theme = themes.get("minimal")
    chart_slide = Slide(
        kind=SlideKind.CHART,
        title="Numbers",
        elements=[
            ChartElement(chart=ChartSpec(categories=["a"], series=[ChartSeries(values=[1.0])]))
        ],
    )
    assert layouts.choose(chart_slide, theme) in {
        "chart_focus",
        "dashboard",
        "split",
        "split_reverse",
    }

    quote_slide = Slide(kind=SlideKind.QUOTE, title="", elements=[])
    assert layouts.choose(quote_slide, theme) in {"quote", "big_statement", "hero_centered"}


def test_full_bleed_layouts_never_swallow_content(layouts: LayoutEngine) -> None:
    """image_full has nowhere to put bullets, so it must not be selectable."""
    slide = Slide(
        kind=SlideKind.IMAGE,
        title="Further reading",
        elements=[ImageElement(src=""), BulletsElement(items=["a", "b"])],
    )
    definition = layouts.definition("image_full")
    assert definition is not None and not definition.accepts(slide)
    assert not layouts.can_render("image_full", slide)


def test_comparison_with_one_element_uses_the_full_width(
    themes: ThemeEngine, layouts: LayoutEngine
) -> None:
    """A single table already contains both sides of the comparison."""
    from deckforge.models.deck import TableElement

    theme = themes.get("github")
    slide = Slide(
        kind=SlideKind.COMPARISON,
        layout="comparison",
        title="Local-first is not cloud-only",
        elements=[
            TableElement(columns=["", "Cloud", "Local"], rows=[["Data", "Server", "Device"]])
        ],
    )
    frame = layouts.resolve(slide, theme)
    assert len(frame.elements) == 1
    assert frame.content_area is not None
    assert frame.elements[0].box.width == pytest.approx(frame.content_area.width)
    assert not any(d.kind == "rule" for d in frame.decor), "no divider without two sides"


def test_unknown_layout_degrades_gracefully(themes: ThemeEngine, layouts: LayoutEngine) -> None:
    slide = Slide(title="x", layout="from-a-plugin-that-is-gone")
    frame = layouts.resolve(slide, themes.get("minimal"))
    assert frame.layout in layouts.names()


def test_theme_layout_preferences_are_honoured(themes: ThemeEngine, layouts: LayoutEngine) -> None:
    theme: Theme = themes.get("finance")
    slide = Slide(kind=SlideKind.CONTENT, title="Revenue", elements=[BulletsElement(items=["a"])])
    ranked = [name for name, _ in layouts.rank(slide, theme)[:6]]
    assert set(ranked) & set(theme.preferred_layouts(SlideKind.CONTENT))
