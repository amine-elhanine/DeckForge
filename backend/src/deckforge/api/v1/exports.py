"""Export endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from deckforge.api.deps import ExportServiceDep, PresentationServiceDep, SettingsDep
from deckforge.core.errors import NotFoundError
from deckforge.exporters.base import EXPORTERS, exporter_catalog
from deckforge.models.chat import ExportRead, ExportRequest

router = APIRouter(tags=["exports"])


@router.get("/formats", summary="List export formats")
async def formats() -> list[dict[str, object]]:
    return exporter_catalog()


@router.post(
    "/presentations/{presentation_id}/exports",
    response_model=ExportRead,
    summary="Render and store an export",
)
async def create_export(
    presentation_id: str,
    payload: ExportRequest,
    service: ExportServiceDep,
    settings: SettingsDep,
) -> ExportRead:
    record = await service.export(
        presentation_id, payload.format.value, version=payload.version, options=payload.options
    )
    return ExportRead(
        id=record.id,
        presentation_id=record.presentation_id,
        format=record.format,
        filename=record.filename,
        size_bytes=record.size_bytes,
        created_at=record.created_at,
        download_url=f"{settings.api_prefix}/exports/{record.id}/download",
    )


@router.get(
    "/presentations/{presentation_id}/exports",
    response_model=list[ExportRead],
    summary="Export history",
)
async def export_history(
    presentation_id: str, service: ExportServiceDep, settings: SettingsDep
) -> list[ExportRead]:
    return [
        ExportRead(
            id=r.id,
            presentation_id=r.presentation_id,
            format=r.format,
            filename=r.filename,
            size_bytes=r.size_bytes,
            created_at=r.created_at,
            download_url=f"{settings.api_prefix}/exports/{r.id}/download",
        )
        for r in await service.history(presentation_id)
    ]


@router.get("/exports/{export_id}/download", summary="Download an export")
async def download_export(export_id: str, service: ExportServiceDep) -> FileResponse:
    record = await service.record(export_id)
    path = Path(record.path)
    # Even a stat() call blocks the event loop on a slow or network volume.
    if not await asyncio.to_thread(path.is_file):
        raise NotFoundError(f"export file for '{export_id}' is missing")
    exporter = EXPORTERS.try_get(record.format)
    return FileResponse(
        path,
        filename=record.filename,
        media_type=exporter.media_type if exporter else "application/octet-stream",
    )


@router.get(
    "/presentations/{presentation_id}/download",
    summary="Render and download in one call",
)
async def download_now(
    presentation_id: str,
    service: ExportServiceDep,
    presentations: PresentationServiceDep,
    format: str = Query("pptx"),
    version: int | None = Query(None),
) -> Response:
    """Convenience endpoint: render on the fly without keeping a copy on disk."""
    deck = (
        await presentations.load_version(presentation_id, version)
        if version is not None
        else await presentations.load(presentation_id)
    )
    result = service.render(deck, format)
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={"content-disposition": f'attachment; filename="{result.filename}"'},
    )
