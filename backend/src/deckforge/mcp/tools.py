"""The tools DeckForge exposes over MCP.

Deliberately thin. Every one of these delegates to the same services the REST
API uses, so there is no deck logic here to drift out of step with the app —
only argument schemas, a progress bridge and error translation.

The calling agent never sees a conversation id. `create_deck` opens one behind
the scenes and returns a deck id; `refine_deck` finds its way back from there.
Version history, undo and the desktop app's sidebar all keep working because the
turn went through the ordinary pipeline.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import types

from deckforge.core.errors import DeckForgeError, NotFoundError, ProviderNotConfiguredError
from deckforge.core.events import EventType
from deckforge.core.logging import get_logger
from deckforge.exporters.base import EXPORTERS, exporter_catalog
from deckforge.mcp.runtime import Runtime, Services
from deckforge.models.chat import ConversationSettings, MessageCreate
from deckforge.models.deck import Presentation
from deckforge.models.enums import ContentDensity

log = get_logger(__name__)

#: Called with (progress 0..1, message) while a turn runs.
ProgressFn = Callable[[float, str], Awaitable[None]]

#: What to tell an agent that has no model configured. A bare "provider not
#: configured" sends it round in circles; this says exactly which door to open.
NO_LLM_HELP = (
    "No language model is configured. Open the DeckForge desktop app, go to "
    "Settings and add a model connection (a local Ollama endpoint or a cloud "
    "API key), or set the provider's key in the .env file in DeckForge's data "
    "directory. Call `deckforge_capabilities` to check the current state."
)

DENSITY_HELP = (
    "How much prose each slide carries. 'concise' is speaker cues, 'balanced' is "
    "a lead sentence plus full-clause bullets, 'rich' is explanatory paragraphs "
    "that read without a presenter. Defaults to the application setting (rich)."
)


def tool_definitions() -> list[types.Tool]:
    """The advertised tool list."""
    formats = EXPORTERS.names()
    return [
        types.Tool(
            name="create_deck",
            title="Create a presentation",
            description=(
                "Generate a complete slide deck from a prompt and return its id and outline. "
                "Runs the full pipeline (plan, outline, write, design, review), which takes "
                "one to four minutes depending on the model and slide count. Refine the result "
                "with `refine_deck` and turn it into a file with `export_deck`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "What the deck should cover, and for whom. Detail helps: audience, "
                            "tone and purpose all change the result."
                        ),
                        "minLength": 1,
                    },
                    "theme": {
                        "type": "string",
                        "description": (
                            "Visual theme name. Omit to let DeckForge choose one that suits the "
                            "topic. `deckforge_capabilities` lists the installed themes."
                        ),
                    },
                    "slide_count": {
                        "type": "integer",
                        "description": "Roughly how many slides. Omit to let the planner decide.",
                        "minimum": 1,
                        "maximum": 60,
                    },
                    "density": {
                        "type": "string",
                        "enum": [d.value for d in ContentDensity],
                        "description": DENSITY_HELP,
                    },
                    "language": {
                        "type": "string",
                        "description": "Language for all copy and speaker notes, e.g. 'fr'.",
                    },
                    "audience": {
                        "type": "string",
                        "description": "Who will see this, e.g. 'first-year medical students'.",
                    },
                },
                "required": ["prompt"],
            },
        ),
        types.Tool(
            name="refine_deck",
            title="Refine a presentation",
            description=(
                "Change an existing deck in place using a natural-language instruction — "
                "rewrite a slide, add or remove slides, change the theme, reorder, translate. "
                "Returns what changed and the new outline. Each call adds a version, so earlier "
                "states are never lost."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "deck_id": {"type": "string", "description": "Id returned by `create_deck`."},
                    "instruction": {
                        "type": "string",
                        "description": (
                            "The change to make, e.g. 'merge slides 4 and 5' or 'make the "
                            "closing slide a call to action'. Name slides by their position "
                            "or title."
                        ),
                        "minLength": 1,
                    },
                },
                "required": ["deck_id", "instruction"],
            },
        ),
        types.Tool(
            name="export_deck",
            title="Export a presentation to a file",
            description=(
                "Write a deck to disk and return the absolute path. This is fast and offline — "
                "it does not call a language model."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "deck_id": {"type": "string", "description": "Id returned by `create_deck`."},
                    "format": {
                        "type": "string",
                        "enum": formats,
                        "description": "Output format.",
                        "default": "pptx",
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            "Absolute path to write to, including the filename. Omit to let "
                            "DeckForge store it in its own exports folder and return that path."
                        ),
                    },
                    "version": {
                        "type": "integer",
                        "description": "Export an earlier version instead of the current one.",
                        "minimum": 1,
                    },
                },
                "required": ["deck_id"],
            },
        ),
        types.Tool(
            name="get_deck",
            title="Read a presentation back",
            description="Return a deck's content, for reading or for further processing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "deck_id": {"type": "string", "description": "Id returned by `create_deck`."},
                    "format": {
                        "type": "string",
                        "enum": ["outline", "markdown", "json"],
                        "default": "outline",
                        "description": (
                            "'outline' is a one-line-per-slide summary, 'markdown' is the full "
                            "text including speaker notes, 'json' is the complete deck structure."
                        ),
                    },
                    "version": {
                        "type": "integer",
                        "description": "Read an earlier version instead of the current one.",
                        "minimum": 1,
                    },
                },
                "required": ["deck_id"],
            },
        ),
        types.Tool(
            name="list_decks",
            title="List recent presentations",
            description=(
                "Recently updated decks, newest first, so an earlier one can be picked up "
                "and refined or exported."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many decks to return, newest first.",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 20,
                    },
                },
            },
            annotations=types.ToolAnnotations(readOnlyHint=True),
        ),
        types.Tool(
            name="deckforge_capabilities",
            title="Check what DeckForge can do",
            description=(
                "Themes, layouts and export formats available, and whether a language model is "
                "configured. Worth calling before `create_deck`: it distinguishes 'not set up "
                "yet' from a failure, without spending minutes finding out."
            ),
            inputSchema={"type": "object", "properties": {}},
            annotations=types.ToolAnnotations(readOnlyHint=True),
        ),
    ]


@dataclass(slots=True)
class TurnOutcome:
    """What one pass through the agent pipeline produced."""

    presentation_id: str | None
    version: int | None
    reply: str
    error: str | None


async def dispatch(
    runtime: Runtime, name: str, arguments: dict[str, Any], progress: ProgressFn | None
) -> dict[str, Any]:
    """Route a tool call. Raises :class:`DeckForgeError` for expected failures."""
    async with runtime.services() as services:
        match name:
            case "create_deck":
                return await _create_deck(services, arguments, progress)
            case "refine_deck":
                return await _refine_deck(services, arguments, progress)
            case "export_deck":
                return await _export_deck(services, arguments)
            case "get_deck":
                return await _get_deck(services, arguments)
            case "list_decks":
                return await _list_decks(services, arguments)
            case "deckforge_capabilities":
                return await _capabilities(services)
            case _:
                raise NotFoundError(f"unknown tool '{name}'")


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


async def _create_deck(
    services: Services, arguments: dict[str, Any], progress: ProgressFn | None
) -> dict[str, Any]:
    settings = ConversationSettings(
        theme=arguments.get("theme"),
        language=arguments.get("language"),
        audience=arguments.get("audience"),
        density=arguments.get("density"),
        default_slide_count=arguments.get("slide_count"),
    )
    conversation = await services.conversations.create(
        title=None, settings=settings.model_dump(exclude_none=True)
    )
    outcome = await _run_turn(services, conversation.id, arguments["prompt"], progress)
    if outcome.presentation_id is None:
        raise _no_deck_error(outcome)
    return await _deck_summary(services, outcome.presentation_id, reply=outcome.reply)


async def _refine_deck(
    services: Services, arguments: dict[str, Any], progress: ProgressFn | None
) -> dict[str, Any]:
    deck_id = arguments["deck_id"]
    row = await services.presentations.get_row(deck_id)
    outcome = await _run_turn(
        services,
        row.conversation_id,
        arguments["instruction"],
        progress,
        presentation_id=deck_id,
    )
    if outcome.error:
        raise _no_deck_error(outcome)
    summary = await _deck_summary(services, deck_id, reply=outcome.reply)
    summary["changed"] = outcome.version != row.current_version
    return summary


async def _run_turn(
    services: Services,
    conversation_id: str,
    content: str,
    progress: ProgressFn | None,
    *,
    presentation_id: str | None = None,
) -> TurnOutcome:
    """Run one pipeline turn, forwarding status events as MCP progress."""
    payload = MessageCreate(content=content, presentation_id=presentation_id)
    outcome = TurnOutcome(presentation_id=None, version=None, reply="", error=None)

    async for event in services.chat.stream(conversation_id, payload):
        match event.type:
            case EventType.STATUS if progress is not None:
                value = event.data.get("progress")
                if isinstance(value, int | float):
                    await progress(float(value), str(event.data.get("message", "")))
            case EventType.MESSAGE:
                outcome.presentation_id = event.data.get("presentation_id")
                outcome.version = event.data.get("presentation_version")
                outcome.reply = str(event.data.get("content", ""))
            case EventType.ERROR:
                outcome.error = str(event.data.get("message", "the run failed"))
                if event.data.get("code") == "provider_not_configured":
                    raise ProviderNotConfiguredError(NO_LLM_HELP)
            case _:
                # Deck and slide snapshots are for a live preview pane; an agent
                # reads the finished deck back with `get_deck` instead.
                pass
    return outcome


def _no_deck_error(outcome: TurnOutcome) -> DeckForgeError:
    detail = outcome.error or outcome.reply or "the model returned no slides"
    return DeckForgeError(f"DeckForge did not produce a deck: {detail}")


# --------------------------------------------------------------------------- #
# Reading and exporting
# --------------------------------------------------------------------------- #


async def _deck_summary(services: Services, deck_id: str, *, reply: str = "") -> dict[str, Any]:
    row = await services.presentations.get_row(deck_id)
    deck = Presentation.model_validate(row.deck)
    stats = deck.stats()
    return {
        "deck_id": row.id,
        "title": deck.title,
        "theme": deck.theme,
        "version": row.current_version,
        "slide_count": stats["slides"],
        "words_per_slide": stats["avg_words_per_slide"],
        "outline": deck.outline_text(),
        "summary": reply,
    }


async def _get_deck(services: Services, arguments: dict[str, Any]) -> dict[str, Any]:
    deck_id = arguments["deck_id"]
    version = arguments.get("version")
    deck = (
        await services.presentations.load_version(deck_id, version)
        if version is not None
        else await services.presentations.load(deck_id)
    )
    fmt = arguments.get("format", "outline")
    content: Any
    if fmt == "json":
        content = deck.model_dump(mode="json")
    elif fmt == "markdown":
        content = services.exports.render(deck, "markdown").content.decode("utf-8")
    else:
        content = deck.outline_text()
    return {
        "deck_id": deck_id,
        "title": deck.title,
        "format": fmt,
        "version": version,
        "content": content,
    }


async def _export_deck(services: Services, arguments: dict[str, Any]) -> dict[str, Any]:
    deck_id = arguments["deck_id"]
    fmt = arguments.get("format", "pptx")
    version = arguments.get("version")
    destination = arguments.get("output_path")

    if not destination:
        # `settings.data_dir` is resolved at startup, so this is already absolute.
        record = await services.exports.export(deck_id, fmt, version=version)
        return {
            "deck_id": deck_id,
            "format": fmt,
            "path": record.path,
            "filename": record.filename,
            "size_bytes": record.size_bytes,
        }

    # An explicit destination is the agent's to own, so render straight to it
    # rather than writing into DeckForge's exports folder and copying.
    deck = (
        await services.presentations.load_version(deck_id, version)
        if version is not None
        else await services.presentations.load(deck_id)
    )
    result = services.exports.render(deck, fmt)
    target = _write_to(destination, result.filename, result.content)
    return {
        "deck_id": deck_id,
        "format": fmt,
        "path": str(target),
        "filename": target.name,
        "size_bytes": result.size,
    }


def _write_to(destination: str, filename: str, content: bytes) -> Path:
    """Write ``content`` where the caller asked, creating parents as needed.

    A destination naming an existing directory takes the exporter's filename,
    which is what an agent that passes a folder means.
    """
    target = Path(destination).expanduser()
    if target.is_dir():
        target = target / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target.resolve()


async def _list_decks(services: Services, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit", 20))
    rows = await services.uow.presentations.recent(limit)
    return {
        "decks": [
            {
                "deck_id": row.id,
                "title": row.title,
                "theme": row.theme,
                "version": row.current_version,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]
    }


async def _capabilities(services: Services) -> dict[str, Any]:
    container = services.container
    profile = await services.llm.active()
    return {
        "llm_configured": profile is not None,
        "llm": (
            {"name": profile.name, "provider": profile.provider, "model": profile.model}
            if profile
            else None
        ),
        "setup_help": None if profile else NO_LLM_HELP,
        "themes": container.themes.names(),
        "layouts": container.layouts.names(),
        "export_formats": [
            {"name": info["name"], "extension": info["extension"]} for info in exporter_catalog()
        ],
        "content_densities": [d.value for d in ContentDensity],
        "data_dir": str(container.settings.data_dir),
    }


# --------------------------------------------------------------------------- #
# Presentation of results
# --------------------------------------------------------------------------- #


def to_content(payload: dict[str, Any]) -> list[types.ContentBlock]:
    """Render a tool result as text an agent can read without parsing JSON."""
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2, ensure_ascii=False))]
