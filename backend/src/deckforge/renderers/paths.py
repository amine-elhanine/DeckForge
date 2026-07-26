"""SVG path flattening.

The icon set is stored as SVG path data, but PPTX and PDF have no notion of
Bézier path strings. This module flattens a path into polylines so the same
icons can be stroked into PowerPoint freeform shapes and PDF drawing commands —
one icon definition, every output format.

Supports the path commands the icon set uses: ``M L H V C S Q T A Z`` and their
relative forms.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_COMMAND_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")
_NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_SEPARATOR_RE = re.compile(r"[\s,]*")

Point = tuple[float, float]


class _Scanner:
    """Cursor over path data.

    A regex tokenizer cannot parse SVG arcs: the ``large-arc`` and ``sweep``
    flags are *single characters* that may run straight into the next number, so
    ``a9 9 0 100-18`` means flags ``1``,``0`` followed by ``0`` and ``-18`` — not
    the number ``100``. The scanner therefore lets the arc branch ask for a flag
    explicitly.
    """

    __slots__ = ("data", "i")

    def __init__(self, data: str) -> None:
        self.data = data
        self.i = 0

    def skip_separators(self) -> None:
        match = _SEPARATOR_RE.match(self.data, self.i)
        if match:
            self.i = match.end()

    def at_end(self) -> bool:
        self.skip_separators()
        return self.i >= len(self.data)

    def read_command(self) -> str | None:
        self.skip_separators()
        match = _COMMAND_RE.match(self.data, self.i)
        if not match:
            return None
        self.i = match.end()
        return match.group()

    def has_number(self) -> bool:
        self.skip_separators()
        return bool(_NUMBER_RE.match(self.data, self.i))

    def read_number(self) -> float:
        self.skip_separators()
        match = _NUMBER_RE.match(self.data, self.i)
        if not match:
            raise ValueError(f"expected a number at offset {self.i}")
        self.i = match.end()
        return float(match.group())

    def read_flag(self) -> bool:
        """Read a single-character ``0``/``1`` arc flag."""
        self.skip_separators()
        if self.i >= len(self.data) or self.data[self.i] not in "01":
            return bool(self.read_number())
        value = self.data[self.i] == "1"
        self.i += 1
        return value


@dataclass(slots=True)
class _State:
    x: float = 0.0
    y: float = 0.0
    start: Point = (0.0, 0.0)
    last_control: Point | None = None
    last_quad: Point | None = None
    subpaths: list[list[Point]] = field(default_factory=list)
    current: list[Point] = field(default_factory=list)

    def move_to(self, x: float, y: float) -> None:
        self.flush()
        self.x, self.y = x, y
        self.start = (x, y)
        self.current = [(x, y)]

    def line_to(self, x: float, y: float) -> None:
        if not self.current:
            self.current = [(self.x, self.y)]
        self.current.append((x, y))
        self.x, self.y = x, y

    def close(self) -> None:
        if self.current:
            self.current.append(self.start)
            self.x, self.y = self.start
        self.flush()

    def flush(self) -> None:
        if len(self.current) > 1:
            self.subpaths.append(self.current)
        self.current = []


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int) -> list[Point]:
    points: list[Point] = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def _quadratic(p0: Point, p1: Point, p2: Point, steps: int) -> list[Point]:
    points: list[Point] = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
        y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
        points.append((x, y))
    return points


def _arc(
    p0: Point,
    rx: float,
    ry: float,
    rotation: float,
    large: bool,
    sweep: bool,
    p1: Point,
    steps: int,
) -> list[Point]:
    """Endpoint-parameterised elliptical arc, per the SVG implementation notes."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1 = cos_phi * dx2 + sin_phi * dy2
    y1 = -sin_phi * dx2 + cos_phi * dy2
    rx, ry = abs(rx), abs(ry)

    lam = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx, ry = rx * scale, ry * scale

    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    numerator = max(0.0, rx * rx * ry * ry - denominator)
    coefficient = (
        (1 if large != sweep else -1) * math.sqrt(numerator / denominator) if denominator else 0.0
    )
    cx1 = coefficient * rx * y1 / ry
    cy1 = -coefficient * ry * x1 / rx
    cx = cos_phi * cx1 - sin_phi * cy1 + (p0[0] + p1[0]) / 2
    cy = sin_phi * cx1 + cos_phi * cy1 + (p0[1] + p1[1]) / 2

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        value = max(-1.0, min(1.0, dot / norm)) if norm else 1.0
        sign = -1.0 if (ux * vy - uy * vx) < 0 else 1.0
        return sign * math.acos(value)

    theta = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    delta = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi

    count = max(2, int(steps * abs(delta) / (2 * math.pi)) + 1)
    points: list[Point] = []
    for i in range(1, count + 1):
        t = theta + delta * i / count
        px = cos_phi * rx * math.cos(t) - sin_phi * ry * math.sin(t) + cx
        py = sin_phi * rx * math.cos(t) + cos_phi * ry * math.sin(t) + cy
        points.append((px, py))
    return points


