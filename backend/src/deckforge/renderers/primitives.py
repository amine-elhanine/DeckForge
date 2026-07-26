"""Renderer-independent vector primitives.

Charts, decorations and diagram fallbacks are described once as primitives and
then drawn by whichever backend is active — SVG for HTML/Reveal, fpdf2 drawing
calls for PDF. Without this shared layer each exporter would reimplement (and
subtly disagree about) every chart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

Anchor = Literal["start", "middle", "end"]


@dataclass(slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float
    fill: str | None = None
    stroke: str | None = None
    stroke_width: float = 1.0
    radius: float = 0.0
    opacity: float = 1.0


@dataclass(slots=True)
class Ellipse:
    cx: float
    cy: float
    rx: float
    ry: float
    fill: str | None = None
    stroke: str | None = None
    stroke_width: float = 1.0
    opacity: float = 1.0


@dataclass(slots=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    stroke: str = "#000000"
    stroke_width: float = 1.0
    dash: tuple[float, float] | None = None
    opacity: float = 1.0


@dataclass(slots=True)
class Polyline:
    points: list[tuple[float, float]]
    stroke: str | None = None
    stroke_width: float = 2.0
    fill: str | None = None
    closed: bool = False
    opacity: float = 1.0


@dataclass(slots=True)
class Wedge:
    """A pie/donut slice. Angles are degrees clockwise from 12 o'clock."""

    cx: float
    cy: float
    radius: float
    start_deg: float
    end_deg: float
    fill: str
    inner_radius: float = 0.0
    stroke: str | None = None
    stroke_width: float = 0.0
    opacity: float = 1.0

    def outline(self, steps: int = 48) -> list[tuple[float, float]]:
        """Flatten the wedge to a polygon — used by backends without arc support."""
        span = self.end_deg - self.start_deg
        count = max(2, int(abs(span) / 360 * steps) + 2)
        outer = [
            _polar(self.cx, self.cy, self.radius, self.start_deg + span * i / (count - 1))
            for i in range(count)
        ]
        if self.inner_radius <= 0:
            return [(self.cx, self.cy), *outer]
        inner = [
            _polar(self.cx, self.cy, self.inner_radius, self.end_deg - span * i / (count - 1))
            for i in range(count)
        ]
        return outer + inner


@dataclass(slots=True)
class Label:
    text: str
    x: float
    y: float
    size: float = 12.0
    color: str = "#000000"
    anchor: Anchor = "start"
    weight: int = 400
    family: str = "body"
    rotate: float = 0.0
    opacity: float = 1.0
    baseline: Literal["top", "middle", "bottom"] = "top"


Primitive = Rect | Ellipse | Line | Polyline | Wedge | Label


@dataclass(slots=True)
class Drawing:
    """An ordered list of primitives plus the box they were laid out in."""

    width: float
    height: float
    items: list[Primitive] = field(default_factory=list)

    def add(self, *primitives: Primitive) -> None:
        self.items.extend(primitives)

    def translated(self, dx: float, dy: float) -> Drawing:
        """Return a copy shifted by ``(dx, dy)`` — used to place a chart in a slot."""
        out = Drawing(self.width, self.height)
        for item in self.items:
            out.items.append(_translate(item, dx, dy))
        return out


def _polar(cx: float, cy: float, radius: float, degrees: float) -> tuple[float, float]:
    """Point on a circle, measuring clockwise from 12 o'clock."""
    rad = math.radians(degrees - 90)
    return cx + radius * math.cos(rad), cy + radius * math.sin(rad)


def _translate(item: Primitive, dx: float, dy: float) -> Primitive:
    match item:
        case Rect():
            return Rect(
                item.x + dx,
                item.y + dy,
                item.width,
                item.height,
                item.fill,
                item.stroke,
                item.stroke_width,
                item.radius,
                item.opacity,
            )
        case Ellipse():
            return Ellipse(
                item.cx + dx,
                item.cy + dy,
                item.rx,
                item.ry,
                item.fill,
                item.stroke,
                item.stroke_width,
                item.opacity,
            )
        case Line():
            return Line(
                item.x1 + dx,
                item.y1 + dy,
                item.x2 + dx,
                item.y2 + dy,
                item.stroke,
                item.stroke_width,
                item.dash,
                item.opacity,
            )
        case Polyline():
            return Polyline(
                [(x + dx, y + dy) for x, y in item.points],
                item.stroke,
                item.stroke_width,
                item.fill,
                item.closed,
                item.opacity,
            )
        case Wedge():
            return Wedge(
                item.cx + dx,
                item.cy + dy,
                item.radius,
                item.start_deg,
                item.end_deg,
                item.fill,
                item.inner_radius,
                item.stroke,
                item.stroke_width,
                item.opacity,
            )
        case Label():
            return Label(
                item.text,
                item.x + dx,
                item.y + dy,
                item.size,
                item.color,
                item.anchor,
                item.weight,
                item.family,
                item.rotate,
                item.opacity,
                item.baseline,
            )


def nice_ceiling(value: float) -> float:
    """Round ``value`` up to a friendly axis maximum (1, 2, 2.5, 5 × 10ⁿ)."""
    if value <= 0:
        return 1.0
    magnitude = float(10 ** math.floor(math.log10(value)))
    for step in (1.0, 2.0, 2.5, 5.0, 10.0):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def axis_ticks(maximum: float, minimum: float = 0.0, count: int = 4) -> list[float]:
    """Evenly spaced tick values from ``minimum`` to a nice ceiling."""
    top = nice_ceiling(maximum) if maximum > 0 else 1.0
    step = (top - minimum) / max(1, count)
    return [minimum + step * i for i in range(count + 1)]
