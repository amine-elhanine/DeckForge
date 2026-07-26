"""Built-in layouts.

Each builder receives a :class:`LayoutContext` and returns a fully positioned
:class:`LayoutFrame`. Builders compose a handful of geometry primitives
(:func:`split_h`, :func:`columns`, :func:`stack`) rather than hardcoding
coordinates, so a theme's margins and rhythm change every layout at once.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from deckforge.layouts import measure
from deckforge.layouts.model import (
    Box,
    DecorPlacement,
    ElementPlacement,
    LayoutContext,
    LayoutDefinition,
    LayoutFrame,
    TextPlacement,
    VAlign,
    decor_for,
)
from deckforge.models.deck import Background, Element
from deckforge.models.enums import Align, BackgroundKind, ElementType, SlideKind
from deckforge.themes.model import Theme
from deckforge.utils import colors

VISUAL_TYPES = {
    ElementType.IMAGE,
    ElementType.CHART,
    ElementType.DIAGRAM,
    ElementType.TABLE,
    ElementType.TIMELINE,
    ElementType.CODE,
    ElementType.CARDS,
}

LAYOUT_BUILDERS: dict[str, LayoutDefinition] = {}


def layout(
    name: str,
    label: str,
    description: str,
    *,
    slots: Sequence[str] = ("title", "body"),
    suits: Sequence[SlideKind] = (),
    capacity: int = 6,
    tags: Sequence[str] = (),
    visual_weight: str = "balanced",
    requires: Sequence[str] = (),
    excludes: Sequence[str] = (),
) -> Callable[[Callable[[LayoutContext], LayoutFrame]], Callable[[LayoutContext], LayoutFrame]]:
    """Decorator registering a layout builder in the built-in table."""

    def wrap(fn: Callable[[LayoutContext], LayoutFrame]) -> Callable[[LayoutContext], LayoutFrame]:
        LAYOUT_BUILDERS[name] = LayoutDefinition(
            name=name,
            label=label,
            description=description,
            builder=fn,
            slots=list(slots),
            suits=list(suits),
            capacity=capacity,
            tags=list(tags),
            visual_weight=visual_weight,  # type: ignore[arg-type]
            requires=list(requires),
            excludes=list(excludes),
        )
        return fn

    return wrap


#: Element types that cannot survive a full-bleed layout.
BLOCKING_CONTENT = ["bullets", "table", "chart", "cards", "timeline", "code", "quote", "metric"]

#: Groups eyebrow/title/subtitle so the HTML renderer flows them together.
HEADER_GROUP = "header"


# --------------------------------------------------------------------------- #
# Geometry primitives
# --------------------------------------------------------------------------- #


def split_h(box: Box, ratio: float = 0.5, gap: float = 28.0) -> tuple[Box, Box]:
    """Split ``box`` horizontally; ``ratio`` is the left share."""
    left_w = (box.width - gap) * ratio
    right_w = box.width - gap - left_w
    return (
        Box(x=box.x, y=box.y, width=max(40.0, left_w), height=box.height),
        Box(x=box.x + left_w + gap, y=box.y, width=max(40.0, right_w), height=box.height),
    )


def split_v(box: Box, ratio: float = 0.5, gap: float = 24.0) -> tuple[Box, Box]:
    """Split ``box`` vertically; ``ratio`` is the top share."""
    top_h = (box.height - gap) * ratio
    bottom_h = box.height - gap - top_h
    return (
        Box(x=box.x, y=box.y, width=box.width, height=max(30.0, top_h)),
        Box(x=box.x, y=box.y + top_h + gap, width=box.width, height=max(30.0, bottom_h)),
    )


def columns(box: Box, count: int, gap: float = 28.0) -> list[Box]:
    """Split ``box`` into ``count`` equal columns."""
    count = max(1, count)
    width = (box.width - gap * (count - 1)) / count
    return [
        Box(x=box.x + i * (width + gap), y=box.y, width=max(30.0, width), height=box.height)
        for i in range(count)
    ]


def rows(box: Box, count: int, gap: float = 24.0) -> list[Box]:
    """Split ``box`` into ``count`` equal rows."""
    count = max(1, count)
    height = (box.height - gap * (count - 1)) / count
    return [
        Box(x=box.x, y=box.y + i * (height + gap), width=box.width, height=max(24.0, height))
        for i in range(count)
    ]


def grid_cells(box: Box, count: int, cols: int, gap: float = 24.0) -> list[Box]:
    """Lay ``count`` cells out on a ``cols``-wide grid inside ``box``."""
    if count <= 0:
        return []
    cols = max(1, min(cols, count))
    row_count = -(-count // cols)
    cell_w = (box.width - gap * (cols - 1)) / cols
    cell_h = (box.height - gap * (row_count - 1)) / row_count
    cells: list[Box] = []
    for i in range(count):
        r, c = divmod(i, cols)
        cells.append(
            Box(
                x=box.x + c * (cell_w + gap),
                y=box.y + r * (cell_h + gap),
                width=max(30.0, cell_w),
                height=max(30.0, cell_h),
            )
        )
    return cells


#: Elements that redraw themselves at whatever size they are given, so spare
#: room is pure gain: a chart or a diagram simply gets bigger and clearer.
_FILLS = frozenset({ElementType.CHART, ElementType.DIAGRAM, ElementType.IMAGE, ElementType.SHAPE})
#: Elements whose height comes from their content. They take spare room up to
#: :data:`MAX_GROWTH` — a card row twice its natural height frames the copy
#: nicely, but one stretched across half a slide is just a big empty box.
_GROWS = frozenset({ElementType.CARDS, ElementType.TABLE, ElementType.TIMELINE})
MAX_GROWTH = 1.8
#: Smallest a visual may be squeezed to before the type is asked to give way.
MIN_VISUAL = 120.0

#: Text and bullets are in neither set on purpose: a taller box adds trailing
#: whitespace and nothing else, and `valign` already decides where they sit.


def _release_slack(elements: list[Element], heights: list[float], budget: float) -> list[float]:
    """Fit ``heights`` into ``budget``, taking the space from visuals first.

    A diagram asked for less height simply draws smaller; a paragraph given
    less height than its text needs is painted over by whatever comes next. So
    the visuals give up their room before anything else is squeezed.
    """
    out = list(heights)
    total = sum(out)
    for index, element in enumerate(elements):
        if total <= budget:
            break
        if element.type not in _FILLS:
            continue
        give = min(out[index] - min(out[index], MIN_VISUAL), total - budget)
        out[index] -= give
        total -= give
    if total > budget:
        # Last resort. Renderers clip, which is why the type was shrunk first.
        squeeze = budget / total
        out = [h * squeeze for h in out]
    return out


def _absorb_slack(elements: list[Element], heights: list[float], slack: float) -> list[float]:
    """Hand leftover vertical space to the elements that can use it."""
    if slack <= 1.0:
        return heights
    ceilings = {
        index: (float("inf") if element.type in _FILLS else heights[index] * MAX_GROWTH)
        for index, element in enumerate(elements)
        if element.type in _FILLS or element.type in _GROWS
    }
    out = list(heights)
    # Several passes, because an element that hits its ceiling hands what it
    # could not use back to the others.
    for _ in range(3):
        hungry = [i for i, limit in ceilings.items() if out[i] < limit and slack > 1.0]
        if not hungry:
            break
        share = slack / len(hungry)
        for index in hungry:
            taken = min(share, ceilings[index] - out[index])
            out[index] += taken
            slack -= taken
    return out


def stack(
    elements: Sequence[Element],
    box: Box,
    theme: Theme,
    *,
    gap: float | None = None,
    valign: VAlign = "start",
) -> list[ElementPlacement]:
    """Lay elements out vertically inside ``box``, fitting them to the space.

    Overflow is resolved in the order that costs the reader least. Visuals go
    first — a diagram redraws at any size. Then the type is scaled down to the
    largest size at which the copy still fits, because a paragraph set a point
    smaller reads fine. Squeezing a text box below the height its words need is
    the last resort, and it is what makes one block paint over the next.

    Underflow is the opposite problem: leftover room goes to whatever can use
    it. A row of cards drawn at its minimum height above half an empty slide is
    the most common way a generated deck looks unfinished.
    """
    if not elements:
        return []
    items = list(elements)
    gap = theme.spacing.gap if gap is None else gap
    budget = max(60.0, box.height - gap * (len(items) - 1))

    # Type only has to fit around whatever the visuals cannot give up.
    rigid = [e for e in items if e.type not in _FILLS]
    reserved = sum(
        min(measure.element_height(e, box.width, theme), MIN_VISUAL)
        for e in items
        if e.type in _FILLS
    )
    scale = measure.fit_scale(rigid, theme, box.width, max(60.0, budget - reserved), 0.0)
    fitted = theme.type_scaled(scale)

    heights = [max(24.0, measure.element_height(e, box.width, fitted)) for e in items]
    total = sum(heights)
    if total > budget:
        heights = _release_slack(items, heights, budget)
    elif valign != "end":
        heights = _absorb_slack(items, heights, budget - total)
    natural = min(box.height, sum(heights) + gap * (len(items) - 1))

    y = box.y
    if valign == "center":
        y += max(0.0, (box.height - natural) / 2)
    elif valign == "end":
        y += max(0.0, box.height - natural)

    out: list[ElementPlacement] = []
    for element, height in zip(elements, heights, strict=True):
        out.append(
            ElementPlacement(
                element,
                Box(x=box.x, y=y, width=box.width, height=max(24.0, height)),
                scale=scale,
            )
        )
        y += height + gap
    return out


# --------------------------------------------------------------------------- #
# Frame scaffolding
# --------------------------------------------------------------------------- #


def resolve_background(ctx: LayoutContext) -> Background:
    """Slide background wins over the theme's per-kind background."""
    if ctx.slide.background is not None:
        return ctx.slide.background
    if ctx.deck is not None and ctx.deck.background is not None and not ctx.theme.backgrounds:
        return ctx.deck.background
    return ctx.theme.background_for(ctx.slide.kind)


