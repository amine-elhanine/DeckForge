"""Drawing flowcharts.

A parsed Mermaid graph becomes vector primitives, exactly like charts do — so
one implementation gives a real diagram in the HTML preview, in PowerPoint and
in the PDF, instead of a block of Mermaid source pasted onto a slide.

Layout is a small layered ("Sugiyama-lite") pass: assign nodes to layers along
the flow, order each layer to reduce crossings, then place them on a grid.
"""

from __future__ import annotations

import itertools
import math
from typing import overload

from deckforge.models.deck import DiagramElement
from deckforge.models.enums import DiagramEngine
from deckforge.renderers import mermaid
from deckforge.renderers.mermaid import Direction, EdgeStyle, Graph, NodeShape
from deckforge.renderers.primitives import Drawing, Ellipse, Label, Line, Polyline, Rect
from deckforge.themes.model import Theme
from deckforge.utils import colors

#: Node box sizing, in logical canvas units.
MIN_NODE_WIDTH = 108.0
MAX_NODE_WIDTH = 240.0
NODE_PADDING_X = 22.0
NODE_PADDING_Y = 16.0
LINE_HEIGHT = 1.25
ARROW_LENGTH = 11.0
ARROW_HALF_WIDTH = 5.0
#: Enough room for an edge label to sit on the line without touching a node.
LAYER_GAP = 74.0
NODE_GAP = 26.0
#: Space kept outside the nodes so a back edge can loop around them.
DETOUR_MARGIN = 46.0
#: How far a small diagram may be grown to fill its box. Past this the node
#: boxes read as buttons rather than as a diagram.
MAX_UPSCALE = 1.75


class _Placed:
    """A node with resolved geometry."""

    __slots__ = ("cx", "cy", "height", "node", "width")

    def __init__(self, node: mermaid.Node, width: float, height: float) -> None:
        self.node = node
        self.width = width
        self.height = height
        self.cx = 0.0
        self.cy = 0.0

    @property
    def left(self) -> float:
        return self.cx - self.width / 2

    @property
    def top(self) -> float:
        return self.cy - self.height / 2


def render_diagram(
    element: DiagramElement, width: float, height: float, theme: Theme
) -> Drawing | None:
    """Draw ``element`` if it is a flowchart we understand, else ``None``."""
    if element.engine is not DiagramEngine.MERMAID:
        return None
    graph = mermaid.parse(element.source)
    if graph is None or len(graph.nodes) < 2:
        return None
    return draw_graph(graph, width, height, theme)


def draw_graph(graph: Graph, width: float, height: float, theme: Theme) -> Drawing:
    """Lay out and draw a parsed flowchart into a ``width`` x ``height`` box."""
    drawing = Drawing(width, height)
    font_size = _font_size(graph, width, height, theme)
    layers = _ordered_layers(graph)
    placed = _measure(graph, layers, font_size, theme)
    _position(placed, layers, graph.direction, width, height)

    # Back edges detour around the layers, so they need to know how far out the
    # diagram already reaches before anything is scaled.
    back = mermaid.back_edge_indices(graph)
    font_size = _fit(placed, width, height, font_size, bool(back))
    detour = _detour_line(placed, graph.direction)

    for index, edge in enumerate(graph.edges):
        source, target = placed.get(edge.source), placed.get(edge.target)
        if source is None or target is None or source is target:
            continue
        if index in back:
            _draw_back_edge(
                drawing, source, target, edge, theme, font_size, graph.direction, detour
            )
        else:
            _draw_edge(drawing, source, target, edge, theme, font_size)

    for node in placed.values():
        _draw_node(drawing, node, theme, font_size)
    return drawing


