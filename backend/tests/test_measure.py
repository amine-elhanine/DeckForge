"""Content measurement.

Layout boxes are sized from these estimates, and elements that hide their
overflow (cards, code panels) silently lose content when the estimate is too
small — so the estimates must stay at or above what the renderer draws.
"""

from __future__ import annotations

from deckforge.layouts import measure
from deckforge.models.deck import (
    BulletsElement,
    Card,
    CardsElement,
    CodeElement,
    TableElement,
    TextElement,
)
from deckforge.models.enums import TextRole


def test_text_height_grows_with_content(themes) -> None:
    theme = themes.get("minimal")
    style = theme.type_scale.body
    short = measure.text_height("one line", 800, style)
    long = measure.text_height("word " * 200, 800, style)
    assert 0 < short < long
    assert measure.text_height("", 800, style) == 0.0


def test_bold_display_type_measures_wider(themes) -> None:
    """A heavy face fits fewer characters per line than a regular one.

    Under-measuring a heading reserves one line too few, and the block below is
    then drawn on top of it — which is exactly what happened to a real
    generated cover slide.
    """
    theme = themes.get("technology")
    display = theme.type_scale.display
    body = theme.type_scale.body

    assert display.weight >= 600
    assert measure.glyph_width(display) > display.size * measure.GLYPH_RATIO
    assert measure.chars_per_line(645, display) < measure.chars_per_line(645, body)

    title = "Agentic AI: The Next Frontier in Autonomous Systems"
    lines = measure.text_height(title, 645, display) / (display.size * display.line_height)
    assert lines >= 4, "a 51-character display title wraps to four lines in a 645pt column"


def test_letter_spacing_changes_the_measure(themes) -> None:
    """Negative tracking on big display type genuinely fits more per line."""
    theme = themes.get("minimal")
    loose = theme.type_scale.display
    tight = loose.model_copy(update={"letter_spacing": -2.5})
    assert measure.glyph_width(tight) < measure.glyph_width(loose)


def test_narrower_columns_wrap_more(themes) -> None:
    theme = themes.get("minimal")
    style = theme.type_scale.body
    text = "a moderately long sentence that will certainly need to wrap somewhere"
    assert measure.text_height(text, 300, style) > measure.text_height(text, 900, style)


def test_bullets_scale_with_item_count(themes) -> None:
    theme = themes.get("minimal")
    two = BulletsElement(items=["one", "two"])
    ten = BulletsElement(items=[f"item {i}" for i in range(10)])
    assert measure.element_height(ten, 800, theme) > measure.element_height(two, 800, theme)


def test_card_estimate_covers_every_part(themes) -> None:
    """A badge and an icon both take vertical space and must be counted."""
    theme = themes.get("minimal")
    # Bodies long enough that both cards clear the 140pt minimum, so the
    # comparison measures the decorations rather than the floor.
    body = "A body long enough to wrap across several lines inside a narrow card column."
    plain = CardsElement(columns=3, cards=[Card(title="T", body=body)])
    decorated = CardsElement(
        columns=3, cards=[Card(title="T", body=body, icon="target", badge="1")]
    )
    bare = measure.element_height(plain, 1100, theme)
    full = measure.element_height(decorated, 1100, theme)
    assert bare > 140, "test needs cards taller than the minimum to be meaningful"
    # The icon (40) and badge (30) allowances must both be reflected.
    assert full - bare >= 60


def test_card_estimate_grows_with_body_length(themes) -> None:
    theme = themes.get("minimal")
    short = CardsElement(columns=3, cards=[Card(title="T", body="Short.")])
    long = CardsElement(columns=3, cards=[Card(title="T", body="A much longer body. " * 12)])
    assert measure.element_height(long, 900, theme) > measure.element_height(short, 900, theme)


def test_table_and_code_scale_with_rows(themes) -> None:
    theme = themes.get("minimal")
    small = TableElement(columns=["a", "b"], rows=[["1", "2"]])
    big = TableElement(columns=["a", "b"], rows=[["1", "2"]] * 10)
    assert measure.element_height(big, 800, theme) > measure.element_height(small, 800, theme)

    short_code = CodeElement(source="print(1)")
    long_code = CodeElement(source="\n".join(f"line {i}" for i in range(30)))
    assert measure.element_height(long_code, 800, theme) > measure.element_height(
        short_code, 800, theme
    )


def test_total_height_includes_gaps(themes) -> None:
    theme = themes.get("minimal")
    elements = [TextElement(text="a", role=TextRole.BODY) for _ in range(3)]
    single = measure.element_height(elements[0], 800, theme)
    total = measure.total_height(elements, 800, theme, gap=20)
    assert total == 3 * single + 40
    assert measure.total_height([], 800, theme, gap=20) == 0.0


def test_density_and_shrink_factor(themes) -> None:
    theme = themes.get("minimal")
    elements = [BulletsElement(items=[f"point {i}" for i in range(30)])]
    assert measure.density(elements, theme, 800, 200) > 1
    factor = measure.shrink_factor(elements, theme, 800, 200)
    assert 0.72 <= factor < 1.0
    assert measure.shrink_factor(elements, theme, 800, 5000) == 1.0
