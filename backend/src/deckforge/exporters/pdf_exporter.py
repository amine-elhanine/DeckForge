"""PDF exporter built on fpdf2.

fpdf2 is pure Python, so PDF export works with no headless browser, no
LibreOffice and no system libraries — which is what makes "fully local" true on
Windows as well as Linux.

The exporter replays the same layout frames and chart primitives the HTML
renderer uses, so page geometry matches the preview.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import cast

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from deckforge.core.errors import ExportError
from deckforge.core.logging import get_logger
from deckforge.exporters.base import ExportContext, Exporter
from deckforge.layouts import measure
from deckforge.layouts.model import DecorPlacement, ElementPlacement, LayoutFrame, TextPlacement
from deckforge.models.deck import (
    Background,
    Box,
    BulletsElement,
    CardsElement,
    ChartElement,
    CodeElement,
    DiagramElement,
    IconElement,
    ImageElement,
    MetricElement,
    Presentation,
    QuoteElement,
    ShapeElement,
    TableElement,
    TextElement,
    TimelineElement,
)
from deckforge.models.enums import Align, BackgroundKind, BulletStyle
from deckforge.renderers import charts, diagrams, icons
from deckforge.renderers.html import MARKER_GLYPHS
from deckforge.renderers.inline import plain
from deckforge.renderers.paths import flatten_path, scale_subpaths
from deckforge.renderers.primitives import (
    Drawing,
    Ellipse,
    Label,
    Line,
    Polyline,
    Rect,
    Wedge,
)
from deckforge.themes.model import Theme, TypeStyle
from deckforge.utils import colors

log = get_logger(__name__)

PT = 0.75
"""Points per logical canvas unit."""

ALIGN_MAP = {Align.START: "L", Align.CENTER: "C", Align.END: "R", Align.JUSTIFY: "J"}


def _rgb(value: str) -> tuple[int, int, int]:
    try:
        return colors.to_rgb_tuple(value)
    except ValueError:
        return (17, 19, 24)


class PdfExporter(Exporter):
    """Renders a deck to a paginated PDF, one page per slide."""

    name = "pdf"
    label = "PDF"
    extension = "pdf"
    media_type = "application/pdf"
    binary = True
    description = "Print-ready PDF rendered locally — no browser or Office install required."

    def render(self, deck: Presentation, context: ExportContext) -> bytes:
        theme = context.theme
        canvas_w, canvas_h = deck.canvas
        pdf = FPDF(orientation="landscape", unit="pt", format=(canvas_w * PT, canvas_h * PT))
        pdf.set_auto_page_break(False)
        pdf.set_title(deck.title)
        pdf.set_creator("DeckForge")
        if deck.meta.extra.get("author"):
            pdf.set_author(str(deck.meta.extra["author"]))

        self._register_fonts(pdf, context)

        frames = context.renderer.layouts.resolve_deck(deck, theme)
        for slide_model, frame in zip(deck.slides, frames, strict=True):
            if slide_model.hidden and not context.option("include_hidden", False):
                continue
            pdf.add_page()
            self._background(pdf, frame.background, theme, canvas_w, canvas_h)
            for decoration in frame.decor:
                self._decor(pdf, decoration)
            # Backdrops (z < 0) go down first so titles stay legible on top of them.
            for placement in (p for p in frame.elements if p.z < 0):
                self._element(pdf, placement, theme, frame, context)
            for text in frame.texts:
                self._text_placement(pdf, text, theme, frame)
            for placement in (p for p in frame.elements if p.z >= 0):
                self._element(pdf, placement, theme, frame, context)

        try:
            return bytes(pdf.output())
        except Exception as exc:  # pragma: no cover - fpdf internal failure
            raise ExportError(f"PDF generation failed: {exc}") from exc

    # -- fonts --------------------------------------------------------------- #

    def _register_fonts(self, pdf: FPDF, context: ExportContext) -> None:
        """Register a Unicode TTF when one is configured; otherwise use core fonts.

        Core PDF fonts are Latin-1 only. Supplying ``{"font_path": "..."}`` (or
        dropping a ``fonts/`` directory next to the assets) unlocks full Unicode,
        which matters for non-Latin decks.
        """
        self._unicode = False
        candidates: list[Path] = []
        configured = context.option("font_path")
        if configured:
            candidates.append(Path(configured))
        if context.assets_dir is not None:
            candidates.extend(sorted((context.assets_dir / "fonts").glob("*.ttf")))

        for path in candidates:
            if not path.is_file():
                continue
            try:
                pdf.add_font("deck", "", str(path))
                pdf.add_font("deck", "B", str(path))
                self._unicode = True
                return
            except Exception as exc:  # pragma: no cover - font specific
                log.warning("pdf.font_failed", path=str(path), error=str(exc))

    def _font(self, pdf: FPDF, style: TypeStyle, theme: Theme, *, bold: bool = False) -> None:
        family = "deck" if self._unicode else ("courier" if style.font == "mono" else "helvetica")
        weight = "B" if (bold or style.weight >= 600) else ""
        pdf.set_font(family, weight, style.size * PT)

    def _encode(self, text: str) -> str:
        if self._unicode:
            return text
        return text.encode("latin-1", "replace").decode("latin-1")

    # -- background & decoration --------------------------------------------- #

    def _background(
        self, pdf: FPDF, background: Background, theme: Theme, width: float, height: float
    ) -> None:
        match background.kind:
            case BackgroundKind.NONE:
                return
            case BackgroundKind.GRADIENT | BackgroundKind.MESH:
                stops = background.colors or [theme.palette.background, theme.palette.surface]
                bands = 96
                start, end = _rgb(stops[0]), _rgb(stops[-1])
                band_h = height * PT / bands
                for i in range(bands):
                    ratio = i / (bands - 1)
                    pdf.set_fill_color(
                        *[int(start[c] + (end[c] - start[c]) * ratio) for c in range(3)]
                    )
                    pdf.rect(0, i * band_h, width * PT, band_h + 0.6, style="F")
            case BackgroundKind.IMAGE if background.image:
                try:
                    pdf.image(background.image, 0, 0, width * PT, height * PT)
                except Exception:  # pragma: no cover - remote or missing image
                    pdf.set_fill_color(*_rgb(theme.palette.background))
                    pdf.rect(0, 0, width * PT, height * PT, style="F")
            case _:
                pdf.set_fill_color(*_rgb(background.color or theme.palette.background))
                pdf.rect(0, 0, width * PT, height * PT, style="F")

    def _decor(self, pdf: FPDF, decoration: DecorPlacement) -> None:
        b = decoration.box
        pdf.set_fill_color(*_rgb(decoration.color))
        with pdf.local_context(fill_opacity=decoration.opacity, stroke_opacity=decoration.opacity):
            match decoration.kind:
                case "rect" | "rule":
                    pdf.rect(b.x * PT, b.y * PT, b.width * PT, b.height * PT, style="F")
                case "ellipse":
                    pdf.ellipse(b.x * PT, b.y * PT, b.width * PT, b.height * PT, style="F")
                case "triangle":
                    pdf.polygon(
                        [
                            (b.right * PT, b.y * PT),
                            (b.right * PT, b.bottom * PT),
                            (b.x * PT, b.bottom * PT),
                        ],
                        style="F",
                    )
                case "diagonal":
                    pdf.polygon(
                        [
                            (b.x * PT, b.y * PT),
                            (b.right * PT, b.y * PT),
                            (b.right * PT, b.bottom * PT),
                        ],
                        style="F",
                    )
                case _:
                    return

    # -- text ---------------------------------------------------------------- #

    def _write_text(
        self,
        pdf: FPDF,
        text: str,
        box: Box,
        style: TypeStyle,
        theme: Theme,
        *,
        invert: bool,
        align: Align = Align.START,
        valign: str = "start",
    ) -> float:
        """Write wrapped text into ``box``; returns the height consumed."""
        if not text:
            return 0.0
        content = plain(text)
        if style.transform == "uppercase":
            content = content.upper()
        self._font(pdf, style, theme)
        colour = (
            "#ffffff" if invert and style.color in ("text", "heading") else theme.color(style.color)
        )
        pdf.set_text_color(*_rgb(colour))
        line_height = style.size * style.line_height * PT

        y = box.y * PT
        if valign in ("center", "end"):
            # A dry run measures the wrapped text without drawing it.
            lines = cast(
                "list[str]",
                pdf.multi_cell(
                    box.width * PT,
                    line_height,
                    self._encode(content),
                    dry_run=True,
                    output="LINES",
                ),
            )
            used = len(lines) * line_height
            if valign == "center":
                y += max(0.0, (box.height * PT - used) / 2)
            else:
                y += max(0.0, box.height * PT - used)

        pdf.set_xy(box.x * PT, y)
        pdf.multi_cell(
            box.width * PT,
            line_height,
            self._encode(content),
            align=ALIGN_MAP[align],
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        return pdf.get_y() - y

    def _text_placement(
        self, pdf: FPDF, placement: TextPlacement, theme: Theme, frame: LayoutFrame
    ) -> None:
        self._write_text(
            pdf,
            placement.text,
            placement.box,
            theme.type_scale.get(placement.role),
            theme,
            invert=frame.invert_text,
            align=placement.align,
            valign=placement.valign,
        )

    # -- elements ------------------------------------------------------------- #

    def _element(
        self,
        pdf: FPDF,
        placement: ElementPlacement,
        theme: Theme,
        frame: LayoutFrame,
        context: ExportContext,
    ) -> None:
        element, box = placement.element, placement.box
        invert = frame.invert_text
        # The layout may have shrunk the type to fit; every size below follows it.
        theme = theme.type_scaled(placement.scale)
        ts = theme.type_scale

        match element:
            case TextElement():
                self._write_text(
                    pdf,
                    element.text,
                    box,
                    ts.get(str(element.role)),
                    theme,
                    invert=invert,
                    align=element.align,
                    valign=placement.valign,
                )

            case BulletsElement():
                self._bullets(pdf, element, box, theme, invert=invert)

            case ImageElement():
                self._image(pdf, element, box, theme, context)

            case IconElement():
                self._icon(
                    pdf,
                    element.name,
                    box.x,
                    box.y,
                    element.size,
                    theme.color(element.color or "primary"),
                    theme,
                )
                if element.label:
                    self._write_text(
                        pdf,
                        element.label,
                        Box(
                            x=box.x,
                            y=box.y + element.size * 1.25,
                            width=box.width,
                            height=max(20.0, ts.caption.size * 2),
                        ),
                        ts.caption,
                        theme,
                        invert=invert,
                    )

            case ChartElement():
                if element.title:
                    self._write_text(
                        pdf,
                        element.title,
                        Box(x=box.x, y=box.y, width=box.width, height=26),
                        ts.caption,
                        theme,
                        invert=invert,
                    )
                    box = Box(
                        x=box.x, y=box.y + 28, width=box.width, height=max(60.0, box.height - 28)
                    )
                drawing = charts.render_chart(element.chart, box.width, box.height, theme)
                self._draw(pdf, drawing.translated(box.x, box.y), theme)

            case TableElement():
                self._table(pdf, element, box, theme, invert=invert)

            case QuoteElement():
                consumed = self._write_text(
                    pdf,
                    f"“{element.text}”",
                    box,
                    ts.quote,
                    theme,
                    invert=invert,
                    valign="center" if placement.valign == "center" else "start",
                )
                if element.attribution:
                    role = f" · {element.role}" if element.role else ""
                    self._write_text(
                        pdf,
                        f"— {element.attribution}{role}",
                        Box(x=box.x, y=box.y + consumed / PT + 10, width=box.width, height=30),
                        ts.caption,
                        theme,
                        invert=invert,
                    )

            case MetricElement():
                y = box.y + max(0.0, (box.height - ts.metric_value.size * 2.4) / 2)
                self._write_text(
                    pdf,
                    element.value,
                    Box(x=box.x, y=y, width=box.width, height=ts.metric_value.size * 1.3),
                    ts.metric_value,
                    theme,
                    invert=False,
                )
                self._write_text(
                    pdf,
                    element.label,
                    Box(x=box.x, y=y + ts.metric_value.size * 1.25, width=box.width, height=40),
                    ts.metric_label,
                    theme,
                    invert=invert,
                )
                if element.delta:
                    token = {"up": "success", "down": "danger"}.get(
                        element.trend or "", "text_muted"
                    )
                    self._write_text(
                        pdf,
                        element.delta,
                        Box(
                            x=box.x,
                            y=y + ts.metric_value.size * 1.25 + ts.metric_label.size * 1.8,
                            width=box.width,
                            height=30,
                        ),
                        ts.metric_label.model_copy(update={"color": token}),
                        theme,
                        invert=False,
                    )

            case CardsElement():
                self._cards(pdf, element, box, theme)

            case TimelineElement():
                self._timeline(pdf, element, box, theme, invert=invert)

            case CodeElement():
                self._panel(pdf, box, theme)
                self._write_text(
                    pdf, element.source, box.inset(16, 14), ts.code, theme, invert=False
                )

            case DiagramElement():
                # Draw the flowchart itself when we can parse it.
                flowchart = diagrams.render_diagram(element, box.width, box.height, theme)
                if flowchart is not None:
                    self._draw(pdf, flowchart.translated(box.x, box.y), theme)
                    return

                rendered = (
                    context.resolve_asset(element.rendered_asset_id)
                    if element.rendered_asset_id
                    else None
                )
                self._panel(pdf, box, theme)
                if rendered is not None:
                    try:
                        pdf.image(
                            str(rendered), box.x * PT, box.y * PT, box.width * PT, box.height * PT
                        )
                        return
                    except Exception:  # pragma: no cover - image specific
                        pass
                self._write_text(
                    pdf, element.source, box.inset(16, 14), ts.code, theme, invert=False
                )

            case ShapeElement():
                pdf.set_fill_color(*_rgb(theme.color(element.color or "primary")))
                with pdf.local_context(fill_opacity=element.opacity):
                    if element.shape == "ellipse":
                        pdf.ellipse(box.x * PT, box.y * PT, box.width * PT, box.height * PT, "F")
                    else:
                        pdf.rect(box.x * PT, box.y * PT, box.width * PT, box.height * PT, "F")

            case _:
                return

    def _panel(self, pdf: FPDF, box: Box, theme: Theme) -> None:
        pdf.set_fill_color(*_rgb(theme.palette.surface))
        pdf.set_draw_color(*_rgb(theme.palette.border))
        pdf.set_line_width(theme.shape.border_width * PT)
        pdf.rect(box.x * PT, box.y * PT, box.width * PT, box.height * PT, style="DF")

    def _bullets(
        self, pdf: FPDF, element: BulletsElement, box: Box, theme: Theme, *, invert: bool
    ) -> None:
        style = theme.type_scale.bullet
        tokens = theme.bullets
        glyph = MARKER_GLYPHS.get(tokens.marker, "-")
        y = box.y
        for i, item in enumerate(element.items):
            indent = tokens.indent * (item.level + 1)
            if element.bullet_style is BulletStyle.NUMBER:
                marker = f"{i + 1}."
            elif element.bullet_style is BulletStyle.NONE:
                marker = ""
            else:
                marker = glyph
            if marker:
                self._write_text(
                    pdf,
                    marker,
                    Box(
                        x=box.x + tokens.indent * item.level,
                        y=y,
                        width=tokens.indent,
                        height=style.size * 1.4,
                    ),
                    style.model_copy(update={"color": tokens.marker_color}),
                    theme,
                    invert=False,
                )
            consumed = self._write_text(
                pdf,
                item.text,
                Box(
                    x=box.x + indent,
                    y=y,
                    width=max(60.0, box.width - indent),
                    height=max(20.0, box.bottom - y),
                ),
                style.model_copy(update={"weight": 600 if item.emphasis else style.weight}),
                theme,
                invert=invert,
            )
            y += consumed / PT + tokens.row_gap
            if y > box.bottom:
                break

    def _image(
        self, pdf: FPDF, element: ImageElement, box: Box, theme: Theme, context: ExportContext
    ) -> None:
        path = context.resolve_asset(element.src)
        if path is not None:
            try:
                pdf.image(str(path), box.x * PT, box.y * PT, box.width * PT, box.height * PT)
                return
            except Exception as exc:  # pragma: no cover - image specific
                log.warning("pdf.image_failed", path=str(path), error=str(exc))
        pdf.set_fill_color(*_rgb(theme.palette.surface))
        pdf.set_draw_color(*_rgb(theme.palette.border))
        pdf.rect(box.x * PT, box.y * PT, box.width * PT, box.height * PT, style="DF")
        self._write_text(
            pdf,
            element.alt or element.caption or "Image",
            box.inset(16, 16),
            theme.type_scale.caption,
            theme,
            invert=False,
            align=Align.CENTER,
            valign="center",
        )

    def _icon(
        self,
        pdf: FPDF,
        name: str | None,
        x: float,
        y: float,
        size: float,
        colour: str,
        theme: Theme,
    ) -> None:
        try:
            subpaths = scale_subpaths(flatten_path(icons.get_icon(name)), size, dx=x, dy=y)
        except Exception:  # pragma: no cover - malformed plugin icon
            return
        pdf.set_draw_color(*_rgb(colour))
        pdf.set_line_width(theme.icon_stroke * PT)
        for points in subpaths:
            for (x1, y1), (x2, y2) in pairwise(points):
                pdf.line(x1 * PT, y1 * PT, x2 * PT, y2 * PT)

    def _table(
        self, pdf: FPDF, element: TableElement, box: Box, theme: Theme, *, invert: bool
    ) -> None:
        columns = element.columns
        if not columns:
            return
        style = theme.type_scale.table
        col_w = box.width / len(columns)
        row_h = style.size * 2.4
        y = box.y

        if element.header:
            for c, label in enumerate(columns):
                self._write_text(
                    pdf,
                    label,
                    Box(x=box.x + c * col_w + 6, y=y + 6, width=col_w - 12, height=row_h),
                    style.model_copy(update={"weight": 700}),
                    theme,
                    invert=invert,
                )
            pdf.set_draw_color(*_rgb(theme.palette.primary))
            pdf.set_line_width(1.6 * PT)
            pdf.line(box.x * PT, (y + row_h) * PT, box.right * PT, (y + row_h) * PT)
            y += row_h

        pdf.set_line_width(0.8 * PT)
        for r, row in enumerate(element.rows):
            if y + row_h > box.bottom:
                break
            if element.striped and r % 2:
                pdf.set_fill_color(*_rgb(theme.palette.surface))
                pdf.rect(box.x * PT, y * PT, box.width * PT, row_h * PT, style="F")
            for c in range(len(columns)):
                value = row[c] if c < len(row) else ""
                self._write_text(
                    pdf,
                    value,
                    Box(x=box.x + c * col_w + 6, y=y + 5, width=col_w - 12, height=row_h),
                    style,
                    theme,
                    invert=invert,
                )
            pdf.set_draw_color(*_rgb(theme.palette.border))
            pdf.line(box.x * PT, (y + row_h) * PT, box.right * PT, (y + row_h) * PT)
            y += row_h

    def _cards(self, pdf: FPDF, element: CardsElement, box: Box, theme: Theme) -> None:
        from deckforge.layouts.builtin import grid_cells

        cells = grid_cells(box, len(element.cards), max(1, element.columns), theme.spacing.gap)
        for card, cell in zip(element.cards, cells, strict=True):
            accent = theme.color(card.accent or "primary")
            pdf.set_fill_color(*_rgb(theme.color(theme.shape.card_fill)))
            pdf.set_draw_color(*_rgb(theme.palette.border))
            pdf.set_line_width(theme.shape.border_width * PT)
            pdf.rect(cell.x * PT, cell.y * PT, cell.width * PT, cell.height * PT, style="DF")
            pdf.set_fill_color(*_rgb(accent))
            pdf.rect(cell.x * PT, cell.y * PT, cell.width * PT, 3 * PT, style="F")

            inner = cell.inset(theme.spacing.card_padding, theme.spacing.card_padding * 0.8)
            # Centred, to match the HTML preview and PPTX: a card taller than
            # its copy looks deliberate with the text in the middle.
            block = (36.0 if card.icon else 0.0) + measure.text_height(
                card.title, inner.width, theme.type_scale.card_title
            )
            if card.body:
                block += 6.0 + measure.text_height(
                    card.body, inner.width, theme.type_scale.card_body
                )
            y = inner.y + max(0.0, (inner.height - block) / 2)
            if card.icon:
                self._icon(pdf, card.icon, inner.x, y, 24, accent, theme)
                y += 36
            consumed = self._write_text(
                pdf,
                card.title,
                Box(x=inner.x, y=y, width=inner.width, height=40),
                theme.type_scale.card_title,
                theme,
                invert=False,
            )
            if card.body:
                self._write_text(
                    pdf,
                    card.body,
                    Box(
                        x=inner.x,
                        y=y + consumed / PT + 6,
                        width=inner.width,
                        height=max(20.0, inner.bottom - y - consumed / PT - 6),
                    ),
                    theme.type_scale.card_body,
                    theme,
                    invert=False,
                )

    def _timeline(
        self, pdf: FPDF, element: TimelineElement, box: Box, theme: Theme, *, invert: bool
    ) -> None:
        from deckforge.layouts.builtin import columns as split_columns
        from deckforge.layouts.builtin import rows as split_rows

        if not element.entries:
            return
        horizontal = element.orientation == "horizontal"
        cells = (
            split_columns(box, len(element.entries), theme.spacing.gap)
            if horizontal
            else split_rows(box, len(element.entries), theme.spacing.tight_gap)
        )
        pdf.set_fill_color(*_rgb(theme.palette.border))
        if horizontal:
            pdf.rect(box.x * PT, (box.y + 7) * PT, box.width * PT, 2 * PT, style="F")
        else:
            pdf.rect((box.x + 6) * PT, box.y * PT, 2 * PT, box.height * PT, style="F")

        for entry, cell in zip(element.entries, cells, strict=True):
            colour = theme.color(
                "success"
                if entry.status == "done"
                else ("text_muted" if entry.status == "planned" else "primary")
            )
            pdf.set_fill_color(*_rgb(colour))
            pdf.ellipse(cell.x * PT, cell.y * PT, 14 * PT, 14 * PT, style="F")
            y = cell.y + 26
            self._write_text(
                pdf,
                entry.label,
                Box(x=cell.x, y=y, width=max(50.0, cell.width - 12), height=24),
                theme.type_scale.eyebrow.model_copy(update={"color": colour}),
                theme,
                invert=False,
            )
            y += 22
            consumed = self._write_text(
                pdf,
                entry.title,
                Box(x=cell.x, y=y, width=max(50.0, cell.width - 12), height=40),
                theme.type_scale.card_title,
                theme,
                invert=invert,
            )
            if entry.body:
                self._write_text(
                    pdf,
                    entry.body,
                    Box(
                        x=cell.x,
                        y=y + consumed / PT + 4,
                        width=max(50.0, cell.width - 12),
                        height=max(20.0, cell.bottom - y - consumed / PT),
                    ),
                    theme.type_scale.card_body,
                    theme,
                    invert=invert,
                )

    # -- primitives ----------------------------------------------------------- #

    def _draw(self, pdf: FPDF, drawing: Drawing, theme: Theme) -> None:
        """Replay chart primitives as PDF drawing operations."""
        for item in drawing.items:
            match item:
                case Rect():
                    style = ""
                    if item.fill:
                        pdf.set_fill_color(*_rgb(item.fill))
                        style += "F"
                    if item.stroke:
                        pdf.set_draw_color(*_rgb(item.stroke))
                        pdf.set_line_width(item.stroke_width * PT)
                        style = "D" + style
                    if style:
                        with pdf.local_context(
                            fill_opacity=item.opacity, stroke_opacity=item.opacity
                        ):
                            pdf.rect(
                                item.x * PT,
                                item.y * PT,
                                max(0.1, item.width) * PT,
                                max(0.1, item.height) * PT,
                                style=style,
                            )
                case Ellipse():
                    if item.fill:
                        pdf.set_fill_color(*_rgb(item.fill))
                        with pdf.local_context(fill_opacity=item.opacity):
                            pdf.ellipse(
                                (item.cx - item.rx) * PT,
                                (item.cy - item.ry) * PT,
                                item.rx * 2 * PT,
                                item.ry * 2 * PT,
                                style="F",
                            )
                case Line():
                    pdf.set_draw_color(*_rgb(item.stroke))
                    pdf.set_line_width(max(0.2, item.stroke_width) * PT)
                    with pdf.local_context(stroke_opacity=item.opacity):
                        pdf.line(item.x1 * PT, item.y1 * PT, item.x2 * PT, item.y2 * PT)
                case Polyline():
                    points = [(x * PT, y * PT) for x, y in item.points]
                    if item.fill and item.closed:
                        pdf.set_fill_color(*_rgb(item.fill))
                        with pdf.local_context(fill_opacity=item.opacity):
                            pdf.polygon(points, style="F")
                    if item.stroke:
                        pdf.set_draw_color(*_rgb(item.stroke))
                        pdf.set_line_width(max(0.2, item.stroke_width) * PT)
                        with pdf.local_context(stroke_opacity=item.opacity):
                            for a, b in pairwise(points):
                                pdf.line(a[0], a[1], b[0], b[1])
                            if item.closed and len(points) > 2:
                                pdf.line(points[-1][0], points[-1][1], points[0][0], points[0][1])
                case Wedge():
                    pdf.set_fill_color(*_rgb(item.fill))
                    with pdf.local_context(fill_opacity=item.opacity):
                        pdf.polygon([(x * PT, y * PT) for x, y in item.outline()], style="F")
                case Label():
                    self._label(pdf, item, theme)

    def _label(self, pdf: FPDF, item: Label, theme: Theme) -> None:
        style = theme.type_scale.caption.model_copy(
            update={"size": item.size, "weight": item.weight, "font": item.family}
        )
        self._font(pdf, style, theme, bold=item.weight >= 600)
        pdf.set_text_color(*_rgb(item.color))
        text = self._encode(item.text)
        width = pdf.get_string_width(text)
        x = item.x * PT
        if item.anchor == "middle":
            x -= width / 2
        elif item.anchor == "end":
            x -= width
        y = item.y * PT
        if item.baseline == "middle":
            y -= item.size * PT * 0.36
        elif item.baseline == "bottom":
            y -= item.size * PT * 0.8
        if item.rotate:
            with pdf.rotation(-item.rotate, x, y):
                pdf.text(x, y + item.size * PT * 0.8, text)
        else:
            pdf.text(x, y + item.size * PT * 0.8, text)