def _fit(
    placed: dict[str, _Placed],
    width: float,
    height: float,
    font_size: float,
    reserve_detour: bool,
) -> float:
    """Scale the whole diagram to fill its box, and return the adjusted type size.

    Both directions matter. Shrinking gaps alone is not enough for a tall
    decision tree — without this the last node falls off the slide. And a short
    chain of four nodes laid out at its natural size occupies a third of the
    slide and reads as a mistake, so it is grown to fill the space it was given.
    """
    if not placed:
        return font_size

    left = min(node.left for node in placed.values())
    right = max(node.left + node.width for node in placed.values())
    top = min(node.top for node in placed.values())
    bottom = max(node.top + node.height for node in placed.values())
    # Leave room for a back edge to loop around the outside.
    margin = DETOUR_MARGIN if reserve_detour else 4.0

    span_x = max(1.0, right - left + 2 * margin)
    span_y = max(1.0, bottom - top + 2 * margin)
    scale = min(MAX_UPSCALE, width / span_x, height / span_y)

    offset_x = (width - (right - left) * scale) / 2 - left * scale
    offset_y = (height - (bottom - top) * scale) / 2 - top * scale
    for node in placed.values():
        node.cx = node.cx * scale + offset_x
        node.cy = node.cy * scale + offset_y
        node.width *= scale
        node.height *= scale
    # Type grows more slowly than the boxes: a node label set at 28pt looks like
    # a button caption, and the extra box room becomes padding instead.
    return max(9.0, font_size * min(scale, 1.0 + (scale - 1.0) * 0.5))


def _detour_line(placed: dict[str, _Placed], direction: Direction) -> float:
    """The cross-axis coordinate a back edge routes along, outside every node."""
    if not placed:
        return 0.0
    if direction.horizontal:
        return max(node.top + node.height for node in placed.values()) + DETOUR_MARGIN * 0.55
    return max(node.left + node.width for node in placed.values()) + DETOUR_MARGIN * 0.55


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


def _ordered_layers(graph: Graph) -> list[list[str]]:
    """Layer the graph, then reduce crossings with a barycentre sweep."""
    layers = mermaid.layered_order(graph)
    neighbours: dict[str, list[str]] = {node: [] for node in graph.nodes}
    for edge in graph.edges:
        if edge.source in neighbours and edge.target in neighbours:
            neighbours[edge.target].append(edge.source)

    for index in range(1, len(layers)):
        previous = {node: position for position, node in enumerate(layers[index - 1])}

        def barycentre(node: str, previous: dict[str, int] = previous) -> float:
            positions = [previous[n] for n in neighbours[node] if n in previous]
            return sum(positions) / len(positions) if positions else math.inf

        layers[index].sort(key=barycentre)
    return layers


def _font_size(graph: Graph, width: float, height: float, theme: Theme) -> float:
    """Shrink the type as the diagram gets busier, with a readable floor."""
    base = float(theme.type_scale.card_body.size)
    order = mermaid.layered_order(graph)
    widest = max((len(layer) for layer in order), default=1)
    crowding = max(len(order) / 5.0, widest / 4.0, 1.0)
    scale = min(width / 900.0, height / 380.0, 1.0)
    return max(11.0, min(base, base * scale / math.pow(crowding, 0.4)))


def _measure(
    graph: Graph, layers: list[list[str]], font_size: float, theme: Theme
) -> dict[str, _Placed]:
    """Size every node from its label, keeping each layer uniform."""
    placed: dict[str, _Placed] = {}
    for layer in layers:
        boxes = [_size_of(graph.nodes[node_id], font_size) for node_id in layer]
        width = max(box[0] for box in boxes)
        height = max(box[1] for box in boxes)
        for node_id in layer:
            placed[node_id] = _Placed(graph.nodes[node_id], width, height)
    return placed


def _size_of(node: mermaid.Node, font_size: float) -> tuple[float, float]:
    lines = node.label.split("\n")
    longest = max((len(line) for line in lines), default=1)
    width = min(
        MAX_NODE_WIDTH, max(MIN_NODE_WIDTH, longest * font_size * 0.58 + 2 * NODE_PADDING_X)
    )
    # A long single line wraps rather than growing past the maximum.
    wrapped = sum(
        max(1, math.ceil(len(line) * font_size * 0.58 / (width - 2 * NODE_PADDING_X)))
        for line in lines
    )
    height = wrapped * font_size * LINE_HEIGHT + 2 * NODE_PADDING_Y
    if node.shape in (NodeShape.CIRCLE, NodeShape.DIAMOND):
        height = max(height, width * 0.62)
    return width, max(46.0, height)