def flatten_path(data: str, *, steps: int = 10) -> list[list[Point]]:
    """Flatten SVG path ``data`` into subpaths of points on the source grid.

    Args:
        data: SVG ``d`` attribute contents.
        steps: Curve subdivision count; higher is smoother and slower.

    Returns:
        A list of subpaths, each a list of ``(x, y)`` points.
    """
    scanner = _Scanner(data)
    state = _State()
    command = ""

    def take(count: int) -> list[float]:
        return [scanner.read_number() for _ in range(count)]

    while not scanner.at_end():
        next_command = scanner.read_command()
        if next_command:
            command = next_command
            if command in "Zz":
                state.close()
                continue
        elif not command:
            break

        relative = command.islower()
        op = command.upper()
        ox, oy = (state.x, state.y) if relative else (0.0, 0.0)

        match op:
            case "M":
                x, y = take(2)
                state.move_to(x + ox, y + oy)
                # Implicit subsequent pairs of an M command are line-tos.
                command = "l" if relative else "L"
            case "L":
                x, y = take(2)
                state.line_to(x + ox, y + oy)
            case "H":
                (x,) = take(1)
                state.line_to(x + ox, state.y)
            case "V":
                (y,) = take(1)
                state.line_to(state.x, y + oy)
            case "C":
                x1, y1, x2, y2, x, y = take(6)
                p0 = (state.x, state.y)
                c1 = (x1 + ox, y1 + oy)
                c2 = (x2 + ox, y2 + oy)
                end = (x + ox, y + oy)
                for point in _cubic(p0, c1, c2, end, steps):
                    state.line_to(*point)
                state.last_control = c2
            case "S":
                x2, y2, x, y = take(4)
                p0 = (state.x, state.y)
                c1 = (
                    (
                        2 * p0[0] - state.last_control[0],
                        2 * p0[1] - state.last_control[1],
                    )
                    if state.last_control
                    else p0
                )
                c2 = (x2 + ox, y2 + oy)
                end = (x + ox, y + oy)
                for point in _cubic(p0, c1, c2, end, steps):
                    state.line_to(*point)
                state.last_control = c2
            case "Q":
                x1, y1, x, y = take(4)
                p0 = (state.x, state.y)
                c = (x1 + ox, y1 + oy)
                end = (x + ox, y + oy)
                for point in _quadratic(p0, c, end, steps):
                    state.line_to(*point)
                state.last_quad = c
            case "T":
                x, y = take(2)
                p0 = (state.x, state.y)
                c = (
                    (
                        2 * p0[0] - state.last_quad[0],
                        2 * p0[1] - state.last_quad[1],
                    )
                    if state.last_quad
                    else p0
                )
                end = (x + ox, y + oy)
                for point in _quadratic(p0, c, end, steps):
                    state.line_to(*point)
                state.last_quad = c
            case "A":
                rx, ry, rotation = take(3)
                large, sweep = scanner.read_flag(), scanner.read_flag()
                x, y = take(2)
                p0 = (state.x, state.y)
                end = (x + ox, y + oy)
                for point in _arc(p0, rx, ry, rotation, large, sweep, end, steps * 4):
                    state.line_to(*point)
            case _:
                continue

        if op not in ("C", "S"):
            state.last_control = None
        if op not in ("Q", "T"):
            state.last_quad = None

    state.flush()
    return state.subpaths


def scale_subpaths(
    subpaths: list[list[Point]],
    size: float,
    *,
    source: float = 24.0,
    dx: float = 0.0,
    dy: float = 0.0,
) -> list[list[Point]]:
    """Scale flattened subpaths from a ``source``-unit grid to ``size``, then offset."""
    factor = size / source
    return [[(x * factor + dx, y * factor + dy) for x, y in sub] for sub in subpaths]
