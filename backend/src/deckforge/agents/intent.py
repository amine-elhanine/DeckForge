"""Intent router.

The first agent of every turn. Its decision determines which agents run at all,
which is the difference between "make slide 7 bold" costing one model call and
costing thirty.
"""

from __future__ import annotations

import re

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.prompts import INTENT_ROUTER, deck_context_block
from deckforge.core.errors import AgentError
from deckforge.models.enums import ExportFormat, Intent
from deckforge.models.plan import IntentDecision

#: Cheap patterns handled without a model round-trip.
_EXPORT_RE = re.compile(
    r"\b(download|export|save|give me)\b.{0,30}\b(pptx|powerpoint|pdf|markdown|md|html|"
    r"reveal(?:\.?js)?|marp|deck file)\b",
    re.IGNORECASE,
)
_FORMAT_ALIASES = {
    "powerpoint": ExportFormat.PPTX,
    "pptx": ExportFormat.PPTX,
    "ppt": ExportFormat.PPTX,
    "pdf": ExportFormat.PDF,
    "markdown": ExportFormat.MARKDOWN,
    "md": ExportFormat.MARKDOWN,
    "html": ExportFormat.HTML,
    "reveal": ExportFormat.REVEALJS,
    "revealjs": ExportFormat.REVEALJS,
    "reveal.js": ExportFormat.REVEALJS,
    "marp": ExportFormat.MARP,
}


def detect_export_formats(text: str) -> list[str]:
    """Return export formats explicitly named in ``text``."""
    lowered = text.lower()
    found: list[str] = []
    for alias, fmt in _FORMAT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered) and fmt.value not in found:
            found.append(fmt.value)
    return found


class IntentRouter(Agent[str, IntentDecision]):
    """Classifies the user's turn and names the slides it refers to."""

    name = "router"
    description = "Decides which agents a turn needs."
    status_message = "Reading your request"
    temperature = 0.1

    async def run(self, ctx: AgentContext, payload: str) -> IntentDecision:
        message = payload.strip()
        has_deck = ctx.deck is not None and bool(ctx.deck.slides)

        # A bare export request is unambiguous; skip the model entirely.
        if _EXPORT_RE.search(message) and has_deck:
            return IntentDecision(
                intent=Intent.EXPORT,
                export_formats=detect_export_formats(message) or [ExportFormat.PPTX.value],
            )

        system = INTENT_ROUTER
        user = (
            f"{deck_context_block(ctx.deck)}\n\n"
            f"Uploaded source material available: {'yes' if ctx.research else 'no'}\n\n"
            f"User message:\n{message}"
        )
        try:
            decision = await self.structured(ctx, IntentDecision, system=system, user=user)
        except AgentError:
            # Never fail a turn on routing: fall back to a sensible default.
            return IntentDecision(intent=Intent.EDIT if has_deck else Intent.CREATE)

        if decision.intent is Intent.CREATE and has_deck and not self._asks_for_new(message):
            decision.intent = Intent.EDIT
        if decision.intent in (Intent.EDIT, Intent.RESTYLE, Intent.REORDER) and not has_deck:
            decision.intent = Intent.CREATE
        if decision.intent is Intent.EXPORT and not decision.export_formats:
            decision.export_formats = detect_export_formats(message) or [ExportFormat.PPTX.value]
        if decision.needs_clarification and not decision.clarifying_questions:
            decision.needs_clarification = False
        return decision

    @staticmethod
    def _asks_for_new(message: str) -> bool:
        return bool(
            re.search(
                r"\b(new|another|second|fresh|start over|from scratch|different)\b.{0,24}"
                r"\b(deck|presentation|slides)\b",
                message,
                re.IGNORECASE,
            )
        )
