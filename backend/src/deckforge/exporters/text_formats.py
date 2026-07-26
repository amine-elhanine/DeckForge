"""Text-based exporters: HTML, Markdown, Reveal.js and Marp.

They share one traversal of the deck; only the serialisation differs.
"""

from __future__ import annotations

from html import escape

from deckforge.exporters.base import ExportContext, Exporter
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
    Presentation,
    QuoteElement,
    Slide,
    TableElement,
    TextElement,
    TimelineElement,
)
from deckforge.models.enums import SlideKind

# --------------------------------------------------------------------------- #
# Markdown serialisation, shared by Markdown and Marp
# --------------------------------------------------------------------------- #


def element_to_markdown(element: Element) -> str:
    """Serialise one element as Markdown."""
    match element:
        case TextElement():
            return element.text
        case BulletsElement():
            return "\n".join(f"{'  ' * i.level}- {i.text}" for i in element.items)
        case ImageElement():
            caption = f"\n\n*{element.caption}*" if element.caption else ""
            return f"![{element.alt or 'image'}]({element.src}){caption}"
        case IconElement():
            return f"**{element.label}**" if element.label else ""
        case QuoteElement():
            attribution = f"\n>\n> — {element.attribution}" if element.attribution else ""
            return f"> {element.text}{attribution}"
        case MetricElement():
            delta = f" ({element.delta})" if element.delta else ""
            return f"**{element.value}**{delta} — {element.label}"
        case CardsElement():
            return "\n\n".join(
                f"**{c.title}**  \n{c.body}" for c in element.cards if c.title or c.body
            )
        case TimelineElement():
            return "\n".join(
                f"- **{e.label}** — {e.title}" + (f": {e.body}" if e.body else "")
                for e in element.entries
            )
        case TableElement():
            if not element.columns:
                return ""
            head = "| " + " | ".join(element.columns) + " |"
            rule = "| " + " | ".join("---" for _ in element.columns) + " |"
            body = "\n".join("| " + " | ".join(r) + " |" for r in element.rows)
            return f"{head}\n{rule}\n{body}"
        case CodeElement():
            return f"```{element.language}\n{element.source}\n```"
        case ChartElement():
            lines = [f"**{element.title or 'Chart'}** ({element.chart.kind})"]
            if element.chart.categories:
                lines.append("")
                lines.append(
                    "| Category | " + " | ".join(s.name for s in element.chart.series) + " |"
                )
                lines.append("| --- | " + " | ".join("---" for _ in element.chart.series) + " |")
                for i, category in enumerate(element.chart.categories):
                    values = [
                        f"{s.values[i]:g}" if i < len(s.values) else ""
                        for s in element.chart.series
                    ]
                    lines.append(f"| {category} | " + " | ".join(values) + " |")
            return "\n".join(lines)
        case DiagramElement():
            return f"```{element.engine}\n{element.source}\n```"
        case _:
            return ""


def slide_to_markdown(slide: Slide, index: int, *, include_notes: bool = True) -> str:
    """Serialise one slide as a Markdown block."""
    lines: list[str] = []
    heading = "#" if slide.kind in (SlideKind.COVER, SlideKind.SECTION) else "##"
    if slide.eyebrow:
        lines.append(f"*{slide.eyebrow}*")
    lines.append(f"{heading} {slide.title or f'Slide {index + 1}'}")
    if slide.subtitle:
        lines.append(f"\n_{slide.subtitle}_")
    for element in slide.elements:
        if element.hidden:
            continue
        block = element_to_markdown(element).strip()
        if block:
            lines.append("")
            lines.append(block)
    if include_notes and slide.notes:
        lines.append("")
        lines.append("<!-- Speaker notes:")
        lines.append(slide.notes.strip())
        lines.append("-->")
    if slide.references:
        lines.append("")
        lines.extend(f"[^{i + 1}]: {r.format_apa()}" for i, r in enumerate(slide.references))
    return "\n".join(lines).strip()


class MarkdownExporter(Exporter):
    """Plain Markdown, one ``---`` separated block per slide."""

    name = "markdown"
    label = "Markdown"
    extension = "md"
    media_type = "text/markdown; charset=utf-8"
    binary = False
    description = "Portable Markdown with speaker notes as HTML comments."

    def render(self, deck: Presentation, context: ExportContext) -> bytes:
        include_notes = bool(context.option("include_notes", True))
        head = [f"# {deck.title}"]
        if deck.subtitle:
            head.append(f"\n_{deck.subtitle}_")
        if deck.description:
            head.append(f"\n{deck.description}")
        blocks = [
            slide_to_markdown(slide, i, include_notes=include_notes)
            for i, slide in enumerate(deck.slides)
        ]
        if deck.references:
            blocks.append(
                "## References\n\n" + "\n".join(f"- {r.format_apa()}" for r in deck.references)
            )
        body = "\n\n---\n\n".join(blocks)
        return f"{chr(10).join(head)}\n\n---\n\n{body}\n".encode()


