"""Renderers turn deck JSON + layout geometry into concrete visual output."""

from deckforge.renderers.charts import render_chart
from deckforge.renderers.html import HtmlRenderer
from deckforge.renderers.icons import ICONS, get_icon, icon_svg, register_icon, suggest_icon
from deckforge.renderers.primitives import Drawing
from deckforge.renderers.svg import drawing_to_svg

__all__ = [
    "ICONS",
    "Drawing",
    "HtmlRenderer",
    "drawing_to_svg",
    "get_icon",
    "icon_svg",
    "register_icon",
    "render_chart",
    "suggest_icon",
]
