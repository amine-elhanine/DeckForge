"""Layout registry, automatic selection and deck-wide planning.

Two responsibilities:

* **Resolution** — turn a slide plus a theme into positioned geometry.
* **Selection** — decide *which* layout a slide should use when it says ``auto``,
  balancing the slide's content, the theme's preferences and visual variety
  across the deck (repeating one layout twelve times is the single most common
  way an AI deck looks generated).
"""

from __future__ import annotations

from collections.abc import Sequence

from deckforge.core.logging import get_logger
from deckforge.core.registry import Registry
from deckforge.layouts import builtin
from deckforge.layouts.model import (
    LayoutContext,
    LayoutDefinition,
    LayoutFrame,
)
from deckforge.models.deck import Presentation, Slide
from deckforge.models.enums import ElementType, SlideKind
from deckforge.themes.model import Theme

log = get_logger(__name__)

LAYOUTS: Registry[LayoutDefinition] = Registry("layout")
"""Global layout registry. Plugins add entries; nothing else needs to change."""

for _name, _definition in builtin.LAYOUT_BUILDERS.items():
    LAYOUTS.register(_name, _definition)


def register_layout(definition: LayoutDefinition, *, override: bool = False) -> LayoutDefinition:
    """Register a layout (used by plugins)."""
    return LAYOUTS.register(definition.name, definition, override=override)


FALLBACK_LAYOUT = "bullets"
#: How far back the variety penalty looks.
VARIETY_WINDOW = 3


