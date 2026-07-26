"""Mermaid parsing and flowchart drawing."""

from __future__ import annotations

import io
import zipfile

import pytest

from deckforge.exporters.base import EXPORTERS, ExportContext
from deckforge.models.deck import DiagramElement, Presentation, Slide
from deckforge.models.enums import DiagramEngine, SlideKind
from deckforge.renderers import diagrams, mermaid
from deckforge.renderers.mermaid import Direction, EdgeStyle, NodeShape
from deckforge.renderers.primitives import Label, Line, Polyline, Rect

LOOP = """flowchart LR
    P[Perceive] --> R[Reason]
    R --> A[Act]
    A --> L[Learn]
    L --> P
    style P fill:#4a90d9,color:#fff"""

DECISION = """flowchart TD
    S([Start]) --> C{Enough context?}
    C -->|yes| P[Plan the steps]
    C -->|no| G[Gather more]
    G --> C
    P --> T[[Call tools]]
    T --> V{Result good?}
    V -- no --> P
    V -- yes --> D([Done])"""


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parses_nodes_edges_and_styles() -> None:
    graph = mermaid.parse(LOOP)
    assert graph is not None
    assert graph.direction is Direction.LEFT_RIGHT
    assert set(graph.nodes) == {"P", "R", "A", "L"}
    assert graph.nodes["P"].label == "Perceive"
    assert graph.nodes["P"].fill == "#4a90d9"
    assert graph.nodes["P"].color == "#fff"
    assert [(e.source, e.target) for e in graph.edges] == [
        ("P", "R"),
        ("R", "A"),
        ("A", "L"),
        ("L", "P"),
    ]


@pytest.mark.parametrize(
    ("syntax", "shape"),
    [
        ("A[Rect]", NodeShape.RECT),
        ("A(Round)", NodeShape.ROUNDED),
        ("A([Stadium])", NodeShape.STADIUM),
        ("A((Circle))", NodeShape.CIRCLE),
        ("A{Diamond}", NodeShape.DIAMOND),
        ("A{{Hexagon}}", NodeShape.HEXAGON),
        ("A[[Subroutine]]", NodeShape.SUBROUTINE),
        ("A[(Cylinder)]", NodeShape.CYLINDER),
    ],
)
def test_node_shapes(syntax: str, shape: NodeShape) -> None:
    graph = mermaid.parse(f"flowchart LR\n  {syntax} --> B")
    assert graph is not None
    assert graph.nodes["A"].shape is shape


def test_edge_labels_in_both_syntaxes() -> None:
    graph = mermaid.parse(DECISION)
    assert graph is not None
    labelled = {(e.source, e.target): e.label for e in graph.edges if e.label}
    assert labelled[("C", "P")] == "yes"  # -->|yes|
    assert labelled[("V", "D")] == "yes"  # -- yes -->
    assert labelled[("V", "P")] == "no"


@pytest.mark.parametrize(
    ("arrow", "style"),
    [("-->", EdgeStyle.SOLID), ("-.->", EdgeStyle.DASHED), ("==>", EdgeStyle.THICK)],
)
def test_edge_styles(arrow: str, style: EdgeStyle) -> None:
    graph = mermaid.parse(f"flowchart LR\n  A {arrow} B")
    assert graph is not None
    assert graph.edges[0].style is style


def test_direction_variants() -> None:
    for header, expected in (
        ("flowchart TD", Direction.TOP_DOWN),
        ("flowchart TB", Direction.TOP_DOWN),
        ("graph RL", Direction.RIGHT_LEFT),
        ("graph BT", Direction.BOTTOM_TOP),
    ):
        graph = mermaid.parse(f"{header}\n A --> B")
        assert graph is not None and graph.direction is expected


def test_non_flowcharts_are_declined() -> None:
    """Anything we cannot draw keeps its source rather than rendering wrongly."""
    for source in (
        "sequenceDiagram\n  A->>B: hi",
        "classDiagram\n  Animal <|-- Duck",
        "gantt\n title A",
        "",
        "not a diagram at all",
    ):
        assert mermaid.parse(source) is None


def test_malformed_input_degrades_quietly() -> None:
    """Model output is not always well-formed; it must never raise."""
    graph = mermaid.parse("flowchart LR\n  A[Unclosed --> B\n  --> \n  C -->")
    assert graph is None or isinstance(graph.nodes, dict)


def test_comments_and_subgraphs_are_skipped() -> None:
    graph = mermaid.parse(
        "flowchart LR\n%% a comment\nsubgraph one\n  A --> B\nend\nclassDef x fill:#000"
    )
    assert graph is not None
    assert set(graph.nodes) == {"A", "B"}


def test_cycles_are_layered_not_looped_forever() -> None:
    graph = mermaid.parse(LOOP)
    assert graph is not None
    layers = mermaid.layered_order(graph)
    assert layers == [["P"], ["R"], ["A"], ["L"]]
    assert mermaid.back_edge_indices(graph) == {3}, "L --> P closes the cycle"


