"""Revision agent.

Every change to an existing deck — a user edit or a critic fix — flows through
here as a batch of :mod:`deckforge.models.ops` operations. The model chooses
*what* to change; the engine applies it deterministically, so an edit can never
corrupt the deck structure.
"""

from __future__ import annotations

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.prompts import (
    REVISION,
    deck_context_block,
    density_clause,
    slide_detail_block,
)
from deckforge.core.errors import AgentError
from deckforge.core.logging import get_logger
from deckforge.models.deck import Presentation
from deckforge.models.ops import OperationBatch, OperationResult, apply_operations
from deckforge.models.plan import Critique

log = get_logger(__name__)


class RevisionAgent(Agent[str, OperationBatch]):
    """Translates a request (or a critique) into deck operations."""

    name = "revision"
    description = "Edits an existing deck through structured operations."
    status_message = "Applying your changes"
    temperature = 0.4

    async def run(self, ctx: AgentContext, payload: str) -> OperationBatch:
        deck = ctx.deck
        if deck is None:
            raise AgentError("there is no presentation to edit yet")

        await self.announce(ctx, "Applying your changes", progress=0.4)
        focus: list[str] = ctx.scratch.get("target_slides", [])
        detail = slide_detail_block(deck, focus or [s.id for s in deck.slides[:4]])

        user = "\n\n".join(
            filter(
                None,
                [
                    f"User request:\n{payload}",
                    deck_context_block(deck),
                    f"Slides in focus (full content):\n{detail}" if detail else "",
                    f"Available themes: {', '.join(ctx.themes.names())}",
                    f"Available layouts: {', '.join(ctx.layouts.names())}",
                    f"Source material you may draw on:\n{ctx.research}" if ctx.research else "",
                ],
            )
        )
        system = f"{REVISION}\n\n{density_clause(ctx.density(payload))}"
        return await self.structured(ctx, OperationBatch, system=system, user=user)

    async def revise_from_critique(
        self, ctx: AgentContext, deck: Presentation, critique: Critique
    ) -> OperationBatch:
        """Turn blocking critic findings into concrete edits."""
        blocking = critique.blocking_issues
        if not blocking:
            return OperationBatch()

        await self.announce(ctx, "Polishing the weak spots", progress=0.93)
        findings = "\n".join(
            f"- [{i.severity}] slide {i.slide_id}: {i.problem} → {i.fix}" for i in blocking[:12]
        )
        affected = [i.slide_id for i in blocking if i.slide_id]
        user = "\n\n".join(
            filter(
                None,
                [
                    "A reviewer found these problems. Fix them and change nothing else.",
                    findings,
                    deck_context_block(deck),
                    f"Slides in focus (full content):\n{slide_detail_block(deck, affected)}",
                ],
            )
        )
        system = f"{REVISION}\n\n{density_clause(ctx.density())}"
        try:
            return await self.structured(ctx, OperationBatch, system=system, user=user)
        except AgentError:
            log.info("revision.critique_skipped")
            return OperationBatch()

    @staticmethod
    def apply(deck: Presentation, batch: OperationBatch) -> OperationResult:
        """Apply a batch to the deck and return the changelog."""
        result = apply_operations(deck, batch.operations)
        log.info(
            "revision.applied",
            applied=len(result.applied),
            skipped=len(result.skipped),
            deck=deck.id,
        )
        return result
