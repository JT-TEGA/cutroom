"""Background job status, polling and live progress over WebSocket."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from engine.config import EngineError

from ..deps import Services, services
from ..jobs import FINISHED, RETRYABLE, Job
from .projects import STARTERS

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[Job])
def list_jobs(project_id: str | None = Query(None), svc: Services = Depends(services)) -> list[Job]:
    """Recent jobs (newest first), optionally for one project. Logs are trimmed to the last lines."""
    return svc.jobs.list(project_id)


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, svc: Services = Depends(services)) -> Job:
    """Status, current step, % done, recent log lines, and the result (or error) when finished."""
    return svc.jobs.get(job_id)


@router.delete("/jobs/{job_id}", response_model=Job)
def cancel_job(job_id: str, svc: Services = Depends(services)) -> Job:
    """Cancel a job that is still queued (a running job finishes)."""
    return svc.jobs.cancel(job_id)


@router.post("/jobs/{job_id}/retry", response_model=Job, status_code=202)
def retry_job(job_id: str, svc: Services = Depends(services)) -> Job:
    """Run a failed, cancelled or interrupted job again with the same inputs. Returns the new job
    (its retry_of is the old one)."""
    old = svc.jobs.get(job_id)
    if old.status not in RETRYABLE:
        raise EngineError(f"job {job_id} is {old.status}; only failed, cancelled or interrupted jobs can be retried",
                          code="job_not_retryable", status=409)
    start = STARTERS.get(old.kind)
    if start is None or old.project_id is None:
        raise EngineError(f"{old.kind} jobs can't be retried", code="job_not_retryable", status=409)
    return start(svc, old.project_id, old.params, retry_of=old.id)


@router.websocket("/ws/jobs/{job_id}")
async def job_stream(ws: WebSocket, job_id: str) -> None:
    """Live progress: first {"type": "snapshot", "job": {...}}, then events
    {"type": "status" | "step" | "log", "status", "step", "progress", "line"?, "ts"} until the job finishes."""
    svc: Services = ws.app.state.services
    await ws.accept()
    try:
        q = svc.jobs.subscribe(job_id)
    except EngineError as e:
        await ws.send_json({"type": "error", "error": e.to_dict()})
        await ws.close(code=4404)
        return
    try:
        snap = svc.jobs.get(job_id)
        await ws.send_json({"type": "snapshot", "job": snap.model_dump(mode="json")})
        if snap.status in FINISHED:
            await ws.close()
            return
        while True:
            ev = await q.get()
            await ws.send_json(ev)
            if ev.get("type") == "status" and ev.get("status") in FINISHED:
                final = svc.jobs.get(job_id)
                await ws.send_json({"type": "result", "job": final.model_dump(mode="json")})
                break
        await ws.close()
    except WebSocketDisconnect:
        pass
    finally:
        svc.jobs.unsubscribe(job_id, q)
