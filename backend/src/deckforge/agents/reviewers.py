"""Review agents: fact checker and presentation critic.

Both are read-only. They produce findings; the revision agent decides what to do
about them. Separating "notice" from "fix" keeps the critic honest — an agent
that must also implement its own fixes learns to find easy problems.
"""

from __future__ import annotations

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.prompts import CRITIC, FACT_CHECKER, density_clause
from deckforge.core.errors import AgentError
from deckforge.core.logging import get_logger
from deckforge.models.deck import Presentation
from deckforge.models.enums import ContentDensity
from deckforge.models.plan import Critique, CritiqueIssue, FactCheckReport
from deckforge.utils.text import jaccard, truncate

log = get_logger(__name__)

#: Words per slide past which the deck stops being a deck, per density. Set a
#: little above each density's target so a slide that lands in range is not
#: flagged for hitting the number it was asked for.
WORD_CEILING: dict[ContentDensity, int] = {
    ContentDensity.CONCISE: 80,
    ContentDensity.BALANCED: 160,
    ContentDensity.RICH: 260,
}


def deck_body(deck: Presentation, limit: int = 40) -> str:
    """Full slide text for review agents, budget-capped."""
    blocks: list[str] = []
    for i, slide in enumerate(deck.slides[:limit], start=1):
        blocks.append(
            f"[{i}] id={slide.id} kind={slide.kind} layout={slide.layout}\n"
            f"TITLE: {slide.title}\n"
            + (f"SUBTITLE: {slide.subtitle}\n" if slide.subtitle else "")
            + f"BODY:\n{truncate(slide.text_content(), 900)}\n"
            + f"NOTES: {truncate(slide.notes, 300)}"
        )
    return "\n\n".join(blocks)


class FactCheckerAgent(Agent[Presentation, FactCheckReport]):
    """Flags claims the supplied sources do not support."""

    name = "fact_checker"
    description = "Audits factual claims against the user's source material."
    status_message = "Checking the claims"
    temperature = 0.1

    async def run(self, ctx: AgentContext, payload: Presentation) -> FactCheckReport:
        if not ctx.settings.enable_fact_checker:
            return FactCheckReport()
        await self.announce(ctx, "Checking the claims", progress=0.88)

        sources = ctx.research or "(no source material was supplied)"
        user = (
            f"Source material:\n{sources}\n\n"
            f"Deck under review:\n{deck_body(payload)}\n\n"
            "If no source material was supplied, only flag claims that are internally "
            "inconsistent or implausibly precise."
        )
        try:
            return await self.structured(ctx, FactCheckReport, system=FACT_CHECKER, user=user)
        except AgentError:
            return FactCheckReport()


class PresentationCriticAgent(Agent[Presentation, Critique]):
    """Reviews a finished deck and lists concrete, actionable problems."""

    name = "critic"
    description = "Reviews the finished deck for clarity, density and variety."
    status_message = "Reviewing the deck"
    temperature = 0.3

    async def run(self, ctx: AgentContext, payload: Presentation) -> Critique:
        if not ctx.settings.enable_critic:
            return Critique(score=8.0, verdict="ship")
        await self.announce(ctx, "Reviewing the deck", progress=0.9)

        density = ctx.density()
        stats = payload.stats()
        user = (
            f"Deck statistics: {stats}\n"
            f"Audience: {payload.meta.audience} | Tone: {payload.meta.tone}\n"
            f"Goal: {payload.meta.goal}\n\n"
            f"Deck:\n{deck_body(payload)}"
        )
        system = f"{CRITIC}\n\n{density_clause(density)}"
        try:
            critique = await self.structured(ctx, Critique, system=system, user=user)
        except AgentError:
            critique = Critique(score=7.0, verdict="ship")

        critique.issues.extend(self._mechanical_issues(payload, WORD_CEILING[density]))
        if any(i.severity == "high" for i in critique.issues):
            critique.verdict = "revise"
        return critique

    @staticmethod
    def _mechanical_issues(deck: Presentation, word_ceiling: int) -> list[CritiqueIssue]:
        """Deterministic checks the model should not have to spend tokens on.

        ``word_ceiling`` follows the requested density. A fixed cap here would
        quietly revert every deck the user asked to be explanatory: the slide
        would be flagged high-severity and the reviser would cut it back.
        """
        issues: list[CritiqueIssue] = []

        for slide in deck.slides:
            words = slide.word_count()
            if words > word_ceiling:
                issues.append(
                    CritiqueIssue(
                        slide_id=slide.id,
                        severity="high",
                        category="density",
                        problem=f"Slide '{slide.title}' has {words} words; it reads as a document.",
                        fix="Cut to one idea; move the detail into the speaker notes.",
                    )
                )
            if slide.kind.value not in ("cover", "section", "ending") and not slide.notes.strip():
                issues.append(
                    CritiqueIssue(
                        slide_id=slide.id,
                        severity="low",
                        category="notes",
                        problem=f"Slide '{slide.title}' has no speaker notes.",
                        fix="Add 2-3 sentences of what to say over this slide.",
                    )
                )

        # Repeated layouts in a row read as a template, not a deck.
        run_start = 0
        for i in range(1, len(deck.slides) + 1):
            same = i < len(deck.slides) and deck.slides[i].layout == deck.slides[run_start].layout
            if not same:
                if i - run_start >= 4 and deck.slides[run_start].layout != "auto":
                    issues.append(
                        CritiqueIssue(
                            slide_id=deck.slides[run_start].id,
                            severity="medium",
                            category="variety",
                            problem=f"{i - run_start} consecutive slides use the "
                            f"'{deck.slides[run_start].layout}' layout.",
                            fix="Vary the layout — split one into cards, metrics or a comparison.",
                        )
                    )
                run_start = i

        # Near-duplicate slides.
        for i, slide in enumerate(deck.slides):
            for other in deck.slides[i + 1 : i + 4]:
                if (
                    slide.text_content()
                    and jaccard(slide.text_content(), other.text_content()) > 0.72
                ):
                    issues.append(
                        CritiqueIssue(
                            slide_id=other.id,
                            severity="medium",
                            category="repetition",
                            problem=f"'{other.title}' repeats most of '{slide.title}'.",
                            fix="Merge them, or give the second slide a distinct angle.",
                        )
                    )
                    break
        return issues
