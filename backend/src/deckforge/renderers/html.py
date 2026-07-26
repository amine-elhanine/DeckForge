"""HTML renderer.

This is the reference renderer: the live preview, the HTML export and the
Reveal.js export all use it, and the PPTX/PDF exporters are checked against it.

Slides are drawn on the same 1280×720 logical canvas the layout engine uses.
Every length is expressed as a multiple of a single CSS custom property::

    --df-u: calc(100cqw / 1280)

so a slide scales perfectly to any container width without JavaScript.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

from deckforge.layouts.engine import LayoutEngine
from deckforge.layouts.model import DecorPlacement, ElementPlacement, LayoutFrame, TextPlacement
from deckforge.models.deck import (
    Background,
    BulletsElement,
    CardsElement,
    ChartElement,
    CodeElement,
    DiagramElement,
    Element,
    IconElement,
    ImageElement,
    MetricElement,
    Presentation,
    QuoteElement,
    ShapeElement,
    Slide,
    TableElement,
    TextElement,
    TimelineElement,
)
from deckforge.models.enums import BackgroundKind, BulletStyle, ImageFit
from deckforge.renderers import charts, diagrams, icons
from deckforge.renderers.svg import drawing_to_svg
from deckforge.themes.model import Theme, TypeStyle
from deckforge.utils import colors

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)", re.DOTALL)
_CODE = re.compile(r"`([^`]+?)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

MARKER_GLYPHS = {
    "dot": "•",
    "dash": "–",
    "square": "▪",
    "chevron": "›",
    "check": "✓",
    "none": "",
}


def u(value: float) -> str:
    """Express a logical-canvas length as CSS."""
    return f"calc({value:.2f} * var(--df-u))"


def inline_markdown(text: str) -> str:
    """Render the small markdown subset allowed inside slide text."""
    out = escape(text)
    out = _CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    out = _LINK.sub(r'<a href="\2" rel="noreferrer noopener">\1</a>', out)
    return out.replace("\n", "<br/>")


class HtmlRenderer:
    """Turns decks and slides into HTML."""

    def __init__(self, layout_engine: LayoutEngine | None = None) -> None:
        self.layouts = layout_engine or LayoutEngine()

    # -- public API --------------------------------------------------------- #

    def render_deck_fragment(self, deck: Presentation, theme: Theme) -> str:
        """Render every slide as ``<section>`` elements, without a document shell."""
        frames = self.layouts.resolve_deck(deck, theme)
        return "\n".join(
            self.render_slide(slide, theme, frame, index=i)
            for i, (slide, frame) in enumerate(zip(deck.slides, frames, strict=True))
        )

    def render_document(
        self,
        deck: Presentation,
        theme: Theme,
        *,
        standalone: bool = True,
        include_notes: bool = False,
    ) -> str:
        """Render a complete, self-contained HTML document."""
        body = self.render_deck_fragment(deck, theme)
        notes_css = "" if include_notes else ".df-notes{display:none}"
        title = escape(deck.title)
        if not standalone:
            return f'<div class="df-deck">{body}</div>'
        return f"""<!doctype html>
<html lang="{escape(deck.meta.language or "en")}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>{self.stylesheet(theme)}{notes_css}{theme.css}</style>
</head>
<body class="df-body df-mode-{theme.mode}">
<main class="df-deck">
{body}
</main>
</body>
</html>
"""

    def render_slide(
        self,
        slide: Slide,
        theme: Theme,
        frame: LayoutFrame | None = None,
        *,
        index: int = 0,
        deck: Presentation | None = None,
    ) -> str:
        """Render one slide as a ``<section class="df-stage">`` block."""
        if frame is None:
            canvas = deck.canvas if deck else (1280.0, 720.0)
            frame = self.layouts.resolve(slide, theme, canvas=canvas, index=index, deck=deck)

        parts: list[str] = [self._decor_layer(frame, theme), *self._render_texts(frame, theme)]
        for placement in frame.elements:
            parts.append(self._element_placement(placement, theme, frame))

        notes = (
            f'<aside class="df-notes">{inline_markdown(slide.notes)}</aside>' if slide.notes else ""
        )
        style = self._background_style(frame.background, theme)
        animation = ' data-animate="true"' if slide.animations else ""
        return (
            f'<section class="df-stage" data-slide-id="{slide.id}" data-index="{index}" '
            f'data-kind="{slide.kind}" data-layout="{frame.layout}" aria-label="Slide {index + 1}">'
            f'<div class="df-slide{" df-invert" if frame.invert_text else ""}" style="{style}"{animation}>'
            f"{''.join(p for p in parts if p)}"
            f"</div>{notes}</section>"
        )

    # -- stylesheet --------------------------------------------------------- #

    def stylesheet(self, theme: Theme) -> str:
        """Theme-derived CSS shared by preview and exports."""
        variables = "".join(f"{k}:{v};" for k, v in theme.css_variables().items())
        invert_text = "#ffffff"
        invert_muted = colors.with_alpha("#ffffff", 0.78)
        return f"""