def background_is_dark(background: Background, theme: Theme) -> bool:
    """Whether text on this background needs the light colour."""
    match background.kind:
        case BackgroundKind.SOLID:
            base = background.color or theme.palette.background
        case BackgroundKind.GRADIENT | BackgroundKind.MESH:
            base = background.colors[0] if background.colors else theme.palette.background
        case BackgroundKind.IMAGE:
            return True
        case _:
            base = theme.palette.background
    try:
        return colors.relative_luminance(base) < 0.45
    except ValueError:
        return theme.mode == "dark"


def new_frame(ctx: LayoutContext, name: str, *, with_decor: bool = True) -> LayoutFrame:
    """Create a frame with background and decorations already resolved."""
    background = resolve_background(ctx)
    dark_bg = background_is_dark(background, ctx.theme)
    frame = LayoutFrame(
        layout=name,
        canvas=ctx.canvas,
        background=background,
        invert_text=dark_bg and ctx.theme.mode == "light",
    )
    if with_decor:
        frame.decor = decor_for(ctx, ctx.theme.decor_for(ctx.slide.kind))
    return frame


def header(
    ctx: LayoutContext,
    area: Box,
    *,
    title_role: str = "title",
    align: Align = Align.START,
    include_subtitle: bool = True,
) -> tuple[list[TextPlacement], Box]:
    """Place eyebrow/title/subtitle at the top of ``area``.

    Returns the placements plus the remaining content box.
    """
    theme = ctx.theme
    slide = ctx.slide
    ts = theme.type_scale
    placements: list[TextPlacement] = []
    y = area.y

    if slide.eyebrow:
        h = measure.text_height(slide.eyebrow, area.width, ts.eyebrow)
        placements.append(
            TextPlacement(
                slide.eyebrow,
                Box(x=area.x, y=y, width=area.width, height=h),
                "eyebrow",
                align,
                key="eyebrow",
                group=HEADER_GROUP,
            )
        )
        y += h + theme.spacing.tight_gap * 0.6

    if slide.title:
        style = ts.get(title_role)
        h = measure.text_height(slide.title, area.width, style)
        placements.append(
            TextPlacement(
                slide.title,
                Box(x=area.x, y=y, width=area.width, height=h),
                title_role,
                align,
                key="title",
                group=HEADER_GROUP,
            )
        )
        y += h + theme.spacing.tight_gap

    if include_subtitle and slide.subtitle:
        h = measure.text_height(slide.subtitle, area.width, ts.subtitle)
        placements.append(
            TextPlacement(
                slide.subtitle,
                Box(x=area.x, y=y, width=area.width, height=h),
                "subtitle",
                align,
                key="subtitle",
                group=HEADER_GROUP,
            )
        )
        y += h

    if placements:
        y += theme.spacing.header_gap

    remaining = Box(x=area.x, y=y, width=area.width, height=max(60.0, area.bottom - y))
    return placements, remaining


