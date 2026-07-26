"""Catalog endpoints: what this installation can do.

Everything here reads from a registry, so a newly installed plugin shows up in
the UI without a code change on either side.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse

from deckforge.api.deps import ContainerDep, UowDep
from deckforge.core.errors import NotFoundError
from deckforge.models.chat import LayoutInfo, PluginInfo, ProviderInfo, ThemeInfo
from deckforge.renderers import icons
from deckforge.retrieval.extractors import supported_extensions

router = APIRouter(tags=["catalog"])


@router.get("/providers", response_model=list[ProviderInfo], summary="List LLM providers")
async def list_providers(container: ContainerDep) -> list[ProviderInfo]:
    return [ProviderInfo(**info) for info in container.providers.describe()]


@router.get("/providers/{name}/models", summary="List a provider's models")
async def provider_models(
    name: str, container: ContainerDep, refresh: bool = Query(True)
) -> dict[str, Any]:
    """Query the backend for its model list; falls back to the suggested list."""
    provider = container.providers.get(name)
    try:
        models = await provider.list_models() if refresh else []
    except Exception as exc:
        return {"provider": name, "models": [], "reachable": False, "error": str(exc)}
    return {"provider": name, "models": models, "reachable": True}


# Credentials are configured as *saved connections* — see `/llm/connections`.
# One provider can have several (different endpoints, models or keys), which a
# single per-provider record could not express.


@router.get("/themes", response_model=list[ThemeInfo], summary="List themes")
async def list_themes(container: ContainerDep) -> list[ThemeInfo]:
    return [ThemeInfo(**info) for info in container.themes.catalog()]


@router.get("/themes/{name}", summary="Get a resolved theme")
async def get_theme(name: str, container: ContainerDep) -> dict[str, Any]:
    theme = container.themes.get(name)
    return {**theme.model_dump(mode="json"), "css_variables": theme.css_variables()}


@router.post("/themes", summary="Create or update a custom theme")
async def upsert_theme(
    container: ContainerDep,
    uow: UowDep,
    definition: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Store a theme in the database; it becomes selectable immediately."""
    from deckforge.database.entities import ThemeRecord

    name = str(definition.get("name") or "").strip().lower()
    if not name:
        raise NotFoundError("theme definition needs a 'name'")
    record = await uow.themes.by_name(name)
    if record is None:
        record = ThemeRecord(name=name, label=str(definition.get("label", name)))
        await uow.themes.add(record)
    record.definition = definition
    record.based_on = definition.get("extends")
    await uow.flush()
    container.themes.add_definition(name, definition, source="database")
    return {"name": name, "saved": True}


@router.post("/themes/reload", summary="Rescan theme directories")
async def reload_themes(container: ContainerDep) -> dict[str, Any]:
    container.themes.reload()
    return {"themes": container.themes.names()}


@router.get("/layouts", response_model=list[LayoutInfo], summary="List layouts")
async def list_layouts(container: ContainerDep) -> list[LayoutInfo]:
    return [
        LayoutInfo(
            name=str(item["name"]),
            label=str(item["label"]),
            description=str(item["description"]),
            slots=cast("list[str]", item["slots"]),
            suits=cast("list[str]", item["suits"]),
        )
        for item in container.layouts.catalog()
    ]


@router.get("/icons", summary="List available icons")
async def list_icons() -> dict[str, Any]:
    return {"icons": icons.available(), "keywords": icons.KEYWORD_MAP}


@router.get("/plugins", response_model=list[PluginInfo], summary="List loaded plugins")
async def list_plugins(container: ContainerDep) -> list[PluginInfo]:
    return [PluginInfo(**info) for info in container.plugins.catalog()]


@router.get("/capabilities", summary="Everything this installation supports")
async def capabilities(container: ContainerDep) -> dict[str, Any]:
    from deckforge.exporters.base import exporter_catalog

    return {
        "providers": container.providers.describe(),
        "themes": container.themes.names(),
        "layouts": container.layouts.names(),
        "exporters": exporter_catalog(),
        "icons": len(icons.available()),
        "uploads": supported_extensions(),
        "plugins": container.plugins.catalog(),
        "plugin_errors": container.plugins.errors,
    }


@router.get("/assets/{conversation_id}/{filename}", summary="Serve a stored asset")
async def get_asset(conversation_id: str, filename: str, container: ContainerDep) -> FileResponse:
    """Serve an uploaded image for use inside slides."""
    root = container.settings.assets_dir.resolve()
    candidate = (root / conversation_id / Path(filename).name).resolve()
    if not candidate.is_file() or root not in candidate.parents:
        raise NotFoundError(f"asset '{filename}' not found")
    return FileResponse(candidate)
