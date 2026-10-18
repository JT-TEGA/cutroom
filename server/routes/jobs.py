"""Background job status, polling and live progress over WebSocket."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from engine.config import EngineError

from ..deps import Services, services
from ..jobs import FINISHED, Job

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