def partition(elements: Sequence[Element]) -> tuple[list[Element], list[Element]]:
    """Split elements into (text-ish, visual) groups."""
    text_like = [e for e in elements if e.type not in VISUAL_TYPES]
    visual = [e for e in elements if e.type in VISUAL_TYPES]
    return text_like, visual


def excluding(elements: Sequence[Element], removed: Sequence[Element]) -> list[Element]:
    """Return ``elements`` minus ``removed``, compared by id rather than value.

    Two elements can be field-identical (e.g. duplicated bullets), so identity
    must go through the stable element id.
    """
    taken = {e.id for e in removed}
    return [e for e in elements if e.id not in taken]


# --------------------------------------------------------------------------- #
# Cover / statement layouts
# --------------------------------------------------------------------------- #


@layout(
    "hero",
    "Hero",
    "Large left-aligned title block with an optional visual on the right.",
    slots=["eyebrow", "title", "subtitle", "aside"],
    suits=[SlideKind.COVER, SlideKind.ENDING],
    capacity=2,
    tags=["cover", "opening"],
    visual_weight="visual",
)
def _hero(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "hero")
    area = ctx.content_box()
    text_like, visual = partition(ctx.elements_for())
    text_area, aside = split_h(area, 0.58, ctx.theme.spacing.gap * 1.6) if visual else (area, None)

    texts, rest = header(ctx, text_area, title_role="display")
    frame.texts = texts
    frame.content_area = rest
    frame.elements = stack(text_like, rest, ctx.theme, valign="start")
    if visual and aside is not None:
        frame.elements += stack(visual[:1], aside, ctx.theme, valign="center")
    return frame


@layout(
    "hero_centered",
    "Hero centred",
    "Everything centred on the canvas — maximum impact.",
    slots=["eyebrow", "title", "subtitle"],
    suits=[SlideKind.COVER, SlideKind.ENDING],
    capacity=2,
    tags=["cover", "statement"],
    visual_weight="text",
)
def _hero_centered(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "hero_centered")
    area = ctx.content_box().inset(ctx.width * 0.06, 0)
    ts = ctx.theme.type_scale
    slide = ctx.slide

    blocks: list[tuple[str, str]] = []
    if slide.eyebrow:
        blocks.append(("eyebrow", slide.eyebrow))
    if slide.title:
        blocks.append(("display", slide.title))
    if slide.subtitle:
        blocks.append(("subtitle", slide.subtitle))

    heights = [measure.text_height(text, area.width, ts.get(role)) for role, text in blocks]
    gap = ctx.theme.spacing.tight_gap
    elements = ctx.elements_for()
    element_h = measure.total_height(elements, area.width, ctx.theme, ctx.theme.spacing.gap)
    total = sum(heights) + gap * max(0, len(blocks) - 1) + (element_h + gap * 2 if elements else 0)

    y = area.y + max(0.0, (area.height - total) / 2)
    for (role, text), h in zip(blocks, heights, strict=True):
        frame.texts.append(
            TextPlacement(
                text,
                Box(x=area.x, y=y, width=area.width, height=h),
                role,
                Align.CENTER,
                key=role,
                group=HEADER_GROUP,
            )
        )
        y += h + gap
    if elements:
        y += gap
        frame.elements = stack(
            elements, Box(x=area.x, y=y, width=area.width, height=max(60.0, element_h)), ctx.theme
        )
    frame.content_area = area
    return frame


