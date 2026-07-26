"""Conversation memory.

Four layers, all local:

* **conversation memory** — durable facts about this thread (audience, brand
  colours, "always use metric units"), stored on the conversation row
* **presentation memory** — the deck itself plus its version chain
* **slide memory** — the denormalised slide index, for search and reference
* **preferences** — provider, model, theme and language defaults

Memory is written deterministically from observed events rather than by asking a
model to summarise the conversation, so it cannot drift or hallucinate.
"""

from __future__ import annotations

import re
from typing import Any

from deckforge.core.logging import get_logger
from deckforge.database.entities import Conversation
from deckforge.database.repositories import UnitOfWork
from deckforge.models.deck import Presentation

log = get_logger(__name__)

MAX_FACTS = 40

_THEME_RE = re.compile(r"\b(?:use|switch to|make it)\s+(?:the\s+)?([a-z_]+)\s+theme\b", re.I)
_AUDIENCE_RE = re.compile(
    r"\b(?:for|aimed at|targeting|audience is)\s+((?:an?\s+)?[a-z][a-z \-]{3,40})", re.I
)
_LANGUAGE_RE = re.compile(
    r"\b(?:in|translate (?:it |this )?(?:in)?to)\s+"
    r"(english|french|german|spanish|arabic|portuguese|italian|dutch|japanese|korean|"
    r"chinese|hindi|turkish|polish|russian)\b",
    re.I,
)


class MemoryService:
    """Reads and writes the durable state behind a conversation."""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    # -- conversation memory -------------------------------------------------- #

    async def load(self, conversation: Conversation) -> dict[str, Any]:
        """Return the conversation's memory dictionary."""
        return dict(conversation.memory or {})

    async def remember(self, conversation: Conversation, **facts: Any) -> dict[str, Any]:
        """Merge ``facts`` into conversation memory."""
        memory = dict(conversation.memory or {})
        for key, value in facts.items():
            if value in (None, "", [], {}):
                continue
            memory[key] = value
        if len(memory) > MAX_FACTS:
            memory = dict(list(memory.items())[-MAX_FACTS:])
        conversation.memory = memory
        await self.uow.flush()
        return memory

    async def observe_message(self, conversation: Conversation, message: str) -> dict[str, Any]:
        """Extract durable preferences from what the user just typed.

        Only high-confidence, explicitly stated preferences are captured — the
        cost of a wrong "fact" that silently steers every future deck is far
        higher than the cost of missing one.
        """
        found: dict[str, Any] = {}
        if match := _THEME_RE.search(message):
            found["theme"] = match.group(1).lower()
        if match := _AUDIENCE_RE.search(message):
            found["audience"] = match.group(1).strip().rstrip(".,")
        if match := _LANGUAGE_RE.search(message):
            found["language"] = match.group(1).lower()
        return (
            await self.remember(conversation, **found) if found else dict(conversation.memory or {})
        )

    # -- preferences ---------------------------------------------------------- #

    async def preferences(self, conversation: Conversation) -> dict[str, Any]:
        """Merge global settings, conversation settings and learned memory.

        Precedence, lowest first: global defaults, learned memory, explicit
        conversation settings. What the user set explicitly always wins.
        """
        globals_ = await self.uow.settings.get_value("preferences", {})
        memory = dict(conversation.memory or {})
        explicit = {k: v for k, v in (conversation.settings or {}).items() if v is not None}
        return {**globals_, **memory, **explicit}

    async def set_global_preferences(self, values: dict[str, Any]) -> dict[str, Any]:
        current = await self.uow.settings.get_value("preferences", {})
        merged = {**current, **values}
        await self.uow.settings.set_value("preferences", merged)
        return merged

    # -- deck memory ---------------------------------------------------------- #

    async def deck_digest(self, deck: Presentation) -> dict[str, Any]:
        """A small, promptable summary of a deck for later turns."""
        return {
            "title": deck.title,
            "theme": deck.theme,
            "slides": len(deck.slides),
            "audience": deck.meta.audience,
            "tone": deck.meta.tone,
            "language": deck.meta.language,
            "sections": [s.title for s in deck.sections],
        }

    async def note_deck(self, conversation: Conversation, deck: Presentation) -> None:
        """Record the current deck's shape so later turns have context cheaply."""
        await self.remember(
            conversation,
            last_deck=await self.deck_digest(deck),
            theme=deck.theme,
            language=deck.meta.language,
            audience=deck.meta.audience,
        )
