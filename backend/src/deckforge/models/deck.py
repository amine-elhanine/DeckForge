"""The deck domain model — DeckForge's single source of truth.

Every agent, renderer and exporter reads and writes this structure. No exporter
ever manipulates a PPTX/PDF file directly as a source of state: the file is a
projection of :class:`Presentation`.

Hierarchy::

    Presentation
      └── Section        (ordered grouping, addressable by title)
            └── Slide    (flat ordered list, each carrying ``section_id``)
                  └── Element  (discriminated union, placed into layout slots)

Slides are stored as a flat ordered list rather than nested inside sections so
that "move slide 7 before slide 4" is a single list operation. ``iter_sections``
provides the nested view when one is needed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deckforge.models.enums import (
    Align,
    AspectRatio,
    BackgroundKind,
    BulletStyle,
    ChartKind,
    DiagramEngine,
    ElementType,
    ImageFit,
    SlideKind,
    TextRole,
)

CANVAS_WIDTH = 1280.0
"""Logical canvas width in points. Every geometry box is expressed in these units."""
CANVAS_HEIGHT = 720.0
"""Logical canvas height for 16:9. 4:3 decks use 960x720."""


def new_id(prefix: str) -> str:
    """Return a short, human-greppable identifier such as ``sl_9f2c1a``."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DeckModel(BaseModel):
    """Base model with deck-wide serialization conventions."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        use_enum_values=False,
        validate_assignment=False,
    )


# --------------------------------------------------------------------------- #
# Geometry & styling primitives
# --------------------------------------------------------------------------- #


class Box(DeckModel):
    """An absolute rectangle on the logical canvas, in points."""

    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def inset(self, dx: float, dy: float | None = None) -> Box:
        """Return a copy shrunk by ``dx``/``dy`` on every side."""
        dy = dx if dy is None else dy
        return Box(
            x=self.x + dx,
            y=self.y + dy,
            width=max(1.0, self.width - 2 * dx),
            height=max(1.0, self.height - 2 * dy),
        )

    def fraction(self, canvas_w: float = CANVAS_WIDTH, canvas_h: float = CANVAS_HEIGHT) -> Box:
        """Return the box normalised to 0..1 — handy for HTML percentage layout."""
        return Box(
            x=self.x / canvas_w,
            y=self.y / canvas_h,
            width=self.width / canvas_w,
            height=self.height / canvas_h,
        )


class Background(DeckModel):
    """Slide or deck background specification."""

    kind: BackgroundKind = BackgroundKind.SOLID
    color: str | None = None
    colors: list[str] = Field(default_factory=list)
    angle: float = 135.0
    image: str | None = None
    fit: ImageFit = ImageFit.COVER
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    overlay: str | None = Field(default=None, description="CSS colour drawn above an image.")
    pattern: str | None = Field(default=None, description="Named pattern from the theme.")


class Animation(DeckModel):
    """Declarative entrance animation metadata (honoured by HTML/Reveal exports)."""

    target: str = Field(description="Element id, or '*' for the whole slide.")
    effect: str = "fade-up"
    delay_ms: int = 0
    duration_ms: int = 500
    order: int = 0


class Reference(DeckModel):
    """A citation attached to a slide or to the deck."""

    id: str = Field(default_factory=lambda: new_id("ref"))
    title: str
    url: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    publisher: str | None = None
    note: str | None = None
    source_document: str | None = Field(
        default=None, description="Uploaded asset id this reference was retrieved from."
    )

    def format_apa(self) -> str:
        """Return a compact APA-ish citation string."""
        authors = ", ".join(self.authors) if self.authors else ""
        year = f"({self.year})" if self.year else ""
        bits = [b for b in (authors, year, self.title, self.publisher, self.url) if b]
        return ". ".join(bits)


# --------------------------------------------------------------------------- #
# Elements
# --------------------------------------------------------------------------- #


class BaseElement(DeckModel):
    """Fields shared by every element."""

    id: str = Field(default_factory=lambda: new_id("el"))
    slot: str = Field(
        default="body",
        description="Named layout slot this element goes in (e.g. 'title', 'body', 'aside').",
    )
    frame: Box | None = Field(
        default=None, description="Explicit geometry overriding the layout slot."
    )
    style: dict[str, Any] = Field(
        default_factory=dict, description="Theme-token overrides, e.g. {'color': 'accent'}."
    )
    hidden: bool = False
    z: int = 0


class TextElement(BaseElement):
    type: Literal[ElementType.TEXT] = ElementType.TEXT
    text: str = ""
    role: TextRole = TextRole.BODY
    align: Align = Align.START
    markdown: bool = True


class BulletItem(DeckModel):
    text: str
    level: int = Field(default=0, ge=0, le=3)
    icon: str | None = None
    emphasis: bool = False


class BulletsElement(BaseElement):
    type: Literal[ElementType.BULLETS] = ElementType.BULLETS
    items: list[BulletItem] = Field(default_factory=list)
    bullet_style: BulletStyle = BulletStyle.DOT

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_strings(cls, value: object) -> object:
        """Accept ``["a", "b"]`` from the LLM as well as full objects."""
        if isinstance(value, list):
            return [{"text": v} if isinstance(v, str) else v for v in value]
        return value


class ImageElement(BaseElement):
    type: Literal[ElementType.IMAGE] = ElementType.IMAGE
    src: str = Field(description="Asset id, relative asset path, https URL or data URI.")
    alt: str = ""
    caption: str | None = None
    fit: ImageFit = ImageFit.COVER
    radius: float | None = None


class IconElement(BaseElement):
    type: Literal[ElementType.ICON] = ElementType.ICON
    name: str = "sparkle"
    label: str | None = None
    color: str | None = None
    size: float = 48.0


class ChartSeries(DeckModel):
    name: str = "Series"
    values: list[float] = Field(default_factory=list)
    color: str | None = None


class ChartSpec(DeckModel):
    """A renderer-independent chart description."""

    kind: ChartKind = ChartKind.COLUMN
    categories: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    x_label: str | None = None
    y_label: str | None = None
    legend: bool = True
    value_format: str = "{:,.0f}"
    stacked: bool = False
    palette: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _pad_series(self) -> Self:
        """Ensure every series has one value per category."""
        if self.categories:
            width = len(self.categories)
            for s in self.series:
                if len(s.values) < width:
                    s.values.extend([0.0] * (width - len(s.values)))
                elif len(s.values) > width:
                    del s.values[width:]
        return self


class ChartElement(BaseElement):
    type: Literal[ElementType.CHART] = ElementType.CHART
    chart: ChartSpec = Field(default_factory=ChartSpec)
    title: str | None = None
    caption: str | None = None


class DiagramElement(BaseElement):
    type: Literal[ElementType.DIAGRAM] = ElementType.DIAGRAM
    engine: DiagramEngine = DiagramEngine.MERMAID
    source: str = ""
    caption: str | None = None
    rendered_asset_id: str | None = Field(
        default=None, description="Populated once a diagram renderer has rasterised the source."
    )


class TableElement(BaseElement):
    type: Literal[ElementType.TABLE] = ElementType.TABLE
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    header: bool = True
    striped: bool = True
    column_widths: list[float] = Field(default_factory=list)

    @field_validator("rows", mode="before")
    @classmethod
    def _stringify(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                [("" if c is None else str(c)) for c in row] if isinstance(row, list) else row
                for row in value
            ]
        return value


class QuoteElement(BaseElement):
    type: Literal[ElementType.QUOTE] = ElementType.QUOTE
    text: str = ""
    attribution: str | None = None
    role: str | None = None


class MetricElement(BaseElement):
    type: Literal[ElementType.METRIC] = ElementType.METRIC
    value: str = ""
    label: str = ""
    delta: str | None = None
    trend: Literal["up", "down", "flat"] | None = None
    icon: str | None = None


class Card(DeckModel):
    title: str = ""
    body: str = ""
    icon: str | None = None
    accent: str | None = None
    badge: str | None = None


class CardsElement(BaseElement):
    type: Literal[ElementType.CARDS] = ElementType.CARDS
    cards: list[Card] = Field(default_factory=list)
    columns: int = Field(default=3, ge=1, le=6)


class TimelineEntry(DeckModel):
    label: str = ""
    title: str = ""
    body: str = ""
    icon: str | None = None
    status: Literal["done", "active", "planned"] | None = None


class TimelineElement(BaseElement):
    type: Literal[ElementType.TIMELINE] = ElementType.TIMELINE
    entries: list[TimelineEntry] = Field(default_factory=list)
    orientation: Literal["horizontal", "vertical"] = "horizontal"


class CodeElement(BaseElement):
    type: Literal[ElementType.CODE] = ElementType.CODE
    language: str = "text"
    source: str = ""
    caption: str | None = None
    highlight_lines: list[int] = Field(default_factory=list)


class ShapeElement(BaseElement):
    type: Literal[ElementType.SHAPE] = ElementType.SHAPE
    shape: Literal["rect", "ellipse", "line", "blob", "grid"] = "rect"
    color: str | None = None
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    radius: float = 0.0


Element = Annotated[
    TextElement
    | BulletsElement
    | ImageElement
    | IconElement
    | ChartElement
    | DiagramElement
    | TableElement
    | QuoteElement
    | MetricElement
    | CardsElement
    | TimelineElement
    | CodeElement
    | ShapeElement,
    Field(discriminator="type"),
]
"""Discriminated union of every element type. Plugins extend rendering, not this union."""


# --------------------------------------------------------------------------- #
# Slides, sections, presentation
# --------------------------------------------------------------------------- #


class Slide(DeckModel):
    """One slide: semantic content plus presentation hints."""

    id: str = Field(default_factory=lambda: new_id("sl"))
    kind: SlideKind = SlideKind.CONTENT
    layout: str = Field(default="auto", description="Layout name; 'auto' lets the engine choose.")
    section_id: str | None = None

    eyebrow: str | None = None
    title: str = ""
    subtitle: str | None = None
    elements: list[Element] = Field(default_factory=list)

    notes: str = Field(default="", description="Speaker notes, plain text or markdown.")
    background: Background | None = None
    theme_overrides: dict[str, Any] = Field(default_factory=dict)
    animations: list[Animation] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    locked: bool = Field(default=False, description="Agents must not modify a locked slide.")
    hidden: bool = False

    def element_by_id(self, element_id: str) -> Element | None:
        return next((e for e in self.elements if e.id == element_id), None)

    def elements_in_slot(self, slot: str) -> list[Element]:
        return [e for e in self.elements if e.slot == slot and not e.hidden]

    def slots(self) -> list[str]:
        seen: list[str] = []
        for e in self.elements:
            if e.slot not in seen:
                seen.append(e.slot)
        return seen

    def text_content(self) -> str:
        """Flatten the slide to plain text — used for search, critique and dedup."""
        parts: list[str] = [self.eyebrow or "", self.title, self.subtitle or ""]
        for e in self.elements:
            match e:
                case TextElement():
                    parts.append(e.text)
                case BulletsElement():
                    parts.extend(i.text for i in e.items)
                case QuoteElement():
                    parts.extend([e.text, e.attribution or ""])
                case CardsElement():
                    parts.extend(f"{c.title} {c.body}" for c in e.cards)
                case TimelineElement():
                    parts.extend(f"{t.label} {t.title} {t.body}" for t in e.entries)
                case MetricElement():
                    parts.append(f"{e.value} {e.label}")
                case TableElement():
                    parts.extend(" ".join(r) for r in e.rows)
                case CodeElement():
                    parts.append(e.source)
                case ImageElement():
                    parts.append(e.caption or e.alt)
                case _:
                    pass
        return "\n".join(p for p in parts if p).strip()

    def word_count(self) -> int:
        return len(self.text_content().split())


class Section(DeckModel):
    """An ordered grouping of slides, used for agendas and navigation."""

    id: str = Field(default_factory=lambda: new_id("sec"))
    title: str = ""
    summary: str | None = None
    order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeckMetadata(DeckModel):
    """Authoring intent captured once and reused by every agent."""

    audience: str | None = None
    tone: str | None = None
    goal: str | None = None
    duration_minutes: int | None = None
    language: str = "en"
    reading_level: str | None = None
    keywords: list[str] = Field(default_factory=list)
    source_prompt: str | None = None
    generator: str = "deckforge"
    extra: dict[str, Any] = Field(default_factory=dict)


class Presentation(DeckModel):
    """The complete deck. Every export is a projection of this object."""

    id: str = Field(default_factory=lambda: new_id("pres"))
    title: str = "Untitled presentation"
    subtitle: str | None = None
    description: str | None = None

    theme: str = "minimal"
    theme_overrides: dict[str, Any] = Field(default_factory=dict)
    aspect_ratio: AspectRatio = AspectRatio.WIDESCREEN
    background: Background | None = None

    sections: list[Section] = Field(default_factory=list)
    slides: list[Slide] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    meta: DeckMetadata = Field(default_factory=DeckMetadata)

    version: int = 1
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # -- geometry ---------------------------------------------------------- #

    @property
    def canvas(self) -> tuple[float, float]:
        """Return the logical canvas size for this deck's aspect ratio."""
        if self.aspect_ratio is AspectRatio.STANDARD:
            return 960.0, CANVAS_HEIGHT
        return CANVAS_WIDTH, CANVAS_HEIGHT

    # -- lookups ----------------------------------------------------------- #

    def slide_by_id(self, slide_id: str) -> Slide | None:
        return next((s for s in self.slides if s.id == slide_id), None)

    def index_of(self, slide_id: str) -> int:
        for i, s in enumerate(self.slides):
            if s.id == slide_id:
                return i
        return -1

    def section_by_id(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def iter_sections(self) -> Iterator[tuple[Section | None, list[Slide]]]:
        """Yield ``(section, slides)`` in deck order, including ungrouped slides."""
        buckets: dict[str | None, list[Slide]] = {}
        for slide in self.slides:
            buckets.setdefault(slide.section_id, []).append(slide)
        seen: set[str | None] = set()
        for slide in self.slides:
            key = slide.section_id
            if key in seen:
                continue
            seen.add(key)
            yield (self.section_by_id(key) if key else None), buckets[key]

    # -- mutation helpers (used by the revision agent's operations) --------- #

    def add_slide(self, slide: Slide, index: int | None = None) -> Slide:
        if index is None or index >= len(self.slides):
            self.slides.append(slide)
        else:
            self.slides.insert(max(0, index), slide)
        self.touch()
        return slide

    def remove_slide(self, slide_id: str) -> Slide | None:
        idx = self.index_of(slide_id)
        if idx < 0:
            return None
        removed = self.slides.pop(idx)
        self.touch()
        return removed

    def move_slide(self, slide_id: str, to_index: int) -> bool:
        idx = self.index_of(slide_id)
        if idx < 0:
            return False
        slide = self.slides.pop(idx)
        self.slides.insert(max(0, min(to_index, len(self.slides))), slide)
        self.touch()
        return True

    def touch(self) -> None:
        self.updated_at = _utcnow()

    # -- statistics -------------------------------------------------------- #

    def stats(self) -> dict[str, Any]:
        """Return counters used by the critic agent and the UI."""
        words = sum(s.word_count() for s in self.slides)
        layouts = [s.layout for s in self.slides]
        return {
            "slides": len(self.slides),
            "sections": len(self.sections),
            "words": words,
            "avg_words_per_slide": round(words / len(self.slides), 1) if self.slides else 0,
            "distinct_layouts": len(set(layouts)),
            "with_notes": sum(1 for s in self.slides if s.notes.strip()),
            "references": len(self.references) + sum(len(s.references) for s in self.slides),
            "estimated_minutes": round(len(self.slides) * 1.5, 1),
        }

    def outline_text(self) -> str:
        """Compact textual outline handed to agents so they can reason about the deck."""
        lines: list[str] = []
        for i, slide in enumerate(self.slides, start=1):
            head = f"{i}. [{slide.kind}/{slide.layout}] {slide.title or '(untitled)'}"
            if slide.subtitle:
                head += f" — {slide.subtitle}"
            lines.append(f"{head}  (id={slide.id})")
        return "\n".join(lines)