@layout(
    "title_only",
    "Title only",
    "A single line of text, nothing else.",
    slots=["title"],
    suits=[SlideKind.SECTION],
    capacity=1,
    tags=["statement"],
    visual_weight="text",
)
def _title_only(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "title_only")
    area = ctx.content_box()
    h = measure.text_height(ctx.slide.title, area.width, ctx.theme.type_scale.display)
    frame.texts.append(
        TextPlacement(
            ctx.slide.title,
            Box(x=area.x, y=area.y + (area.height - h) / 2, width=area.width, height=h),
            "display",
            Align.START,
            valign="center",
            key="title",
        )
    )
    frame.content_area = area
    return frame


@layout(
    "big_statement",
    "Big statement",
    "One sentence at display size, centred.",
    slots=["title"],
    suits=[SlideKind.QUOTE, SlideKind.SECTION],
    capacity=1,
    tags=["statement", "impact"],
    visual_weight="text",
)
def _big_statement(ctx: LayoutContext) -> LayoutFrame:
    return _hero_centered(ctx)


@layout(
    "section_divider",
    "Section divider",
    "Chapter break with a rule and section name.",
    slots=["eyebrow", "title"],
    suits=[SlideKind.SECTION],
    capacity=1,
    tags=["divider"],
    visual_weight="text",
)
def _section_divider(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "section_divider")
    area = ctx.content_box()
    ts = ctx.theme.type_scale
    rule_colour = ctx.theme.color("primary")

    title_h = measure.text_height(ctx.slide.title, area.width, ts.display)
    sub_h = measure.text_height(ctx.slide.subtitle or "", area.width, ts.subtitle)
    total = title_h + sub_h + 60
    y = area.y + max(0.0, (area.height - total) / 2)

    frame.decor.append(
        DecorPlacement("rect", Box(x=area.x, y=y, width=96, height=6), rule_colour, 1.0)
    )
    y += 34
    frame.texts.append(
        TextPlacement(
            ctx.slide.title,
            Box(x=area.x, y=y, width=area.width, height=title_h),
            "display",
            key="title",
            group=HEADER_GROUP,
        )
    )
    y += title_h + 14
    if ctx.slide.subtitle:
        frame.texts.append(
            TextPlacement(
                ctx.slide.subtitle,
                Box(x=area.x, y=y, width=area.width * 0.7, height=sub_h),
                "subtitle",
                key="subtitle",
                group=HEADER_GROUP,
            )
        )
    frame.content_area = area
    return frame


@layout(
    "section_number",
    "Numbered section",
    "Oversized section number beside the title.",
    slots=["number", "title"],
    suits=[SlideKind.SECTION],
    capacity=1,
    tags=["divider"],
    visual_weight="text",
)
def _section_number(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "section_number")
    area = ctx.content_box()
    ts = ctx.theme.type_scale
    number = str(ctx.slide.metadata.get("section_number") or ctx.index + 1).zfill(2)

    left, right = split_h(area, 0.3, ctx.theme.spacing.gap * 1.5)
    num_h = ts.section_number.size * 1.05
    frame.texts.append(
        TextPlacement(
            number,
            Box(x=left.x, y=left.y + (left.height - num_h) / 2, width=left.width, height=num_h),
            "section_number",
            valign="center",
            key="number",
        )
    )
    title_h = measure.text_height(ctx.slide.title, right.width, ts.title)
    sub_h = measure.text_height(ctx.slide.subtitle or "", right.width, ts.subtitle)
    y = right.y + max(0.0, (right.height - title_h - sub_h - 16) / 2)
    frame.texts.append(
        TextPlacement(
            ctx.slide.title,
            Box(x=right.x, y=y, width=right.width, height=title_h),
            "title",
            key="title",
            group=HEADER_GROUP,
        )
    )
    if ctx.slide.subtitle:
        frame.texts.append(
            TextPlacement(
                ctx.slide.subtitle,
                Box(x=right.x, y=y + title_h + 16, width=right.width, height=sub_h),
                "subtitle",
                key="subtitle",
                group=HEADER_GROUP,
            )
        )
    frame.content_area = area
    return frame


@layout(
    "ending",
    "Closing",
    "Thank-you / call-to-action slide.",
    slots=["title", "subtitle", "body"],
    suits=[SlideKind.ENDING],
    capacity=3,
    tags=["closing"],
    visual_weight="text",
)
def _ending(ctx: LayoutContext) -> LayoutFrame:
    return _hero_centered(ctx)


