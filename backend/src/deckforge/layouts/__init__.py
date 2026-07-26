"""Layout engine: geometry resolution and automatic layout selection."""

from deckforge.layouts.engine import LAYOUTS, LayoutEngine, register_layout
from deckforge.layouts.model import (
    Box,
    DecorPlacement,
    ElementPlacement,
    LayoutContext,
    LayoutDefinition,
    LayoutFrame,
    TextPlacement,
)

__all__ = [
    "LAYOUTS",
    "Box",
    "DecorPlacement",
    "ElementPlacement",
    "LayoutContext",
    "LayoutDefinition",
    "LayoutEngine",
    "LayoutFrame",
    "TextPlacement",
    "register_layout",
]
