"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from deckforge import __version__, paths
from deckforge.api.spa import mount_spa
from deckforge.api.v1 import router as v1_router
from deckforge.config import Settings, get_settings
from deckforge.container import Container
from deckforge.core.errors import DeckForgeError
from deckforge.core.logging import get_logger

log = get_logger(__name__)

DESCRIPTION = """\
A local-first, agentic presentation platform.

Talk to the assistant in a conversation; it plans, researches, writes, designs and
reviews a deck, then keeps editing it with you. Decks are JSON; PPTX, PDF, HTML,
Reveal.js, Marp and Markdown are projections of that JSON.
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """Build the ASGI application.

    Args:
        settings: overrides the environment-derived settings.
        container: an already-started container; supplying one skips construction
            and lets tests share a single database engine with the app.
    """
    settings = settings or get_settings()
    started_externally = container is not None
    container = container or Container.create(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not started_externally:
            await container.startup()
        app.state.container = container
        log.info("app.started", version=__version__, environment=settings.environment)
        try:
            yield
        finally:
            if not started_externally:
                await container.shutdown()
            log.info("app.stopped")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["content-disposition"],
    )

    @app.exception_handler(DeckForgeError)
    async def _domain_error(_request: Request, exc: DeckForgeError) -> JSONResponse:
        """Map domain errors onto HTTP without leaking stack traces."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.get("/health", tags=["system"], summary="Liveness and dependency check")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "database": await container.database.ping(),
            "themes": len(container.themes.names()),
            "layouts": len(container.layouts.names()),
            "plugins": len(container.plugins.loaded),
            "default_provider": settings.default_provider,
            "paths": paths.describe(),
        }

    app.include_router(v1_router, prefix=settings.api_prefix)
    # Mounted last: the SPA claims "/" as a catch-all, so every API route must
    # already be registered.
    mount_spa(app, paths.bundled_web_dir(), settings.api_prefix)
    return app


def __getattr__(name: str) -> FastAPI:
    """Build the ASGI app lazily on first access.

    ``uvicorn deckforge.main:app`` still works, but merely *importing* this
    module no longer constructs a container — which the desktop shell does when
    it reaches for :func:`create_app`, and which would otherwise load every
    plugin and open a database engine twice per launch.
    """
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
