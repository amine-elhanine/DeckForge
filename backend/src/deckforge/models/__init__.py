"""Domain models: the deck itself, the edit language, agent payloads, API schemas."""

from deckforge.models.deck import (
    Background,
    Box,
    ChartSpec,
    DeckMetadata,
    Element,
    Presentation,
    Reference,
    Section,
    Slide,
    new_id,
)
from deckforge.models.enums import (
    Align,
    AspectRatio,
    BulletStyle,
    ChartKind,
    ElementType,
    ExportFormat,
    Intent,
    MessageRole,
    SlideKind,
    TextRole,
)
from deckforge.models.ops import DeckOperation, OperationBatch, apply_operations

__all__ = [
    "Align",
    "AspectRatio",
    "Background",
    "Box",
    "BulletStyle",
    "ChartKind",
    "ChartSpec",
    "DeckMetadata",
    "DeckOperation",
    "Element",
    "ElementType",
    "ExportFormat",
    "Intent",
    "MessageRole",
    "OperationBatch",
    "Presentation",
    "Reference",
    "Section",
    "Slide",
    "SlideKind",
    "TextRole",
    "apply_operations",
    "new_id",
]