class LayoutEngine:
    """Selects and resolves layouts."""

    def __init__(self, registry: Registry[LayoutDefinition] | None = None) -> None:
        self._registry = registry or LAYOUTS

    # -- resolution --------------------------------------------------------- #

    def resolve(
        self,
        slide: Slide,
        theme: Theme,
        *,
        canvas: tuple[float, float] = (1280.0, 720.0),
        index: int = 0,
        total: int = 1,
        deck: Presentation | None = None,
    ) -> LayoutFrame:
        """Return positioned geometry for ``slide``.

        Unknown layout names degrade to the fallback rather than raising — a deck
        authored against a plugin that is no longer installed must still render.
        """
        name = slide.layout
        if name == "auto" or name not in self._registry:
            name = self.choose(slide, theme)
        definition = self._registry.try_get(name) or self._registry.get(FALLBACK_LAYOUT)
        ctx = LayoutContext(
            slide=slide, theme=theme, canvas=canvas, index=index, total=total, deck=deck
        )
        try:
            return definition.builder(ctx)
        except Exception as exc:  # pragma: no cover - defensive against bad plugins
            log.warning("layout.failed", layout=definition.name, slide=slide.id, error=str(exc))
            return self._registry.get(FALLBACK_LAYOUT).builder(ctx)

    def resolve_deck(self, deck: Presentation, theme: Theme) -> list[LayoutFrame]:
        """Resolve every slide in a deck, honouring the deck-wide layout plan."""
        plan = self.plan(deck, theme)
        canvas = deck.canvas
        frames: list[LayoutFrame] = []
        for index, slide in enumerate(deck.slides):
            effective = slide.model_copy()
            effective.layout = plan.get(slide.id, slide.layout)
            frames.append(
                self.resolve(
                    effective, theme, canvas=canvas, index=index, total=len(deck.slides), deck=deck
                )
            )
        return frames

    # -- selection ---------------------------------------------------------- #

    def choose(self, slide: Slide, theme: Theme, *, recent: Sequence[str] = ()) -> str:
        """Pick the best layout for one slide."""
        ranked = self.rank(slide, theme, recent=recent)
        return ranked[0][0] if ranked else FALLBACK_LAYOUT

    def rank(
        self, slide: Slide, theme: Theme, *, recent: Sequence[str] = ()
    ) -> list[tuple[str, float]]:
        """Score every candidate layout for ``slide``, best first."""
        preferences = theme.preferred_layouts(slide.kind)
        element_types = {str(e.type) for e in slide.elements if not e.hidden}
        element_count = len([e for e in slide.elements if not e.hidden])
        has_visual = bool(element_types & {str(t) for t in builtin.VISUAL_TYPES})
        hint = str(slide.metadata.get("layout_hint") or "")

        scored: list[tuple[str, float]] = []
        for name in self._registry.names():
            definition = self._registry.get(name)
            if not definition.accepts(slide):
                continue
            score = 0.0

            if name in preferences:
                score += 8.0 - preferences.index(name) * 1.5
            if slide.kind in definition.suits:
                score += 4.0
            if hint and hint == name:
                score += 10.0
            elif hint and hint in definition.tags:
                score += 3.0

            # Content fit: penalise layouts that are much bigger or smaller than needed.
            score -= abs(definition.capacity - max(1, element_count)) * 0.55

            if has_visual and definition.visual_weight == "visual":
                score += 2.5
            elif has_visual and definition.visual_weight == "text":
                score -= 2.0
            elif not has_visual and definition.visual_weight == "visual":
                score -= 4.0
            elif not has_visual and definition.visual_weight == "text":
                score += 1.5

            score += self._element_affinity(definition, element_types)

            if recent:
                window = list(recent)[-VARIETY_WINDOW:]
                if window and window[-1] == name:
                    score -= 5.0
                score -= window.count(name) * 1.8

            scored.append((name, score))

        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored

    #: Which element types each layout is designed around.
    _AFFINITY: dict[str, set[str]] = {  # noqa: RUF012
        str(ElementType.CHART): {"chart_focus", "dashboard", "split", "split_reverse"},
        str(ElementType.TABLE): {"table", "comparison"},
        str(ElementType.TIMELINE): {"timeline", "roadmap", "process", "flow", "cycle"},
        str(ElementType.METRIC): {"metrics", "dashboard"},
        str(ElementType.QUOTE): {"quote", "big_statement"},
        str(ElementType.DIAGRAM): {"diagram", "architecture", "flow", "tree", "mind_map"},
        str(ElementType.IMAGE): {
            "image_left",
            "image_right",
            "image_full",
            "image_background",
            "split",
            "split_reverse",
            "hero",
        },
        str(ElementType.CARDS): {"cards", "grid", "infographic", "quiz"},
        str(ElementType.CODE): {"split", "split_reverse"},
    }

    @classmethod
    def _element_affinity(cls, definition: LayoutDefinition, element_types: set[str]) -> float:
        """Reward layouts built around elements the slide has — and penalise the reverse.

        A ``split`` layout with nothing to put in the right-hand column still
        renders, but it is a worse choice than a plain content layout, so an
        unmatched affinity costs points.
        """
        affinity = 0.0
        wants: set[str] = set()
        for element_type, layouts in cls._AFFINITY.items():
            if definition.name in layouts:
                wants.add(element_type)
                if element_type in element_types:
                    affinity += 3.5
        if wants and not (wants & element_types):
            affinity -= 3.5
        return affinity

    def plan(self, deck: Presentation, theme: Theme) -> dict[str, str]:
        """Assign layouts to every ``auto`` slide, maximising variety.

        Explicit layouts are respected and still count towards the variety
        window, so a deck the user hand-tuned does not get fought by the engine.
        """
        chosen: dict[str, str] = {}
        recent: list[str] = []
        for slide in deck.slides:
            if slide.layout != "auto" and slide.layout in self._registry:
                name = slide.layout
            else:
                name = self.choose(slide, theme, recent=recent)
            chosen[slide.id] = name
            recent.append(name)
        return chosen

    # -- introspection ------------------------------------------------------ #

    def names(self) -> list[str]:
        return self._registry.names()

    def definition(self, name: str) -> LayoutDefinition | None:
        """Look up a layout definition, or ``None`` if it is not registered."""
        return self._registry.try_get(name)

    def can_render(self, name: str, slide: Slide) -> bool:
        """Whether ``name`` exists and can render ``slide`` without losing content."""
        definition = self._registry.try_get(name)
        return definition is not None and definition.accepts(slide)

    def catalog(self) -> list[dict[str, object]]:
        """Layout metadata for the UI and for the layout-selector agent's prompt."""
        out: list[dict[str, object]] = []
        for name in self._registry.names():
            d = self._registry.get(name)
            out.append(
                {
                    "name": d.name,
                    "label": d.label,
                    "description": d.description,
                    "slots": d.slots,
                    "suits": [str(k) for k in d.suits],
                    "capacity": d.capacity,
                    "tags": d.tags,
                    "visual_weight": d.visual_weight,
                    "requires": d.requires,
                }
            )
        return out

    def prompt_reference(self) -> str:
        """Compact layout menu embedded in agent prompts."""
        lines: list[str] = []
        for name in self._registry.names():
            d = self._registry.get(name)
            suits = ",".join(str(k) for k in d.suits) or "any"
            lines.append(
                f"- {name}: {d.description} (best for: {suits}; holds ~{d.capacity} items)"
            )
        return "\n".join(lines)

    def for_kind(self, kind: SlideKind) -> list[str]:
        return [n for n in self._registry.names() if kind in self._registry.get(n).suits]
