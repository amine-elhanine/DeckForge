"""A small, local, dependency-free icon set.

Icons ship as 24×24 stroke paths so they inherit the theme's accent colour and
stroke weight. Everything is offline — no icon CDN, no font download. Plugins
register additional icons through :func:`register_icon`.
"""

from __future__ import annotations

from deckforge.core.registry import Registry

ICONS: Registry[str] = Registry("icon")
"""name -> SVG path data on a 24×24 grid."""

_BUILTIN: dict[str, str] = {
    # general
    "sparkle": "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z",
    "star": "M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z",
    "check": "M4 12.5l5 5L20 6.5",
    "close": "M6 6l12 12M18 6L6 18",
    "plus": "M12 5v14M5 12h14",
    "minus": "M5 12h14",
    "arrow-right": "M4 12h15m-6-6l6 6-6 6",
    "arrow-up-right": "M7 17L17 7m-7 0h7v7",
    "arrow-down": "M12 4v15m-6-6l6 6 6-6",
    "chevron-right": "M9 5l7 7-7 7",
    "refresh": "M20 11a8 8 0 10-2.3 6M20 5v6h-6",
    "external": "M14 4h6v6M20 4L11 13M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5",
    # people & org
    "user": "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 3.6-6 8-6s8 2 8 6",
    "users": "M9 12a4 4 0 100-8 4 4 0 000 8zM2 21c0-4 3.2-6 7-6s7 2 7 6M17 5a3.5 3.5 0 010 7M18 21c0-3-1-4.6-2.5-5.6",
    "handshake": "M3 12l4-4 3 3 2-2 3 3 4-4M3 12l4 4 3-3 2 2 3-3 4 4",
    "team": "M12 8a3 3 0 100-6 3 3 0 000 6zM5 21v-3a4 4 0 014-4h6a4 4 0 014 4v3",
    # business
    "target": "M12 21a9 9 0 100-18 9 9 0 000 18zM12 16a4 4 0 100-8 4 4 0 000 8zM12 13a1 1 0 100-2 1 1 0 000 2z",
    "trend-up": "M3 17l6-6 4 4 8-8m0 0h-6m6 0v6",
    "trend-down": "M3 7l6 6 4-4 8 8m0 0h-6m6 0v-6",
    "chart-bar": "M4 20V10m5 10V4m5 16v-7m5 7V8",
    "chart-pie": "M12 3v9h9a9 9 0 11-9-9z",
    "growth": "M4 20h16M7 20V9m5 11V4m5 16v-7",
    "coins": "M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
    "briefcase": "M4 8h16a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V9a1 1 0 011-1zM9 8V5a1 1 0 011-1h4a1 1 0 011 1v3",
    "scale": "M12 4v16M6 8l-3 6h6zM18 8l-3 6h6zM6 8h12",
    # tech
    "cpu": "M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3M6 6h12v12H6zM10 10h4v4h-4z",
    "database": "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6",
    "cloud": "M7 18a4 4 0 010-8 5.5 5.5 0 0110.5 1.5A3.5 3.5 0 0117 18z",
    "code": "M9 6l-6 6 6 6M15 6l6 6-6 6",
    "terminal": "M4 5h16a1 1 0 011 1v12a1 1 0 01-1 1H4a1 1 0 01-1-1V6a1 1 0 011-1zM7 9l3 3-3 3M13 15h4",
    "server": "M4 4h16v6H4zM4 14h16v6H4zM7 7h.01M7 17h.01",
    "network": "M12 8a2 2 0 100-4 2 2 0 000 4zM5 20a2 2 0 100-4 2 2 0 000 4zM19 20a2 2 0 100-4 2 2 0 000 4zM12 8v4M12 12l-6 4M12 12l6 4",
    "shield": "M12 3l8 3v6c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V6z",
    "lock": "M6 11h12v9H6zM9 11V8a3 3 0 016 0v3",
    "key": "M15 4a5 5 0 11-3.5 8.5L4 20v-3h3v-3h3l1.5-1.5A5 5 0 0115 4z",
    "bug": "M9 6a3 3 0 016 0M6 10h12v4a6 6 0 01-12 0zM3 12h3M18 12h3M5 7l2 2M19 7l-2 2M5 18l2-2M19 18l-2-2",
    "rocket": "M12 3s4 2 4 8c0 3-1.5 5-4 7-2.5-2-4-4-4-7 0-6 4-8 4-8zM12 11a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM8 15l-3 3 3 .5.5 3 3-3M16 15l3 3-3 .5-.5 3-3-3",
    "gear": "M12 15a3 3 0 100-6 3 3 0 000 6zM12 2v3M12 19v3M4.2 4.2l2.2 2.2M17.6 17.6l2.2 2.2M2 12h3M19 12h3M4.2 19.8l2.2-2.2M17.6 6.4l2.2-2.2",
    "layers": "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5",
    "puzzle": "M10 4h4v2a2 2 0 104 0V4h2v6h-2a2 2 0 100 4h2v6h-6v-2a2 2 0 10-4 0v2H4v-6h2a2 2 0 100-4H4V4h6z",
    # knowledge
    "book": "M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2zM19 3v18",
    "lightbulb": "M9 18h6M10 21h4M12 3a6 6 0 013.5 10.9c-.6.5-.9 1.2-.9 1.9v.2H9.4v-.2c0-.7-.3-1.4-.9-1.9A6 6 0 0112 3z",
    "brain": "M9 4a3 3 0 00-3 3 3 3 0 00-1 5.8A3 3 0 007 18a3 3 0 005 1.5V5.5A3 3 0 009 4zM15 4a3 3 0 013 3 3 3 0 011 5.8A3 3 0 0117 18a3 3 0 01-5 1.5",
    "graduation": "M12 4l10 5-10 5L2 9zM6 12v5c0 1.5 3 3 6 3s6-1.5 6-3v-5",
    "search": "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.3-4.3",
    "document": "M14 3H7a1 1 0 00-1 1v16a1 1 0 001 1h10a1 1 0 001-1V7zM14 3v4h4M9 13h6M9 17h4",
    "clipboard": "M9 4h6v3H9zM8 5H6a1 1 0 00-1 1v14a1 1 0 001 1h12a1 1 0 001-1V6a1 1 0 00-1-1h-2",
    "quote": "M9 7c-3 1-4 3.5-4 6.5V18h6v-6H7c0-2 .7-3.4 2-4zM19 7c-3 1-4 3.5-4 6.5V18h6v-6h-4c0-2 .7-3.4 2-4z",
    # time & process
    "clock": "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
    "calendar": "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
    "flag": "M5 21V4h13l-2.5 4L18 12H5",
    "milestone": "M5 21V3M5 5h11l3 3.5-3 3.5H5",
    "route": "M6 20a2 2 0 100-4 2 2 0 000 4zM18 8a2 2 0 100-4 2 2 0 000 4zM18 8v3a4 4 0 01-4 4h-4a4 4 0 00-4 4",
    "hourglass": "M7 3h10v3l-5 6 5 6v3H7v-3l5-6-5-6z",
    # misc content
    "globe": "M12 21a9 9 0 100-18 9 9 0 000 18zM3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9S14.5 18.5 12 21c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z",
    "map-pin": "M12 21s7-5.5 7-11a7 7 0 10-14 0c0 5.5 7 11 7 11zM12 13a3 3 0 100-6 3 3 0 000 6z",
    "mail": "M4 5h16a1 1 0 011 1v12a1 1 0 01-1 1H4a1 1 0 01-1-1V6a1 1 0 011-1zM3 7l9 6 9-6",
    "phone": "M6 3h3l2 5-2.5 1.5a12 12 0 006 6L16 13l5 2v3a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2z",
    "warning": "M12 4l9 16H3zM12 10v4M12 17h.01",
    "info": "M12 21a9 9 0 100-18 9 9 0 000 18zM12 11v6M12 7.5h.01",
    "heart": "M12 20s-7-4.4-7-9.2A4 4 0 0112 8a4 4 0 017 2.8C19 15.6 12 20 12 20z",
    "leaf": "M4 20C4 10 12 4 20 4c0 9-5.5 15-13 15H4zM4 20c3-4 6-6 10-7",
    "eye": "M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6zM12 15a3 3 0 100-6 3 3 0 000 6z",
    "filter": "M3 5h18l-7 8v6l-4 2v-8z",
    "grid": "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    "play": "M8 5l11 7-11 7z",
}

