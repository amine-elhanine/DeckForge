"""Domain level exceptions.

The API layer maps these onto HTTP status codes in a single place
(:mod:`deckforge.api.exception_handlers`), so business code never imports
``fastapi.HTTPException``.
"""

from __future__ import annotations


class DeckForgeError(Exception):
    """Base class for every DeckForge error."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DeckForgeError):
    """A requested entity does not exist."""

    status_code = 404
    code = "not_found"


class ValidationError(DeckForgeError):
    """The caller supplied invalid input."""

    status_code = 422
    code = "validation_error"


class ConflictError(DeckForgeError):
    """The operation conflicts with the current state."""

    status_code = 409
    code = "conflict"


class ProviderError(DeckForgeError):
    """An LLM provider failed or is misconfigured."""

    status_code = 502
    code = "provider_error"


class ProviderNotConfiguredError(ProviderError):
    """Credentials or endpoint for the provider are missing."""

    status_code = 400
    code = "provider_not_configured"


class AgentError(DeckForgeError):
    """An agent could not produce a usable structured result."""

    status_code = 502
    code = "agent_error"


class ExportError(DeckForgeError):
    """An exporter failed to render the deck."""

    status_code = 500
    code = "export_error"


class PluginError(DeckForgeError):
    """A plugin failed to load or registered an invalid component."""

    status_code = 500
    code = "plugin_error"


class UnsupportedFileError(ValidationError):
    """An uploaded file type has no registered extractor."""

    code = "unsupported_file"
