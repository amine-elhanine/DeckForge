"""Outline agent: brief in, narrative spine out."""

from __future__ import annotations

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.prompts import OUTLINE, audience_clause, density_clause, language_clause
from deckforge.models.enums import SlideKind
from deckforge.models.plan import DeckBrief, Outline, OutlineItem


class OutlineAgent(Agent[DeckBrief, Outline]):
    """Designs the slide-by-slide narrative before any body copy is written."""

    name = "outline"
    description = "Designs the deck's narrative arc and slide inventory."
    status_message = "Shaping the story"
    temperature = 0.65

    async def run(self, ctx: AgentContext, payload: DeckBrief) -> Outline:
        await self.announce(ctx, "Shaping the story", progress=0.2)

        system = (
            f"{OUTLINE}\n\n{density_clause(payload.density)}\n\n{language_clause(payload.language)}"
        )
        user = "\n\n".join(
            filter(
                None,
                [
                    f"Original request:\n{ctx.user_message}",
                    "Brief:\n" + payload.model_dump_json(indent=2),
                    audience_clause(payload.audience, payload.tone),
                    f"Produce exactly {payload.slide_count} items, including the cover and the "
                    f"closing slide.",
                    f"Evidence from the user's documents:\n{ctx.research}" if ctx.research else "",
                    "Available slide kinds: " + ", ".join(k.value for k in SlideKind),
                ],
            )
        )
        outline = await self.structured(ctx, Outline, system=system, user=user)
        return self._normalise(outline, payload)

    def _normalise(self, outline: Outline, brief: DeckBrief) -> Outline:
        """Guarantee structural invariants the model sometimes misses."""
        items = [i for i in outline.items if i.title.strip()]
        if not items:
            items = [OutlineItem(title=brief.title, kind=SlideKind.COVER)]

        if items[0].kind is not SlideKind.COVER:
            items.insert(
                0,
                OutlineItem(
                    title=brief.title,
                    kind=SlideKind.COVER,
                    intent="Set the topic and promise of the talk.",
                ),
            )
        if items[-1].kind is not SlideKind.ENDING:
            items.append(
                OutlineItem(
                    title="What to do next",
                    kind=SlideKind.ENDING,
                    intent="Leave the audience with a single action or idea.",
                )
            )

        # Trim to the requested length, protecting the cover and the ending.
        limit = max(2, brief.slide_count)
        if len(items) > limit:
            items = [items[0], *items[1 : limit - 1], items[-1]]

        outline.items = items
        outline.title = outline.title or brief.title
        if not outline.sections:
            outline.sections = [
                i.section for i in items if i.section and i.section not in outline.sections
            ]
        return outline
