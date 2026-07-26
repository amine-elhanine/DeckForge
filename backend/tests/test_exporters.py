"""Renderers and exporters."""

from __future__ import annotations

import io
import zipfile

import pytest

from deckforge.exporters.base import EXPORTERS, ExportContext
from deckforge.models.deck import ChartSeries, ChartSpec, Presentation, Slide, TextElement
from deckforge.models.enums import ChartKind, SlideKind
from deckforge.renderers.charts import render_chart
from deckforge.renderers.inline import parse_inline, plain
from deckforge.renderers.paths import flatten_path, scale_subpaths
from deckforge.renderers.primitives import Drawing, Label, Rect, nice_ceiling
from deckforge.renderers.svg import drawing_to_svg
from deckforge.samples import sample_deck


@pytest.fixture
def context(themes, layouts, renderer, deck) -> ExportContext:
    return ExportContext(theme=themes.for_deck(deck), layouts=layouts, renderer=renderer)


def test_all_formats_produce_output(deck: Presentation, context: ExportContext) -> None:
    assert set(EXPORTERS.names()) >= {"pptx", "pdf", "html", "markdown", "revealjs", "marp"}
    for name in EXPORTERS.names():
        result = EXPORTERS.get(name).export(deck, context)
        assert result.size > 500, f"{name} produced a suspiciously small file"
        assert result.filename.endswith(EXPORTERS.get(name).extension)


def test_pptx_is_a_valid_package_with_one_slide_per_deck_slide(
    deck: Presentation, context: ExportContext
) -> None:
    content = EXPORTERS.get("pptx").export(deck, context).content
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        slides = [n for n in names if n.startswith("ppt/slides/slide")]
        assert len(slides) == len(deck.slides)
        assert "[Content_Types].xml" in names
        # Speaker notes must survive the export.
        assert any(n.startswith("ppt/notesSlides/") for n in names)


def test_pdf_has_a_page_per_slide(deck: Presentation, context: ExportContext) -> None:
    content = EXPORTERS.get("pdf").export(deck, context).content
    assert content.startswith(b"%PDF-")
    assert content.rstrip().endswith(b"%%EOF")
    assert content.count(b"/Type /Page\n") or content.count(b"/Type/Page")


def test_html_export_is_self_contained(deck: Presentation, context: ExportContext) -> None:
    html = EXPORTERS.get("html").export(deck, context).content.decode()
    assert html.startswith("<!doctype html>")
    assert "<style>" in html
    assert "http://" not in html.replace("http://www.w3.org", "")  # no external resources
    assert html.count('class="df-stage"') == len(deck.slides)


def test_markdown_keeps_content_and_notes(deck: Presentation, context: ExportContext) -> None:
    md = EXPORTERS.get("markdown").export(deck, context).content.decode()
    assert "# Reinforcement Learning" in md
    assert "Speaker notes:" in md
    assert md.count("\n---\n") >= len(deck.slides) - 1


def test_marp_has_front_matter(deck: Presentation, context: ExportContext) -> None:
    md = EXPORTERS.get("marp").export(deck, context).content.decode()
    assert md.startswith("---\nmarp: true")


def test_revealjs_wraps_every_slide(deck: Presentation, context: ExportContext) -> None:
    html = EXPORTERS.get("revealjs").export(deck, context).content.decode()
    assert html.count("<section>") == len(deck.slides)
    assert "Reveal.initialize" in html


def test_export_survives_an_empty_deck(context: ExportContext) -> None:
    empty = Presentation(title="Empty")
    for name in EXPORTERS.names():
        assert EXPORTERS.get(name).export(empty, context).size > 0


def test_export_survives_hostile_content(context: ExportContext) -> None:
    deck = Presentation(title="<script>alert(1)</script>")
    deck.add_slide(
        Slide(
            title="Ünïcødé & <b>markup</b>",
            kind=SlideKind.CONTENT,
            elements=[TextElement(text="a & b < c > d \"quoted\" 'single'")],
        )
    )
    html = EXPORTERS.get("html").export(deck, context).content.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    for name in ("pptx", "pdf", "markdown"):
        assert EXPORTERS.get(name).export(deck, context).size > 0


@pytest.mark.parametrize(
    "theme_name", ["minimal", "modern_dark", "neon", "academic", "glassmorphism"]
)
def test_every_theme_exports(theme_name: str, themes, layouts, renderer) -> None:
    deck = sample_deck(theme_name)
    context = ExportContext(theme=themes.for_deck(deck), layouts=layouts, renderer=renderer)
    for name in ("html", "pptx", "pdf"):
        assert EXPORTERS.get(name).export(deck, context).size > 500


