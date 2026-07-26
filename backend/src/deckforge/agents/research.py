"""Research agent.

Grounds a deck in the user's own documents. It runs only when the router says the
turn needs it and the conversation actually has indexed material — an ungrounded
"research" step is just an extra model call that invites hallucination.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from deckforge.agents.base import Agent, AgentContext
from deckforge.core.errors import AgentError
from deckforge.core.logging import get_logger
from deckforge.models.plan import ResearchResult, ResearchSnippet

log = get_logger(__name__)

RESEARCH_SYSTEM = """\
You extract what a presentation needs from source material the user supplied.

Rules:
- Every finding must be traceable to the passages given. Do not add outside knowledge.
- Findings are specific and quotable: numbers, definitions, causal claims, named examples.
- Prefer 6-12 findings over an exhaustive list.
- open_questions lists what the deck will need but the sources do not answer.
- references lists the documents you actually drew on, as {"title": ..., "source_document": ...}."""


@runtime_checkable
class Retriever(Protocol):
    """What the research agent needs from the retrieval layer."""

    async def search(self, query: str, top_k: int = 8) -> list[ResearchSnippet]:
        """Return the most relevant passages for ``query``."""
        ...


class ResearchAgent(Agent[str, ResearchResult]):
    """Retrieves relevant passages and condenses them into usable findings."""

    name = "research"
    description = "Retrieves and condenses evidence from uploaded documents."
    status_message = "Reading your documents"
    temperature = 0.2

    async def run(self, ctx: AgentContext, payload: str) -> ResearchResult:
        if ctx.retriever is None:
            return ResearchResult()

        await self.announce(ctx, "Reading your documents", progress=0.12)
        try:
            snippets = await ctx.retriever.search(payload, ctx.settings.retrieval_top_k)
        except Exception as exc:  # pragma: no cover - retrieval is best effort
            log.warning("research.retrieval_failed", error=str(exc))
            return ResearchResult()

        if not snippets:
            return ResearchResult()

        passages = "\n\n".join(
            f"[{i + 1}] source={s.source or 'document'}"
            + (f" page={s.page}" if s.page else "")
            + f"\n{s.text.strip()[:1600]}"
            for i, s in enumerate(snippets)
        )
        user = f"Presentation request:\n{payload}\n\nSource passages:\n{passages}"

        try:
            result = await self.structured(ctx, ResearchResult, system=RESEARCH_SYSTEM, user=user)
        except AgentError:
            # Retrieval still succeeded — hand the raw passages downstream rather
            # than losing the grounding entirely.
            return ResearchResult(snippets=snippets)

        result.snippets = snippets
        return result
