"""Layout model — the geometry contract shared by every renderer.

A layout turns a :class:`~deckforge.models.deck.Slide` into a :class:`LayoutFrame`:
a flat list of absolutely positioned boxes on the logical canvas. HTML, PPTX and
PDF renderers all consume the *same* frame, which is why a deck looks the same in
the browser preview and in the downloaded file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from deckforge.models.deck import Background, Box, Element, Presentation, Slide
from deckforge.models.enums import Align, SlideKind
from deckforge.themes.model import Decor, Theme

VAlign = Literal["start", "center", "end"]

__all__ = [
    "Box",
    "DecorPlacement",
    "ElementPlacement",
    "LayoutBuilder",
    "LayoutContext",
    "LayoutDefinition",
    "LayoutFrame",
    "TextPlacement",
    "VAlign",
    "decor_for",
]


@dataclass(slots=True)
class TextPlacement:
    """A run of text the layout owns (title, subtitle, eyebrow, page number).

    ``group`` marks consecutive runs that belong together, such as an
    eyebrow/title/subtitle header. The HTML renderer lays a group out in normal
    document flow instead of positioning each run at its estimated ``y``: the
    browser may substitute a font the theme asked for but the machine does not
    have, and a title that then wraps one line further would otherwise be drawn
    straight over the subtitle. Renderers with real font metrics keep using the
    individual boxes.
    """

    text: str
    box: Box
    role: str
    align: Align = Align.START
    valign: VAlign = "start"
    color: str | None = None
    key: str = "text"
    group: str | None = None


@dataclass(slots=True)
class ElementPlacement:
    """A slide element with resolved geometry.

    ``z`` orders painting: full-bleed backdrops use a negative value so the
    layout's own title and subtitle stay on top of them.

    ``scale`` is the type autofit factor. When a slide's copy is too long for
    the space its layout could give it, the layout shrinks the type rather than
    letting the text run past the box — a paragraph set two points smaller is
    still a slide; a paragraph with its last three lines cut off is not.
    """

    element: Element
    box: Box
    valign: VAlign = "start"
    z: int = 0
    scale: float = 1.0


@dataclass(slots=True)
class DecorPlacement:
    """A decorative shape drawn beneath the content."""

    kind: str
    box: Box
    color: str
    opacity: float = 1.0
    radius: float = 0.0


@dataclass(slots=True)
class LayoutFrame:
    """Everything a renderer needs to draw one slide."""

    layout: str
    canvas: tuple[float, float]
    background: Background
    texts: list[TextPlacement] = field(default_factory=list)
    elements: list[ElementPlacement] = field(default_factory=list)
    decor: list[DecorPlacement] = field(default_factory=list)
    content_area: Box | None = None
    invert_text: bool = False
    """True when the background is dark and body text must flip to the light colour."""

    def all_boxes(self) -> list[Box]:
        return [t.box for t in self.texts] + [e.box for e in self.elements]


@dataclass(slots=True)
class LayoutContext:
    """Inputs available to a layout builder."""

    slide: Slide
    theme: Theme
    canvas: tuple[float, float]
    index: int = 0
    total: int = 1
    deck: Presentation | None = None

    @property
    def width(self) -> float:
        return self.canvas[0]

    @property
    def height(self) -> float:
        return self.canvas[1]

    def content_box(self) -> Box:
        """The full canvas minus theme margins."""
        s = self.theme.spacing
        return Box(
            x=s.margin_x,
            y=s.margin_y,
            width=self.width - 2 * s.margin_x,
            height=self.height - 2 * s.margin_y,
        )

    def elements_for(self, *types: str) -> list[Element]:
        """Return visible elements whose ``type`` is in ``types`` (all if empty)."""
        visible = [e for e in self.slide.elements if not e.hidden]
        if not types:
            return visible
        wanted = set(types)
        return [e for e in visible if str(e.type) in wanted]


LayoutBuilder = Callable[[LayoutContext], LayoutFrame]


@dataclass(slots=True)
class LayoutDefinition:
    """Registry entry describing one layout."""

    name: str
    label: str
    description: str
    builder: LayoutBuilder
    slots: list[str] = field(default_factory=lambda: ["body"])
    suits: list[SlideKind] = field(default_factory=list)
    capacity: int = 6
    """Roughly how many content items the layout holds gracefully."""
    tags: list[str] = field(default_factory=list)
    visual_weight: Literal["text", "balanced", "visual"] = "balanced"
    requires: list[str] = field(default_factory=list)
    """Element types that must be present for this layout to be selectable."""
    excludes: list[str] = field(default_factory=list)
    """Element types whose presence disqualifies this layout.

    A full-bleed image layout has nowhere to put a bullet list, so it must not be
    picked for a slide that has one — otherwise content silently disappears.
    """

    def accepts(self, slide: Slide) -> bool:
        """Whether this layout can render ``slide`` without dropping content."""
        present = {str(e.type) for e in slide.elements if not e.hidden}
        if self.requires and not all(req in present for req in self.requires):
            return False
        return not (self.excludes and present & set(self.excludes))


def decor_for(ctx: LayoutContext, decor: Decor) -> list[DecorPlacement]:
    """Translate a theme decor token into concrete shapes for this canvas."""
    w, h = ctx.canvas
    colour = ctx.theme.color(decor.color)
    match decor.kind:
        case "bar":
            return [
                DecorPlacement("rect", Box(x=0, y=0, width=w, height=decor.size or 6), colour, 1.0)
            ]
        case "underline":
            s = ctx.theme.spacing
            return [
                DecorPlacement(
                    "rect",
                    Box(x=s.margin_x, y=h - s.margin_y * 0.62, width=96, height=decor.size or 4),
                    colour,
                    1.0,
                )
            ]
        case "corner":
            size = decor.size or 160
            return [
                DecorPlacement(
                    "triangle",
                    Box(x=w - size, y=h - size, width=size, height=size),
                    colour,
                    decor.opacity,
                )
            ]
        case "orbs":
            size = decor.size or 320
            return [
                DecorPlacement(
                    "ellipse",
                    Box(x=w - size * 0.45, y=-size * 0.3, width=size, height=size),
                    colour,
                    decor.opacity,
                ),
                DecorPlacement(
                    "ellipse",
                    Box(x=-size * 0.35, y=h - size * 0.55, width=size * 0.8, height=size * 0.8),
                    ctx.theme.color("secondary"),
                    decor.opacity * 0.8,
                ),
            ]
        case "grid":
            return [DecorPlacement("grid", Box(x=0, y=0, width=w, height=h), colour, decor.opacity)]
        case "dots":
            size = decor.size or 180
            return [
                DecorPlacement(
                    "dots",
                    Box(x=w - size - 40, y=h - size - 40, width=size, height=size),
                    colour,
                    decor.opacity,
                )
            ]
        case "diagonal":
            size = decor.size or 300
            return [
                DecorPlacement(
                    "diagonal", Box(x=w - size, y=0, width=size, height=h), colour, decor.opacity
                )
            ]
        case _:
            return []