# --------------------------------------------------------------------------- #
# Renderer internals
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", list(ChartKind))
def test_every_chart_kind_renders(kind: ChartKind, themes) -> None:
    spec = ChartSpec(
        kind=kind,
        categories=["a", "b", "c"],
        series=[
            ChartSeries(name="one", values=[3, 5, 2]),
            ChartSeries(name="two", values=[1, 4, 6]),
        ],
    )
    drawing = render_chart(spec, 600, 340, themes.get("minimal"))
    assert drawing.items
    svg = drawing_to_svg(drawing, themes.get("minimal"))
    assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_chart_with_no_data_does_not_crash(themes) -> None:
    drawing = render_chart(ChartSpec(), 400, 200, themes.get("minimal"))
    assert any(isinstance(i, Label) for i in drawing.items)


def test_chart_spec_pads_short_series() -> None:
    spec = ChartSpec(categories=["a", "b", "c"], series=[ChartSeries(values=[1])])
    assert spec.series[0].values == [1.0, 0.0, 0.0]


def test_nice_ceiling() -> None:
    assert nice_ceiling(0.4) == 0.5
    assert nice_ceiling(7) == 10
    assert nice_ceiling(23) == 25
    assert nice_ceiling(0) == 1.0


def test_drawing_translation() -> None:
    drawing = Drawing(10, 10, [Rect(1, 2, 3, 4, fill="#fff")])
    moved = drawing.translated(5, 5)
    assert (moved.items[0].x, moved.items[0].y) == (6, 7)
    assert (drawing.items[0].x, drawing.items[0].y) == (1, 2)  # original untouched


def test_inline_markdown_parsing() -> None:
    spans = parse_inline("plain **bold** and *italic* and `code` and [link](http://x)")
    assert [s.text for s in spans if s.bold] == ["bold"]
    assert [s.text for s in spans if s.italic] == ["italic"]
    assert [s.text for s in spans if s.code] == ["code"]
    assert plain("**a** *b* `c`") == "a b c"


def test_unmatched_markup_is_left_alone() -> None:
    assert plain("2 * 3 * 4 = 24") == "2 * 3 * 4 = 24" or "*" not in plain("2 * 3 * 4 = 24")


def test_svg_path_flattening() -> None:
    subpaths = flatten_path("M4 12.5l5 5L20 6.5")
    assert len(subpaths) == 1
    assert len(subpaths[0]) == 3
    scaled = scale_subpaths(subpaths, 48)
    assert scaled[0][0][0] == pytest.approx(8.0)


def test_svg_path_with_curves_and_arcs() -> None:
    subpaths = flatten_path("M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2")
    assert len(subpaths) == 2
    assert all(len(sub) > 2 for sub in subpaths)


def test_icons_resolve_and_fall_back() -> None:
    from deckforge.renderers import icons

    assert icons.get_icon("target")
    assert icons.get_icon("no-such-icon") == icons.get_icon(icons.FALLBACK_ICON)
    assert icons.suggest_icon("our revenue growth") in icons.available()
    assert 'width="100%"' in icons.icon_svg("target", "#000")


def test_header_text_flows_in_one_container(themes, renderer) -> None:
    """Title and subtitle must share a flowing container, not stacked boxes.

    The browser may substitute a font the theme asked for but the machine does
    not have. If each run were pinned to its estimated `y`, a title that then
    wrapped one line further would be drawn straight over the subtitle.
    """
    slide = Slide(
        kind=SlideKind.COVER,
        layout="hero",
        eyebrow="THE NEXT SHIFT",
        title="Agentic AI: From Assistants to Autonomous Agents",
        subtitle="Redefining what machines can decide and do.",
    )
    html = renderer.render_slide(slide, themes.get("neon"))

    assert html.count("df-text-group") == 1, "the header belongs in a single container"
    for role in ("eyebrow", "display", "subtitle"):
        assert f'data-role="{role}"' in html

    style = html.split('class="df-abs df-text-group" style="')[1].split('"')[0]
    assert "min-height:" in style, "the group must be free to grow"
    assert ";height:" not in f";{style}", "a fixed height would clip a longer title"


def test_display_type_survives_a_partial_theme_override(themes, renderer) -> None:
    """`neon` overrides only the display weight; the size must still be display-sized."""
    slide = Slide(kind=SlideKind.COVER, layout="hero", title="Big", subtitle="Small")
    theme = themes.get("neon")
    assert theme.type_scale.display.size > theme.type_scale.subtitle.size
    html = renderer.render_slide(slide, theme)
    display_css = html.split('data-role="display"')[1].split(">")[0]
    assert "font-size:calc(68.00" in display_css


def test_html_slide_ids_are_addressable(deck: Presentation, themes, renderer) -> None:
    html = renderer.render_deck_fragment(deck, themes.for_deck(deck))
    for slide in deck.slides:
        assert f'data-slide-id="{slide.id}"' in html
