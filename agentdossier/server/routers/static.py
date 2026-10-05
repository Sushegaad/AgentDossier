"""Catalog files and the web UI."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ... import __version__
from ..deps import Deps, deps

router = APIRouter()


# --- static: catalog files and the web UI ----------------------------------------------
@router.get("/catalog/{path:path}")
def catalog_file(request: Request, path: str):
    d = deps(request)
    d.user(request)
    base = d.catalog.path.resolve()
    target = (base / path).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(404)
    if not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


def mount(app: FastAPI, d: Deps) -> None:
    """Register the catalog route and serve the web UI (or a JSON index) at /."""
    app.include_router(router)
    dist = d.settings.web_dist
    if dist and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")
    else:

        @app.get("/")
        def root():
            return JSONResponse(
                {
                    "name": "AgentDossier",
                    "version": __version__,
                    "docs": "/api/docs",
                    "ard": "/.well-known/ard.json",
                }
            )