def _position(
    placed: dict[str, _Placed],
    layers: list[list[str]],
    direction: Direction,
    width: float,
    height: float,
) -> None:
    """Place layers along the flow axis and centre each one across it."""
    horizontal = direction.horizontal
    layer_extent = [
        max(placed[n].width if horizontal else placed[n].height for n in layer) for layer in layers
    ]
    cross_extent = [
        sum(placed[n].height if horizontal else placed[n].width for n in layer)
        + NODE_GAP * (len(layer) - 1)
        for layer in layers
    ]

    total_flow = sum(layer_extent) + LAYER_GAP * (len(layers) - 1)
    flow_span = width if horizontal else height
    cross_span = height if horizontal else width

    # Shrink the gaps before letting the diagram overflow its box.
    gap = LAYER_GAP
    if total_flow > flow_span and len(layers) > 1:
        gap = max(30.0, (flow_span - sum(layer_extent)) / (len(layers) - 1))
        total_flow = sum(layer_extent) + gap * (len(layers) - 1)

    cursor = max(0.0, (flow_span - total_flow) / 2)
    order = range(len(layers))
    if direction.reversed:
        order = reversed(order)  # type: ignore[assignment]

    for layer_index in order:
        layer = layers[layer_index]
        extent = layer_extent[layer_index]
        across = max(0.0, (cross_span - cross_extent[layer_index]) / 2)
        for node_id in layer:
            node = placed[node_id]
            if horizontal:
                node.cx = cursor + extent / 2
                node.cy = across + node.height / 2
                across += node.height + NODE_GAP
            else:
                node.cy = cursor + extent / 2
                node.cx = across + node.width / 2
                across += node.width + NODE_GAP
        cursor += extent + gap


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #


def _draw_node(drawing: Drawing, placed: _Placed, theme: Theme, font_size: float) -> None:
    node = placed.node
    fill = _colour(node.fill, theme, theme.color("surface"))
    stroke = _colour(node.stroke, theme, theme.color("primary"))
    text_colour = _colour(node.color, theme, None) or colors.readable_on(
        fill, "#ffffff", theme.palette.text
    )

    left, top, width, height = placed.left, placed.top, placed.width, placed.height
    match node.shape:
        case NodeShape.CIRCLE:
            drawing.add(Ellipse(placed.cx, placed.cy, width / 2, height / 2, fill, stroke, 1.8))
        case NodeShape.DIAMOND:
            drawing.add(
                Polyline(
                    [
                        (placed.cx, top),
                        (left + width, placed.cy),
                        (placed.cx, top + height),
                        (left, placed.cy),
                    ],
                    stroke=stroke,
                    stroke_width=1.8,
                    fill=fill,
                    closed=True,
                )
            )
        case NodeShape.HEXAGON:
            inset = min(24.0, width * 0.18)
            drawing.add(
                Polyline(
                    [
                        (left + inset, top),
                        (left + width - inset, top),
                        (left + width, placed.cy),
                        (left + width - inset, top + height),
                        (left + inset, top + height),
                        (left, placed.cy),
                    ],
                    stroke=stroke,
                    stroke_width=1.8,
                    fill=fill,
                    closed=True,
                )
            )
        case NodeShape.STADIUM | NodeShape.ROUNDED:
            radius = height / 2 if node.shape is NodeShape.STADIUM else theme.shape.card_radius
            drawing.add(Rect(left, top, width, height, fill, stroke, 1.8, radius))
        case NodeShape.CYLINDER:
            drawing.add(Rect(left, top, width, height, fill, stroke, 1.8, 10))
            drawing.add(Ellipse(placed.cx, top + 9, width / 2, 9, fill, stroke, 1.4))
        case NodeShape.SUBROUTINE:
            drawing.add(Rect(left, top, width, height, fill, stroke, 1.8, 3))
            drawing.add(Line(left + 9, top, left + 9, top + height, stroke, 1.4))
            drawing.add(Line(left + width - 9, top, left + width - 9, top + height, stroke, 1.4))
        case _:
            drawing.add(Rect(left, top, width, height, fill, stroke, 1.8, theme.shape.radius))

    lines = _wrap(node.label, width - 2 * NODE_PADDING_X, font_size)
    start = placed.cy - (len(lines) - 1) * font_size * LINE_HEIGHT / 2
    for index, line in enumerate(lines):
        drawing.add(
            Label(
                line,
                placed.cx,
                start + index * font_size * LINE_HEIGHT,
                font_size,
                text_colour,
                "middle",
                weight=600,
                family="body",
                baseline="middle",
            )
        )


