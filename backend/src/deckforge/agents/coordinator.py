"""Coordinator agent.

Owns the turn. It routes the request, runs only the agents that request needs,
and produces the single natural-language reply the user sees. Agent chatter,
retries and structured payloads never reach the transcript.

Creation runs the full pipeline::

    router → planner → research → outline → slide writer → theme → designer
           → layout → fact checker → critic → revision

Edits skip straight to the revision agent, so "move slide 7 before slide 4"
costs two model calls instead of thirty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from deckforge.agents.base import AgentContext
from deckforge.agents.designer import VisualDesignerAgent
from deckforge.agents.intent import IntentRouter
from deckforge.agents.outline import OutlineAgent
from deckforge.agents.planner import PlannerAgent
from deckforge.agents.prompts import CONVERSATION, deck_context_block
from deckforge.agents.research import ResearchAgent
from deckforge.agents.reviewers import FactCheckerAgent, PresentationCriticAgent
from deckforge.agents.reviser import RevisionAgent
from deckforge.agents.selectors import LayoutSelectorAgent, ThemeSelectorAgent
from deckforge.agents.writer import DeckAssembler, SlideWriterAgent
from deckforge.core.errors import AgentError, DeckForgeError
from deckforge.core.events import EventType, RunEvent
from deckforge.core.logging import get_logger
from deckforge.models.deck import Presentation
from deckforge.models.enums import Intent
from deckforge.models.plan import Critique, IntentDecision
from deckforge.providers.base import ChatMessage

log = get_logger(__name__)


@dataclass(slots=True)
class TurnResult:
    """Everything a single user turn produced."""

    reply: str = ""
    deck: Presentation | None = None
    intent: Intent = Intent.CHAT
    changed: bool = False
    changelog: list[str] = field(default_factory=list)
    export_formats: list[str] = field(default_factory=list)
    critique: Critique | None = None
    clarifying_questions: list[str] = field(default_factory=list)
    error: str | None = None


class CoordinatorAgent:
    """Orchestrates a turn end to end."""

    name = "coordinator"

    def __init__(self) -> None:
        self.router = IntentRouter()
        self.planner = PlannerAgent()
        self.research = ResearchAgent()
        self.outline = OutlineAgent()
        self.assembler = DeckAssembler(SlideWriterAgent())
        self.designer = VisualDesignerAgent()
        self.layout_selector = LayoutSelectorAgent()
        self.theme_selector = ThemeSelectorAgent()
        self.fact_checker = FactCheckerAgent()
        self.critic = PresentationCriticAgent()
        self.reviser = RevisionAgent()

    # -- entry point --------------------------------------------------------- #

    async def handle(self, ctx: AgentContext) -> TurnResult:
        """Run one user turn."""
        try:
            decision = await self.router.run(ctx, ctx.user_message)
            log.info("turn.routed", intent=str(decision.intent), conversation=ctx.conversation_id)

            if decision.needs_clarification and decision.clarifying_questions:
                return await self._clarify(ctx, decision)

            match decision.intent:
                case Intent.CREATE:
                    return await self._create(ctx, decision)
                case Intent.EDIT | Intent.RESTYLE | Intent.REORDER:
                    return await self._edit(ctx, decision)
                case Intent.EXPORT:
                    return await self._export(ctx, decision)
                case _:
                    return await self._converse(ctx, decision)
        except DeckForgeError as exc:
            await ctx.events.emit(RunEvent.error(exc.message, code=exc.code))
            log.warning("turn.failed", error=exc.message, conversation=ctx.conversation_id)
            return TurnResult(
                reply=f"I hit a problem: {exc.message}",
                deck=ctx.deck,
                error=exc.message,
            )

    # -- flows ---------------------------------------------------------------- #

    async def _create(self, ctx: AgentContext, decision: IntentDecision) -> TurnResult:
        """Full generation pipeline."""
        if decision.needs_research:
            ctx.research = (await self.research.run(ctx, ctx.user_message)).as_context()

        brief = await self.planner.run(ctx, ctx.user_message)
        ctx.scratch["brief"] = brief

        outline = await self.outline.run(ctx, brief)
        ctx.scratch["outline"] = outline
        await ctx.events.status(
            f"Writing {len(outline.items)} slides", phase="outline", progress=0.25
        )

        deck = await self.assembler.build(ctx, brief, outline)
        ctx.deck = deck
        await ctx.events.push(EventType.DECK, deck=deck.model_dump(mode="json"))

        await self.theme_selector.run(ctx, deck)
        await self.designer.run(ctx, deck)
        await self.layout_selector.run(ctx, deck)

        changelog: list[str] = []
        critique = await self._review_and_polish(ctx, deck, changelog)

        deck.touch()
        await ctx.events.push(EventType.DECK, deck=deck.model_dump(mode="json"))
        reply = await self._reply(
            ctx,
            summary=(
                f'Created a {len(deck.slides)}-slide deck titled "{deck.title}" '
                f"using the '{deck.theme}' theme for {brief.audience}."
            ),
            changelog=changelog,
        )
        return TurnResult(
            reply=reply,
            deck=deck,
            intent=Intent.CREATE,
            changed=True,
            changelog=[f"Created {len(deck.slides)} slides", *changelog],
            critique=critique,
        )

    async def _edit(self, ctx: AgentContext, decision: IntentDecision) -> TurnResult:
        """Incremental edit: only the revision agent runs unless the deck changed a lot."""
        deck = ctx.deck
        if deck is None:
            return await self._create(ctx, decision)

        if decision.needs_research and not ctx.research:
            ctx.research = (await self.research.run(ctx, ctx.user_message)).as_context()
        ctx.scratch["target_slides"] = self._resolve_targets(deck, decision.target_slides)

        batch = await self.reviser.run(ctx, ctx.user_message)
        result = self.reviser.apply(deck, batch)

        # A restyle can invalidate layout choices; a content edit can invalidate icons.
        if (decision.intent is Intent.RESTYLE and result.changed) or (
            result.changed and self._touched_content(result.applied)
        ):
            await self.layout_selector.run(ctx, deck)

        changelog = list(result.applied)
        critique = None
        if result.changed and len(deck.slides) > 2 and ctx.settings.enable_critic:
            critique = await self.critic.run(ctx, deck)

        deck.touch()
        await ctx.events.push(EventType.DECK, deck=deck.model_dump(mode="json"))
        summary = batch.summary or ("; ".join(changelog) if changelog else "No change was needed.")
        if result.skipped and not changelog:
            summary = "I could not apply that change."
        reply = await self._reply(ctx, summary=summary, changelog=changelog)
        return TurnResult(
            reply=reply,
            deck=deck,
            intent=decision.intent,
            changed=result.changed,
            changelog=changelog,
            critique=critique,
        )

    async def _export(self, ctx: AgentContext, decision: IntentDecision) -> TurnResult:
        formats = decision.export_formats or ["pptx"]
        return TurnResult(
            reply="",  # the service fills this in once the files exist
            deck=ctx.deck,
            intent=Intent.EXPORT,
            export_formats=formats,
        )

    async def _clarify(self, ctx: AgentContext, decision: IntentDecision) -> TurnResult:
        questions = decision.clarifying_questions[:2]
        reply = await self._reply(
            ctx,
            summary="Before building this I need one or two details: " + " ".join(questions),
            changelog=[],
        )
        return TurnResult(
            reply=reply or " ".join(questions),
            deck=ctx.deck,
            intent=Intent.CLARIFY,
            clarifying_questions=questions,
        )

    async def _converse(self, ctx: AgentContext, decision: IntentDecision) -> TurnResult:
        """Answer a question without touching the deck."""
        chunks: list[str] = []
        system = f"{CONVERSATION}\n\n{deck_context_block(ctx.deck)}"
        async for chunk in self.reviser.converse(
            ctx,
            system=system,
            user=ctx.user_message,
            history=ctx.recent_history(6),
            temperature=0.6,
        ):
            chunks.append(chunk)
            await ctx.events.token(chunk)
        return TurnResult(reply="".join(chunks).strip(), deck=ctx.deck, intent=decision.intent)

    # -- shared steps ---------------------------------------------------------- #

    async def _review_and_polish(
        self, ctx: AgentContext, deck: Presentation, changelog: list[str]
    ) -> Critique | None:
        """Fact-check, critique, and apply the fixes worth applying."""
        if ctx.settings.enable_fact_checker and ctx.research:
            report = await self.fact_checker.run(ctx, deck)
            if report.problems:
                changelog.append(f"Flagged {len(report.problems)} claims for review")
                ctx.scratch["fact_problems"] = [p.model_dump() for p in report.problems]

        if not ctx.settings.enable_critic:
            return None

        critique = await self.critic.run(ctx, deck)
        if critique.verdict == "revise":
            batch = await self.reviser.revise_from_critique(ctx, deck, critique)
            result = self.reviser.apply(deck, batch)
            changelog.extend(result.applied)
        return critique

    async def _reply(self, ctx: AgentContext, *, summary: str, changelog: list[str]) -> str:
        """Stream the short, human reply that closes the turn."""
        detail = "\n".join(f"- {c}" for c in changelog[:8])
        user = (
            f"You just finished this work on the user's deck:\n{summary}\n"
            + (f"\nChanges applied:\n{detail}\n" if detail else "")
            + f"\nThe user said: {ctx.user_message}\n\n"
            "Reply to them in two or three sentences. Do not list every change; "
            "say what happened and offer the single most useful next step."
        )
        chunks: list[str] = []
        try:
            async for chunk in self.reviser.converse(
                ctx, system=CONVERSATION, user=user, temperature=0.6
            ):
                chunks.append(chunk)
                await ctx.events.token(chunk)
        except AgentError, DeckForgeError:
            return summary
        return "".join(chunks).strip() or summary

    @staticmethod
    def _resolve_targets(deck: Presentation, targets: list[str]) -> list[str]:
        """Map slide ids or 1-based positions onto real slide ids."""
        resolved: list[str] = []
        for target in targets:
            if deck.slide_by_id(target):
                resolved.append(target)
                continue
            try:
                index = int(str(target).strip()) - 1
            except ValueError:
                continue
            if 0 <= index < len(deck.slides):
                resolved.append(deck.slides[index].id)
        return resolved

    @staticmethod
    def _touched_content(applied: list[str]) -> bool:
        markers = ("added slide", "rewrote", "restyled", "split", "merged", "deleted")
        return any(any(m in entry for m in markers) for entry in applied)

    @staticmethod
    def history_messages(pairs: list[tuple[str, str]]) -> list[ChatMessage]:
        """Convert stored (role, content) pairs into provider messages."""
        return [
            ChatMessage(role=role, content=content)  # type: ignore[arg-type]
            for role, content in pairs
            if role in ("user", "assistant", "system")
        ]
