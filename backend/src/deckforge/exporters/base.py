"""Exporter interface and registry.

An exporter turns the deck JSON into bytes. Adding a format means writing one
class and registering it — the API, the UI menu and the export history pick it up
automatically from the registry.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deckforge.core.registry import Registry
from deckforge.layouts.engine import LayoutEngine
from deckforge.models.deck import Presentation
from deckforge.renderers.html import HtmlRenderer
from deckforge.themes.model import Theme
from deckforge.utils.text import slugify


@dataclass(slots=True)
class ExportContext:
    """Shared services and options handed to every exporter."""

    theme: Theme
    layouts: LayoutEngine
    renderer: HtmlRenderer
    assets_dir: Path | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def option(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    def resolve_asset(self, src: str) -> Path | None:
        """Map an element ``src`` onto a local file, when one exists."""
        if not src or src.startswith(("http://", "https://", "data:")):
            return None
        if self.assets_dir is None:
            return None
        candidate = (self.assets_dir / src).resolve()
        try:
            candidate.relative_to(self.assets_dir.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None


@dataclass(slots=True)
class ExportResult:
    """What an exporter produced."""

    content: bytes
    filename: str
    media_type: str

    @property
    def size(self) -> int:
        return len(self.content)


class Exporter(abc.ABC):
    """Base class for all exporters."""

    #: Registry key used in the API (``?format=pptx``).
    name: str = "base"
    label: str = "Base"
    extension: str = "bin"
    media_type: str = "application/octet-stream"
    #: False for text formats, which are decoded for preview in the UI.
    binary: bool = True
    description: str = ""

    @abc.abstractmethod
    def render(self, deck: Presentation, context: ExportContext) -> bytes:
        """Produce the file body."""

    def filename_for(self, deck: Presentation) -> str:
        return f"{slugify(deck.title) or 'presentation'}.{self.extension}"

    def export(self, deck: Presentation, context: ExportContext) -> ExportResult:
        """Render ``deck`` and wrap it with filename/media-type metadata."""
        return ExportResult(
            content=self.render(deck, context),
            filename=self.filename_for(deck),
            media_type=self.media_type,
        )


EXPORTERS: Registry[Exporter] = Registry("exporter")
"""Global exporter registry; plugins add formats here."""


def register_exporter(exporter: Exporter, *, override: bool = False) -> Exporter:
    return EXPORTERS.register(exporter.name, exporter, override=override)


def exporter_catalog() -> list[dict[str, Any]]:
    """Metadata for the export menu."""
    return [
        {
            "name": name,
            "label": EXPORTERS.get(name).label,
            "extension": EXPORTERS.get(name).extension,
            "media_type": EXPORTERS.get(name).media_type,
            "binary": EXPORTERS.get(name).binary,
            "description": EXPORTERS.get(name).description,
        }
        for name in EXPORTERS.names()
    ]
