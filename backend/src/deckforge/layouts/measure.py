"""Content measurement.

Layouts need to know roughly how tall an element will render before any renderer
runs, so that two bullets and twelve bullets do not get the same box. The
estimates are deliberately cheap and approximate — good enough to distribute
space, with renderers auto-shrinking type as a safety net.
"""

from __future__ import annotations

import math

from deckforge.models.deck import (
    BulletsElement,
    CardsElement,
    ChartElement,
    CodeElement,
    DiagramElement,
    Element,
    IconElement,
    ImageElement,
    MetricElement,
    QuoteElement,
    ShapeElement,
    TableElement,
    TextElement,
    TimelineElement,
)
from deckforge.themes.model import Theme, TypeStyle

#: Mean glyph advance as a fraction of the font size, for a regular humanist sans.
GLYPH_RATIO = 0.52
#: Bold and heavier faces are noticeably wider at the same nominal size.
BOLD_GLYPH_BONUS = 0.04


def glyph_width(style: TypeStyle) -> float:
    """Average advance width of one character at ``style``.

    Weight and tracking both matter: a 68pt bold display line fits far fewer
    characters than the plain ratio suggests, and under-measuring a heading
    makes the layout reserve one line too few — so the next block is drawn on
    top of it.
    """
    ratio = GLYPH_RATIO + (BOLD_GLYPH_BONUS if style.weight >= 600 else 0.0)
    return max(1.0, style.size * ratio + style.letter_spacing)


def chars_per_line(width: float, style: TypeStyle) -> int:
    """How many characters fit on one line of ``width`` at ``style``."""
    return max(8, int(width / glyph_width(style)))


def text_height(text: str, width: float, style: TypeStyle) -> float:
    """Estimated rendered height of ``text`` wrapped to ``width``."""
    if not text:
        return 0.0
    per_line = chars_per_line(width, style)
    lines = 0
    for paragraph in text.split("\n"):
        lines += max(1, math.ceil(len(paragraph) / per_line))
    if style.max_lines:
        lines = min(lines, style.max_lines)
    return lines * style.size * style.line_height


def element_height(element: Element, width: float, theme: Theme) -> float:
    """Estimated height of ``element`` at ``width``."""
    ts = theme.type_scale
    match element:
        case TextElement():
            return text_height(element.text, width, ts.get(str(element.role)))
        case BulletsElement():
            style = ts.bullet
            gap = theme.bullets.row_gap
            indent = theme.bullets.indent
            total = 0.0
            for item in element.items:
                avail = width - indent * (item.level + 1)
                total += text_height(item.text, max(60.0, avail), style) + gap
            return max(style.size, total - gap if element.items else 0.0)
        case ImageElement():
            return width * 0.62
        case ChartElement():
            return max(220.0, width * 0.55)
        case DiagramElement():
            return max(220.0, width * 0.5)
        case TableElement():
            rows = len(element.rows) + (1 if element.header else 0)
            return max(80.0, rows * ts.table.size * 2.3)
        case QuoteElement():
            body = text_height(element.text, width, ts.quote)
            return body + (ts.caption.size * 2.4 if element.attribution else 0.0)
        case MetricElement():
            return ts.metric_value.size * 1.25 + ts.metric_label.size * 2.2
        case CardsElement():
            # Must match what the HTML renderer actually draws: badge, icon,
            # title, body, plus the gaps between them. Underestimating here
            # clips the card body, because cards hide their overflow.
            columns = max(1, element.columns)
            rows = math.ceil(len(element.cards) / columns) if element.cards else 1
            card_width = (width - theme.spacing.gap * (columns - 1)) / columns
            inner_width = max(60.0, card_width - 2 * theme.spacing.card_padding)
            tallest = 0.0
            for card in element.cards:
                h = 2 * theme.spacing.card_padding
                if card.badge:
                    h += 30.0
                if card.icon:
                    h += 40.0
                h += text_height(card.title, inner_width, ts.card_title)
                if card.body:
                    h += 6.0 + text_height(card.body, inner_width, ts.card_body)
                tallest = max(tallest, h)
            return rows * max(140.0, tallest) + (rows - 1) * theme.spacing.gap
        case TimelineElement():
            if element.orientation == "vertical":
                return max(180.0, len(element.entries) * 78.0)
            return 250.0
        case CodeElement():
            lines = len(element.source.splitlines()) or 1
            return min(460.0, 36.0 + lines * ts.code.size * ts.code.line_height)
        case IconElement():
            return element.size * 1.7 + (ts.caption.size * 1.6 if element.label else 0.0)
        case ShapeElement():
            return 120.0
        case _:
            return 120.0


def total_height(elements: list[Element], width: float, theme: Theme, gap: float) -> float:
    """Height of a vertical stack of ``elements`` including gaps."""
    if not elements:
        return 0.0
    return sum(element_height(e, width, theme) for e in elements) + gap * (len(elements) - 1)


def density(elements: list[Element], theme: Theme, width: float, height: float) -> float:
    """Ratio of estimated content height to available height (>1 means overflow)."""
    if height <= 0:
        return 0.0
    return total_height(elements, width, theme, theme.spacing.gap) / height


#: Type never shrinks below this fraction of the theme's size — smaller is unreadable
#: from the back of a room, and the honest failure is to let the layout overflow.
MIN_TYPE_SCALE = 0.72


def shrink_factor(elements: list[Element], theme: Theme, width: float, height: float) -> float:
    """Type scale factor that would make the stack fit, clamped to a readable floor."""
    d = density(elements, theme, width, height)
    if d <= 1.0:
        return 1.0
    return max(MIN_TYPE_SCALE, 1.0 / d)


def fit_scale(
    elements: list[Element],
    theme: Theme,
    width: float,
    height: float,
    gap: float,
    *,
    floor: float = MIN_TYPE_SCALE,
) -> float:
    """The largest type scale at which ``elements`` still fit in ``height``.

    :func:`shrink_factor` divides by the overflow ratio, which overshoots badly
    for wrapped text: halving the type size roughly *quarters* the height,
    because each line also holds twice as many characters. Elements with a
    fixed aspect (images, charts) do not shrink with the type at all. Rather
    than model either, this searches for the answer by measuring.
    """
    if not elements or height <= 0:
        return 1.0
    natural = total_height(elements, width, theme, gap)
    if natural <= height:
        return 1.0

    smallest = total_height(elements, width, theme.type_scaled(floor), gap)
    if smallest > height:
        # Even the floor overflows. Shrinking is only worth it if the type is
        # what is taking the room: a chart or a diagram keeps its aspect
        # whatever the type does, and making its labels tiny buys nothing.
        return floor if smallest <= natural * 0.85 else 1.0

    low, high = floor, 1.0
    for _ in range(6):
        middle = (low + high) / 2
        if total_height(elements, width, theme.type_scaled(middle), gap) <= height:
            low = middle
        else:
            high = middle
    return low
