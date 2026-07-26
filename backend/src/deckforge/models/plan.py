"""Structured outputs exchanged between agents.

Agents never pass free text to each other. Every hand-off is a validated Pydantic
model, which keeps the pipeline debuggable and lets weaker local models
participate (a malformed field is repaired or retried rather than silently
corrupting the deck).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deckforge.models.enums import ContentDensity, Intent, SlideKind


class AgentModel(BaseModel):
    """Base for agent payloads — tolerant of extra keys emitted by small models."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class IntentDecision(AgentModel):
    """Router output: what does the user want, and which agents must run?"""

    intent: Intent = Intent.CHAT
    needs_research: bool = False
    needs_clarification: bool = False
    clarifying_questions: list[str] = Field(default_factory=list, max_length=4)
    target_slides: list[str] = Field(
        default_factory=list, description="Slide ids or 1-based indices the request refers to."
    )
    export_formats: list[str] = Field(default_factory=list)
    rationale: str = Field(default="", description="Internal only; never surfaced to the user.")


class DeckBrief(AgentModel):
    """Planner output: the creative brief for the whole deck."""

    title: str = "Untitled presentation"
    subtitle: str | None = None
    goal: str = ""
    audience: str = "a general professional audience"
    tone: str = "clear, confident, modern"
    language: str = "en"
    density: ContentDensity = Field(
        default=ContentDensity.RICH,
        description="How much prose each slide carries. Set by the user, not by the model.",
    )
    duration_minutes: int = Field(default=10, ge=1, le=180)
    slide_count: int = Field(default=12, ge=1, le=60)
    key_questions: list[str] = Field(default_factory=list)
    must_cover: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    theme_hint: str | None = None
    visual_direction: str = ""


class ResearchSnippet(AgentModel):
    """A retrieved passage with provenance."""

    text: str
    source: str = ""
    asset_id: str | None = None
    score: float = 0.0
    page: int | None = None


class ResearchResult(AgentModel):
    """Research agent output."""

    findings: list[str] = Field(default_factory=list)
    snippets: list[ResearchSnippet] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)

    def as_context(self, limit: int = 12) -> str:
        """Render the research as a compact context block for downstream prompts."""
        lines = [f"- {f}" for f in self.findings[:limit]]
        for snip in self.snippets[:limit]:
            source = f" [{snip.source}]" if snip.source else ""
            lines.append(f"- {snip.text.strip()[:400]}{source}")
        return "\n".join(lines)


class OutlineItem(AgentModel):
    """One planned slide, before any prose is written."""

    title: str
    kind: SlideKind = SlideKind.CONTENT
    section: str | None = None
    intent: str = Field(default="", description="What this slide must accomplish.")
    talking_points: list[str] = Field(default_factory=list)
    visual: str = Field(default="", description="Suggested visual treatment.")
    layout_hint: str | None = None


class Outline(AgentModel):
    """Outline agent output."""

    title: str = ""
    sections: list[str] = Field(default_factory=list)
    items: list[OutlineItem] = Field(default_factory=list)
    narrative_arc: str = ""


class SlideDraft(AgentModel):
    """Slide writer output for one slide, before layout and theming."""

    title: str = ""
    eyebrow: str | None = None
    subtitle: str | None = None
    kind: SlideKind = SlideKind.CONTENT
    bullets: list[str] = Field(default_factory=list, max_length=8)
    body: str | None = Field(
        default=None, description="The slide's lead prose. Markdown bold and italics are honoured."
    )
    paragraphs: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Lead prose as separate paragraphs. Merged into `body` when both are given.",
    )
    quote: str | None = None
    quote_attribution: str | None = None
    metrics: list[dict[str, str]] = Field(default_factory=list)
    cards: list[dict[str, str]] = Field(default_factory=list)
    timeline: list[dict[str, str]] = Field(default_factory=list)
    table: dict[str, Any] | None = None
    chart: dict[str, Any] | None = None
    diagram: dict[str, str] | None = None
    code: dict[str, str] | None = None
    image_prompt: str | None = None
    icons: list[str] = Field(default_factory=list)
    notes: str = ""
    layout_hint: str | None = None
    references: list[dict[str, Any]] = Field(default_factory=list)


class LayoutChoice(AgentModel):
    """Layout selector output for one slide."""

    slide_id: str
    layout: str
    reason: str = ""


class LayoutPlan(AgentModel):
    choices: list[LayoutChoice] = Field(default_factory=list)


class ThemeChoice(AgentModel):
    """Theme selector output."""

    theme: str = "minimal"
    overrides: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class VisualDirective(AgentModel):
    """Visual designer output for one slide."""

    slide_id: str
    icons: list[str] = Field(default_factory=list)
    accent: str | None = None
    background: dict[str, Any] | None = None
    image_prompt: str | None = None
    emphasis_element_ids: list[str] = Field(default_factory=list)


class VisualPlan(AgentModel):
    directives: list[VisualDirective] = Field(default_factory=list)


class CritiqueIssue(AgentModel):
    slide_id: str | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    category: str = "clarity"
    problem: str = ""
    fix: str = ""


class Critique(AgentModel):
    """Presentation critic output."""

    score: float = Field(default=0.0, ge=0.0, le=10.0)
    strengths: list[str] = Field(default_factory=list)
    issues: list[CritiqueIssue] = Field(default_factory=list)
    verdict: Literal["ship", "revise"] = "ship"

    @property
    def blocking_issues(self) -> list[CritiqueIssue]:
        return [i for i in self.issues if i.severity in ("high", "medium")]


class FactClaim(AgentModel):
    slide_id: str | None = None
    claim: str = ""
    status: Literal["supported", "unsupported", "uncertain"] = "uncertain"
    correction: str | None = None
    source: str | None = None


class FactCheckReport(AgentModel):
    """Fact checker output."""

    claims: list[FactClaim] = Field(default_factory=list)

    @property
    def problems(self) -> list[FactClaim]:
        return [c for c in self.claims if c.status != "supported"]


class RunPlan(AgentModel):
    """Coordinator's execution plan for a single user turn."""

    intent: Intent = Intent.CHAT
    steps: list[str] = Field(default_factory=list)
    reuse_existing_deck: bool = False
    summary_for_user: str = ""
