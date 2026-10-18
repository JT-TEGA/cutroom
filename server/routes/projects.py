"""Projects and the editing actions on them (analyse, plan, timeline, render, revise, reference)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from engine import pipeline
from engine.config import EngineError, paths
from engine.models import BriefData
from engine.project import Project, ProjectSummary
from engine.timeline import Timeline, TimelineView

from ..deps import Services, services
from ..jobs import Job

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str = Field("", description="defaults to the brief title")
    brief: BriefData | None = None


class ProjectImport(BaseModel):
    path: str | None = Field(None, description="a brief in the repo, e.g. briefs/oct-dump.md")
    markdown: str | None = Field(None, description="or the brief's text")
    name: str | None = None
    copy_media: bool = Field(True, description="copy the clips / voiceover / music the brief names")


class ProjectPatch(BaseModel):
    name: str | None = None
    brief: dict[str, Any] | None = Field(None, description="brief fields to change (others stay)")
    answers: dict[str, str] | None = Field(None, description="answers to clarifying questions, by question id")


class RenderRequest(BaseModel):
    draft: bool = Field(False, description="quicker, lower-quality encode for checking")


class ReviseRequest(BaseModel):
    notes: str = Field(min_length=1, description="what to change, in plain words")
    render: bool = Field(False, description="queue a render when the plan is updated")


class ReferenceRequest(BaseModel):
    url: str | None = Field(None, description="defaults to the brief's reference URL")
    cookies_from_browser: str | None = Field(None, description="e.g. chrome: Instagram often needs your login")


# ---------------------------------------------------------------- CRUD

@router.get("/projects", response_model=list[ProjectSummary], tags=["projects"])
def list_projects(svc: Services = Depends(services)) -> list[ProjectSummary]:
    return svc.store.list()


@router.post("/projects", response_model=Project, status_code=status.HTTP_201_CREATED, tags=["projects"])
def create_project(body: ProjectCreate, svc: Services = Depends(services)) -> Project:
    return svc.store.create(body.name, body.brief)


@router.post("/projects/import", response_model=Project, status_code=status.HTTP_201_CREATED, tags=["projects"])
def import_project(body: ProjectImport, svc: Services = Depends(services)) -> Project:
    """Create a project from a markdown brief (briefs/*.md format)."""
    if body.path:
        root = paths().root.resolve()
        p = (root / body.path).resolve()
        if not p.is_relative_to(root) or p.suffix != ".md":
            raise EngineError("path must be a .md brief inside the Cutroom folder", code="invalid_path", status=422)
        return svc.store.import_markdown(p, copy_media=body.copy_media, name=body.name)
    if body.markdown:
        return svc.store.import_markdown(body.markdown, copy_media=body.copy_media, name=body.name)
    raise EngineError("give either path or markdown", code="invalid_request", status=422)


@router.get("/projects/{pid}", response_model=Project, tags=["projects"])
def get_project(pid: str, svc: Services = Depends(services)) -> Project:
    return svc.store.get(pid)


@router.patch("/projects/{pid}", response_model=Project, tags=["projects"])
def patch_project(pid: str, body: ProjectPatch, svc: Services = Depends(services)) -> Project:
    with svc.store.edit(pid) as p:
        if body.name:
            p.name = body.name.strip()
        if body.brief:
            unknown = set(body.brief) - set(BriefData.model_fields) - {"in"}
            if unknown:
                raise EngineError(f"unknown brief field(s): {', '.join(sorted(unknown))}", code="invalid_brief",
                                  status=422)
            try:
                p.brief = BriefData.model_validate(p.brief.model_dump(by_alias=True) | body.brief)
            except ValueError as e:
                raise EngineError(f"invalid brief: {e}", code="invalid_brief", status=422) from e
        if body.answers:
            p.answers.update(body.answers)
    return svc.store.get(pid)


@router.delete("/projects/{pid}", status_code=status.HTTP_204_NO_CONTENT, tags=["projects"])
def delete_project(pid: str, svc: Services = Depends(services)) -> None:
    busy = svc.jobs.active(pid, ("analyse", "plan", "render", "revise", "reference"))
    if busy:
        raise EngineError(f"a {busy.kind} job is {busy.status} for this project", code="project_busy", status=409)
    svc.store.delete(pid)


@router.get("/projects/{pid}/log", response_class=PlainTextResponse, tags=["projects"])
def project_log(pid: str, lines: int = Query(200, ge=1, le=5000), svc: Services = Depends(services)) -> str:
    """The project's job log: brain calls (purpose, duration), renders, failures."""
    f = svc.store.dir(pid) / "work" / "jobs.log"
    svc.store.get(pid)
    return "\n".join(f.read_text().splitlines()[-lines:]) if f.exists() else ""


# ---------------------------------------------------------------- jobs on a project

async def _respond(svc: Services, job: Job, wait: bool) -> Any:
    if not wait:
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=job.model_dump(mode="json"))
    job = await svc.jobs.wait(job.id)
    if job.status == "failed" and job.error:
        return JSONResponse(status_code=int(job.error.get("status") or 500),
                            content={"error": job.error, "job": job.model_dump(mode="json")})
    return JSONResponse(status_code=status.HTTP_200_OK, content=job.model_dump(mode="json"))


def _guard(svc: Services, pid: str, kinds: tuple[str, ...]) -> None:
    svc.store.get(pid)
    busy = svc.jobs.active(pid, kinds)
    if busy:
        raise EngineError(f"a {busy.kind} job is already {busy.status} for this project (job {busy.id})",
                          code="project_busy", status=409)


def _on_error(svc: Services, pid: str):
    return lambda e: pipeline.failed(svc.store, pid, e)


# Each editing job is started here, from its endpoint or from POST /jobs/{id}/retry with the saved params.

def start_analyse(svc: Services, pid: str, params: dict[str, Any], retry_of: str | None = None) -> Job:
    _guard(svc, pid, ("analyse", "plan", "revise"))
    return svc.jobs.submit("analyse", lambda: pipeline.analyse(svc.store, pid, svc.brain_factory()),
                           project_id=pid, on_error=_on_error(svc, pid), params=params, retry_of=retry_of)


def start_plan(svc: Services, pid: str, params: dict[str, Any], retry_of: str | None = None) -> Job:
    _guard(svc, pid, ("plan", "revise", "render"))
    return svc.jobs.submit("plan", lambda: pipeline.plan(svc.store, pid, svc.brain_factory()),
                           project_id=pid, on_error=_on_error(svc, pid), params=params, retry_of=retry_of)


def start_render(svc: Services, pid: str, params: dict[str, Any], retry_of: str | None = None) -> Job:
    from engine.common import need
    need("ffmpeg")
    need("node")
    _guard(svc, pid, ("plan", "revise", "render"))
    if not (svc.store.dir(pid) / "work" / "edl.json").exists():
        raise EngineError("this project has no plan yet: run plan first", code="no_plan", status=409)
    draft = bool(params.get("draft"))
    return svc.jobs.submit("render", lambda: pipeline.render(svc.store, pid, draft), project_id=pid,
                           queue="render", on_error=_on_error(svc, pid), params=params, retry_of=retry_of)


def start_revise(svc: Services, pid: str, params: dict[str, Any], retry_of: str | None = None) -> Job:
    _guard(svc, pid, ("plan", "revise", "render"))

    def then_render(_: Any) -> None:
        if params.get("render"):
            svc.jobs.submit("render", lambda: pipeline.render(svc.store, pid), project_id=pid, queue="render",
                            on_error=_on_error(svc, pid), params={"draft": False})

    return svc.jobs.submit("revise", lambda: pipeline.revise(svc.store, pid, params["notes"], svc.brain_factory()),
                           project_id=pid, on_error=_on_error(svc, pid), on_done=then_render, params=params,
                           retry_of=retry_of)


def start_reference(svc: Services, pid: str, params: dict[str, Any], retry_of: str | None = None) -> Job:
    _guard(svc, pid, ("reference", "plan"))
    return svc.jobs.submit("reference", lambda: pipeline.reference(svc.store, pid, svc.brain_factory(),
                                                                   params.get("url"),
                                                                   params.get("cookies_from_browser")),
                           project_id=pid, on_error=_on_error(svc, pid), params=params, retry_of=retry_of)


STARTERS = {"analyse": start_analyse, "plan": start_plan, "render": start_render, "revise": start_revise,
            "reference": start_reference}

WAIT = Query(False, description="block until the job finishes and return it (otherwise 202 + job to poll)")


@router.post("/projects/{pid}/analyse", response_model=Job, status_code=202, tags=["editing"])
async def analyse(pid: str, wait: bool = WAIT, svc: Services = Depends(services)) -> Any:
    """Check the brief; the result is a list of clarifying questions (empty when it's ready to plan)."""
    return await _respond(svc, start_analyse(svc, pid, {}), wait)


@router.post("/projects/{pid}/plan", response_model=Job, status_code=202, tags=["editing"])
async def plan(pid: str, wait: bool = WAIT, svc: Services = Depends(services)) -> Any:
    """Transcribe, clean the voiceover, draft and let the brain build the edit plan. Result: the timeline."""
    return await _respond(svc, start_plan(svc, pid, {}), wait)


@router.get("/projects/{pid}/timeline", response_model=TimelineView, tags=["editing"])
def get_timeline(pid: str, svc: Services = Depends(services)) -> TimelineView:
    return pipeline.get_timeline(svc.store, pid)


@router.put("/projects/{pid}/timeline", response_model=TimelineView, tags=["editing"])
def put_timeline(pid: str, body: Timeline, svc: Services = Depends(services)) -> TimelineView:
    """Save the creator's own edits to the plan (validated: files, ranges, anchors)."""
    _guard(svc, pid, ("plan", "revise"))
    return pipeline.save_timeline(svc.store, pid, body)


@router.post("/projects/{pid}/render", response_model=Job, status_code=202, tags=["editing"])
async def render(pid: str, body: RenderRequest | None = None, wait: bool = WAIT,
                 svc: Services = Depends(services)) -> Any:
    """Queue a render (one runs at a time). Result: the new output version."""
    return await _respond(svc, start_render(svc, pid, {"draft": bool(body and body.draft)}), wait)


@router.post("/projects/{pid}/revise", response_model=Job, status_code=202, tags=["editing"])
async def revise(pid: str, body: ReviseRequest, wait: bool = WAIT, svc: Services = Depends(services)) -> Any:
    """Apply notes to the plan with the brain. Set render=true to queue a render afterwards."""
    return await _respond(svc, start_revise(svc, pid, body.model_dump()), wait)


@router.post("/projects/{pid}/reference", response_model=Job, status_code=202, tags=["editing"])
async def reference(pid: str, body: ReferenceRequest | None = None, wait: bool = WAIT,
                    svc: Services = Depends(services)) -> Any:
    """REFERENCE mode: download the reel, measure it and let the brain write a style spec."""
    return await _respond(svc, start_reference(svc, pid, (body or ReferenceRequest()).model_dump()), wait)


# ---------------------------------------------------------------- outputs

class OutputVersion(BaseModel):
    version: int
    video: str
    contact_sheet: str | None
    video_url: str
    contact_sheet_url: str | None
    size_bytes: int
    duration: float | None = None
    draft: bool | None = None
    plan_version: int | None = None
    created_at: Any = None


@router.get("/projects/{pid}/outputs", response_model=list[OutputVersion], tags=["media"])
def outputs(pid: str, svc: Services = Depends(services)) -> list[OutputVersion]:
    out = []
    for o in pipeline.outputs(svc.store, pid):
        out.append(OutputVersion(**o, video_url=f"/projects/{pid}/outputs/{o['version']}/video",
                                 contact_sheet_url=f"/projects/{pid}/outputs/{o['version']}/contact"
                                 if o["contact_sheet"] else None))
    return out


def output_file(svc: Services, pid: str, version: int, what: str) -> Path:
    for o in pipeline.outputs(svc.store, pid):
        if o["version"] == version:
            rel = o["video"] if what == "video" else o["contact_sheet"]
            if rel:
                return svc.store.dir(pid) / rel
    raise EngineError(f"no {what} for version {version}", code="output_not_found", status=404)