def test_branching_shares_a_layer() -> None:
    graph = mermaid.parse(DECISION)
    assert graph is not None
    layers = mermaid.layered_order(graph)
    assert ["P", "G"] in layers or ["G", "P"] in layers


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #


def test_flowchart_becomes_shapes_not_text(themes) -> None:
    element = DiagramElement(source=LOOP)
    drawing = diagrams.render_diagram(element, 900, 400, themes.get("technology"))
    assert drawing is not None

    labels = [i.text for i in drawing.items if isinstance(i, Label)]
    assert {"Perceive", "Reason", "Act", "Learn"} <= set(labels)
    assert sum(isinstance(i, Rect) for i in drawing.items) >= 4, "one box per node"
    assert sum(isinstance(i, Line) for i in drawing.items) >= 3, "connectors between them"
    assert any(isinstance(i, Polyline) and i.closed for i in drawing.items), "arrow heads"
    # The Mermaid source must not appear anywhere on the slide.
    assert not any("flowchart" in text for text in labels)


def test_node_styles_are_honoured(themes) -> None:
    drawing = diagrams.render_diagram(DiagramElement(source=LOOP), 900, 400, themes.get("minimal"))
    assert drawing is not None
    fills = {i.fill for i in drawing.items if isinstance(i, Rect)}
    assert "#4a90d9" in fills, "style fill:#4a90d9 applies to the node"


def test_everything_stays_inside_the_box(themes) -> None:
    """A tall decision tree must be scaled to fit, not run off the slide."""
    theme = themes.get("minimal")
    for source in (LOOP, DECISION):
        drawing = diagrams.render_diagram(DiagramElement(source=source), 700, 320, theme)
        assert drawing is not None
        for item in drawing.items:
            if isinstance(item, Rect):
                assert item.x >= -1 and item.y >= -1
                assert item.x + item.width <= 701
                assert item.y + item.height <= 321


def test_a_long_edge_label_is_elided_to_its_connector(themes) -> None:
    """A whole clause drawn at full width runs underneath the nodes at each end."""
    source = (
        "flowchart LR\n"
        "  A[Perception] -->|calls APIs, parses the response and builds a state| B[Planning]"
    )
    drawing = diagrams.render_diagram(
        DiagramElement(source=source), 700, 300, themes.get("minimal")
    )
    assert drawing is not None
    label = next(i for i in drawing.items if isinstance(i, Label) and "call" in i.text)
    assert label.text.endswith("…"), "the label is shortened, not drawn over the nodes"

    # The two node boxes are the widest rects; the label must stay between them.
    boxes = sorted(
        (i for i in drawing.items if isinstance(i, Rect)), key=lambda r: r.width, reverse=True
    )[:2]
    left, right = sorted(boxes, key=lambda r: r.x)
    assert label.x - len(label.text) * label.size * 0.29 >= left.x + left.width - 1
    assert label.x + len(label.text) * label.size * 0.29 <= right.x + 1


def test_unsupported_engines_are_declined(themes) -> None:
    element = DiagramElement(source="A --> B", engine=DiagramEngine.PLANTUML)
    assert diagrams.render_diagram(element, 600, 300, themes.get("minimal")) is None


def test_single_node_is_not_worth_drawing(themes) -> None:
    element = DiagramElement(source="flowchart LR\n  A[Only one]")
    assert diagrams.render_diagram(element, 600, 300, themes.get("minimal")) is None


def test_html_renders_the_diagram_inline(themes, renderer) -> None:
    slide = Slide(
        kind=SlideKind.DIAGRAM,
        layout="diagram",
        title="The agent loop",
        elements=[DiagramElement(source=LOOP)],
    )
    html = renderer.render_slide(slide, themes.get("technology"))
    assert "df-diagram-figure" in html
    assert "<svg" in html
    assert "flowchart LR" not in html, "the source must not be shown"
    assert ">Perceive<" in html


def test_html_keeps_the_source_for_unsupported_diagrams(themes, renderer) -> None:
    slide = Slide(
        kind=SlideKind.DIAGRAM,
        layout="diagram",
        title="Sequence",
        elements=[DiagramElement(source="sequenceDiagram\n  A->>B: hi")],
    )
    html = renderer.render_slide(slide, themes.get("minimal"))
    assert "sequenceDiagram" in html, "better to show the source than to render it wrongly"


def test_exports_contain_diagram_shapes(themes, layouts, renderer) -> None:
    """PPTX gets native shapes, not a bitmap or a wall of source."""
    deck = Presentation(title="Diagram", theme="technology")
    deck.add_slide(
        Slide(
            kind=SlideKind.DIAGRAM,
            layout="diagram",
            title="The agent loop",
            elements=[DiagramElement(source=LOOP)],
        )
    )
    theme = themes.for_deck(deck)
    context = ExportContext(theme=theme, layouts=layouts, renderer=renderer)

    content = EXPORTERS.get("pptx").export(deck, context).content
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "Perceive" in xml
    assert "flowchart" not in xml, "the Mermaid source must not reach the slide"

    assert EXPORTERS.get("pdf").export(deck, context).size > 1000