class MarpExporter(Exporter):
    """Marp-flavoured Markdown with front matter and per-slide directives."""

    name = "marp"
    label = "Marp"
    extension = "md"
    media_type = "text/markdown; charset=utf-8"
    binary = False
    description = "Marp CLI compatible Markdown (`marp deck.md --pdf`)."

    def filename_for(self, deck: Presentation) -> str:
        from deckforge.utils.text import slugify

        return f"{slugify(deck.title) or 'presentation'}.marp.md"

    def render(self, deck: Presentation, context: ExportContext) -> bytes:
        theme = context.theme
        front_matter = "\n".join(
            [
                "---",
                "marp: true",
                "paginate: true",
                f"title: {deck.title}",
                f"backgroundColor: {theme.palette.background}",
                f"color: {theme.palette.text}",
                "style: |",
                f"  section {{ font-family: {theme.fonts.body}, sans-serif; }}",
                f"  h1, h2 {{ color: {theme.palette.heading or theme.palette.text}; "
                f"font-family: {theme.fonts.heading}, sans-serif; }}",
                f"  strong {{ color: {theme.palette.primary}; }}",
                "---",
                "",
            ]
        )
        blocks: list[str] = []
        for i, slide in enumerate(deck.slides):
            directives = []
            if slide.kind in (SlideKind.COVER, SlideKind.SECTION, SlideKind.ENDING):
                directives.append("<!-- _class: lead -->")
            block = slide_to_markdown(slide, i, include_notes=False)
            if slide.notes:
                block += f"\n\n<!--\n{slide.notes.strip()}\n-->"
            blocks.append("\n".join([*directives, block]))
        return (front_matter + "\n\n---\n\n".join(blocks) + "\n").encode()


class HtmlExporter(Exporter):
    """A single self-contained HTML file using the reference renderer."""

    name = "html"
    label = "HTML"
    extension = "html"
    media_type = "text/html; charset=utf-8"
    binary = False
    description = "Scrollable, print-ready HTML that matches the in-app preview exactly."

    def render(self, deck: Presentation, context: ExportContext) -> bytes:
        html = context.renderer.render_document(
            deck,
            context.theme,
            standalone=True,
            include_notes=bool(context.option("include_notes", False)),
        )
        return html.encode("utf-8")


class RevealJsExporter(Exporter):
    """Reveal.js deck.

    Reveal's runtime is loaded from a local ``reveal.js`` path by default so the
    export stays offline-first; pass ``{"cdn": true}`` to use a CDN instead.
    """

    name = "revealjs"
    label = "Reveal.js"
    extension = "html"
    media_type = "text/html; charset=utf-8"
    binary = False
    description = "Interactive Reveal.js presentation with speaker notes."

    CDN_BASE = "https://cdn.jsdelivr.net/npm/reveal.js@5"

    def filename_for(self, deck: Presentation) -> str:
        from deckforge.utils.text import slugify

        return f"{slugify(deck.title) or 'presentation'}.reveal.html"

    def render(self, deck: Presentation, context: ExportContext) -> bytes:
        theme = context.theme
        renderer = context.renderer
        base = (
            self.CDN_BASE
            if context.option("cdn", False)
            else context.option("reveal_base", "./reveal.js")
        )
        frames = renderer.layouts.resolve_deck(deck, theme)
        sections: list[str] = []
        for i, (slide, frame) in enumerate(zip(deck.slides, frames, strict=True)):
            inner = renderer.render_slide(slide, theme, frame, index=i)
            notes = f'<aside class="notes">{escape(slide.notes)}</aside>' if slide.notes else ""
            sections.append(f"<section>{inner}{notes}</section>")

        return f"""<!doctype html>
<html lang="{escape(deck.meta.language or "en")}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{escape(deck.title)}</title>
<link rel="stylesheet" href="{base}/dist/reveal.css"/>
<style>
{renderer.stylesheet(theme)}
.reveal .slides section{{padding:0;height:100%}}
.reveal .df-stage{{box-shadow:none;border-radius:0;height:100%}}
.reveal .df-notes{{display:none}}
{theme.css}
</style>
</head>
<body class="df-mode-{theme.mode}">
<div class="reveal"><div class="slides">
{chr(10).join(sections)}
</div></div>
<script src="{base}/dist/reveal.js"></script>
<script src="{base}/plugin/notes/notes.js"></script>
<script>Reveal.initialize({{hash:true,width:1280,height:720,margin:0,plugins:[RevealNotes]}});</script>
</body>
</html>
""".encode()
