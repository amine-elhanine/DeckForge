"""Layout and theme selection agents.

Both agents are *advisory*: the deterministic engines already produce a good
answer, so the model only overrides where it has a reason to. That keeps decks
sane when a small local model returns nonsense.
"""

from __future__ import annotations

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.prompts import LAYOUT_SELECTOR, THEME_SELECTOR
from deckforge.core.errors import AgentError
from deckforge.core.logging import get_logger
from deckforge.models.deck import Presentation
from deckforge.models.plan import LayoutPlan, ThemeChoice
from deckforge.utils.text import truncate

log = get_logger(__name__)


class LayoutSelectorAgent(Agent[Presentation, LayoutPlan]):
    """Chooses a layout per slide, seeded by the engine's own ranking."""

    name = "layout_selector"
    description = "Assigns a layout to every slide, maximising variety."
    status_message = "Choosing layouts"
    temperature = 0.35

    async def run(self, ctx: AgentContext, payload: Presentation) -> LayoutPlan:
        await self.announce(ctx, "Choosing layouts", progress=0.84)
        theme = ctx.themes.for_deck(payload)
        engine_plan = ctx.layouts.plan(payload, theme)

        editable = [s for s in payload.slides if not s.locked]
        if not editable:
            return LayoutPlan()

        inventory = "\n".join(
            f"- id={s.id} kind={s.kind} elements={[str(e.type) for e in s.elements]} "
            f"engine_suggestion={engine_plan.get(s.id)} title={truncate(s.title, 70)!r}"
            for s in editable[:40]
        )
        user = (
            f"Available layouts:\n{ctx.layouts.prompt_reference()}\n\n"
            f"Slides:\n{inventory}\n\n"
            "Return a choice for every slide. Keep the engine suggestion unless you have a "
            "clear reason to change it."
        )
        try:
            plan = await self.structured(ctx, LayoutPlan, system=LAYOUT_SELECTOR, user=user)
        except AgentError:
            plan = LayoutPlan()

        self.apply(payload, plan, engine_plan, ctx)
        return plan

    def apply(
        self,
        deck: Presentation,
        plan: LayoutPlan,
        engine_plan: dict[str, str],
        ctx: AgentContext,
    ) -> None:
        """Write layouts into the deck, ignoring any name the engine doesn't know."""
        chosen = {c.slide_id: c.layout for c in plan.choices}
        for slide in deck.slides:
            if slide.locked:
                continue
            candidate = chosen.get(slide.id)
            if candidate and ctx.layouts.can_render(candidate, slide):
                slide.layout = candidate
                continue
            if candidate:
                log.debug("layout.rejected", slide=slide.id, layout=candidate)
            slide.layout = engine_plan.get(slide.id, "auto")


class ThemeSelectorAgent(Agent[Presentation, ThemeChoice]):
    """Picks the theme package for a deck."""

    name = "theme_selector"
    description = "Chooses a theme that fits the audience and setting."
    status_message = "Choosing a theme"
    temperature = 0.3

    async def run(self, ctx: AgentContext, payload: Presentation) -> ThemeChoice:
        # An explicit user or conversation preference always wins.
        preferred = ctx.preferences.get("theme")
        if preferred and preferred in ctx.themes.names():
            payload.theme = str(preferred)
            return ThemeChoice(theme=payload.theme, reason="conversation preference")

        # Progress values must increase in *pipeline* order (theme -> design ->
        # layout), otherwise the client's progress bar walks backwards.
        await self.announce(ctx, "Choosing a theme", progress=0.74)
        catalog = "\n".join(
            f"- {t['name']} ({t['mode']}): {t['description']} [tags: {', '.join(t['tags'])}]"
            for t in ctx.themes.catalog()
        )
        user = (
            f"Request:\n{ctx.user_message}\n\n"
            f"Deck: {payload.title}\n"
            f"Audience: {payload.meta.audience}\nTone: {payload.meta.tone}\n"
            f"Goal: {payload.meta.goal}\n\n"
            f"Available themes:\n{catalog}"
        )
        try:
            choice = await self.structured(ctx, ThemeChoice, system=THEME_SELECTOR, user=user)
        except AgentError:
            keywords = [payload.meta.audience or "", payload.meta.tone or "", payload.title]
            suggestions = ctx.themes.suggest(" ".join(keywords).split())
            choice = ThemeChoice(theme=suggestions[0] if suggestions else "minimal")

        if choice.theme not in ctx.themes.names():
            log.debug("theme.unknown", requested=choice.theme)
            choice.theme = payload.theme if payload.theme in ctx.themes.names() else "minimal"
        payload.theme = choice.theme
        if choice.overrides:
            payload.theme_overrides = {**payload.theme_overrides, **choice.overrides}
        return choice