def _draw_edge(
    drawing: Drawing,
    source: _Placed,
    target: _Placed,
    edge: mermaid.Edge,
    theme: Theme,
    font_size: float,
) -> None:
    start, end = _anchor(source, target)
    stroke = colors.with_alpha(theme.palette.text_muted, 0.75)
    thickness = 2.6 if edge.style is EdgeStyle.THICK else 1.6
    dash = (7.0, 5.0) if edge.style is EdgeStyle.DASHED else None

    tip = end
    if edge.arrow:
        # Stop the line at the base of the arrowhead so it does not poke through.
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        end = (end[0] - ARROW_LENGTH * math.cos(angle), end[1] - ARROW_LENGTH * math.sin(angle))
        drawing.add(_arrow_head(tip, angle, stroke))

    drawing.add(Line(start[0], start[1], end[0], end[1], stroke, thickness, dash))

    if edge.label:
        # The label may only use the run of the connector itself: anything wider
        # slides under the nodes at each end and is read as clipped nonsense.
        span = math.dist(start, end) - 8
        _edge_label(
            drawing,
            ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2),
            edge.label,
            theme,
            font_size,
            span,
        )


def _draw_back_edge(
    drawing: Drawing,
    source: _Placed,
    target: _Placed,
    edge: mermaid.Edge,
    theme: Theme,
    font_size: float,
    direction: Direction,
    detour: float,
) -> None:
    """Route a cycle-closing edge around the outside of the diagram.

    Drawn straight, a back edge ploughs through every node between its ends —
    which is what made ``Learn --> Perceive`` look like an arrow pointing the
    wrong way in the middle of the row.
    """
    stroke = colors.with_alpha(theme.palette.text_muted, 0.65)
    thickness = 2.4 if edge.style is EdgeStyle.THICK else 1.5
    dash = (7.0, 5.0) if edge.style is EdgeStyle.DASHED else None

    if direction.horizontal:
        start = (source.cx, source.top + source.height)
        finish = (target.cx, target.top + target.height)
        corners = [start, (start[0], detour), (finish[0], detour), (finish[0], finish[1] + 2)]
        approach = -math.pi / 2  # arriving from below, pointing up
    else:
        start = (source.left + source.width, source.cy)
        finish = (target.left + target.width, target.cy)
        corners = [start, (detour, start[1]), (detour, finish[1]), (finish[0] + 2, finish[1])]
        approach = math.pi  # arriving from the right, pointing left

    tip = corners[-1]
    if edge.arrow:
        corners[-1] = (
            tip[0] - ARROW_LENGTH * math.cos(approach),
            tip[1] - ARROW_LENGTH * math.sin(approach),
        )
        drawing.add(_arrow_head(tip, approach, stroke))

    # Straight segments rather than a polyline: only Line carries a dash pattern.
    for first, second in itertools.pairwise(corners):
        drawing.add(Line(first[0], first[1], second[0], second[1], stroke, thickness, dash))

    if edge.label:
        middle, far = corners[1], corners[2]
        _edge_label(
            drawing,
            ((middle[0] + far[0]) / 2, (middle[1] + far[1]) / 2),
            edge.label,
            theme,
            font_size,
            math.dist(middle, far) - 8,
        )