:root{{{variables}}}
*,*::before,*::after{{box-sizing:border-box}}
.df-body{{margin:0;background:var(--df-surface-alt);color:var(--df-text);
  font-family:var(--df-font-body);-webkit-font-smoothing:antialiased}}
.df-deck{{display:flex;flex-direction:column;gap:24px;padding:24px;max-width:1400px;margin:0 auto}}
.df-stage{{position:relative;width:100%;aspect-ratio:16/9;container-type:size;
  border-radius:10px;overflow:hidden;box-shadow:0 6px 30px rgba(10,14,25,.14)}}
.df-slide{{--df-u:calc(100cqw / 1280);position:absolute;inset:0;overflow:hidden;isolation:isolate;
  color:var(--df-text);font-family:var(--df-font-body);
  /* Base size so any text without an explicit style still scales with the canvas. */
  font-size:calc(19 * var(--df-u))}}
.df-slide.df-invert{{color:{invert_text}}}
.df-slide.df-invert .df-muted{{color:{invert_muted}}}
.df-abs{{position:absolute;display:flex;flex-direction:column}}
.df-abs>*{{min-width:0}}
.df-text{{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}
.df-text a{{color:var(--df-primary);text-decoration:underline}}
.df-text code,.df-code code{{font-family:var(--df-font-mono)}}
.df-bullets{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}}
.df-bullet{{display:flex;align-items:flex-start}}
.df-marker{{flex:none;color:var(--df-primary);line-height:1;display:flex;align-items:center;
  justify-content:center}}
.df-bullet-text{{flex:1}}
.df-image{{width:100%;height:100%;display:block;border-radius:var(--df-image-radius);
  background:var(--df-surface)}}
.df-image-wrap{{position:relative;width:100%;height:100%;overflow:hidden;
  border-radius:var(--df-image-radius)}}
.df-image-fallback{{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
  background:var(--df-surface);color:var(--df-text-muted);border:1px dashed var(--df-border);
  border-radius:var(--df-image-radius);text-align:center;padding:8%}}
.df-caption{{color:var(--df-text-muted)}}
.df-card{{background:var(--df-surface);border-radius:var(--df-card-radius);
  border:var(--df-border-width) solid var(--df-border);display:flex;flex-direction:column;
  justify-content:center;overflow:hidden}}
.df-cards{{display:grid;height:100%;width:100%}}
.df-metric{{display:flex;flex-direction:column;justify-content:center;height:100%}}
.df-delta-up{{color:var(--df-success)}}
.df-delta-down{{color:var(--df-danger)}}
.df-table{{width:100%;border-collapse:collapse;table-layout:fixed}}
.df-table th{{text-align:left;font-weight:600;border-bottom:2px solid var(--df-primary)}}
.df-table td{{border-bottom:1px solid var(--df-border);vertical-align:top}}
.df-table tr.df-stripe td{{background:var(--df-surface)}}
.df-quote{{display:flex;flex-direction:column;justify-content:center;height:100%}}
.df-quote-mark{{color:var(--df-primary);opacity:.5;line-height:.8}}
.df-timeline{{display:flex;width:100%;height:100%}}
.df-timeline-h{{flex-direction:row;align-items:stretch}}
.df-timeline-v{{flex-direction:column}}
.df-tl-item{{flex:1;display:flex;flex-direction:column;position:relative}}
.df-tl-rail{{position:absolute;background:var(--df-border)}}
.df-tl-dot{{border-radius:999px;background:var(--df-primary);flex:none}}
.df-code{{background:var(--df-surface);border:var(--df-border-width) solid var(--df-border);
  border-radius:var(--df-radius);overflow:hidden;height:100%}}
