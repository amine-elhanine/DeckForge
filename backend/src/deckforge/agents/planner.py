"""Planner agent: request in, creative brief out."""

from __future__ import annotations

import re

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.prompts import PLANNER, audience_clause, density_clause, language_clause
from deckforge.models.plan import DeckBrief

_DURATION_RE = re.compile(r"(\d{1,3})\s*(?:-|to)?\s*(?:minute|min\b|mins\b)", re.IGNORECASE)
_COUNT_RE = re.compile(r"(\d{1,2})\s*(?:slide|slides)", re.IGNORECASE)


class PlannerAgent(Agent[str, DeckBrief]):
    """Turns a free-form request into a structured brief the rest of the pipeline follows."""

    name = "planner"
    description = "Establishes goal, audience, tone, length and visual direction."
    status_message = "Planning the deck"
    temperature = 0.5

    async def run(self, ctx: AgentContext, payload: str) -> DeckBrief:
        await self.announce(ctx, "Planning the deck", progress=0.05)
        preferences = ctx.preferences
        language = str(preferences.get("language") or "en")

        density = ctx.density(payload)
        system = f"{PLANNER}\n\n{density_clause(density)}\n\n{language_clause(language)}"
        user = "\n\n".join(
            filter(
                None,
                [
                    f"Request:\n{payload}",
                    audience_clause(preferences.get("audience"), preferences.get("tone")),
                    f"Source material the deck can draw on:\n{ctx.research}"
                    if ctx.research
                    else "",
                    f"What we already know about this user's preferences: {ctx.memory}"
                    if ctx.memory
                    else "",
                    "Earlier in this conversation:\n"
                    + "\n".join(f"{m.role}: {m.content[:400]}" for m in ctx.recent_history(4))
                    if ctx.history
                    else "",
                ],
            )
        )
        brief = await self.structured(ctx, DeckBrief, system=system, user=user)
        brief.density = density
        return self._apply_explicit_constraints(brief, payload, ctx)

    def _apply_explicit_constraints(
        self, brief: DeckBrief, request: str, ctx: AgentContext
    ) -> DeckBrief:
        """Let numbers the user actually typed win over the model's guess."""
        if match := _COUNT_RE.search(request):
            brief.slide_count = max(1, min(ctx.settings.max_slides, int(match.group(1))))
        elif match := _DURATION_RE.search(request):
            minutes = max(1, min(180, int(match.group(1))))
            brief.duration_minutes = minutes
            brief.slide_count = max(3, min(ctx.settings.max_slides, round(minutes / 1.5)))

        preferences = ctx.preferences
        if preferences.get("audience"):
            brief.audience = str(preferences["audience"])
        if preferences.get("tone"):
            brief.tone = str(preferences["tone"])
        if preferences.get("language"):
            brief.language = str(preferences["language"])
        if preferences.get("default_slide_count") and not _COUNT_RE.search(request):
            brief.slide_count = int(preferences["default_slide_count"])
        brief.slide_count = max(1, min(ctx.settings.max_slides, brief.slide_count))
        return brief