# --------------------------------------------------------------------------- #
# Content layouts
# --------------------------------------------------------------------------- #


@layout(
    "bullets",
    "Title and body",
    "Classic heading with a single content column.",
    slots=["title", "body"],
    suits=[SlideKind.CONTENT, SlideKind.APPENDIX],
    capacity=6,
    tags=["text"],
    visual_weight="text",
)
def _bullets(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "bullets")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body
    frame.elements = stack(ctx.elements_for(), body, ctx.theme)
    return frame


@layout(
    "split",
    "Split",
    "Text on the left, the visual on the right.",
    slots=["title", "body", "aside"],
    suits=[SlideKind.CONTENT, SlideKind.CHART],
    capacity=5,
    tags=["mixed"],
    visual_weight="balanced",
)
def _split(ctx: LayoutContext) -> LayoutFrame:
    return _split_impl(ctx, "split", reverse=False, ratio=0.48)


@layout(
    "split_reverse",
    "Split reversed",
    "Visual on the left, text on the right.",
    slots=["title", "aside", "body"],
    suits=[SlideKind.CONTENT, SlideKind.CHART],
    capacity=5,
    tags=["mixed"],
    visual_weight="balanced",
)
def _split_reverse(ctx: LayoutContext) -> LayoutFrame:
    return _split_impl(ctx, "split_reverse", reverse=True, ratio=0.52)


def _split_impl(ctx: LayoutContext, name: str, *, reverse: bool, ratio: float) -> LayoutFrame:
    frame = new_frame(ctx, name)
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body

    text_like, visual = partition(ctx.elements_for())
    if not visual:
        # Nothing to put in the aside column. Rather than silently collapsing to
        # a plain content slide, split a long list across two columns so the
        # deck still gets visual variety.
        from deckforge.models.deck import BulletsElement

        long_list = (
            len(text_like) == 1
            and isinstance(text_like[0], BulletsElement)
            and len(text_like[0].items) >= 5
        )
        if long_list:
            left, right = split_h(body, 0.5, ctx.theme.spacing.gap * 1.3)
            buckets = _split_bullets(text_like[0], 2)
            frame.elements = stack(buckets[0], left, ctx.theme)
            frame.elements += stack(buckets[1], right, ctx.theme)
        else:
            frame.elements = stack(text_like, body, ctx.theme)
        return frame
    if not text_like:
        frame.elements = stack(visual, body, ctx.theme)
        return frame

    left, right = split_h(body, ratio, ctx.theme.spacing.gap * 1.4)
    text_box, visual_box = (right, left) if reverse else (left, right)
    frame.elements = stack(text_like, text_box, ctx.theme, valign="center")
    frame.elements += stack(visual, visual_box, ctx.theme, valign="center")
    return frame


@layout(
    "two_column",
    "Two columns",
    "Content balanced across two equal columns.",
    slots=["title", "left", "right"],
    suits=[SlideKind.CONTENT, SlideKind.AGENDA],
    capacity=8,
    tags=["text", "dense"],
    visual_weight="text",
)
def _two_column(ctx: LayoutContext) -> LayoutFrame:
    return _n_column(ctx, "two_column", 2)


@layout(
    "three_column",
    "Three columns",
    "Three parallel ideas side by side.",
    slots=["title", "col1", "col2", "col3"],
    suits=[SlideKind.CONTENT],
    capacity=9,
    tags=["text", "dense"],
    visual_weight="text",
)
def _three_column(ctx: LayoutContext) -> LayoutFrame:
    return _n_column(ctx, "three_column", 3)


def _n_column(ctx: LayoutContext, name: str, count: int) -> LayoutFrame:
    frame = new_frame(ctx, name)
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body

    elements = ctx.elements_for()
    if not elements:
        return frame
    cols = columns(body, count, ctx.theme.spacing.gap * 1.3)
    buckets: list[list[Element]] = [[] for _ in range(count)]
    if len(elements) == 1 and elements[0].type is ElementType.BULLETS:
        buckets = _split_bullets(elements[0], count)
    else:
        for i, element in enumerate(elements):
            buckets[i % count].append(element)
    for bucket, box in zip(buckets, cols, strict=True):
        frame.elements += stack(bucket, box, ctx.theme)
    return frame