.df-code pre{{margin:0;font-family:var(--df-font-mono);white-space:pre-wrap;
  overflow-wrap:anywhere}}
.df-diagram{{background:var(--df-surface);border:var(--df-border-width) solid var(--df-border);
  border-radius:var(--df-radius);height:100%;display:flex;align-items:center;
  justify-content:center;overflow:hidden}}
.df-diagram pre{{margin:0;font-family:var(--df-font-mono);white-space:pre-wrap}}
.df-diagram-figure{{width:100%;height:100%;display:flex;align-items:center;
  justify-content:center}}
.df-diagram-figure svg{{width:100%;height:100%}}
.df-chart-wrap{{width:100%;height:100%}}
.df-decor{{position:absolute;inset:0;pointer-events:none}}
.df-notes{{padding:12px 16px;background:var(--df-surface);border-radius:8px;
  color:var(--df-text-muted);font-size:14px}}
@media print{{
  .df-deck{{gap:0;padding:0;max-width:none}}
  .df-stage{{border-radius:0;box-shadow:none;break-after:page;page-break-after:always}}
}}
@media (prefers-reduced-motion:no-preference){{
  .df-slide[data-animate="true"] .df-abs{{animation:df-rise .5s ease both}}
  @keyframes df-rise{{from{{opacity:0;transform:translateY(calc(14 * var(--df-u)))}}
    to{{opacity:1;transform:none}}}}
}}
"""

    # -- background & decoration -------------------------------------------- #

    def _background_style(self, background: Background, theme: Theme) -> str:
        match background.kind:
            case BackgroundKind.SOLID:
                return f"background:{background.color or theme.palette.background};"
            case BackgroundKind.GRADIENT:
                stops = background.colors or [theme.palette.background, theme.palette.surface]
                return f"background:linear-gradient({background.angle}deg,{','.join(stops)});"
            case BackgroundKind.MESH:
                stops = background.colors or [theme.palette.background]
                base = stops[0]
                spots = [
                    ("18% 22%", 1),
                    ("82% 12%", 2),
                    ("70% 88%", 3),
                    ("12% 82%", 4),
                ]
                layers = [
                    f"radial-gradient(closest-side at {pos},"
                    f"{colors.with_alpha(stops[i % len(stops)], 0.85)},transparent)"
                    for pos, i in spots
                ]
                return f"background:{','.join(layers)},{base};"
            case BackgroundKind.IMAGE:
                overlay = background.overlay or "rgba(8,10,18,.45)"
                src = escape(background.image or "", quote=True)
                return (
                    f"background-image:linear-gradient({overlay},{overlay}),url('{src}');"
                    f"background-size:{background.fit.value};background-position:center;"
                )
            case BackgroundKind.PATTERN:
                tint = colors.with_alpha(theme.palette.primary, 0.08)
                return (
                    f"background:repeating-linear-gradient(45deg,{tint} 0 2px,"
                    f"transparent 2px 14px),{theme.palette.background};"
                )
            case _:
                return ""

    def _decor_layer(self, frame: LayoutFrame, theme: Theme) -> str:
        if not frame.decor:
            return ""
        w, h = frame.canvas
        shapes = "".join(self._decor_shape(d) for d in frame.decor)
        return (
            f'<svg class="df-decor" viewBox="0 0 {w:.0f} {h:.0f}" preserveAspectRatio="none" '
            f'aria-hidden="true">{shapes}</svg>'
        )

    @staticmethod
    def _decor_shape(d: DecorPlacement) -> str:
        b = d.box
        match d.kind:
            case "rect" | "rule":
                return (
                    f'<rect x="{b.x:.1f}" y="{b.y:.1f}" width="{b.width:.1f}" '
                    f'height="{b.height:.1f}" fill="{d.color}" opacity="{d.opacity}"/>'
                )
            case "ellipse":
                return (
                    f'<ellipse cx="{b.x + b.width / 2:.1f}" cy="{b.y + b.height / 2:.1f}" '
                    f'rx="{b.width / 2:.1f}" ry="{b.height / 2:.1f}" fill="{d.color}" '
                    f'opacity="{d.opacity}"/>'
                )
            case "triangle":
                return (
                    f'<polygon points="{b.right:.1f},{b.y:.1f} {b.right:.1f},{b.bottom:.1f} '
                    f'{b.x:.1f},{b.bottom:.1f}" fill="{d.color}" opacity="{d.opacity}"/>'
                )
            case "diagonal":
                return (
                    f'<polygon points="{b.x:.1f},{b.y:.1f} {b.right:.1f},{b.y:.1f} '
                    f'{b.right:.1f},{b.bottom:.1f}" fill="{d.color}" opacity="{d.opacity}"/>'
                )
            case "grid":
                step = 48
                lines = "".join(
                    f'<path d="M{x} 0V{b.height:.0f}" stroke="{d.color}" stroke-width="1"/>'
                    for x in range(0, int(b.width), step)
                ) + "".join(
                    f'<path d="M0 {y}H{b.width:.0f}" stroke="{d.color}" stroke-width="1"/>'
                    for y in range(0, int(b.height), step)
                )
                return f'<g opacity="{d.opacity}">{lines}</g>'
            case "dots":
                step = 22
                dots = "".join(
                    f'<circle cx="{b.x + x}" cy="{b.y + y}" r="2.4" fill="{d.color}"/>'
                    for x in range(0, int(b.width), step)
                    for y in range(0, int(b.height), step)
                )
                return f'<g opacity="{d.opacity}">{dots}</g>'
            case _:
                return ""

    # -- text --------------------------------------------------------------- #

    def _type_css(self, style: TypeStyle, theme: Theme, *, invert: bool) -> str:
        color = (
            "inherit" if invert and style.color in ("text", "heading") else theme.color(style.color)
        )
        css = (
            f"font-size:{u(style.size)};font-weight:{style.weight};"
            f"line-height:{style.line_height};color:{color};"
            f"font-family:{theme.font_family(style.font)};"
        )
        if style.letter_spacing:
            css += f"letter-spacing:{u(style.letter_spacing)};"
        if style.transform != "none":
            css += f"text-transform:{style.transform};"
        return css

    def _box_css(self, placement: TextPlacement | ElementPlacement) -> str:
        b = placement.box
        justify = {"start": "flex-start", "center": "center", "end": "flex-end"}[placement.valign]
        return (
            f"left:{u(b.x)};top:{u(b.y)};width:{u(b.width)};height:{u(b.height)};"
            f"justify-content:{justify};"
        )

    def _render_texts(self, frame: LayoutFrame, theme: Theme) -> list[str]:
        """Render text runs, flowing grouped ones together.

        Ungrouped runs keep their absolute box. A group gets one container
        anchored at the first box, with its runs stacked in normal flow — so if
        the browser substitutes a wider font and the title wraps an extra line,
        the subtitle moves down instead of being overdrawn.
        """
        out: list[str] = []
        index = 0
        while index < len(frame.texts):
            current = frame.texts[index]
            if current.group is None:
                out.append(self._text_placement(current, theme, frame))
                index += 1
                continue
            run = [current]
            index += 1
            while index < len(frame.texts) and frame.texts[index].group == current.group:
                run.append(frame.texts[index])
                index += 1
            out.append(self._text_group(run, theme, frame))
        return out

    def _text_group(self, run: list[TextPlacement], theme: Theme, frame: LayoutFrame) -> str:
        """One flex column holding a header's eyebrow, title and subtitle."""
        if len(run) == 1:
            return self._text_placement(run[0], theme, frame)

        first, last = run[0], run[-1]
        box = first.box
        # min-height, not height: the group must be free to grow when the real
        # font wraps further than the estimate predicted.
        height = max(last.box.bottom - first.box.y, first.box.height)
        justify = {"start": "flex-start", "center": "center", "end": "flex-end"}[first.valign]
        blocks = "".join(self._text_block(text, theme, frame) for text in run)
        return (
            f'<div class="df-abs df-text-group" style="left:{u(box.x)};top:{u(box.y)};'
            f"width:{u(box.width)};min-height:{u(height)};justify-content:{justify};"
            f'gap:{u(theme.spacing.tight_gap)};">{blocks}</div>'
        )

    def _text_block(self, text: TextPlacement, theme: Theme, frame: LayoutFrame) -> str:
        """A single styled paragraph, sized by its own content."""
        style = theme.type_scale.get(text.role)
        align = {"start": "left", "center": "center", "end": "right", "justify": "justify"}[
            text.align.value
        ]
        muted = " df-muted" if style.color == "text_muted" else ""
        return (
            f'<p class="df-text{muted}" data-role="{text.role}" '
            f'style="{self._type_css(style, theme, invert=frame.invert_text)}text-align:{align};">'
            f"{inline_markdown(text.text)}</p>"
        )

    def _text_placement(self, text: TextPlacement, theme: Theme, frame: LayoutFrame) -> str:
        return (
            f'<div class="df-abs df-text-block" style="{self._box_css(text)}">'
            f"{self._text_block(text, theme, frame)}</div>"
        )

    # -- elements ----------------------------------------------------------- #

    def _element_placement(
        self, placement: ElementPlacement, theme: Theme, frame: LayoutFrame
    ) -> str:
        inner = self._element_html(
            placement.element,
            placement.box.width,
            placement.box.height,
            theme.type_scaled(placement.scale),
            frame,
        )
        z = f"z-index:{placement.z};" if placement.z else ""
        return (
            f'<div class="df-abs df-el" data-element-id="{placement.element.id}" '
            f'data-type="{placement.element.type}" style="{self._box_css(placement)}{z}">'
            f"{inner}</div>"
        )

    def _element_html(
        self, element: Element, width: float, height: float, theme: Theme, frame: LayoutFrame
    ) -> str:
        ts = theme.type_scale
        invert = frame.invert_text
        match element:
            case TextElement():
                style = ts.get(str(element.role))
                align = {"start": "left", "center": "center", "end": "right", "justify": "justify"}[
                    element.align.value
                ]
                body = inline_markdown(element.text) if element.markdown else escape(element.text)
                muted = " df-muted" if style.color == "text_muted" else ""
                return (
                    f'<p class="df-text{muted}" style="'
                    f'{self._type_css(style, theme, invert=invert)}text-align:{align};">{body}</p>'
                )

            case BulletsElement():
                return self._bullets(element, theme, invert)

            case ImageElement():
                return self._image(element, theme)

            case IconElement():
                colour = theme.color(element.color or "primary")
                label = (
                    f'<span class="df-caption" style="{self._type_css(ts.caption, theme, invert=invert)}">'
                    f"{escape(element.label)}</span>"
                    if element.label
                    else ""
                )
                return (
                    f'<div style="display:flex;flex-direction:column;gap:{u(8)};align-items:flex-start;">'
                    f"{icons.icon_svg(element.name, colour, size=u(element.size), stroke=theme.icon_stroke)}"
                    f"{label}</div>"
                )

            case ChartElement():
                title = (
                    f'<p class="df-text df-muted" style="{self._type_css(ts.caption, theme, invert=invert)}'
                    f'margin-bottom:{u(6)};">{escape(element.title)}</p>'
                    if element.title
                    else ""
                )
                # Draw at the real slot size: deriving a height from the width
                # would letterbox the chart and shrink its labels.
                chart_h = max(140.0, height - (ts.caption.size * 2.2 if element.title else 0.0))
                drawing = charts.render_chart(element.chart, width, chart_h, theme)
                return f'{title}<div class="df-chart-wrap">{drawing_to_svg(drawing, theme)}</div>'

            case DiagramElement():
                return self._diagram(element, theme, invert, width, height)

            case TableElement():
                return self._table(element, theme, invert)

            case QuoteElement():
                return self._quote(element, theme, invert)

            case MetricElement():
                return self._metric(element, theme, invert)

            case CardsElement():
                return self._cards(element, theme, invert)

            case TimelineElement():
                return self._timeline(element, theme, invert)

            case CodeElement():
                return (
                    f'<div class="df-code" style="padding:{u(16)};">'
                    f'<pre style="{self._type_css(ts.code, theme, invert=False)}">'
                    f"<code>{escape(element.source)}</code></pre></div>"
                )

            case ShapeElement():
                colour = theme.color(element.color or "primary")
                radius = "999px" if element.shape == "ellipse" else u(element.radius)
                return (
                    f'<div style="width:100%;height:100%;background:{colour};'
                    f'opacity:{element.opacity};border-radius:{radius};"></div>'
                )

            case _:  # pragma: no cover - union is exhaustive
                return ""

    def _bullets(self, element: BulletsElement, theme: Theme, invert: bool) -> str:
        ts = theme.type_scale.bullet
        tokens = theme.bullets
        marker_glyph = MARKER_GLYPHS.get(
            element.bullet_style.value
            if element.bullet_style != BulletStyle.DOT
            else tokens.marker,
            MARKER_GLYPHS.get(tokens.marker, "•"),
        )
        rows: list[str] = []
        for i, item in enumerate(element.items):
            indent = tokens.indent * item.level
            if element.bullet_style is BulletStyle.NUMBER:
                marker = f"{i + 1}."
            elif element.bullet_style is BulletStyle.ICON or item.icon:
                marker = icons.icon_svg(
                    item.icon,
                    theme.color(tokens.marker_color),
                    size=u(ts.size * 0.95),
                    stroke=theme.icon_stroke,
                )
            elif element.bullet_style is BulletStyle.NONE:
                marker = ""
            else:
                marker = escape(marker_glyph)
            weight = 600 if item.emphasis else ts.weight
            rows.append(
                f'<li class="df-bullet" style="margin-left:{u(indent)};'
                f'margin-bottom:{u(tokens.row_gap)};">'
                f'<span class="df-marker" style="width:{u(tokens.indent * 0.8)};'
                f"height:{u(ts.size * ts.line_height)};font-size:{u(ts.size)};"
                f'color:{theme.color(tokens.marker_color)};">{marker}</span>'
                f'<span class="df-bullet-text" style="'
                f'{self._type_css(ts, theme, invert=invert)}font-weight:{weight};">'
                f"{inline_markdown(item.text)}</span></li>"
            )
        return f'<ul class="df-bullets">{"".join(rows)}</ul>'

    def _image(self, element: ImageElement, theme: Theme) -> str:
        radius = u(element.radius) if element.radius is not None else "var(--df-image-radius)"
        caption = (
            f'<p class="df-caption" style="'
            f"{self._type_css(theme.type_scale.caption, theme, invert=False)}"
            f'margin-top:{u(8)};">{escape(element.caption)}</p>'
            if element.caption
            else ""
        )
        if not element.src:
            return (
                f'<div class="df-image-fallback" style="border-radius:{radius};">'
                f"{escape(element.alt or 'Image placeholder')}</div>{caption}"
            )
        fit = element.fit.value if element.fit != ImageFit.FILL else "fill"
        return (
            f'<div class="df-image-wrap" style="border-radius:{radius};">'
            f'<img class="df-image" src="{escape(element.src, quote=True)}" '
            f'alt="{escape(element.alt, quote=True)}" loading="lazy" '
            f'style="object-fit:{fit};border-radius:{radius};"/></div>{caption}'
        )

    def _diagram(
        self, element: DiagramElement, theme: Theme, invert: bool, width: float, height: float
    ) -> str:
        # A flowchart we can parse is drawn as a real diagram; anything else
        # keeps its source, which is honest rather than wrong.
        drawing = diagrams.render_diagram(element, width, height, theme)
        if drawing is not None:
            caption = (
                f'<p class="df-caption" style="'
                f"{self._type_css(theme.type_scale.caption, theme, invert=invert)}"
                f'margin-top:{u(6)};text-align:center;">{escape(element.caption)}</p>'
                if element.caption
                else ""
            )
            return f'<div class="df-diagram-figure">{drawing_to_svg(drawing, theme)}</div>{caption}'

        if element.rendered_asset_id:
            return (
                f'<div class="df-diagram">'
                f'<img class="df-image" src="/api/v1/assets/{element.rendered_asset_id}/content" '
                f'alt="{escape(element.caption or "Diagram", quote=True)}" '
                f'style="object-fit:contain;"/></div>'
            )
        # Left as source: the app renders Mermaid client-side, and viewers without
        # a Mermaid runtime still see readable, copyable diagram code.
        return (
            f'<div class="df-diagram" style="padding:{u(16)};">'
            f'<pre class="{element.engine.value}" style="'
            f'{self._type_css(theme.type_scale.code, theme, invert=False)}">'
            f"{escape(element.source)}</pre></div>"
        )

    def _table(self, element: TableElement, theme: Theme, invert: bool) -> str:
        ts = theme.type_scale.table
        cell = f"padding:{u(ts.size * 0.66)} {u(ts.size * 0.5)};"
        widths = ""
        if element.column_widths and len(element.column_widths) == len(element.columns):
            total = sum(element.column_widths) or 1
            widths = "".join(
                f'<col style="width:{100 * w / total:.1f}%"/>' for w in element.column_widths
            )
        head = ""
        if element.header and element.columns:
            cells = "".join(
                f'<th style="{cell}{self._type_css(ts, theme, invert=invert)}font-weight:600;">'
                f"{inline_markdown(c)}</th>"
                for c in element.columns
            )
            head = f"<thead><tr>{cells}</tr></thead>"
        rows = []
        for i, row in enumerate(element.rows):
            stripe = ' class="df-stripe"' if element.striped and i % 2 else ""
            cells = "".join(
                f'<td style="{cell}{self._type_css(ts, theme, invert=invert)}">'
                f"{inline_markdown(c)}</td>"
                for c in row
            )
            rows.append(f"<tr{stripe}>{cells}</tr>")
        return f'<table class="df-table">{widths}{head}<tbody>{"".join(rows)}</tbody></table>'

    def _quote(self, element: QuoteElement, theme: Theme, invert: bool) -> str:
        ts = theme.type_scale
        attribution = ""
        if element.attribution:
            role = f" · {escape(element.role)}" if element.role else ""
            attribution = (
                f'<footer class="df-muted" style="'
                f'{self._type_css(ts.caption, theme, invert=invert)}margin-top:{u(18)};">'
                f"— {escape(element.attribution)}{role}</footer>"
            )
        return (
            f'<blockquote class="df-quote" style="margin:0;">'
            f'<span class="df-quote-mark" style="font-size:{u(ts.quote.size * 1.6)};'
            f'font-family:{theme.font_family("heading")};">&ldquo;</span>'
            f'<p class="df-text" style="{self._type_css(ts.quote, theme, invert=invert)}">'
            f"{inline_markdown(element.text)}</p>{attribution}</blockquote>"
        )

    def _metric(self, element: MetricElement, theme: Theme, invert: bool) -> str:
        ts = theme.type_scale
        delta = ""
        if element.delta:
            cls = {"up": "df-delta-up", "down": "df-delta-down"}.get(
                element.trend or "", "df-muted"
            )
            delta = (
                f'<span class="{cls}" style="{self._type_css(ts.metric_label, theme, invert=invert)}'
                f'font-weight:600;">{escape(element.delta)}</span>'
            )
        icon = (
            f'<span style="display:block;margin-bottom:{u(8)};">'
            f"{icons.icon_svg(element.icon, theme.palette.primary, size=u(30), stroke=theme.icon_stroke)}"
            f"</span>"
            if element.icon
            else ""
        )
        return (
            f'<div class="df-metric">{icon}'
            f'<span style="{self._type_css(ts.metric_value, theme, invert=False)}">'
            f"{escape(element.value)}</span>"
            f'<span class="df-muted" style="{self._type_css(ts.metric_label, theme, invert=invert)}'
            f'margin-top:{u(4)};">{escape(element.label)}</span>{delta}</div>'
        )

    def _cards(self, element: CardsElement, theme: Theme, invert: bool) -> str:
        ts = theme.type_scale
        pad = theme.spacing.card_padding
        cells: list[str] = []
        for card in element.cards:
            accent = theme.color(card.accent or "primary")
            icon = (
                f'<span style="display:block;margin-bottom:{u(10)};">'
                f"{icons.icon_svg(card.icon, accent, size=u(30), stroke=theme.icon_stroke)}</span>"
                if card.icon
                else ""
            )
            badge = (
                f'<span style="align-self:flex-start;background:{colors.with_alpha(accent, 0.14)};'
                f"color:{accent};border-radius:999px;padding:{u(4)} {u(10)};"
                f'font-size:{u(12)};font-weight:600;margin-bottom:{u(8)};">'
                f"{escape(card.badge)}</span>"
                if card.badge
                else ""
            )
            body = (
                f'<p class="df-text df-muted" style="'
                f'{self._type_css(ts.card_body, theme, invert=False)}margin-top:{u(6)};">'
                f"{inline_markdown(card.body)}</p>"
                if card.body
                else ""
            )
            cells.append(
                f'<div class="df-card" style="padding:{u(pad)};border-top:{u(3)} solid {accent};">'
                f'{badge}{icon}<p class="df-text" style="'
                f'{self._type_css(ts.card_title, theme, invert=False)}">{escape(card.title)}</p>'
                f"{body}</div>"
            )
        columns = max(1, min(element.columns, len(element.cards) or 1))
        return (
            f'<div class="df-cards" style="grid-template-columns:repeat({columns},1fr);'
            f'gap:{u(theme.spacing.gap)};">{"".join(cells)}</div>'
        )

    def _timeline(self, element: TimelineElement, theme: Theme, invert: bool) -> str:
        ts = theme.type_scale
        horizontal = element.orientation == "horizontal"
        items: list[str] = []
        for entry in element.entries:
            colour = theme.color(
                "primary"
                if entry.status in (None, "active")
                else ("success" if entry.status == "done" else "text_muted")
            )
            marker = (
                f'<span class="df-tl-dot" style="width:{u(14)};height:{u(14)};background:{colour};'
                f'margin:{u(0)} {u(10)} {u(10)} 0;"></span>'
            )
            body = (
                f'<p class="df-text df-muted" style="'
                f'{self._type_css(ts.card_body, theme, invert=invert)}">{escape(entry.body)}</p>'
                if entry.body
                else ""
            )
            items.append(
                f'<div class="df-tl-item" style="padding-right:{u(theme.spacing.gap)};">'
                f'<div style="display:flex;align-items:center;">{marker}'
                f'<span style="{self._type_css(ts.eyebrow, theme, invert=invert)}color:{colour};">'
                f"{escape(entry.label)}</span></div>"
                f'<p class="df-text" style="{self._type_css(ts.card_title, theme, invert=invert)}'
                f'margin-top:{u(8)};">{escape(entry.title)}</p>{body}</div>'
            )
        rail = (
            f'<div class="df-tl-rail" style="left:0;right:0;top:{u(7)};height:{u(2)};"></div>'
            if horizontal
            else f'<div class="df-tl-rail" style="top:0;bottom:0;left:{u(6)};width:{u(2)};"></div>'
        )
        direction = "df-timeline-h" if horizontal else "df-timeline-v"
        return (
            f'<div class="df-timeline {direction}" style="position:relative;gap:{u(theme.spacing.gap)};">'
            f"{rail}{''.join(items)}</div>"
        )

    # -- misc --------------------------------------------------------------- #

    def slide_summary(self, deck: Presentation, theme: Theme) -> list[dict[str, Any]]:
        """Lightweight per-slide metadata for the thumbnail rail."""
        plan = self.layouts.plan(deck, theme)
        return [
            {
                "id": slide.id,
                "index": i,
                "title": slide.title,
                "kind": str(slide.kind),
                "layout": plan.get(slide.id, slide.layout),
                "words": slide.word_count(),
                "has_notes": bool(slide.notes.strip()),
            }
            for i, slide in enumerate(deck.slides)
        ]
