"""A Mermaid flowchart parser.

Only the flowchart/graph subset is handled — the shapes and arrows that actually
turn up in generated slides. Anything else (sequence, class, gantt…) returns
``None`` and the renderer falls back to showing the source, which is honest
rather than wrong.

Parsing is deliberately forgiving: this text comes from a language model, so a
stray space or a missing quote must degrade to a slightly plainer diagram, never
to an exception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

#: Diagram headers this module understands.
_HEADER_RE = re.compile(
    r"^\s*(?:flowchart|graph)\s+(TB|TD|BT|RL|LR)?\s*$", re.IGNORECASE | re.MULTILINE
)
_COMMENT_RE = re.compile(r"%%.*?$", re.MULTILINE)
#: `A -- text --> B` is normalised to `A -->|text| B` before splitting.
_MID_LABEL_RE = re.compile(r"--\s*([^->|\n]+?)\s*(-{2,3}>|-{3})")
_ARROW_RE = re.compile(r"(-\.->|-\.-|={2,}>|={2,}|-{2,3}>|-{3}|--)(?:\|([^|]*)\|)?")
_NODE_RE = re.compile(
    r"^(?P<id>[A-Za-z_][\w.-]*)\s*"
    r"(?P<body>\(\(.*?\)\)|\(\[.*?\]\)|\[\[.*?\]\]|\[\(.*?\)\]|\[.*?\]|\(.*?\)|\{\{.*?\}\}|\{.*?\})?\s*$",
    re.DOTALL,
)
_STYLE_RE = re.compile(r"^\s*style\s+(?P<id>[\w.-]+)\s+(?P<rules>.+)$", re.IGNORECASE)
_SUBGRAPH_RE = re.compile(r"^\s*subgraph\b", re.IGNORECASE)
_IGNORED_RE = re.compile(r"^\s*(classDef|class|click|linkStyle|direction|end)\b", re.IGNORECASE)


class Direction(StrEnum):
    """Flow direction. Mermaid's TB and TD mean the same thing."""

    LEFT_RIGHT = "LR"
    RIGHT_LEFT = "RL"
    TOP_DOWN = "TD"
    BOTTOM_TOP = "BT"

    @property
    def horizontal(self) -> bool:
        return self in (Direction.LEFT_RIGHT, Direction.RIGHT_LEFT)

    @property
    def reversed(self) -> bool:
        return self in (Direction.RIGHT_LEFT, Direction.BOTTOM_TOP)


class NodeShape(StrEnum):
    RECT = "rect"
    ROUNDED = "rounded"
    STADIUM = "stadium"
    CIRCLE = "circle"
    DIAMOND = "diamond"
    HEXAGON = "hexagon"
    CYLINDER = "cylinder"
    SUBROUTINE = "subroutine"


class EdgeStyle(StrEnum):
    SOLID = "solid"
    DASHED = "dashed"
    THICK = "thick"


#: Wrapper characters to the shape they denote, longest first so `((` wins over `(`.
_SHAPES: tuple[tuple[str, str, NodeShape], ...] = (
    ("((", "))", NodeShape.CIRCLE),
    ("([", "])", NodeShape.STADIUM),
    ("[[", "]]", NodeShape.SUBROUTINE),
    ("[(", ")]", NodeShape.CYLINDER),
    ("{{", "}}", NodeShape.HEXAGON),
    ("[", "]", NodeShape.RECT),
    ("(", ")", NodeShape.ROUNDED),
    ("{", "}", NodeShape.DIAMOND),
)


@dataclass(slots=True)
class Node:
    id: str
    label: str
    shape: NodeShape = NodeShape.RECT
    fill: str | None = None
    color: str | None = None
    stroke: str | None = None


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    label: str = ""
    style: EdgeStyle = EdgeStyle.SOLID
    arrow: bool = True


@dataclass(slots=True)
class Graph:
    direction: Direction = Direction.LEFT_RIGHT
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def node(self, node_id: str) -> Node:
        return self.nodes.setdefault(node_id, Node(id=node_id, label=node_id))

    def __bool__(self) -> bool:
        return bool(self.nodes)


def looks_like_flowchart(source: str) -> bool:
    """Whether ``source`` is a flowchart we can draw."""
    head = _COMMENT_RE.sub("", source).strip().splitlines()
    if not head:
        return False
    first = head[0].strip().lower()
    return first.startswith(("flowchart", "graph"))


def parse(source: str) -> Graph | None:
    """Parse a Mermaid flowchart.

    Returns:
        The graph, or ``None`` when the source is not a flowchart or has no nodes.
    """
    if not looks_like_flowchart(source):
        return None

    text = _COMMENT_RE.sub("", source)
    graph = Graph()

    header = _HEADER_RE.search(text)
    if header and header.group(1):
        raw = header.group(1).upper()
        graph.direction = Direction.TOP_DOWN if raw == "TB" else Direction(raw)
        text = text[header.end() :]
    else:
        # `flowchart LR` on the same line as the first statement.
        text = re.sub(
            r"^\s*(?:flowchart|graph)\s+(TB|TD|BT|RL|LR)\b", "", text, count=1, flags=re.IGNORECASE
        )

    for statement in _statements(text):
        if _SUBGRAPH_RE.match(statement) or _IGNORED_RE.match(statement):
            continue
        if style := _STYLE_RE.match(statement):
            _apply_style(graph, style.group("id"), style.group("rules"))
            continue
        _parse_chain(graph, statement)

    return graph or None


