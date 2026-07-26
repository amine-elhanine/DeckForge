"""Export service: render a deck through any registered exporter and record it."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from deckforge.config import Settings
from deckforge.core.errors import ExportError, NotFoundError
from deckforge.core.logging import get_logger
from deckforge.database.entities import ExportRecord
from deckforge.database.repositories import UnitOfWork
from deckforge.exporters.base import EXPORTERS, ExportContext, ExportResult
from deckforge.layouts.engine import LayoutEngine
from deckforge.models.deck import Presentation
from deckforge.renderers.html import HtmlRenderer
from deckforge.services.presentation_service import PresentationService
from deckforge.themes.engine import ThemeEngine
from deckforge.utils.text import slugify

log = get_logger(__name__)


class ExportService:
    """Turns decks into files."""

    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        themes: ThemeEngine,
        layouts: LayoutEngine,
        renderer: HtmlRenderer,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.themes = themes
        self.layouts = layouts
        self.renderer = renderer
        self.presentations = PresentationService(uow)

    def context(self, deck: Presentation, options: dict[str, Any] | None = None) -> ExportContext:
        return ExportContext(
            theme=self.themes.for_deck(deck),
            layouts=self.layouts,
            renderer=self.renderer,
            assets_dir=self.settings.assets_dir,
            options=options or {},
        )

    def render(
        self, deck: Presentation, fmt: str, options: dict[str, Any] | None = None
    ) -> ExportResult:
        """Render ``deck`` without persisting anything.

        Raises:
            NotFoundError: if the format is not registered.
            ExportError: if the exporter fails.
        """
        exporter = EXPORTERS.try_get(fmt)
        if exporter is None:
            raise NotFoundError(
                f"unknown export format '{fmt}'", details={"available": EXPORTERS.names()}
            )
        try:
            return exporter.export(deck, self.context(deck, options))
        except ExportError:
            raise
        except Exception as exc:
            log.warning("export.failed", format=fmt, error=str(exc))
            raise ExportError(f"{exporter.label} export failed: {exc}") from exc

    async def export(
        self,
        presentation_id: str,
        fmt: str,
        *,
        version: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> ExportRecord:
        """Render and store a deck, returning the export record."""
        row = await self.presentations.get_row(presentation_id)
        deck = (
            await self.presentations.load_version(presentation_id, version)
            if version is not None
            else Presentation.model_validate(row.deck)
        )
        result = self.render(deck, fmt, options)

        target = self._target_path(deck, result.filename)
        target.write_bytes(result.content)

        record = ExportRecord(
            presentation_id=row.id,
            version=version or row.current_version,
            format=fmt,
            filename=result.filename,
            path=str(target),
            size_bytes=result.size,
            options=options or {},
        )
        await self.uow.exports.add(record)
        log.info("export.done", presentation=row.id, format=fmt, bytes=result.size)
        return record

    def _target_path(self, deck: Presentation, filename: str) -> Path:
        directory = self.settings.exports_dir / slugify(deck.title or "deck")
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{uuid.uuid4().hex[:8]}-{filename}"

    async def history(self, presentation_id: str) -> list[ExportRecord]:
        return list(await self.uow.exports.history(presentation_id))

    async def record(self, export_id: str) -> ExportRecord:
        record = await self.uow.exports.get(export_id)
        if record is None:
            raise NotFoundError(f"export '{export_id}' not found")
        return record
