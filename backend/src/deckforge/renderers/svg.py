"""SVG backend for the shared vector primitives."""

from __future__ import annotations

from html import escape

from deckforge.renderers.primitives import (
    Drawing,
    Ellipse,
    Label,
    Line,
    Polyline,
    Primitive,
    Rect,
    Wedge,
)
from deckforge.themes.model import Theme


def _fmt(value: float) -> str:
    """Trim float noise so the SVG stays readable and diffable."""
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _points(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points)


def primitive_to_svg(item: Primitive, theme: Theme | None = None) -> str:
    """Render a single primitive as an SVG element."""
    match item:
        case Rect():
            attrs = [
                f'x="{_fmt(item.x)}"',
                f'y="{_fmt(item.y)}"',
                f'width="{_fmt(max(0.0, item.width))}"',
                f'height="{_fmt(max(0.0, item.height))}"',
                f'fill="{item.fill or "none"}"',
            ]
            if item.radius:
                attrs.append(f'rx="{_fmt(item.radius)}"')
            if item.stroke:
                attrs += [f'stroke="{item.stroke}"', f'stroke-width="{_fmt(item.stroke_width)}"']
            if item.opacity < 1:
                attrs.append(f'opacity="{_fmt(item.opacity)}"')
            return f"<rect {' '.join(attrs)}/>"

        case Ellipse():
            attrs = [
                f'cx="{_fmt(item.cx)}"',
                f'cy="{_fmt(item.cy)}"',
                f'rx="{_fmt(item.rx)}"',
                f'ry="{_fmt(item.ry)}"',
                f'fill="{item.fill or "none"}"',
            ]
            if item.stroke:
                attrs += [f'stroke="{item.stroke}"', f'stroke-width="{_fmt(item.stroke_width)}"']
            if item.opacity < 1:
                attrs.append(f'opacity="{_fmt(item.opacity)}"')
            return f"<ellipse {' '.join(attrs)}/>"

        case Line():
            attrs = [
                f'x1="{_fmt(item.x1)}"',
                f'y1="{_fmt(item.y1)}"',
                f'x2="{_fmt(item.x2)}"',
                f'y2="{_fmt(item.y2)}"',
                f'stroke="{item.stroke}"',
                f'stroke-width="{_fmt(item.stroke_width)}"',
            ]
            if item.dash:
                attrs.append(f'stroke-dasharray="{_fmt(item.dash[0])} {_fmt(item.dash[1])}"')
            if item.opacity < 1:
                attrs.append(f'opacity="{_fmt(item.opacity)}"')
            return f"<line {' '.join(attrs)}/>"

        case Polyline():
            tag = "polygon" if item.closed else "polyline"
            attrs = [
                f'points="{_points(item.points)}"',
                f'fill="{item.fill or "none"}"',
            ]
            if item.stroke:
                attrs += [
                    f'stroke="{item.stroke}"',
                    f'stroke-width="{_fmt(item.stroke_width)}"',
                    'stroke-linejoin="round"',
                    'stroke-linecap="round"',
                ]
            if item.opacity < 1:
                attrs.append(f'opacity="{_fmt(item.opacity)}"')
            return f"<{tag} {' '.join(attrs)}/>"

        case Wedge():
            attrs = [f'points="{_points(item.outline())}"', f'fill="{item.fill}"']
            if item.stroke and item.stroke_width:
                attrs += [f'stroke="{item.stroke}"', f'stroke-width="{_fmt(item.stroke_width)}"']
            if item.opacity < 1:
                attrs.append(f'opacity="{_fmt(item.opacity)}"')
            return f"<polygon {' '.join(attrs)}/>"

        case Label():
            baseline = {"top": "hanging", "middle": "central", "bottom": "auto"}[item.baseline]
            family = (
                theme.font_family(item.family) if theme is not None else "system-ui, sans-serif"
            )
            attrs = [
                f'x="{_fmt(item.x)}"',
                f'y="{_fmt(item.y)}"',
                f'font-size="{_fmt(item.size)}"',
                f'fill="{item.color}"',
                f'text-anchor="{item.anchor}"',
                f'dominant-baseline="{baseline}"',
                f'font-weight="{item.weight}"',
                f'font-family="{escape(family, quote=True)}"',
            ]
            if item.rotate:
                attrs.append(
                    f'transform="rotate({_fmt(item.rotate)} {_fmt(item.x)} {_fmt(item.y)})"'
                )
            if item.opacity < 1:
                attrs.append(f'opacity="{_fmt(item.opacity)}"')
            return f"<text {' '.join(attrs)}>{escape(item.text)}</text>"


def drawing_to_svg(
    drawing: Drawing,
    theme: Theme | None = None,
    *,
    class_name: str = "df-chart",
    preserve_aspect: str = "xMidYMid meet",
) -> str:
    """Render a whole :class:`Drawing` as a standalone ``<svg>`` element."""
    body = "".join(primitive_to_svg(item, theme) for item in drawing.items)
    return (
        f'<svg class="{class_name}" viewBox="0 0 {_fmt(drawing.width)} {_fmt(drawing.height)}" '
        f'preserveAspectRatio="{preserve_aspect}" width="100%" height="100%" '
        f'xmlns="http://www.w3.org/2000/svg" role="img">{body}</svg>'
    )