def _statements(text: str) -> list[str]:
    parts: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        parts.extend(piece.strip() for piece in line.split(";"))
    return [p for p in parts if p]


def _parse_chain(graph: Graph, statement: str) -> None:
    """Parse ``A[x] --> B{y} --> C`` into nodes and edges."""
    normalised = _MID_LABEL_RE.sub(lambda m: f"-->|{m.group(1)}|", statement)
    tokens = _ARROW_RE.split(normalised)
    if len(tokens) == 1:
        # A bare node declaration.
        if node := _parse_node(graph, tokens[0]):
            graph.node(node)
        return

    # split() yields: text, arrow, label, text, arrow, label, ...
    previous = _parse_node(graph, tokens[0])
    index = 1
    while index + 2 < len(tokens) + 1 and index + 2 <= len(tokens):
        arrow, label, target_text = tokens[index], tokens[index + 1], tokens[index + 2]
        current = _parse_node(graph, target_text)
        if previous and current:
            graph.edges.append(
                Edge(
                    source=previous,
                    target=current,
                    label=(label or "").strip(),
                    style=_edge_style(arrow),
                    arrow=arrow.endswith(">"),
                )
            )
        previous = current
        index += 3


def _edge_style(arrow: str) -> EdgeStyle:
    if arrow.startswith("-."):
        return EdgeStyle.DASHED
    if arrow.startswith("="):
        return EdgeStyle.THICK
    return EdgeStyle.SOLID


def _parse_node(graph: Graph, text: str) -> str | None:
    """Register a node from ``A[Label]`` and return its id."""
    match = _NODE_RE.match(text.strip())
    if not match:
        return None
    node_id = match.group("id")
    node = graph.node(node_id)
    body = match.group("body")
    if body:
        for open_char, close_char, shape in _SHAPES:
            if body.startswith(open_char) and body.endswith(close_char):
                node.shape = shape
                node.label = _clean_label(body[len(open_char) : -len(close_char)])
                break
    return node_id


def _clean_label(label: str) -> str:
    text = label.strip().strip("\"'").strip()
    text = text.replace("<br/>", "\n").replace("<br>", "\n").replace("<br />", "\n")
    # Mermaid escapes; keep it simple and readable.
    return re.sub(r"\s*\n\s*", "\n", text).strip() or " "


def _apply_style(graph: Graph, node_id: str, rules: str) -> None:
    node = graph.node(node_id)
    for rule in rules.split(","):
        if ":" not in rule:
            continue
        key, _, value = rule.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not value:
            continue
        if key == "fill":
            node.fill = value
        elif key == "color":
            node.color = value
        elif key == "stroke":
            node.stroke = value


# --------------------------------------------------------------------------- #
# Layering
# --------------------------------------------------------------------------- #


def layered_order(graph: Graph) -> list[list[str]]:
    """Assign nodes to layers, left to right along the flow.

    Cycles are common in generated diagrams (``Perceive -> Reason -> Act ->
    Learn -> Perceive``), so back edges are detected and ignored for layering;
    they are still drawn.
    """
    back_edges = _back_edges(graph)
    incoming: dict[str, int] = dict.fromkeys(graph.nodes, 0)
    forward: dict[str, list[str]] = {node: [] for node in graph.nodes}
    for index, edge in enumerate(graph.edges):
        if index in back_edges or edge.source == edge.target:
            continue
        forward[edge.source].append(edge.target)
        incoming[edge.target] += 1

    layer_of: dict[str, int] = dict.fromkeys(graph.nodes, 0)
    queue = [node for node, count in incoming.items() if count == 0] or [next(iter(graph.nodes))]
    seen = set(queue)
    while queue:
        node = queue.pop(0)
        for target in forward[node]:
            layer_of[target] = max(layer_of[target], layer_of[node] + 1)
            incoming[target] -= 1
            if incoming[target] <= 0 and target not in seen:
                seen.add(target)
                queue.append(target)

    # Anything left unvisited (a fully cyclic component) trails the rest.
    for node in graph.nodes:
        if node not in seen:
            layer_of[node] = max(layer_of.values(), default=0)

    layers: dict[int, list[str]] = {}
    for node in graph.nodes:
        layers.setdefault(layer_of[node], []).append(node)
    return [layers[key] for key in sorted(layers)]


def back_edge_indices(graph: Graph) -> set[int]:
    """Indices of edges that close a cycle.

    Renderers need these so a cycle-closing arrow can be routed around the
    diagram rather than straight back through every node between its ends.
    """
    return _back_edges(graph)


def _back_edges(graph: Graph) -> set[int]:
    """Indices of edges that close a cycle, found by depth-first search."""
    colour: dict[str, int] = dict.fromkeys(graph.nodes, 0)  # 0 unseen, 1 open, 2 done
    outgoing: dict[str, list[tuple[int, str]]] = {node: [] for node in graph.nodes}
    for index, edge in enumerate(graph.edges):
        if edge.source in outgoing and edge.target in graph.nodes:
            outgoing[edge.source].append((index, edge.target))

    back: set[int] = set()

    def visit(node: str) -> None:
        colour[node] = 1
        for index, target in outgoing[node]:
            if colour[target] == 1:
                back.add(index)
            elif colour[target] == 0:
                visit(target)
        colour[node] = 2

    for node in graph.nodes:
        if colour[node] == 0:
            visit(node)
    return back
