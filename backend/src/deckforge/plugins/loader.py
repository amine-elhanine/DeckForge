"""Plugin discovery and loading.

Two sources, both optional:

1. **Directories** — every subdirectory of ``DECKFORGE_PLUGIN_PATHS`` (and the
   repository's ``plugins/`` folder) containing an importable package.
2. **Entry points** — installed distributions advertising ``deckforge.plugins``.

A plugin that raises during registration is skipped with a warning; one bad
plugin must never take the application down.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from deckforge.core.logging import get_logger
from deckforge.plugins.spec import PluginManifest, PluginRegistry

log = get_logger(__name__)

ENTRY_POINT_GROUP = "deckforge.plugins"


@dataclass(slots=True)
class LoadedPlugin:
    registry: PluginRegistry
    module: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {**self.registry.as_dict(), "source": self.source}


@dataclass(slots=True)
class PluginManager:
    """Loads plugins and reports what they contributed."""

    search_paths: list[Path] = field(default_factory=list)
    loaded: list[LoadedPlugin] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def load_all(self) -> list[LoadedPlugin]:
        """Discover and register every available plugin."""
        self.loaded.clear()
        self.errors.clear()
        for path in self.search_paths:
            self._load_directory(path)
        self._load_entry_points()
        log.info("plugins.loaded", count=len(self.loaded), errors=len(self.errors))
        return self.loaded

    @property
    def theme_directories(self) -> list[Path]:
        """Theme directories contributed by plugins."""
        return [d for plugin in self.loaded for d in plugin.registry.theme_directories]

    # -- sources -------------------------------------------------------------- #

    def _load_directory(self, root: Path) -> None:
        if not root.exists() or not root.is_dir():
            return
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        for child in sorted(root.iterdir()):
            if child.name.startswith((".", "_")):
                continue
            module_path = child / "__init__.py" if child.is_dir() else child
            if child.is_dir() and not module_path.exists():
                continue
            if child.is_file() and child.suffix != ".py":
                continue
            self._register_module(child.stem, source=f"directory:{root.name}")

    def _load_entry_points(self) -> None:
        try:
            entry_points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
        except Exception as exc:  # pragma: no cover - packaging edge cases
            log.debug("plugins.entry_points_failed", error=str(exc))
            return
        for entry_point in entry_points:
            try:
                register = entry_point.load()
            except Exception as exc:
                self._record_error(entry_point.name, exc)
                continue
            self._invoke(entry_point.name, register, source="entry_point")

    # -- registration --------------------------------------------------------- #

    def _register_module(self, module_name: str, *, source: str) -> None:
        try:
            module: ModuleType = importlib.import_module(module_name)
        except Exception as exc:
            self._record_error(module_name, exc)
            return
        register = getattr(module, "register", None)
        if not callable(register):
            log.debug("plugins.no_register", module=module_name)
            return
        manifest = getattr(module, "MANIFEST", None)
        self._invoke(module_name, register, source=source, manifest=manifest)

    def _invoke(
        self,
        name: str,
        register: Callable[[PluginRegistry], None],
        *,
        source: str,
        manifest: PluginManifest | None = None,
    ) -> None:
        registry = PluginRegistry(manifest=manifest or PluginManifest(name=name))
        try:
            register(registry)
        except Exception as exc:
            self._record_error(name, exc)
            return
        self.loaded.append(LoadedPlugin(registry=registry, module=name, source=source))

    def _record_error(self, name: str, exc: Exception) -> None:
        log.warning("plugins.failed", plugin=name, error=str(exc))
        self.errors.append({"plugin": name, "error": str(exc)})

    def catalog(self) -> list[dict[str, Any]]:
        return [plugin.as_dict() for plugin in self.loaded]
