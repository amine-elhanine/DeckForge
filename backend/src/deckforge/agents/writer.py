"""Slide writer.

Writes one slide per outline item, then materialises the drafts into deck JSON.

Slides are written concurrently: neighbour context comes from the *outline*, not
from previously written slides, so nothing is lost by parallelising — and on a
local 8B model it is the difference between a 30-second and a 4-minute deck.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.prompts import (
    SLIDE_WRITER,
    audience_clause,
    density_clause,
    language_clause,
)
from deckforge.core.errors import AgentError
from deckforge.core.events import EventType
from deckforge.core.logging import get_logger
from deckforge.models.deck import (
    BulletsElement,
    Card,
    CardsElement,
    ChartElement,
    ChartSeries,
    ChartSpec,
    CodeElement,
    DeckMetadata,
    DiagramElement,
    Element,
    ImageElement,
    MetricElement,
    Presentation,
    QuoteElement,
    Reference,
    Section,
    Slide,
    TableElement,
    TextElement,
    TimelineElement,
    TimelineEntry,
)
from deckforge.models.enums import ChartKind, DiagramEngine, SlideKind, TextRole
from deckforge.models.plan import DeckBrief, Outline, OutlineItem, SlideDraft

log = get_logger(__name__)

#: What a slide of each kind has to carry to be that kind of slide. Without
#: this the writer happily returns a paragraph for a `diagram` slide and the
#: deck ends up with a title over empty space.
REQUIRED_FIELD: dict[SlideKind, str] = {
    SlideKind.DIAGRAM: (
        "This slide MUST fill `diagram` with real Mermaid. Start with `flowchart LR` or "
        "`flowchart TD`, then edges like `A[Perceive] --> B{Decide}`. It is drawn as an "
        "actual diagram, so do not describe the flow in prose instead."
    ),
    SlideKind.PROCESS: (
        "This slide MUST fill either `diagram` with a Mermaid `flowchart`, or `timeline` "
        "with the ordered steps. A process described only in sentences is a missed slide."
    ),
    SlideKind.CHART: (
        "This slide MUST fill `chart` with categories and numeric series. If you do not have "
        "real numbers, do not invent them — use `cards` or `bullets` instead."
    ),
    SlideKind.METRICS: "This slide MUST fill `metrics` with 2-4 headline numbers and labels.",
    SlideKind.TIMELINE: "This slide MUST fill `timeline` with dated or phased entries.",
    SlideKind.TABLE: "This slide MUST fill `table` with `columns` and `rows`.",
    SlideKind.COMPARISON: (
        "This slide MUST set the two sides against each other in `cards` or `table` — "
        "a comparison written as one paragraph does not compare anything."
    ),
    SlideKind.QUOTE: "This slide MUST fill `quote` and `quote_attribution`.",
}


class SlideWriterAgent(Agent[OutlineItem, SlideDraft]):
    """Writes the copy for a single slide."""

    name = "slide_writer"
    description = "Writes the copy and speaker notes for one slide."
    status_message = "Writing slides"
    temperature = 0.7

    async def run(self, ctx: AgentContext, payload: OutlineItem) -> SlideDraft:
        brief: DeckBrief = ctx.scratch.get("brief") or DeckBrief()
        neighbours: str = ctx.scratch.get("neighbours", {}).get(payload.title, "")
        position: str = ctx.scratch.get("positions", {}).get(payload.title, "")

        system = (
            f"{SLIDE_WRITER}\n\n{density_clause(brief.density)}\n\n"
            f"{language_clause(brief.language)}"
        )
        user = "\n\n".join(
            filter(
                None,
                [
                    f'Deck: "{brief.title}" — {brief.goal}',
                    audience_clause(brief.audience, brief.tone),
                    f"This slide: {payload.title}\n"
                    f"Kind: {payload.kind}\n"
                    f"Job it must do: {payload.intent}\n"
                    f"Talking points to develop:\n"
                    + "\n".join(f"- {p}" for p in payload.talking_points),
                    REQUIRED_FIELD.get(payload.kind, ""),
                    f"Suggested visual treatment: {payload.visual}" if payload.visual else "",
                    position,
                    f"Neighbouring slides (do not repeat them):\n{neighbours}"
                    if neighbours
                    else "",
                    f"Evidence you may use (do not go beyond it for facts):\n{ctx.research}"
                    if ctx.research
                    else "",
                ],
            )
        )
        draft = await self.structured(ctx, SlideDraft, system=system, user=user)
        draft.kind = draft.kind or payload.kind
        draft.title = draft.title or payload.title
        return draft


class DeckAssembler:
    """Runs the writer across an outline and builds the deck JSON.

    Not an :class:`Agent` — it orchestrates one and owns the draft-to-JSON
    mapping, which is deterministic code rather than a model decision.
    """

    def __init__(self, writer: SlideWriterAgent | None = None) -> None:
        self.writer = writer or SlideWriterAgent()

    async def build(self, ctx: AgentContext, brief: DeckBrief, outline: Outline) -> Presentation:
        """Write every slide and return a complete deck."""
        deck = Presentation(
            title=outline.title or brief.title,
            subtitle=brief.subtitle,
            description=brief.goal,
            theme=brief.theme_hint or ctx.preferences.get("theme") or "minimal",
            meta=DeckMetadata(
                audience=brief.audience,
                tone=brief.tone,
                goal=brief.goal,
                duration_minutes=brief.duration_minutes,
                language=brief.language,
                keywords=brief.must_cover[:8],
                source_prompt=ctx.user_message,
            ),
        )
        sections = self._build_sections(deck, outline)
        ctx.scratch["brief"] = brief
        ctx.scratch["neighbours"] = self._neighbour_map(outline)
        ctx.scratch["positions"] = self._position_map(outline)

        total = len(outline.items)
        drafts: list[SlideDraft | None] = [None] * total
        completed = 0
        semaphore = asyncio.Semaphore(max(1, ctx.settings.worker_concurrency))
        lock = asyncio.Lock()

        async def write(index: int, item: OutlineItem) -> None:
            nonlocal completed
            async with semaphore:
                try:
                    drafts[index] = await self.writer.run(ctx, item)
                except AgentError as exc:
                    log.warning("writer.slide_failed", slide=item.title, error=str(exc))
                    drafts[index] = self._fallback_draft(item)
            async with lock:
                completed += 1
                await ctx.events.status(
                    f"Writing slides ({completed} of {total})",
                    phase="slide_writer",
                    progress=0.25 + 0.45 * completed / max(1, total),
                )

        await asyncio.gather(*(write(i, item) for i, item in enumerate(outline.items)))

        for item, draft in zip(outline.items, drafts, strict=True):
            slide = self.to_slide(draft or self._fallback_draft(item), item, sections)
            deck.add_slide(slide)
            await ctx.events.push(EventType.SLIDE, slide=slide.model_dump(mode="json"))

        self._collect_references(deck)
        return deck

    # -- outline plumbing --------------------------------------------------- #

    @staticmethod
    def _build_sections(deck: Presentation, outline: Outline) -> dict[str, Section]:
        sections: dict[str, Section] = {}
        for order, name in enumerate(
            [s for s in outline.sections if s] or [i.section for i in outline.items if i.section]
        ):
            if name not in sections:
                sections[name] = Section(title=name, order=order)
        deck.sections = sorted(sections.values(), key=lambda s: s.order)
        return sections

    @staticmethod
    def _neighbour_map(outline: Outline) -> dict[str, str]:
        out: dict[str, str] = {}
        for i, item in enumerate(outline.items):
            before = outline.items[i - 1].title if i else None
            after = outline.items[i + 1].title if i + 1 < len(outline.items) else None
            lines = [f"previous: {before}" if before else "", f"next: {after}" if after else ""]
            out[item.title] = "\n".join(filter(None, lines))
        return out

    @staticmethod
    def _position_map(outline: Outline) -> dict[str, str]:
        total = len(outline.items)
        return {
            item.title: f"This is slide {i + 1} of {total}."
            + (f" Narrative arc: {outline.narrative_arc}" if outline.narrative_arc else "")
            for i, item in enumerate(outline.items)
        }

    @staticmethod
    def _fallback_draft(item: OutlineItem) -> SlideDraft:
        """Used when a single slide's generation fails; the deck still ships."""
        return SlideDraft(
            title=item.title,
            kind=item.kind,
            bullets=item.talking_points[:5],
            notes=item.intent,
        )

    # -- draft -> slide ----------------------------------------------------- #

    def to_slide(self, draft: SlideDraft, item: OutlineItem, sections: dict[str, Section]) -> Slide:
        """Materialise a draft into deck JSON."""
        slide = Slide(
            kind=draft.kind or item.kind,
            title=draft.title or item.title,
            subtitle=draft.subtitle,
            eyebrow=draft.eyebrow,
            notes=draft.notes,
            section_id=sections[item.section].id if item.section in sections else None,
        )
        if hint := (draft.layout_hint or item.layout_hint):
            slide.metadata["layout_hint"] = hint

        slide.elements = self._elements_for(draft)
        slide.references = [
            Reference.model_validate(r)
            for r in draft.references
            if isinstance(r, dict) and r.get("title")
        ]
        return slide

    @staticmethod
    def _lead_prose(draft: SlideDraft) -> str:
        """Join the draft's prose into one lead block.

        Models split multi-paragraph copy either way — a `body` string with
        blank lines, or a `paragraphs` list — and some emit both, repeating the
        first paragraph. Duplicates are dropped so the slide never says the same
        sentence twice.
        """
        blocks: list[str] = []
        for text in [draft.body or "", *draft.paragraphs]:
            candidate = text.strip()
            if candidate and candidate not in blocks:
                blocks.append(candidate)
        return "\n\n".join(blocks)

    def _elements_for(self, draft: SlideDraft) -> list[Element]:
        elements: list[Element] = []

        if draft.quote:
            elements.append(QuoteElement(text=draft.quote, attribution=draft.quote_attribution))
        if lead := self._lead_prose(draft):
            elements.append(TextElement(text=lead, role=TextRole.LEAD))
        if draft.bullets:
            elements.append(BulletsElement(items=draft.bullets[:6]))
        for metric in draft.metrics[:4]:
            value = _field(metric, "value", "number", "figure", "stat")
            label = _field(metric, "label", "name", "title", "caption")
            if not value and not label:
                continue
            elements.append(
                MetricElement(
                    value=value,
                    label=label,
                    delta=_field(metric, "delta", "change") or None,
                    trend=metric.get("trend")
                    if metric.get("trend") in ("up", "down", "flat")
                    else None,
                    icon=metric.get("icon"),
                )
            )
        cards = [
            Card(
                title=_field(c, "title", "heading", "name", "label", "term"),
                body=_field(c, "body", "description", "text", "detail", "content", "definition"),
                icon=c.get("icon"),
                badge=_field(c, "badge", "tag") or None,
            )
            for c in draft.cards[:6]
        ]
        # A card with neither a title nor a body draws as an empty box, which is
        # worse than not drawing it: models do emit these when they run out of
        # ideas or use a key we do not read.
        cards = [c for c in cards if c.title.strip() or c.body.strip()]
        if cards:
            elements.append(CardsElement(columns=min(4, max(2, len(cards))), cards=cards))
        entries = [
            TimelineEntry(
                label=_field(e, "label", "date", "when", "period", "phase"),
                title=_field(e, "title", "heading", "name", "milestone"),
                body=_field(e, "body", "description", "text", "detail"),
                status=e.get("status")
                if e.get("status") in ("done", "active", "planned")
                else None,
            )
            for e in draft.timeline[:6]
        ]
        entries = [e for e in entries if e.label.strip() or e.title.strip() or e.body.strip()]
        if entries:
            elements.append(TimelineElement(entries=entries))
        if table := self._table_element(draft.table):
            elements.append(table)
        if chart := self._chart_element(draft.chart):
            elements.append(chart)
        if diagram := _diagram_source(draft.diagram):
            engine = str((draft.diagram or {}).get("engine", "mermaid")).lower()
            elements.append(
                DiagramElement(
                    engine=DiagramEngine(engine)
                    if engine in DiagramEngine.__members__.values()
                    else DiagramEngine.MERMAID,
                    source=diagram,
                    caption=(draft.diagram or {}).get("caption"),
                )
            )
        if draft.code and (source := _field(draft.code, "source", "code", "content", "snippet")):
            elements.append(
                CodeElement(
                    language=_field(draft.code, "language", "lang") or "text",
                    source=source,
                    caption=draft.code.get("caption"),
                )
            )
        if draft.image_prompt:
            # No local image generator by default: keep the intent as an
            # addressable placeholder so an image plugin can fill it in later.
            elements.append(
                ImageElement(src="", alt=draft.image_prompt, style={"generate": draft.image_prompt})
            )
        return elements

    @staticmethod
    def _table_element(spec: dict[str, Any] | None) -> TableElement | None:
        if not spec:
            return None
        columns = [str(c) for c in (spec.get("columns") or [])]
        rows = [[str(c) for c in row] for row in (spec.get("rows") or []) if isinstance(row, list)]
        if not columns and rows:
            columns, rows = rows[0], rows[1:]
        if not columns:
            return None
        return TableElement(columns=columns, rows=rows)

    @staticmethod
    def _chart_element(spec: dict[str, Any] | None) -> ChartElement | None:
        if not spec:
            return None
        raw_series = spec.get("series") or []
        series: list[ChartSeries] = []
        for entry in raw_series:
            if isinstance(entry, dict):
                values = [float(v) for v in (entry.get("values") or []) if _is_number(v)]
                series.append(ChartSeries(name=str(entry.get("name", "Series")), values=values))
            elif isinstance(entry, int | float):
                series.append(ChartSeries(name="Series", values=[float(entry)]))
        if not series or not any(s.values for s in series):
            return None
        kind_name = str(spec.get("kind", "column")).lower()
        kind = ChartKind(kind_name) if kind_name in set(ChartKind) else ChartKind.COLUMN
        return ChartElement(
            title=spec.get("title"),
            chart=ChartSpec(
                kind=kind,
                categories=[str(c) for c in (spec.get("categories") or [])],
                series=series,
                x_label=spec.get("x_label"),
                y_label=spec.get("y_label"),
                legend=len(series) > 1,
            ),
        )

    @staticmethod
    def _collect_references(deck: Presentation) -> None:
        """Promote per-slide references to the deck level, de-duplicated."""
        seen: set[str] = {r.title.lower() for r in deck.references}
        for slide in deck.slides:
            for reference in slide.references:
                key = reference.title.lower()
                if key not in seen:
                    seen.add(key)
                    deck.references.append(reference)


_FENCE_RE = re.compile(r"^```[\w]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def _diagram_source(spec: dict[str, str] | None) -> str:
    """The diagram's own text, however the model chose to label it.

    Models name this field `mermaid`, `code` or `definition` at least as often
    as `source`, and reading only `source` drops the diagram silently — the
    slide keeps its title and loses the picture it exists for. A fenced code
    block is unwrapped too, since Mermaid inside ``` is common.
    """
    if not spec:
        return ""
    text = _field(spec, "source", "mermaid", "code", "definition", "content", "chart", "graph")
    if fenced := _FENCE_RE.match(text.strip()):
        text = fenced.group(1)
    return text.strip()


def _field(mapping: dict[str, Any], *names: str) -> str:
    """First non-empty value among ``names``, as a string.

    The schema asks for `title`/`body`, but models substitute synonyms —
    `heading`, `description`, `term`/`definition` — and the strict reading of
    one key name is the difference between a populated card and an empty box on
    the slide.
    """
    for name in names:
        value = mapping.get(name)
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except TypeError, ValueError:
        return False
    return True
