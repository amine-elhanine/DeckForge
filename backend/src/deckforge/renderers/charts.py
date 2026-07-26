"""Chart rendering: :class:`ChartSpec` to vector primitives.

One implementation drives every output format. HTML turns the primitives into
SVG; the PDF exporter replays them as fpdf2 drawing calls; PPTX uses a native
Office chart instead so the numbers stay editable in PowerPoint.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from deckforge.models.deck import ChartSpec
from deckforge.models.enums import ChartKind
from deckforge.renderers.primitives import (
    Drawing,
    Ellipse,
    Label,
    Line,
    Polyline,
    Rect,
    Wedge,
    axis_ticks,
    nice_ceiling,
)
from deckforge.themes.model import Theme
from deckforge.utils import colors
from deckforge.utils import text as textutil

AXIS_LEFT = 62.0
AXIS_BOTTOM = 46.0
LEGEND_HEIGHT = 32.0
TOP_PAD = 18.0
RIGHT_PAD = 18.0


def series_colors(spec: ChartSpec, theme: Theme) -> list[str]:
    """Resolve the colour for each series, honouring explicit overrides."""
    palette = spec.palette or theme.chart_palette or theme.palette.chart_defaults(6)
    out: list[str] = []
    for i, series in enumerate(spec.series):
        out.append(series.color or palette[i % len(palette)])
    return out


def category_colors(spec: ChartSpec, theme: Theme, count: int) -> list[str]:
    palette = spec.palette or theme.chart_palette or theme.palette.chart_defaults(max(1, count))
    return [palette[i % len(palette)] for i in range(count)]


def format_value(spec: ChartSpec, value: float) -> str:
    try:
        return spec.value_format.format(value)
    except ValueError, KeyError, IndexError:
        return f"{value:,.0f}"


def render_chart(spec: ChartSpec, width: float, height: float, theme: Theme) -> Drawing:
    """Render ``spec`` into a :class:`Drawing` sized ``width`` × ``height``."""
    drawing = Drawing(width, height)
    if not spec.series or not any(s.values for s in spec.series):
        drawing.add(Label("No data", width / 2, height / 2, 16, theme.palette.text_muted, "middle"))
        return drawing

    match spec.kind:
        case ChartKind.PIE | ChartKind.DONUT:
            _radial(drawing, spec, theme, donut=spec.kind is ChartKind.DONUT)
        case ChartKind.BAR:
            _bars(drawing, spec, theme, horizontal=True)
        case ChartKind.STACKED_BAR:
            _bars(drawing, spec, theme, horizontal=False, stacked=True)
        case ChartKind.LINE | ChartKind.AREA:
            _lines(drawing, spec, theme, area=spec.kind is ChartKind.AREA)
        case ChartKind.SCATTER:
            _scatter(drawing, spec, theme)
        case ChartKind.RADAR:
            _radar(drawing, spec, theme)
        case _:
            _bars(drawing, spec, theme, horizontal=False, stacked=spec.stacked)
    return drawing


# --------------------------------------------------------------------------- #
# Cartesian helpers
# --------------------------------------------------------------------------- #


def _plot_box(drawing: Drawing, spec: ChartSpec) -> tuple[float, float, float, float]:
    """Return ``(x, y, width, height)`` of the plotting area."""
    legend = LEGEND_HEIGHT if (spec.legend and len(spec.series) > 1) else 0.0
    x = AXIS_LEFT
    y = TOP_PAD
    w = max(40.0, drawing.width - AXIS_LEFT - RIGHT_PAD)
    h = max(40.0, drawing.height - TOP_PAD - AXIS_BOTTOM - legend)
    return x, y, w, h


def _draw_axes(
    drawing: Drawing,
    spec: ChartSpec,
    theme: Theme,
    box: tuple[float, float, float, float],
    maximum: float,
    *,
    horizontal: bool = False,
) -> None:
    """Grid lines, value labels and the baseline."""
    x, y, w, h = box
    grid = colors.with_alpha(theme.palette.text_muted, 0.18)
    label_color = theme.palette.text_muted
    ticks = axis_ticks(maximum)

    for tick in ticks:
        ratio = tick / ticks[-1] if ticks[-1] else 0.0
        if horizontal:
            gx = x + w * ratio
            drawing.add(Line(gx, y, gx, y + h, grid, 1.0))
            drawing.add(Label(format_value(spec, tick), gx, y + h + 8, 11, label_color, "middle"))
        else:
            gy = y + h - h * ratio
            drawing.add(Line(x, gy, x + w, gy, grid, 1.0))
            drawing.add(
                Label(
                    format_value(spec, tick), x - 10, gy, 11, label_color, "end", baseline="middle"
                )
            )

    drawing.add(Line(x, y + h, x + w, y + h, colors.with_alpha(theme.palette.text_muted, 0.4), 1.2))
    if spec.y_label and not horizontal:
        drawing.add(Label(spec.y_label, x - 46, y + h / 2, 11, label_color, "middle", rotate=-90))
    if spec.x_label:
        drawing.add(Label(spec.x_label, x + w / 2, y + h + 26, 11, label_color, "middle"))


def _draw_legend(drawing: Drawing, spec: ChartSpec, theme: Theme, palette: Sequence[str]) -> None:
    if not spec.legend or len(spec.series) <= 1:
        return
    y = drawing.height - LEGEND_HEIGHT / 2
    swatch = 11.0
    entries = [(s.name, palette[i]) for i, s in enumerate(spec.series)]
    widths = [swatch + 6 + len(name) * 6.4 + 22 for name, _ in entries]
    total = sum(widths)
    x = max(AXIS_LEFT, (drawing.width - total) / 2)
    for (name, colour), width in zip(entries, widths, strict=True):
        drawing.add(Rect(x, y - swatch / 2, swatch, swatch, colour, radius=2.5))
        drawing.add(
            Label(name, x + swatch + 6, y, 12, theme.palette.text_muted, "start", baseline="middle")
        )
        x += width


def _series_max(spec: ChartSpec, *, stacked: bool) -> float:
    if stacked and spec.categories:
        totals = [
            sum(s.values[i] if i < len(s.values) else 0.0 for s in spec.series)
            for i in range(len(spec.categories))
        ]
        return max(totals) if totals else 1.0
    return max((max(s.values) for s in spec.series if s.values), default=1.0)


# --------------------------------------------------------------------------- #
# Chart types
# --------------------------------------------------------------------------- #


def _bars(
    drawing: Drawing,
    spec: ChartSpec,
    theme: Theme,
    *,
    horizontal: bool,
    stacked: bool = False,
) -> None:
    palette = series_colors(spec, theme)
    box = _plot_box(drawing, spec)
    x, y, w, h = box
    categories = spec.categories or [f"#{i + 1}" for i in range(len(spec.series[0].values))]
    maximum = nice_ceiling(_series_max(spec, stacked=stacked))
    group_count = len(categories)
    series_count = 1 if stacked else len(spec.series)

    _draw_axes(drawing, spec, theme, box, maximum, horizontal=horizontal)

    if horizontal:
        group_h = h / max(1, group_count)
        bar_h = group_h * 0.66 / series_count
        for ci, category in enumerate(categories):
            top = y + ci * group_h + (group_h - bar_h * series_count) / 2
            for si, series in enumerate(spec.series):
                value = series.values[ci] if ci < len(series.values) else 0.0
                length = w * (value / maximum) if maximum else 0.0
                drawing.add(
                    Rect(x, top + si * bar_h, max(1.0, length), bar_h * 0.88, palette[si], radius=3)
                )
            drawing.add(
                Label(
                    textutil.truncate(category, 22),
                    x - 10,
                    top + group_h * 0.32,
                    12,
                    theme.palette.text_muted,
                    "end",
                    baseline="middle",
                )
            )
        return

    group_w = w / max(1, group_count)
    bar_w = group_w * 0.62 / series_count
    for ci, category in enumerate(categories):
        left = x + ci * group_w + (group_w - bar_w * series_count) / 2
        if stacked:
            cursor = y + h
            for si, series in enumerate(spec.series):
                value = series.values[ci] if ci < len(series.values) else 0.0
                height = h * (value / maximum) if maximum else 0.0
                cursor -= height
                drawing.add(Rect(left, cursor, max(2.0, bar_w), max(1.0, height), palette[si]))
        else:
            for si, series in enumerate(spec.series):
                value = series.values[ci] if ci < len(series.values) else 0.0
                height = h * (value / maximum) if maximum else 0.0
                drawing.add(
                    Rect(
                        left + si * bar_w,
                        y + h - height,
                        max(2.0, bar_w * 0.9),
                        max(1.0, height),
                        palette[si],
                        radius=4,
                    )
                )
        drawing.add(
            Label(
                textutil.truncate(category, 16),
                x + ci * group_w + group_w / 2,
                y + h + 8,
                12,
                theme.palette.text_muted,
                "middle",
            )
        )
    _draw_legend(drawing, spec, theme, palette)


def _lines(drawing: Drawing, spec: ChartSpec, theme: Theme, *, area: bool) -> None:
    palette = series_colors(spec, theme)
    box = _plot_box(drawing, spec)
    x, y, w, h = box
    categories = spec.categories or [f"#{i + 1}" for i in range(len(spec.series[0].values))]
    maximum = nice_ceiling(_series_max(spec, stacked=False))
    _draw_axes(drawing, spec, theme, box, maximum)

    steps = max(1, len(categories) - 1)
    for si, series in enumerate(spec.series):
        points: list[tuple[float, float]] = []
        for i in range(len(categories)):
            value = series.values[i] if i < len(series.values) else 0.0
            px = x + (w * i / steps if steps else w / 2)
            py = y + h - (h * value / maximum if maximum else 0.0)
            points.append((px, py))
        if area:
            polygon = [*points, (points[-1][0], y + h), (points[0][0], y + h)]
            drawing.add(
                Polyline(
                    polygon,
                    fill=colors.with_alpha(palette[si], 0.22),
                    closed=True,
                    stroke=None,
                    stroke_width=0,
                )
            )
        drawing.add(Polyline(points, stroke=palette[si], stroke_width=2.6))
        for px, py in points:
            drawing.add(Ellipse(px, py, 3.6, 3.6, palette[si]))

    for i, category in enumerate(categories):
        px = x + (w * i / steps if steps else w / 2)
        drawing.add(
            Label(
                textutil.truncate(category, 14),
                px,
                y + h + 8,
                12,
                theme.palette.text_muted,
                "middle",
            )
        )
    _draw_legend(drawing, spec, theme, palette)


def _scatter(drawing: Drawing, spec: ChartSpec, theme: Theme) -> None:
    palette = series_colors(spec, theme)
    box = _plot_box(drawing, spec)
    x, y, w, h = box
    maximum = nice_ceiling(_series_max(spec, stacked=False))
    _draw_axes(drawing, spec, theme, box, maximum)
    count = max(1, *(len(s.values) for s in spec.series))
    for si, series in enumerate(spec.series):
        for i, value in enumerate(series.values):
            px = x + w * (i / max(1, count - 1)) if count > 1 else x + w / 2
            py = y + h - (h * value / maximum if maximum else 0.0)
            drawing.add(Ellipse(px, py, 6, 6, palette[si], opacity=0.85))
    _draw_legend(drawing, spec, theme, palette)


def _radial(drawing: Drawing, spec: ChartSpec, theme: Theme, *, donut: bool) -> None:
    series = spec.series[0]
    values = [max(0.0, v) for v in series.values]
    total = sum(values) or 1.0
    categories = spec.categories or [f"#{i + 1}" for i in range(len(values))]
    palette = category_colors(spec, theme, len(values))

    legend_w = min(260.0, drawing.width * 0.34) if spec.legend else 0.0
    chart_w = drawing.width - legend_w
    radius = min(chart_w, drawing.height) / 2 - 18
    cx, cy = chart_w / 2, drawing.height / 2

    angle = 0.0
    for i, value in enumerate(values):
        sweep = 360.0 * value / total
        drawing.add(
            Wedge(
                cx,
                cy,
                radius,
                angle,
                angle + sweep,
                palette[i],
                inner_radius=radius * 0.58 if donut else 0.0,
                stroke=theme.palette.background,
                stroke_width=2,
            )
        )
        angle += sweep

    if donut:
        drawing.add(
            Label(
                format_value(spec, total),
                cx,
                cy - 6,
                22,
                theme.palette.text,
                "middle",
                weight=700,
                family="heading",
                baseline="middle",
            )
        )
        drawing.add(
            Label("total", cx, cy + 18, 12, theme.palette.text_muted, "middle", baseline="middle")
        )

    if spec.legend:
        lx = chart_w + 12
        ly = max(20.0, cy - len(values) * 13)
        for i, category in enumerate(categories):
            share = 100 * values[i] / total
            drawing.add(Rect(lx, ly - 5, 11, 11, palette[i], radius=2.5))
            drawing.add(
                Label(
                    f"{textutil.truncate(category, 20)}  {share:.0f}%",
                    lx + 18,
                    ly,
                    12,
                    theme.palette.text_muted,
                    "start",
                    baseline="middle",
                )
            )
            ly += 26


def _radar(drawing: Drawing, spec: ChartSpec, theme: Theme) -> None:
    palette = series_colors(spec, theme)
    categories = spec.categories or [f"#{i + 1}" for i in range(len(spec.series[0].values))]
    axes = max(3, len(categories))
    radius = min(drawing.width, drawing.height) / 2 - 46
    cx, cy = drawing.width / 2, drawing.height / 2
    maximum = nice_ceiling(_series_max(spec, stacked=False))
    grid = colors.with_alpha(theme.palette.text_muted, 0.22)

    for ring in (0.25, 0.5, 0.75, 1.0):
        points = [
            (
                cx + radius * ring * math.cos(math.radians(-90 + 360 * i / axes)),
                cy + radius * ring * math.sin(math.radians(-90 + 360 * i / axes)),
            )
            for i in range(axes)
        ]
        drawing.add(Polyline(points, stroke=grid, stroke_width=1, closed=True))

    for si, series in enumerate(spec.series):
        points = []
        for i in range(axes):
            value = series.values[i] if i < len(series.values) else 0.0
            r = radius * (value / maximum if maximum else 0.0)
            points.append(
                (
                    cx + r * math.cos(math.radians(-90 + 360 * i / axes)),
                    cy + r * math.sin(math.radians(-90 + 360 * i / axes)),
                )
            )
        drawing.add(
            Polyline(
                points,
                stroke=palette[si],
                stroke_width=2.4,
                fill=colors.with_alpha(palette[si], 0.18),
                closed=True,
            )
        )

    for i, category in enumerate(categories[:axes]):
        angle = math.radians(-90 + 360 * i / axes)
        drawing.add(
            Label(
                textutil.truncate(category, 14),
                cx + (radius + 20) * math.cos(angle),
                cy + (radius + 20) * math.sin(angle),
                12,
                theme.palette.text_muted,
                "middle",
                baseline="middle",
            )
        )
    _draw_legend(drawing, spec, theme, palette)
