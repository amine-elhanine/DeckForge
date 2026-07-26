"""Colour maths for theming, contrast checks and chart palettes."""

from __future__ import annotations

import colorsys
import re

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def parse_hex(value: str) -> tuple[int, int, int, float]:
    """Parse ``#rgb``/``#rrggbb``/``#rrggbbaa`` into ``(r, g, b, alpha)``."""
    match = _HEX_RE.match(value.strip())
    if not match:
        raise ValueError(f"invalid hex colour: {value!r}")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
    alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
    return r, g, b, alpha


def to_hex(r: float, g: float, b: float) -> str:
    """Clamp channels to 0-255 and format as ``#rrggbb``."""

    def clamp(value: float) -> int:
        return max(0, min(255, round(value)))

    return f"#{clamp(r):02x}{clamp(g):02x}{clamp(b):02x}"


def to_rgb_tuple(value: str) -> tuple[int, int, int]:
    r, g, b, _ = parse_hex(value)
    return r, g, b


def relative_luminance(value: str) -> float:
    """WCAG relative luminance of a hex colour."""
    r, g, b, _ = parse_hex(value)

    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two hex colours (1.0 – 21.0)."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def readable_on(background: str, light: str = "#ffffff", dark: str = "#111318") -> str:
    """Pick whichever of ``light``/``dark`` reads better on ``background``."""
    return light if contrast_ratio(light, background) >= contrast_ratio(dark, background) else dark


def mix(a: str, b: str, weight: float = 0.5) -> str:
    """Linear blend of two colours; ``weight`` is the share of ``b``."""
    ar, ag, ab, _ = parse_hex(a)
    br, bg, bb, _ = parse_hex(b)
    w = max(0.0, min(1.0, weight))
    return to_hex(ar + (br - ar) * w, ag + (bg - ag) * w, ab + (bb - ab) * w)


def lighten(value: str, amount: float = 0.15) -> str:
    return mix(value, "#ffffff", amount)


def darken(value: str, amount: float = 0.15) -> str:
    return mix(value, "#000000", amount)


def with_alpha(value: str, alpha: float) -> str:
    """Return an ``rgba()`` string — used in CSS backgrounds and overlays."""
    r, g, b, _ = parse_hex(value)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, alpha)):.3f})"


def rotate_hue(value: str, degrees: float) -> str:
    r, g, b, _ = parse_hex(value)
    h, ls, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    h = (h + degrees / 360.0) % 1.0
    nr, ng, nb = colorsys.hls_to_rgb(h, ls, s)
    return to_hex(nr * 255, ng * 255, nb * 255)


def build_palette(seed: str, count: int, spread: float = 32.0) -> list[str]:
    """Generate a harmonious categorical palette from a seed colour."""
    if count <= 0:
        return []
    palette = [seed]
    for i in range(1, count):
        shifted = rotate_hue(seed, spread * i)
        palette.append(lighten(shifted, 0.08 * (i % 3)))
    return palette[:count]


def ensure_contrast(fg: str, bg: str, minimum: float = 4.5) -> str:
    """Darken or lighten ``fg`` until it meets ``minimum`` contrast on ``bg``."""
    candidate = fg
    target_dark = relative_luminance(bg) > 0.5
    for _ in range(24):
        if contrast_ratio(candidate, bg) >= minimum:
            return candidate
        candidate = darken(candidate, 0.08) if target_dark else lighten(candidate, 0.08)
    return "#111318" if target_dark else "#ffffff"
