"""Small structural helpers shared across layers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into a copy of ``base``.

    Nested dictionaries are merged rather than replaced, which is what makes
    partial theme overrides (``{"palette": {"primary": "#f00"}}``) compose
    instead of wiping out every sibling key.
    """
    out = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out
