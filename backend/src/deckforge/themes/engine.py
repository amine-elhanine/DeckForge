"""Theme engine — discovery, inheritance and resolution.

Themes are discovered from three sources, in increasing priority:

1. built-in packages shipped in ``deckforge/themes/packages``
2. extra directories listed in ``DECKFORGE_THEME_PATHS``
3. themes registered programmatically by plugins, or stored in the database

A theme package is a directory containing ``theme.json``. An ``extends`` key
pulls in another theme as a base, so a brand variant is a ten-line file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deckforge.core.errors import NotFoundError, ValidationError
from deckforge.core.logging import get_logger
from deckforge.core.registry import Registry
from deckforge.models.deck import Presentation
from deckforge.themes.model import Theme, deep_merge

log = get_logger(__name__)

THEME_FILE = "theme.json"

THEMES: Registry[Theme] = Registry("theme")
"""Programmatically registered themes (plugins). Merged with filesystem themes."""


def register_theme(theme: Theme, *, override: bool = True) -> Theme:
    """Register a theme built in Python (used by plugins)."""
    return THEMES.register(theme.name, theme, override=override)


class ThemeEngine:
    """Loads themes from disk and resolves them for a deck."""

    def __init__(self, search_paths: list[Path], *, fallback: str = "minimal") -> None:
        self._search_paths = [p for p in search_paths if p]
        self._fallback = fallback
        self._raw: dict[str, dict[str, Any]] = {}
        self._resolved: dict[str, Theme] = {}
        self._sources: dict[str, str] = {}
        self.reload()

    # -- discovery ---------------------------------------------------------- #

    def reload(self) -> None:
        """Rescan every search path. Safe to call at runtime."""
        self._raw.clear()
        self._resolved.clear()
        self._sources.clear()
        for root in self._search_paths:
            if not root.exists():
                continue
            for definition_file in sorted(root.glob(f"*/{THEME_FILE}")):
                self._load_file(definition_file, source=root.name)
        log.info("themes.loaded", count=len(self._raw), names=sorted(self._raw))

    def _load_file(self, path: Path, source: str) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("themes.invalid", path=str(path), error=str(exc))
            return
        name = str(data.get("name") or path.parent.name).lower()
        data["name"] = name
        self._raw[name] = data
        self._sources[name] = source

    def add_definition(
        self, name: str, definition: dict[str, Any], source: str = "database"
    ) -> None:
        """Register a raw theme definition (from the database or an API call)."""
        key = name.lower()
        self._raw[key] = {**definition, "name": key}
        self._sources[key] = source
        self._resolved.pop(key, None)

    # -- resolution --------------------------------------------------------- #

    def _resolve_raw(self, name: str, _seen: frozenset[str] = frozenset()) -> dict[str, Any]:
        """Flatten a theme's ``extends`` chain into a single definition."""
        key = name.lower()
        if key in _seen:
            raise ValidationError(f"circular theme inheritance at '{key}'")
        data = self._raw.get(key)
        if data is None:
            raise NotFoundError(f"unknown theme '{name}'", details={"available": self.names()})
        parent_name = data.get("extends")
        if not parent_name:
            return data
        parent = self._resolve_raw(str(parent_name), _seen | {key})
        merged = deep_merge(parent, {k: v for k, v in data.items() if k != "extends"})
        merged["name"] = key
        return merged

    def get(self, name: str | None) -> Theme:
        """Return a fully resolved theme, falling back to the default on miss."""
        key = (name or self._fallback).lower()
        if key in self._resolved:
            return self._resolved[key]

        plugin_theme = THEMES.try_get(key)
        if plugin_theme is not None:
            self._resolved[key] = plugin_theme
            self._sources.setdefault(key, "plugin")
            return plugin_theme

        if key not in self._raw:
            if key == self._fallback:
                # Nothing on disk at all — keep the app usable with library defaults.
                theme = Theme(name=self._fallback, label="Minimal", source="fallback")
                self._resolved[key] = theme
                return theme
            log.warning("themes.missing", requested=key, fallback=self._fallback)
            return self.get(self._fallback)

        theme = Theme.model_validate(self._resolve_raw(key))
        theme.source = self._sources.get(key, "builtin")
        self._resolved[key] = theme
        return theme

    def for_deck(self, deck: Presentation) -> Theme:
        """Resolve the theme for a deck, applying its ``theme_overrides``."""
        return self.get(deck.theme).merged(deck.theme_overrides)

    def for_slide(self, deck: Presentation, slide_index: int) -> Theme:
        """Resolve the theme for one slide, applying slide-level overrides on top."""
        theme = self.for_deck(deck)
        if 0 <= slide_index < len(deck.slides):
            slide = deck.slides[slide_index]
            if slide.theme_overrides:
                return theme.merged(slide.theme_overrides)
        return theme

    # -- introspection ------------------------------------------------------ #

    def names(self) -> list[str]:
        return sorted(set(self._raw) | set(THEMES.names()))

    def catalog(self) -> list[dict[str, Any]]:
        """Summaries for the theme picker."""
        out: list[dict[str, Any]] = []
        for name in self.names():
            try:
                theme = self.get(name)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("themes.catalog_failed", theme=name, error=str(exc))
                continue
            out.append(
                {
                    "name": theme.name,
                    "label": theme.label,
                    "description": theme.description,
                    "tags": theme.tags,
                    "mode": theme.mode,
                    "source": theme.source,
                    "palette": {
                        "background": theme.palette.background,
                        "surface": theme.palette.surface,
                        "text": theme.palette.text,
                        "primary": theme.palette.primary,
                        "secondary": theme.palette.secondary,
                        "accent": theme.palette.accent,
                    },
                    "fonts": {
                        "heading": theme.fonts.heading,
                        "body": theme.fonts.body,
                    },
                }
            )
        return out

    def suggest(self, keywords: list[str], limit: int = 5) -> list[str]:
        """Rank themes by tag/description overlap with ``keywords``."""
        wanted = {k.lower() for k in keywords if k}
        scored: list[tuple[int, str]] = []
        for name in self.names():
            theme = self.get(name)
            haystack = {t.lower() for t in theme.tags} | set(theme.description.lower().split())
            score = len(wanted & haystack) + (2 if name in wanted else 0)
            scored.append((score, name))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [name for score, name in scored if score > 0][:limit] or self.names()[:limit]