def _split_bullets(element: Element, count: int) -> list[list[Element]]:
    """Divide one bullet list across ``count`` columns, preserving order."""
    from deckforge.models.deck import BulletsElement

    if not isinstance(element, BulletsElement) or not element.items:
        return [[element], *([] for _ in range(count - 1))]
    per = -(-len(element.items) // count)
    buckets: list[list[Element]] = []
    for i in range(count):
        chunk = element.items[i * per : (i + 1) * per]
        clone = element.model_copy(deep=True)
        clone.items = chunk
        clone.id = f"{element.id}_c{i}"
        buckets.append([clone] if chunk else [])
    return buckets


@layout(
    "agenda",
    "Agenda",
    "Numbered running order with generous spacing.",
    slots=["title", "body"],
    suits=[SlideKind.AGENDA],
    capacity=8,
    tags=["list"],
    visual_weight="text",
)
def _agenda(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "agenda")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body
    elements = ctx.elements_for()
    box = Box(x=body.x, y=body.y, width=body.width * 0.78, height=body.height)
    frame.elements = stack(elements, box, ctx.theme, gap=ctx.theme.spacing.gap * 1.2)
    return frame


# --------------------------------------------------------------------------- #
# Image layouts
# --------------------------------------------------------------------------- #


@layout(
    "image_left",
    "Image left",
    "Full-bleed image on the left half.",
    slots=["image", "title", "body"],
    suits=[SlideKind.IMAGE, SlideKind.CONTENT],
    capacity=4,
    tags=["image"],
    visual_weight="visual",
)
def _image_left(ctx: LayoutContext) -> LayoutFrame:
    return _image_side(ctx, "image_left", side="left")


@layout(
    "image_right",
    "Image right",
    "Full-bleed image on the right half.",
    slots=["title", "body", "image"],
    suits=[SlideKind.IMAGE, SlideKind.CONTENT],
    capacity=4,
    tags=["image"],
    visual_weight="visual",
)
def _image_right(ctx: LayoutContext) -> LayoutFrame:
    return _image_side(ctx, "image_right", side="right")


def _image_side(ctx: LayoutContext, name: str, *, side: str) -> LayoutFrame:
    frame = new_frame(ctx, name)
    w, h = ctx.canvas
    text_like, visual = partition(ctx.elements_for())
    image_w = w * 0.44

    if visual:
        image_box = Box(x=0 if side == "left" else w - image_w, y=0, width=image_w, height=h)
        frame.elements.append(ElementPlacement(visual[0], image_box))
        remaining = Box(
            x=(image_w if side == "left" else 0) + ctx.theme.spacing.margin_x * 0.7,
            y=ctx.theme.spacing.margin_y,
            width=w - image_w - ctx.theme.spacing.margin_x * 1.7,
            height=h - 2 * ctx.theme.spacing.margin_y,
        )
    else:
        remaining = ctx.content_box()

    texts, body = header(ctx, remaining)
    frame.texts = texts
    frame.content_area = body
    frame.elements += stack(text_like + visual[1:], body, ctx.theme, valign="center")
    return frame


@layout(
    "image_full",
    "Full image",
    "Edge-to-edge image with a caption strip.",
    slots=["image", "caption"],
    suits=[SlideKind.IMAGE],
    capacity=1,
    tags=["image"],
    visual_weight="visual",
    requires=["image"],
    excludes=BLOCKING_CONTENT,
)
def _image_full(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "image_full", with_decor=False)
    w, h = ctx.canvas
    _, visual = partition(ctx.elements_for())
    if visual:
        frame.elements.append(ElementPlacement(visual[0], Box(x=0, y=0, width=w, height=h), z=-1))
    if ctx.slide.title:
        title_h = measure.text_height(ctx.slide.title, w * 0.7, ctx.theme.type_scale.title)
        frame.texts.append(
            TextPlacement(
                ctx.slide.title,
                Box(
                    x=ctx.theme.spacing.margin_x,
                    y=h - title_h - ctx.theme.spacing.margin_y,
                    width=w * 0.7,
                    height=title_h,
                ),
                "title",
                key="title",
            )
        )
        frame.invert_text = True
    frame.content_area = Box(x=0, y=0, width=w, height=h)
    return frame


@layout(
    "image_background",
    "Image background",
    "Image behind the title with a scrim overlay.",
    slots=["image", "title", "subtitle"],
    suits=[SlideKind.COVER, SlideKind.SECTION],
    capacity=1,
    tags=["image", "cover"],
    visual_weight="visual",
    excludes=BLOCKING_CONTENT,
)
def _image_background(ctx: LayoutContext) -> LayoutFrame:
    frame = _hero_centered(ctx)
    frame.layout = "image_background"
    _, visual = partition(ctx.elements_for())
    if visual and visual[0].type is ElementType.IMAGE:
        frame.elements = [
            ElementPlacement(visual[0], Box(x=0, y=0, width=ctx.width, height=ctx.height), z=-1)
        ]
        frame.invert_text = True
    return frame


# --------------------------------------------------------------------------- #
# Structured layouts
# --------------------------------------------------------------------------- #


@layout(
    "cards",
    "Cards",
    "Content chunked into surface cards.",
    slots=["title", "cards"],
    suits=[SlideKind.CONTENT, SlideKind.QUIZ],
    capacity=6,
    tags=["cards"],
    visual_weight="balanced",
)
def _cards(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "cards")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body
    # Centred: cards grow only so far, so what is left over reads best split
    # evenly above and below the row rather than pooled under it.
    frame.elements = stack(ctx.elements_for(), body, ctx.theme, valign="center")
    return frame


@layout(
    "grid",
    "Grid",
    "Equal cells in a responsive grid.",
    slots=["title", "grid"],
    suits=[SlideKind.CONTENT],
    capacity=9,
    tags=["grid", "dense"],
    visual_weight="balanced",
)
def _grid(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "grid")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body
    elements = ctx.elements_for()
    if not elements:
        return frame
    if len(elements) == 1:
        frame.elements = stack(elements, body, ctx.theme)
        return frame
    cols = 2 if len(elements) <= 4 else 3
    for element, cell in zip(
        elements, grid_cells(body, len(elements), cols, ctx.theme.spacing.gap), strict=True
    ):
        # Through `stack` rather than placed directly: a grid cell is the
        # tightest box on any slide, so its contents most need the type autofit.
        frame.elements += stack([element], cell, ctx.theme)
    return frame


@layout(
    "comparison",
    "Comparison",
    "Two panels set against each other.",
    slots=["title", "left", "right"],
    suits=[SlideKind.COMPARISON],
    capacity=6,
    tags=["compare"],
    visual_weight="balanced",
)
def _comparison(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "comparison")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body

    elements = ctx.elements_for()
    # A single element *is* the comparison — a table or chart with both sides in
    # it. Splitting would strand it in the left half and leave the slide looking
    # half-finished, so it gets the full width and no divider.
    if len(elements) < 2:
        frame.elements = stack(elements, body, ctx.theme, valign="center")
        return frame

    left_box, right_box = split_h(body, 0.5, ctx.theme.spacing.gap * 1.5)
    frame.decor.append(
        DecorPlacement(
            "rule",
            Box(x=body.x + body.width / 2 - 1, y=body.y, width=2, height=body.height),
            ctx.theme.color("border"),
            1.0,
        )
    )
    mid = -(-len(elements) // 2)
    frame.elements = stack(elements[:mid], left_box, ctx.theme)
    frame.elements += stack(elements[mid:], right_box, ctx.theme)
    return frame


@layout(
    "metrics",
    "Metrics",
    "A row of headline numbers.",
    slots=["title", "metrics"],
    suits=[SlideKind.METRICS],
    capacity=5,
    tags=["kpi"],
    visual_weight="balanced",
)
def _metrics(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "metrics")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body

    metrics = ctx.elements_for(str(ElementType.METRIC))
    if not metrics:
        frame.elements = stack(ctx.elements_for(), body, ctx.theme)
        return frame

    others = excluding(ctx.elements_for(), metrics)
    metric_band = body
    if others:
        metric_band, rest = split_v(body, 0.42, ctx.theme.spacing.gap)
        frame.elements += stack(others, rest, ctx.theme)
    for element, cell in zip(
        metrics, columns(metric_band, len(metrics), ctx.theme.spacing.gap), strict=True
    ):
        frame.elements.append(ElementPlacement(element, cell, valign="center"))
    return frame


@layout(
    "dashboard",
    "Dashboard",
    "KPI row above a chart.",
    slots=["title", "metrics", "chart"],
    suits=[SlideKind.METRICS, SlideKind.CHART],
    capacity=6,
    tags=["kpi", "data"],
    visual_weight="visual",
)
def _dashboard(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "dashboard")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body

    metrics = ctx.elements_for(str(ElementType.METRIC))
    rest = excluding(ctx.elements_for(), metrics)
    if metrics and rest:
        top, bottom = split_v(body, 0.3, ctx.theme.spacing.gap)
        for element, cell in zip(
            metrics, columns(top, len(metrics), ctx.theme.spacing.gap), strict=True
        ):
            frame.elements.append(ElementPlacement(element, cell, valign="center"))
        frame.elements += stack(rest, bottom, ctx.theme)
    else:
        frame.elements = stack(ctx.elements_for(), body, ctx.theme)
    return frame


@layout(
    "chart_focus",
    "Chart focus",
    "One chart at full width with a takeaway line.",
    slots=["title", "chart", "takeaway"],
    suits=[SlideKind.CHART],
    capacity=3,
    tags=["data"],
    visual_weight="visual",
    requires=["chart"],
)
def _chart_focus(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "chart_focus")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body

    charts = ctx.elements_for(str(ElementType.CHART))
    others = excluding(ctx.elements_for(), charts)
    if others:
        chart_box, note_box = split_v(body, 0.76, ctx.theme.spacing.tight_gap)
        frame.elements = stack(charts, chart_box, ctx.theme)
        frame.elements += stack(others, note_box, ctx.theme)
    else:
        frame.elements = stack(charts or ctx.elements_for(), body, ctx.theme)
    return frame


@layout(
    "table",
    "Table",
    "A single data table filling the content area.",
    slots=["title", "table"],
    suits=[SlideKind.TABLE],
    capacity=2,
    tags=["data"],
    visual_weight="visual",
)
def _table(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "table")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body
    frame.elements = stack(ctx.elements_for(), body, ctx.theme)
    return frame


@layout(
    "timeline",
    "Timeline",
    "Chronological milestones along an axis.",
    slots=["title", "timeline"],
    suits=[SlideKind.TIMELINE],
    capacity=6,
    tags=["time"],
    visual_weight="visual",
)
def _timeline(ctx: LayoutContext) -> LayoutFrame:
    return _timeline_impl(ctx, "timeline")


@layout(
    "roadmap",
    "Roadmap",
    "Phased plan across horizontal lanes.",
    slots=["title", "timeline"],
    suits=[SlideKind.ROADMAP],
    capacity=6,
    tags=["time", "plan"],
    visual_weight="visual",
)
def _roadmap(ctx: LayoutContext) -> LayoutFrame:
    return _timeline_impl(ctx, "roadmap")


@layout(
    "process",
    "Process",
    "Sequential steps with connectors.",
    slots=["title", "steps"],
    suits=[SlideKind.PROCESS],
    capacity=6,
    tags=["flow"],
    visual_weight="visual",
)
def _process(ctx: LayoutContext) -> LayoutFrame:
    return _timeline_impl(ctx, "process")


@layout(
    "cycle",
    "Cycle",
    "Repeating loop of stages.",
    slots=["title", "steps"],
    suits=[SlideKind.PROCESS],
    capacity=6,
    tags=["flow"],
    visual_weight="visual",
)
def _cycle(ctx: LayoutContext) -> LayoutFrame:
    return _timeline_impl(ctx, "cycle")


def _timeline_impl(ctx: LayoutContext, name: str) -> LayoutFrame:
    frame = new_frame(ctx, name)
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body
    elements = ctx.elements_for()
    timeline = [e for e in elements if e.type is ElementType.TIMELINE]
    others = excluding(elements, timeline)
    if timeline and others:
        top, bottom = split_v(body, 0.66, ctx.theme.spacing.gap)
        frame.elements = stack(timeline, top, ctx.theme, valign="center")
        frame.elements += stack(others, bottom, ctx.theme)
    else:
        frame.elements = stack(elements, body, ctx.theme, valign="center")
    return frame


@layout(
    "diagram",
    "Diagram",
    "A single diagram with a short caption.",
    slots=["title", "diagram"],
    suits=[SlideKind.DIAGRAM],
    capacity=2,
    tags=["diagram"],
    visual_weight="visual",
    # A diagram slide with no diagram is a title over empty space. The writer
    # does sometimes describe the flow in prose instead of drawing it, and when
    # it does the slide is better served by an ordinary text layout.
    requires=["diagram"],
)
def _diagram(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "diagram")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    frame.content_area = body
    frame.elements = stack(ctx.elements_for(), body, ctx.theme, valign="center")
    return frame


@layout(
    "architecture",
    "Architecture",
    "System diagram with annotation column.",
    slots=["title", "diagram", "notes"],
    suits=[SlideKind.DIAGRAM],
    capacity=4,
    tags=["diagram", "technical"],
    visual_weight="visual",
)
def _architecture(ctx: LayoutContext) -> LayoutFrame:
    return _split_impl(ctx, "architecture", reverse=True, ratio=0.62)


@layout(
    "flow",
    "Flow",
    "Left-to-right flow of stages.",
    slots=["title", "flow"],
    suits=[SlideKind.PROCESS, SlideKind.DIAGRAM],
    capacity=6,
    tags=["diagram", "flow"],
    visual_weight="visual",
)
def _flow(ctx: LayoutContext) -> LayoutFrame:
    return _timeline_impl(ctx, "flow")


@layout(
    "tree",
    "Tree",
    "Hierarchy such as an org chart.",
    slots=["title", "tree"],
    suits=[SlideKind.DIAGRAM],
    capacity=4,
    tags=["diagram"],
    visual_weight="visual",
)
def _tree(ctx: LayoutContext) -> LayoutFrame:
    return _diagram(ctx)


@layout(
    "mind_map",
    "Mind map",
    "Central idea with radiating branches.",
    slots=["title", "map"],
    suits=[SlideKind.DIAGRAM],
    capacity=4,
    tags=["diagram"],
    visual_weight="visual",
)
def _mind_map(ctx: LayoutContext) -> LayoutFrame:
    return _diagram(ctx)


@layout(
    "infographic",
    "Infographic",
    "Icon-led visual explanation in cells.",
    slots=["title", "cells"],
    suits=[SlideKind.CONTENT],
    capacity=6,
    tags=["visual"],
    visual_weight="visual",
)
def _infographic(ctx: LayoutContext) -> LayoutFrame:
    return _grid(ctx)


@layout(
    "quote",
    "Quote",
    "Pull quote with attribution.",
    slots=["quote", "attribution"],
    suits=[SlideKind.QUOTE],
    capacity=1,
    tags=["quote"],
    visual_weight="text",
)
def _quote(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "quote")
    area = ctx.content_box().inset(ctx.width * 0.05, 0)
    elements = ctx.elements_for()
    quotes: list[Element] = [e for e in elements if e.type is ElementType.QUOTE]
    target: list[Element] = quotes or elements
    height = measure.total_height(target, area.width, ctx.theme, ctx.theme.spacing.gap)
    box = Box(
        x=area.x,
        y=area.y + max(0.0, (area.height - height) / 2),
        width=area.width,
        height=max(80.0, min(height, area.height)),
    )
    frame.elements = stack(target, box, ctx.theme, valign="center")
    frame.content_area = area
    return frame


@layout(
    "quiz",
    "Quiz",
    "Question with answer cards.",
    slots=["title", "options"],
    suits=[SlideKind.QUIZ],
    capacity=5,
    tags=["interactive"],
    visual_weight="balanced",
)
def _quiz(ctx: LayoutContext) -> LayoutFrame:
    return _cards(ctx)


@layout(
    "references",
    "References",
    "Two-column citation list at small type.",
    slots=["title", "refs"],
    suits=[SlideKind.REFERENCES],
    capacity=14,
    tags=["text"],
    visual_weight="text",
)
def _references(ctx: LayoutContext) -> LayoutFrame:
    elements = ctx.elements_for()
    return _n_column(ctx, "references", 2 if len(elements) > 1 else 1)
