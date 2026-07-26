"""Serving the built frontend from the API process.

The desktop build has no separate web server: FastAPI serves the exported
Next.js bundle at ``/``. That also makes everything same-origin, which removes
CORS entirely and sidesteps the response buffering that a development proxy
introduces on the Server-Sent Events stream.

When no bundle is present (a source checkout running ``npm run dev``) the mount
is skipped and ``/`` explains where the UI actually is.
"""

from __future__ import annotations

import os
from os import PathLike
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from deckforge.core.logging import get_logger

log = get_logger(__name__)

#: Fingerprinted build output can be cached forever; everything else must not be.
IMMUTABLE_PREFIXES = ("/_next/static/",)
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache, no-store, must-revalidate"


class SpaStaticFiles(StaticFiles):
    """Static files with history-API fallback and sane cache headers."""

    def __init__(self, directory: Path) -> None:
        super().__init__(directory=str(directory), html=True)
        self._index = directory / "index.html"

    def file_response(
        self,
        full_path: str | PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        path = str(scope.get("path", ""))
        response.headers["cache-control"] = (
            IMMUTABLE_CACHE if path.startswith(IMMUTABLE_PREFIXES) else NO_CACHE
        )
        return response

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Fall back to ``index.html`` so client-side routes resolve."""
        response = await super().get_response(path, scope)
        if response.status_code == 404 and self._index.is_file():
            return FileResponse(self._index, headers={"cache-control": NO_CACHE})
        return response


def mount_spa(app: FastAPI, web_dir: Path | None, api_prefix: str) -> bool:
    """Mount the exported frontend at ``/``.

    Returns:
        True if a bundle was found and mounted.
    """
    if web_dir is None or not (web_dir / "index.html").is_file():
        _mount_placeholder(app, api_prefix)
        return False

    # A 404 under the API prefix must stay JSON: the SPA fallback would
    # otherwise hand callers an HTML page where they expect an error body.
    @app.exception_handler(404)
    async def _not_found(request: Request, _exc: Exception) -> JSONResponse | FileResponse:
        if request.url.path.startswith(api_prefix) or request.url.path.startswith("/health"):
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "No such endpoint."}},
            )
        return FileResponse(web_dir / "index.html", headers={"cache-control": NO_CACHE})

    app.mount("/", SpaStaticFiles(web_dir), name="app")
    log.info("spa.mounted", directory=str(web_dir))
    return True


def _mount_placeholder(app: FastAPI, api_prefix: str) -> None:
    """Explain where the UI is when only the API is running."""

    @app.get("/", include_in_schema=False)
    async def _root() -> JSONResponse:
        return JSONResponse(
            {
                "app": "DeckForge",
                "ui": "not bundled in this build — run `npm run dev` in ./frontend",
                "api": api_prefix,
                "docs": "/docs",
            }
        )

    log.info("spa.not_bundled")
