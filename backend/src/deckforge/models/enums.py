"""Enumerations shared across the domain model."""

from __future__ import annotations

from enum import StrEnum


class SlideKind(StrEnum):
    """Semantic role of a slide.

    The theme engine styles slides by *kind*; the layout engine arranges them by
    *layout*. Keeping the two axes separate is what lets the same content look
    completely different under another theme.
    """

    COVER = "cover"
    AGENDA = "agenda"
    SECTION = "section"
    CONTENT = "content"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    ROADMAP = "roadmap"
    PROCESS = "process"
    METRICS = "metrics"
    CHART = "chart"
    DIAGRAM = "diagram"
    TABLE = "table"
    IMAGE = "image"
    QUOTE = "quote"
    QUIZ = "quiz"
    REFERENCES = "references"
    APPENDIX = "appendix"
    ENDING = "ending"


class ElementType(StrEnum):
    """Discriminator for the element union."""

    TEXT = "text"
    BULLETS = "bullets"
    IMAGE = "image"
    ICON = "icon"
    CHART = "chart"
    DIAGRAM = "diagram"
    TABLE = "table"
    QUOTE = "quote"
    METRIC = "metric"
    CARDS = "cards"
    TIMELINE = "timeline"
    CODE = "code"
    SHAPE = "shape"


class TextRole(StrEnum):
    """Typographic role, resolved to concrete type styles by the theme."""

    TITLE = "title"
    SUBTITLE = "subtitle"
    EYEBROW = "eyebrow"
    LEAD = "lead"
    BODY = "body"
    CAPTION = "caption"
    FOOTNOTE = "footnote"


class ContentDensity(StrEnum):
    """How much prose a slide carries.

    A deck of terse fragments and a deck of explanatory paragraphs are both
    legitimate — a conference keynote wants the first, a lecture handout or a
    deck that will be read without a presenter wants the second. The difference
    is a writing instruction, not a different pipeline, so it travels with the
    brief and every writing agent reads it.
    """

    CONCISE = "concise"
    BALANCED = "balanced"
    RICH = "rich"


class Align(StrEnum):
    START = "start"
    CENTER = "center"
    END = "end"
    JUSTIFY = "justify"


class BulletStyle(StrEnum):
    DOT = "dot"
    DASH = "dash"
    CHECK = "check"
    ARROW = "arrow"
    NUMBER = "number"
    ICON = "icon"
    NONE = "none"


class ChartKind(StrEnum):
    BAR = "bar"
    COLUMN = "column"
    STACKED_BAR = "stacked_bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    DONUT = "donut"
    SCATTER = "scatter"
    RADAR = "radar"


class DiagramEngine(StrEnum):
    MERMAID = "mermaid"
    PLANTUML = "plantuml"
    GRAPHVIZ = "graphviz"


class BackgroundKind(StrEnum):
    SOLID = "solid"
    GRADIENT = "gradient"
    MESH = "mesh"
    IMAGE = "image"
    PATTERN = "pattern"
    NONE = "none"


class ImageFit(StrEnum):
    COVER = "cover"
    CONTAIN = "contain"
    FILL = "fill"


class AspectRatio(StrEnum):
    WIDESCREEN = "16:9"
    STANDARD = "4:3"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ExportFormat(StrEnum):
    PPTX = "pptx"
    PDF = "pdf"
    MARKDOWN = "markdown"
    HTML = "html"
    REVEALJS = "revealjs"
    MARP = "marp"


class Intent(StrEnum):
    """What the user is asking the coordinator to do."""

    CREATE = "create"
    EDIT = "edit"
    RESTYLE = "restyle"
    REORDER = "reorder"
    EXPORT = "export"
    QUESTION = "question"
    CLARIFY = "clarify"
    CHAT = "chat"
