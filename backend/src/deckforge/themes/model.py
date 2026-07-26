"""Theme model.

A theme is data, never code. It declares colours, type, spacing, backgrounds and
per-slide-kind preferences; renderers translate those tokens into CSS, PPTX
shapes or PDF drawing calls. Adding a theme therefore means adding a folder with
a ``theme.json`` — no Python changes.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deckforge.models.deck import Background
from deckforge.models.enums import SlideKind
from deckforge.utils import colors
from deckforge.utils.structures import deep_merge

__all__ = [
    "BulletStyleTokens",
    "Decor",
    "FontStack",
    "Palette",
    "Shape",
    "Spacing",
    "Theme",
    "TypeScale",
    "TypeStyle",
    "deep_merge",
]


class ThemeModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Palette(ThemeModel):
    """Semantic colour roles. Every renderer resolves colours through these names."""

    background: str = "#ffffff"
    surface: str = "#f6f7f9"
    surface_alt: str = "#eceef2"
    text: str = "#14161a"
    text_muted: str = "#5b6270"
    heading: str | None = None
    primary: str = "#2f6bff"
    on_primary: str = "#ffffff"
    secondary: str = "#7a5af8"
    accent: str = "#00c2a8"
    border: str = "#dfe3ea"
    success: str = "#12a150"
    warning: str = "#e8a33d"
    danger: str = "#e5484d"

    def resolve(self, token: str | None, fallback: str | None = None) -> str:
        """Resolve a palette token name or a literal colour to a hex string."""
        if not token:
            return fallback or self.text
        if token.startswith("#") or token.startswith("rgb"):
            return token
        value = getattr(self, token, None)
        if isinstance(value, str):
            return value
        return fallback or self.text

    def chart_defaults(self, count: int) -> list[str]:
        base = [self.primary, self.accent, self.secondary, self.warning, self.success, self.danger]
        if count <= len(base):
            return base[:count]
        return base + colors.build_palette(self.primary, count - len(base), spread=47)


class FontStack(ThemeModel):
    """Font families. ``fallback`` keeps HTML output readable without web fonts."""

    heading: str = "Inter"
    body: str = "Inter"
    mono: str = "JetBrains Mono"
    fallback: str = "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    mono_fallback: str = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    #: PPTX/PDF need a font that actually exists on the machine.
    office_heading: str = "Calibri Light"
    office_body: str = "Calibri"

    def css_heading(self) -> str:
        return f"'{self.heading}', {self.fallback}"

    def css_body(self) -> str:
        return f"'{self.body}', {self.fallback}"

    def css_mono(self) -> str:
        return f"'{self.mono}', {self.mono_fallback}"


class TypeStyle(ThemeModel):
    """One typographic step, sized for the 1280x720 logical canvas."""

    size: float = 20.0
    weight: int = 400
    line_height: float = 1.35
    letter_spacing: float = 0.0
    transform: Literal["none", "uppercase", "capitalize"] = "none"
    color: str = "text"
    font: Literal["heading", "body", "mono"] = "body"
    max_lines: int | None = None


class TypeScale(ThemeModel):
    """The full set of typographic roles a slide can use."""

    display: TypeStyle = TypeStyle(
        size=68, weight=700, line_height=1.05, color="heading", font="heading"
    )
    title: TypeStyle = TypeStyle(
        size=44, weight=650, line_height=1.15, color="heading", font="heading"
    )
    subtitle: TypeStyle = TypeStyle(size=24, weight=400, line_height=1.3, color="text_muted")
    eyebrow: TypeStyle = TypeStyle(
        size=14, weight=600, letter_spacing=1.6, transform="uppercase", color="primary"
    )
    lead: TypeStyle = TypeStyle(size=24, weight=400, line_height=1.4)
    body: TypeStyle = TypeStyle(size=19, weight=400, line_height=1.45)
    bullet: TypeStyle = TypeStyle(size=19, weight=400, line_height=1.5)
    caption: TypeStyle = TypeStyle(size=14, weight=400, color="text_muted")
    footnote: TypeStyle = TypeStyle(size=12, weight=400, color="text_muted")
    metric_value: TypeStyle = TypeStyle(size=54, weight=700, color="primary", font="heading")
    metric_label: TypeStyle = TypeStyle(size=15, weight=500, color="text_muted")
    quote: TypeStyle = TypeStyle(
        size=34, weight=500, line_height=1.3, color="heading", font="heading"
    )
    card_title: TypeStyle = TypeStyle(size=20, weight=600, color="heading", font="heading")
    card_body: TypeStyle = TypeStyle(size=16, weight=400, line_height=1.45, color="text_muted")
    code: TypeStyle = TypeStyle(size=16, weight=400, line_height=1.5, font="mono")
    table: TypeStyle = TypeStyle(size=16, weight=400, line_height=1.35)
    section_number: TypeStyle = TypeStyle(size=110, weight=800, color="primary", font="heading")

    @model_validator(mode="before")
    @classmethod
    def _merge_onto_role_defaults(cls, data: Any) -> Any:
        """Let a theme override one property of a type style without losing the rest.

        ``{"display": {"weight": 800}}`` in a ``theme.json`` should mean "the
        usual display style, but heavier". Without this, Pydantic builds a fresh
        ``TypeStyle`` from that dict alone and every unstated field falls back to
        the *class* default — so a display heading silently became 20pt body
        text. Six shipped themes were affected.
        """
        if not isinstance(data, dict):
            return data
        merged: dict[str, Any] = {}
        for role, value in data.items():
            field = cls.model_fields.get(role)
            default = getattr(field, "default", None) if field else None
            if isinstance(value, dict) and isinstance(default, TypeStyle):
                merged[role] = {**default.model_dump(), **value}
            else:
                merged[role] = value
        return merged

    def get(self, role: str) -> TypeStyle:
        style = getattr(self, role, None)
        return style if isinstance(style, TypeStyle) else self.body

    def scaled(self, factor: float) -> TypeScale:
        """A copy with every size multiplied by ``factor``.

        Used to fit a block of copy into the box a layout gave it. Letter
        spacing scales too, otherwise tracked uppercase text stops shrinking
        with the rest of the line.
        """
        if factor == 1.0:
            return self
        updates = {
            role: style.model_copy(
                update={
                    "size": style.size * factor,
                    "letter_spacing": style.letter_spacing * factor,
                }
            )
            for role, style in self
            if isinstance(style, TypeStyle)
        }
        return self.model_copy(update=updates)


class Spacing(ThemeModel):
    """Canvas margins and rhythm, in logical points."""

    margin_x: float = 84.0
    margin_y: float = 64.0
    gap: float = 28.0
    tight_gap: float = 14.0
    header_gap: float = 20.0
    card_padding: float = 24.0
    content_top: float = 178.0
    """Y coordinate where the content region starts on a standard content slide."""


class Decor(ThemeModel):
    """Purely decorative flourishes drawn behind content."""

    kind: Literal["none", "bar", "corner", "orbs", "grid", "diagonal", "dots", "underline"] = "none"
    color: str = "primary"
    opacity: float = 0.12
    size: float = 220.0


class Shape(ThemeModel):
    radius: float = 14.0
    card_radius: float = 18.0
    image_radius: float = 16.0
    border_width: float = 1.0
    shadow: str = "0 8px 30px rgba(15, 20, 35, 0.08)"
    card_border: bool = True
    card_fill: str = "surface"


class BulletStyleTokens(ThemeModel):
    marker: Literal["dot", "dash", "square", "chevron", "check", "none"] = "dot"
    marker_color: str = "primary"
    marker_size: float = 8.0
    indent: float = 30.0
    row_gap: float = 16.0


class Theme(ThemeModel):
    """A complete visual system."""

    name: str
    label: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    mode: Literal["light", "dark"] = "light"
    version: str = "1.0.0"
    author: str = "DeckForge"
    source: str = "builtin"

    palette: Palette = Field(default_factory=Palette)
    fonts: FontStack = Field(default_factory=FontStack)
    type_scale: TypeScale = Field(default_factory=TypeScale)
    spacing: Spacing = Field(default_factory=Spacing)
    shape: Shape = Field(default_factory=Shape)
    bullets: BulletStyleTokens = Field(default_factory=BulletStyleTokens)

    chart_palette: list[str] = Field(default_factory=list)
    icon_style: Literal["outline", "solid", "duotone"] = "outline"
    icon_stroke: float = 1.8

    background: Background = Field(default_factory=Background)
    backgrounds: dict[str, Background] = Field(
        default_factory=dict, description="Per slide-kind background overrides."
    )
    decor: dict[str, Decor] = Field(
        default_factory=dict, description="Per slide-kind decorative treatment."
    )
    layout_preferences: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Preferred layouts per slide kind, best first. Guides the layout selector.",
    )
    css: str = Field(default="", description="Extra CSS appended to HTML/Reveal exports.")
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _fill_defaults(self) -> Self:
        if not self.label:
            self.label = self.name.replace("_", " ").replace("-", " ").title()
        if self.palette.heading is None:
            self.palette.heading = self.palette.text
        if not self.chart_palette:
            self.chart_palette = self.palette.chart_defaults(6)
        if self.background.kind.value == "solid" and not self.background.color:
            self.background.color = self.palette.background
        return self

    # -- lookups ------------------------------------------------------------ #

    def background_for(self, kind: SlideKind | str) -> Background:
        """Return the background for a slide kind, falling back to the deck default."""
        return self.backgrounds.get(str(kind), self.background)

    def decor_for(self, kind: SlideKind | str) -> Decor:
        return self.decor.get(str(kind), self.decor.get("default", Decor()))

    def preferred_layouts(self, kind: SlideKind | str) -> list[str]:
        return self.layout_preferences.get(str(kind), [])

    def color(self, token: str | None, fallback: str | None = None) -> str:
        return self.palette.resolve(token, fallback)

    def type_scaled(self, factor: float) -> Theme:
        """This theme with its type scaled by ``factor``, colours untouched.

        Renderers use it to fit an element into the box the layout gave it.
        Returning a theme rather than a bare scale means every downstream call
        (`type_scale.get`, card padding, marker sizing) stays consistent without
        threading a scale factor through each one.
        """
        if factor == 1.0:
            return self
        return self.model_copy(update={"type_scale": self.type_scale.scaled(factor)})

    def font_family(self, which: str) -> str:
        match which:
            case "heading":
                return self.fonts.css_heading()
            case "mono":
                return self.fonts.css_mono()
            case _:
                return self.fonts.css_body()

    def office_font(self, which: str) -> str:
        """Font name for PPTX/PDF output, where web fonts are unavailable."""
        return self.fonts.office_heading if which == "heading" else self.fonts.office_body

    def text_color_on(self, background: str) -> str:
        """Pick an accessible text colour for an arbitrary background."""
        return colors.readable_on(background, "#ffffff", self.palette.text)

    # -- customisation ------------------------------------------------------ #

    def merged(self, overrides: dict[str, Any] | None) -> Theme:
        """Return a copy with ``overrides`` deep-merged in.

        This is how "make it dark" or "use our brand blue" is applied without
        creating a new theme package.
        """
        if not overrides:
            return self
        data = deep_merge(self.model_dump(mode="json"), overrides)
        return Theme.model_validate(data)

    def css_variables(self) -> dict[str, str]:
        """Flatten the theme into CSS custom properties for the HTML renderer."""
        p = self.palette
        variables = {
            "--df-bg": p.background,
            "--df-surface": p.surface,
            "--df-surface-alt": p.surface_alt,
            "--df-text": p.text,
            "--df-text-muted": p.text_muted,
            "--df-heading": p.heading or p.text,
            "--df-primary": p.primary,
            "--df-on-primary": p.on_primary,
            "--df-secondary": p.secondary,
            "--df-accent": p.accent,
            "--df-border": p.border,
            "--df-success": p.success,
            "--df-warning": p.warning,
            "--df-danger": p.danger,
            "--df-font-heading": self.fonts.css_heading(),
            "--df-font-body": self.fonts.css_body(),
            "--df-font-mono": self.fonts.css_mono(),
            "--df-radius": f"{self.shape.radius}px",
            "--df-card-radius": f"{self.shape.card_radius}px",
            "--df-image-radius": f"{self.shape.image_radius}px",
            "--df-shadow": self.shape.shadow,
            "--df-border-width": f"{self.shape.border_width}px",
        }
        for i, colour in enumerate(self.chart_palette):
            variables[f"--df-chart-{i + 1}"] = colour
        return variables
