"""Saved LLM connections: add, edit, test, switch, delete."""

from __future__ import annotations

from fastapi import APIRouter, status

from deckforge.api.deps import LlmServiceDep
from deckforge.models.llm import (
    LlmProbeRequest,
    LlmProbeResult,
    LlmProfileCreate,
    LlmProfileRead,
    LlmProfileUpdate,
    ProviderTemplate,
)

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers", response_model=list[ProviderTemplate], summary="Provider templates")
async def provider_templates(service: LlmServiceDep) -> list[ProviderTemplate]:
    """Every adapter with its default endpoint and suggested models."""
    return service.templates()


@router.get("/connections", response_model=list[LlmProfileRead], summary="List connections")
async def list_connections(service: LlmServiceDep) -> list[LlmProfileRead]:
    return await service.list_all()


@router.post(
    "/connections",
    response_model=LlmProfileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a connection",
)
async def create_connection(payload: LlmProfileCreate, service: LlmServiceDep) -> LlmProfileRead:
    return service.to_read(await service.create(payload))


@router.get("/connections/{profile_id}", response_model=LlmProfileRead, summary="Get a connection")
async def get_connection(profile_id: str, service: LlmServiceDep) -> LlmProfileRead:
    return service.to_read(await service.get(profile_id))


@router.patch(
    "/connections/{profile_id}", response_model=LlmProfileRead, summary="Edit a connection"
)
async def update_connection(
    profile_id: str, payload: LlmProfileUpdate, service: LlmServiceDep
) -> LlmProfileRead:
    """Partial update.

    Omit ``api_key`` to keep the stored key, send a new string to replace it, or
    send an empty string to clear it.
    """
    return service.to_read(await service.update(profile_id, payload))


@router.post(
    "/connections/{profile_id}/activate",
    response_model=LlmProfileRead,
    summary="Use this connection",
)
async def activate_connection(profile_id: str, service: LlmServiceDep) -> LlmProfileRead:
    return service.to_read(await service.activate(profile_id))


@router.delete(
    "/connections/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connection",
)
async def delete_connection(profile_id: str, service: LlmServiceDep) -> None:
    await service.delete(profile_id)


@router.post("/test", response_model=LlmProbeResult, summary="Test a connection")
async def test_connection(payload: LlmProbeRequest, service: LlmServiceDep) -> LlmProbeResult:
    """Reach the endpoint and list its models.

    Works for an unsaved form (send the fields) or a saved one (send
    ``profile_id`` and the stored key is reused).
    """
    return await service.probe(payload)
