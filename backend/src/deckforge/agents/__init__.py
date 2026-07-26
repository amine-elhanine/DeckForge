"""The agent framework.

Agent roster (each is a separate, independently testable unit):

===================== ==========================================================
Agent                 Responsibility
===================== ==========================================================
``IntentRouter``      Classify the turn; decide which agents run at all.
``PlannerAgent``      Produce the creative brief (goal, audience, tone, length).
``ResearchAgent``     Retrieve and condense evidence from uploaded documents.
``OutlineAgent``      Design the narrative arc and slide inventory.
``SlideWriterAgent``  Write the copy and speaker notes for one slide.
``VisualDesignerAgent`` Choose icons, accents and emphasis.
``LayoutSelectorAgent`` Assign a layout to each slide.
``ThemeSelectorAgent``  Choose the theme package.
``FactCheckerAgent``  Audit claims against the source material.
``PresentationCriticAgent`` Review the finished deck.
``RevisionAgent``     Apply changes as structured deck operations.
``CoordinatorAgent``  Orchestrate the turn and produce the user-facing reply.
===================== ==========================================================
"""

from deckforge.agents.base import Agent, AgentContext
from deckforge.agents.coordinator import CoordinatorAgent, TurnResult
from deckforge.agents.designer import VisualDesignerAgent
from deckforge.agents.intent import IntentRouter
from deckforge.agents.outline import OutlineAgent
from deckforge.agents.planner import PlannerAgent
from deckforge.agents.research import ResearchAgent, Retriever
from deckforge.agents.reviewers import FactCheckerAgent, PresentationCriticAgent
from deckforge.agents.reviser import RevisionAgent
from deckforge.agents.selectors import LayoutSelectorAgent, ThemeSelectorAgent
from deckforge.agents.writer import DeckAssembler, SlideWriterAgent

__all__ = [
    "Agent",
    "AgentContext",
    "CoordinatorAgent",
    "DeckAssembler",
    "FactCheckerAgent",
    "IntentRouter",
    "LayoutSelectorAgent",
    "OutlineAgent",
    "PlannerAgent",
    "PresentationCriticAgent",
    "ResearchAgent",
    "Retriever",
    "RevisionAgent",
    "SlideWriterAgent",
    "ThemeSelectorAgent",
    "TurnResult",
    "VisualDesignerAgent",
]