for _name, _path in _BUILTIN.items():
    ICONS.register(_name, _path)

#: Fallback used when a model invents an icon name.
FALLBACK_ICON = "sparkle"

#: Keyword hints so the visual designer can map concepts to icons.
KEYWORD_MAP: dict[str, str] = {
    "goal": "target",
    "objective": "target",
    "kpi": "target",
    "growth": "trend-up",
    "increase": "trend-up",
    "revenue": "coins",
    "cost": "coins",
    "budget": "coins",
    "finance": "coins",
    "money": "coins",
    "risk": "warning",
    "problem": "warning",
    "challenge": "warning",
    "idea": "lightbulb",
    "innovation": "lightbulb",
    "insight": "lightbulb",
    "ai": "brain",
    "model": "brain",
    "learning": "brain",
    "research": "search",
    "data": "database",
    "dataset": "database",
    "storage": "database",
    "cloud": "cloud",
    "infrastructure": "server",
    "api": "code",
    "code": "code",
    "security": "shield",
    "privacy": "lock",
    "auth": "key",
    "team": "users",
    "people": "users",
    "customer": "user",
    "user": "user",
    "partner": "handshake",
    "timeline": "clock",
    "schedule": "calendar",
    "milestone": "milestone",
    "roadmap": "route",
    "process": "refresh",
    "education": "graduation",
    "training": "graduation",
    "document": "document",
    "reference": "book",
    "quote": "quote",
    "global": "globe",
    "market": "globe",
    "location": "map-pin",
    "contact": "mail",
    "health": "heart",
    "sustainability": "leaf",
    "compliance": "clipboard",
    "architecture": "layers",
    "integration": "puzzle",
    "performance": "chart-bar",
    "analysis": "chart-pie",
    "launch": "rocket",
    "start": "play",
    "settings": "gear",
    "network": "network",
}


