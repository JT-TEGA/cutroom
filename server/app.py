"""Cutroom API.

    uvicorn server.app:app --port 8000        (or: scripts/ve serve)
    docs: http://127.0.0.1:8000/docs

Every error comes back as {"error": {"code", "message", "hint"}} with a fitting HTTP status, whether it happens in
the request or later in a background job (then it is on the job: GET /jobs/{id} -> "error").
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from engine import __version__, pipeline
from engine.config import EngineError, paths

from .deps import Services
from .routes import config_routes, files, jobs, media, projects

TAGS = [
    {"name": "projects", "description": "One video per project: brief, files, status."},
    {"name": "files", "description": "Clips, photos (HEIC ok), voiceover and music in edit order."},
    {"name": "editing", "description": "Brain calls and renders. They run as background jobs."},
    {"name": "jobs", "description": "Progress of background work (also as a WebSocket stream)."},
    {"name": "media", "description": "Streaming (HTTP range) and thumbnails."},
    {"name": "config", "description": "Presets, brand + app settings, system status."},
]


def create_app(services: Services | None = None) -> FastAPI:
    svc = services or Services()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc.jobs.loop = asyncio.get_running_loop()
        paths().workspace.mkdir(parents=True, exist_ok=True)
        for job in svc.jobs.restore():
            if job.project_id and job.started_at:          # it was half-way through: the project shows the error
                err = job.error or {}
                pipeline.failed(svc.store, job.project_id,
                                EngineError(err.get("message", ""), code="interrupted", hint=err.get("hint")))
        yield
        svc.jobs.shutdown()

    app = FastAPI(title="Cutroom API", version=__version__, lifespan=lifespan, openapi_tags=TAGS,
                  description="Short-form (9:16) video editor backend. The editing decisions are made by Claude "
                              "through your logged-in Claude Code (no API key); the pipeline does the rest.")
    app.state.services = svc
    origins = os.environ.get("CUTROOM_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in origins if o.strip()],
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Range", "Accept-Ranges"])

    @app.exception_handler(EngineError)
    async def engine_error(_: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.to_dict()})

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": "Cutroom API", "version": __version__, "docs": "/docs"}

    for r in (projects.router, files.router, jobs.router, media.router, config_routes.router):
        app.include_router(r)
    return app


app = create_app()
