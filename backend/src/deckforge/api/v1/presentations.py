"""Presentation endpoints: read, preview, edit, version control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query, status
from fastapi.responses import HTMLResponse

from deckforge.api.deps import ContainerDep, PresentationServiceDep
from deckforge.models.chat import PresentationRead, PresentationSummary, VersionSummary
from deckforge.models.deck import Presentation
from deckforge.models.ops import OperationBatch, apply_operations

router = APIRouter(prefix="/presentations", tags=["presentations"])


def _summary(row: Any) -> PresentationSummary:
    return PresentationSummary(
        id=row.id,
        conversation_id=row.conversation_id,
        title=row.title,
        theme=row.theme,
        slide_count=len(row.deck.get("slides", [])),
        version=row.current_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "", response_model=list[PresentationSummary], summary="List a conversation's presentations"
)
async def list_presentations(
    service: PresentationServiceDep, conversation_id: str = Query(...)
) -> list[PresentationSummary]:
    rows = await service.uow.presentations.list_for_conversation(conversation_id)
    return [_summary(r) for r in rows]


@router.get("/{presentation_id}", response_model=PresentationRead, summary="Get a presentation")
async def get_presentation(
    presentation_id: str, service: PresentationServiceDep
) -> PresentationRead:
    row = await service.get_row(presentation_id)
    versions = await service.versions(presentation_id)
    return PresentationRead(
        **_summary(row).model_dump(),
        deck=row.deck,
        versions=[VersionSummary(**v) for v in versions],
    )


@router.put("/{presentation_id}/deck", response_model=PresentationRead, summary="Replace the deck")
async def replace_deck(
    presentation_id: str,
    service: PresentationServiceDep,
    deck: dict[str, Any] = Body(...),
    label: str = Body("Manual edit", embed=True),
) -> PresentationRead:
    """Overwrite the deck JSON — used by direct manipulation in the editor."""
    row = await service.get_row(presentation_id)
    model = Presentation.model_validate(deck)
    await service.commit_version(row, model, label=label)
    return await get_presentation(presentation_id, service)


@router.post(
    "/{presentation_id}/operations",
    response_model=PresentationRead,
    summary="Apply deck operations",
)
async def apply_ops(
    presentation_id: str, batch: OperationBatch, service: PresentationServiceDep
) -> PresentationRead:
    """Apply the same operation language the revision agent emits.

    This is what powers drag-to-reorder, delete and duplicate in the UI: the
    client sends operations, never a mutated deck, so client and agent edits go
    through one validated path.
    """
    row = await service.get_row(presentation_id)
    deck = Presentation.model_validate(row.deck)
    result = apply_operations(deck, batch.operations)
    await service.commit_version(
        row, deck, label=batch.summary or "Manual edit", change_log=result.applied
    )
    return await get_presentation(presentation_id, service)


@router.get(
    "/{presentation_id}/versions", response_model=list[VersionSummary], summary="Version history"
)
async def list_versions(
    presentation_id: str, service: PresentationServiceDep
) -> list[VersionSummary]:
    return [VersionSummary(**v) for v in await service.versions(presentation_id)]


@router.post(
    "/{presentation_id}/versions/{version}/restore",
    response_model=PresentationRead,
    summary="Restore a version",
)
async def restore_version(
    presentation_id: str, version: int, service: PresentationServiceDep
) -> PresentationRead:
    await service.restore(presentation_id, version)
    return await get_presentation(presentation_id, service)


@router.post("/{presentation_id}/undo", response_model=PresentationRead, summary="Undo")
async def undo(presentation_id: str, service: PresentationServiceDep) -> PresentationRead:
    await service.undo(presentation_id)
    return await get_presentation(presentation_id, service)


@router.get("/{presentation_id}/compare", summary="Compare two versions")
async def compare(
    presentation_id: str,
    service: PresentationServiceDep,
    left: int = Query(..., ge=1),
    right: int = Query(..., ge=1),
) -> dict[str, Any]:
    return await service.compare(presentation_id, left, right)


@router.post(
    "/{presentation_id}/fork",
    response_model=PresentationSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Fork a presentation",
)
async def fork(
    presentation_id: str,
    service: PresentationServiceDep,
    version: int | None = Query(None),
    title: str | None = Query(None),
) -> PresentationSummary:
    row = await service.fork(presentation_id, version=version, title=title)
    return _summary(row)


@router.delete(
    "/{presentation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a presentation"
)
async def delete_presentation(presentation_id: str, service: PresentationServiceDep) -> None:
    await service.delete(presentation_id)


@router.get(
    "/{presentation_id}/preview",
    response_class=HTMLResponse,
    summary="Rendered HTML preview",
)
async def preview(
    presentation_id: str,
    service: PresentationServiceDep,
    container: ContainerDep,
    version: int | None = Query(None),
    slide: str | None = Query(None, description="Render a single slide by id."),
    standalone: bool = Query(True),
) -> HTMLResponse:
    """Server-rendered preview — the exact HTML the exporters are built on."""
    deck = (
        await service.load_version(presentation_id, version)
        if version is not None
        else await service.load(presentation_id)
    )
    theme = container.themes.for_deck(deck)
    if slide:
        target = deck.slide_by_id(slide)
        if target is not None:
            deck.slides = [target]
    html = container.renderer.render_document(deck, theme, standalone=standalone)
    return HTMLResponse(content=html)


@router.get("/{presentation_id}/stylesheet", summary="Theme stylesheet for client rendering")
async def stylesheet(
    presentation_id: str, service: PresentationServiceDep, container: ContainerDep
) -> dict[str, Any]:
    """CSS plus per-slide HTML, so the client can render without an iframe."""
    deck = await service.load(presentation_id)
    theme = container.themes.for_deck(deck)
    frames = container.layouts.resolve_deck(deck, theme)
    return {
        "css": container.renderer.stylesheet(theme),
        "theme": theme.name,
        "mode": theme.mode,
        "slides": [
            {
                "id": slide.id,
                "index": index,
                "html": container.renderer.render_slide(slide, theme, frame, index=index),
                "layout": frame.layout,
                "kind": str(slide.kind),
                "title": slide.title,
                "notes": slide.notes,
            }
            for index, (slide, frame) in enumerate(zip(deck.slides, frames, strict=True))
        ],
    }
