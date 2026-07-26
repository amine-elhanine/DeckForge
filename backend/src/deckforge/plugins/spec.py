"""The plugin contract.

A plugin is any importable module exposing ``register(registry: PluginRegistry)``.
It receives a facade over every extension point, so a plugin never imports
DeckForge internals it does not need and never has to know how the registries
are wired.

Example ``plugins/acme/__init__.py``::

    from deckforge.plugins import PluginRegistry, PluginManifest

    MANIFEST = PluginManifest(
        name="acme",
        version="1.0.0",
        description="Acme brand theme and a PNG exporter.",
    )


    def register(registry: PluginRegistry) -> None:
        registry.add_theme_directory(Path(__file__).parent / "themes")
        registry.add_exporter(PngExporter())
        registry.add_icon("acme-logo", "M2 2h20v20H2z")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deckforge.core.logging import get_logger
from deckforge.exporters.base import Exporter, register_exporter
from deckforge.layouts.engine import register_layout
from deckforge.layouts.model import LayoutDefinition
from deckforge.providers.registry import ProviderSpec, register_provider
from deckforge.renderers.icons import register_icon
from deckforge.retrieval.extractors import Extractor, register_extractor
from deckforge.themes.engine import register_theme
from deckforge.themes.model import Theme

log = get_logger(__name__)


@dataclass(slots=True)
class PluginManifest:
    """Metadata a plugin declares about itself."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    requires: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PluginRegistry:
    """The facade handed to every plugin's ``register`` function."""

    manifest: PluginManifest
    provides: dict[str, list[str]] = field(default_factory=dict)
    theme_directories: list[Path] = field(default_factory=list)

    def _record(self, kind: str, name: str) -> None:
        self.provides.setdefault(kind, []).append(name)
        log.info("plugin.registered", plugin=self.manifest.name, kind=kind, name=name)

    # -- extension points ---------------------------------------------------- #

    def add_provider(self, spec: ProviderSpec) -> None:
        """Register an LLM provider adapter."""
        register_provider(spec, override=True)
        self._record("providers", spec.cls.name)

    def add_theme(self, theme: Theme) -> None:
        """Register a theme built in Python."""
        register_theme(theme, override=True)
        self._record("themes", theme.name)

    def add_theme_directory(self, path: Path) -> None:
        """Register a directory of ``theme.json`` packages."""
        self.theme_directories.append(Path(path))
        self._record("theme_directories", str(path))

    def add_layout(self, definition: LayoutDefinition) -> None:
        """Register a layout."""
        register_layout(definition, override=True)
        self._record("layouts", definition.name)

    def add_exporter(self, exporter: Exporter) -> None:
        """Register an export format."""
        register_exporter(exporter, override=True)
        self._record("exporters", exporter.name)

    def add_extractor(self, extractor: Extractor) -> None:
        """Register a document extractor for retrieval."""
        register_extractor(extractor, override=True)
        self._record("extractors", ",".join(extractor.extensions))

    def add_icon(self, name: str, path: str) -> None:
        """Register an SVG icon (24×24 path data)."""
        register_icon(name, path, override=True)
        self._record("icons", name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "description": self.manifest.description,
            "provides": self.provides,
        }
