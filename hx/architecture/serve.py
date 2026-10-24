"""Dedicated architecture preview, with optional existing Hx source navigation."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .presentation import build_html, payload
from .service import load_architecture


def create_architecture_app(design: str, *, root: str | None = None,
                            graph: str | None = None, bridge: str | None = None) -> FastAPI:
    """Preview D2 on /architecture; an optional saved graph enables the source viewer.

    Browser refresh recompiles the design and its imports. No extraction runs.
    The code viewer retains its normal annotation behavior, separately from D2.
    """
    source = str(Path(design).resolve())
    project = str(Path(root).resolve()) if root else str(Path(source).parent)
    saved = str(Path(graph).resolve()) if graph else None
    if saved:
        from ..serve.app import create_app
        app = create_app(saved, allow_extract=False)
    else:
        app = FastAPI(title="Hx architecture", docs_url=None, redoc_url=None)

        @app.get("/")
        def home():
            return RedirectResponse("/architecture")

    @app.get("/architecture", response_class=HTMLResponse)
    def page():
        return HTMLResponse(build_html())

    @app.get("/api/architecture")
    def architecture(request: Request):
        try:
            doc = load_architecture(source, root=project, graph=saved, bridge=bridge)
            return payload(doc, str(request.base_url) if saved else None)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    return app
