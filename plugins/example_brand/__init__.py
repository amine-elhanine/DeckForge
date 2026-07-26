"""Example plugin: a brand theme, a custom icon, a layout and an extra exporter.

Drop a directory like this one into ``plugins/`` (or any path listed in
``DECKFORGE_PLUGIN_PATHS``) and it loads at startup — no core code changes, no
registration file to edit.

Verify it loaded::

    curl http://localhost:8000/api/v1/plugins
"""

from __future__ import annotations

import json
from pathlib import Path

from deckforge.exporters.base import Exporter, ExportContext
from deckforge.layouts.builtin import header, new_frame, split_h, stack
from deckforge.layouts.model import LayoutContext, LayoutDefinition, LayoutFrame
from deckforge.models.deck import Presentation
from deckforge.models.enums import SlideKind
from deckforge.plugins import PluginManifest, PluginRegistry

MANIFEST = PluginManifest(
    name="example_brand",
    version="1.0.0",
    description="Reference plugin: brand theme, icon, layout and a JSON exporter.",
    author="DeckForge",
)


class JsonExporter(Exporter):
    """Exports the raw deck JSON — useful for backups and for diffing decks."""

    name = "json"
    label = "Deck JSON"
    extension = "json"
    media_type = "application/json"
    binary = False
    description = "The deck's source of truth, exactly as the agents see it."

    def render(self, deck: Presentation, context: ExportContext) -> bytes:
        indent = int(context.option("indent", 2))
        return json.dumps(deck.model_dump(mode="json"), indent=indent, ensure_ascii=False).encode()


def _sidebar(ctx: LayoutContext) -> LayoutFrame:
    """A narrow accent rail on the left with content on the right."""
    frame = new_frame(ctx, "brand_sidebar")
    rail, body = split_h(ctx.content_box(), 0.26, ctx.theme.spacing.gap * 1.5)
    texts, remaining = header(ctx, rail)
    frame.texts = texts
    frame.content_area = body
    frame.elements = stack(ctx.elements_for(), body, ctx.theme, valign="center")
    return frame


def register(registry: PluginRegistry) -> None:
    """Entry point called by the plugin loader."""
    registry.add_theme_directory(Path(__file__).parent / "themes")
    registry.add_exporter(JsonExporter())
    registry.add_icon(
        "acme-mark",
        "M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 8l4 2.2v4.4L12 17l-4-2.4v-4.4z",
    )
    registry.add_layout(
        LayoutDefinition(
            name="brand_sidebar",
            label="Brand sidebar",
            description="Title in a narrow left rail, content on the right.",
            builder=_sidebar,
            slots=["title", "body"],
            suits=[SlideKind.CONTENT],
            capacity=4,
            tags=["brand"],
        )
    )
