"""Visual designer agent.

Decides icons, accents and emphasis after the copy exists. Running it *after*
writing (rather than asking the writer to also art-direct) keeps each model call
focused, and means a restyle request can re-run only this agent.
"""

from __future__ import annotations

from typing import Any

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.prompts import VISUAL_DESIGNER
from deckforge.core.errors import AgentError
from deckforge.core.logging import get_logger
from deckforge.models.deck import (
    Background,
    BulletsElement,
    CardsElement,
    IconElement,
    MetricElement,
    Presentation,
    Slide,
)
from deckforge.models.enums import BackgroundKind, SlideKind
from deckforge.models.plan import VisualDirective, VisualPlan
from deckforge.renderers import icons
from deckforge.utils.text import truncate

log = get_logger(__name__)


class VisualDesignerAgent(Agent[Presentation, VisualPlan]):
    """Assigns icons and accents, then applies them to the deck."""

    name = "visual_designer"
    description = "Chooses icons, accents and emphasis for each slide."
    status_message = "Designing the visuals"
    temperature = 0.5

    async def run(self, ctx: AgentContext, payload: Presentation) -> VisualPlan:
        await self.announce(ctx, "Designing the visuals", progress=0.79)
        candidates = [
            s
            for s in payload.slides
            if not s.locked and s.kind not in (SlideKind.COVER, SlideKind.ENDING)
        ]
        if not candidates:
            return VisualPlan()

        inventory = "\n".join(
            f"- id={s.id} kind={s.kind} title={s.title!r} "
            f"content={truncate(s.text_content().replace(chr(10), ' / '), 220)!r} "
            f"elements={[f'{e.id}:{e.type}' for e in s.elements]}"
            for s in candidates[:40]
        )
        user = (
            f"Deck: {payload.title}\nTheme: {payload.theme}\n\n"
            f"Available icons:\n{', '.join(icons.available())}\n\n"
            f"Slides:\n{inventory}"
        )
        try:
            plan = await self.structured(ctx, VisualPlan, system=VISUAL_DESIGNER, user=user)
        except AgentError:
            # Visual polish is optional; fall back to keyword-derived icons.
            plan = self._heuristic_plan(payload)
        self.apply(payload, plan)
        return plan

    def _heuristic_plan(self, deck: Presentation) -> VisualPlan:
        """Derive icons from content keywords when the model is unavailable."""
        directives: list[VisualDirective] = []
        for slide in deck.slides:
            has_cards = any(isinstance(e, CardsElement) for e in slide.elements)
            has_metrics = any(isinstance(e, MetricElement) for e in slide.elements)
            if not (has_cards or has_metrics):
                continue
            directives.append(
                VisualDirective(
                    slide_id=slide.id,
                    icons=[icons.suggest_icon(slide.text_content())],
                )
            )
        return VisualPlan(directives=directives)

    def apply(self, deck: Presentation, plan: VisualPlan) -> None:
        """Write the plan into the deck JSON."""
        for directive in plan.directives:
            slide = deck.slide_by_id(directive.slide_id)
            if slide is None or slide.locked:
                continue
            if directive.accent:
                slide.theme_overrides.setdefault("palette", {})["primary"] = directive.accent

            icon_names = [icons.get_icon(n) and n for n in directive.icons if n]
            self._distribute_icons(slide, icon_names)

            for element_id in directive.emphasis_element_ids:
                element = slide.element_by_id(element_id)
                if isinstance(element, BulletsElement) and element.items:
                    element.items[0].emphasis = True

            if directive.background and slide.kind in (
                SlideKind.COVER,
                SlideKind.SECTION,
                SlideKind.ENDING,
            ):
                slide.background = self._background(directive.background)

    @staticmethod
    def _distribute_icons(slide: Slide, names: list[str]) -> None:
        """Attach icons where they belong: on cards, metrics, or as a standalone mark."""
        if not names:
            return
        for element in slide.elements:
            if isinstance(element, CardsElement):
                for card, name in zip(element.cards, names, strict=False):
                    card.icon = card.icon or name
                return
            if isinstance(element, MetricElement) and not element.icon:
                element.icon = names[0]
                names = names[1:] or names
        metrics = [e for e in slide.elements if isinstance(e, MetricElement)]
        if metrics or any(isinstance(e, IconElement) for e in slide.elements):
            return
        if slide.kind in (SlideKind.SECTION,):
            slide.elements.insert(0, IconElement(name=names[0], slot="aside", size=44))

    @staticmethod
    def _background(spec: dict[str, Any]) -> Background:
        kind = str(spec.get("kind", "gradient"))
        colors = spec.get("colors") or []
        return Background(
            kind=BackgroundKind(kind) if kind in set(BackgroundKind) else BackgroundKind.GRADIENT,
            colors=[str(c) for c in colors] if isinstance(colors, list) else [],
            color=str(spec["color"]) if spec.get("color") else None,
            angle=float(spec.get("angle", 135) or 135),
        )