def _edge_label(
    drawing: Drawing,
    at: tuple[float, float],
    text: str,
    theme: Theme,
    font_size: float,
    span: float,
) -> None:
    """A label sitting on a connector, on its own chip so the line does not cross it.

    ``span`` is how much room the connector actually has. Models write edge
    labels as whole clauses ("calls APIs, parses the response"), and one drawn
    at its natural width runs underneath the nodes at either end — legible in
    neither place. It is shrunk a little, then elided to fit.
    """
    size = max(8.0, min(font_size * 0.82, font_size * 0.82 * max(0.7, span / 90.0)))
    per_char = size * 0.58
    room = max(1, int((max(24.0, span) - 12) / per_char))
    if len(text) > room:
        text = text[: max(1, room - 1)].rstrip() + "…"

    width = len(text) * per_char + 12
    drawing.add(
        Rect(
            at[0] - width / 2,
            at[1] - size * 0.9,
            width,
            size * 1.8,
            theme.color("background"),
            radius=4,
        )
    )
    drawing.add(
        Label(text, at[0], at[1], size, theme.palette.text_muted, "middle", baseline="middle")
    )


def _anchor(source: _Placed, target: _Placed) -> tuple[tuple[float, float], tuple[float, float]]:
    """Where the connector meets each node's boundary."""
    angle = math.atan2(target.cy - source.cy, target.cx - source.cx)
    return (
        _boundary(source, angle),
        _boundary(target, angle + math.pi),
    )


def _boundary(placed: _Placed, angle: float) -> tuple[float, float]:
    """Point on a node's rectangle in the given direction, plus a small margin."""
    half_w, half_h = placed.width / 2 + 3, placed.height / 2 + 3
    cos, sin = math.cos(angle), math.sin(angle)
    if abs(cos) < 1e-6:
        return placed.cx, placed.cy + math.copysign(half_h, sin)
    if abs(sin) < 1e-6:
        return placed.cx + math.copysign(half_w, cos), placed.cy
    scale = min(half_w / abs(cos), half_h / abs(sin))
    return placed.cx + cos * scale, placed.cy + sin * scale


def _arrow_head(tip: tuple[float, float], angle: float, colour: str) -> Polyline:
    back = (tip[0] - ARROW_LENGTH * math.cos(angle), tip[1] - ARROW_LENGTH * math.sin(angle))
    normal = (-math.sin(angle), math.cos(angle))
    return Polyline(
        [
            tip,
            (back[0] + normal[0] * ARROW_HALF_WIDTH, back[1] + normal[1] * ARROW_HALF_WIDTH),
            (back[0] - normal[0] * ARROW_HALF_WIDTH, back[1] - normal[1] * ARROW_HALF_WIDTH),
        ],
        fill=colour,
        closed=True,
        stroke=None,
        stroke_width=0,
    )


def _wrap(text: str, width: float, font_size: float) -> list[str]:
    """Greedy word wrap at the node's inner width."""
    per_line = max(6, int(width / max(1.0, font_size * 0.58)))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if len(candidate) <= per_line or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return [line for line in lines if line] or [" "]


@overload
def _colour(value: str | None, theme: Theme, fallback: str) -> str: ...
@overload
def _colour(value: str | None, theme: Theme, fallback: None) -> str | None: ...
def _colour(value: str | None, theme: Theme, fallback: str | None) -> str | None:
    """Resolve a Mermaid colour, a theme token, or fall back."""
    if not value:
        return fallback
    text = value.strip()
    if text.startswith("#") or text.startswith("rgb"):
        return text
    resolved = theme.color(text, fallback)
    return resolved or fallback