def register_icon(name: str, path: str, *, override: bool = True) -> None:
    """Register an SVG path under ``name`` (24×24 view box)."""
    ICONS.register(name, path, override=override)


def get_icon(name: str | None) -> str:
    """Return path data for ``name``, falling back to a neutral icon."""
    if not name:
        return ICONS.get(FALLBACK_ICON)
    key = name.strip().lower().replace(" ", "-").replace("_", "-")
    return ICONS.try_get(key) or ICONS.try_get(KEYWORD_MAP.get(key, "")) or ICONS.get(FALLBACK_ICON)


def suggest_icon(text: str) -> str:
    """Best-effort concept -> icon mapping used by the visual designer agent."""
    lowered = text.lower()
    for keyword, icon in KEYWORD_MAP.items():
        if keyword in lowered:
            return icon
    return FALLBACK_ICON


def icon_svg(name: str | None, color: str, *, size: str = "100%", stroke: float = 1.8) -> str:
    """Return an inline SVG element for ``name``.

    ``size`` is a CSS length, not a pixel count: slide geometry is expressed in
    canvas units that scale with the container, so callers pass something like
    ``calc(28 * var(--df-u))`` rather than ``28``.
    """
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true" style="display:block;flex:none;">'
        f'<path d="{get_icon(name)}"/></svg>'
    )


def available() -> list[str]:
    return ICONS.names()
