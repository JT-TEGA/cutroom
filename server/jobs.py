"""In-process background jobs: brain calls, transcription and renders never block the API.

Two queues: "render" has one worker (one render at a time, the rest wait their turn); "general" has a small pool
for analyse / plan / revise. Every job streams events (status, step + % done, log lines) to WebSocket subscribers
and keeps its last log lines for GET /jobs/{id}. Job records live in memory; project state is on disk.
"""
from __future__ import annotations

import asyncio
import contextvars
import secrets
import threading
import traceback
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from engine.config import EngineError, use_reporter

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]
FINISHED = ("done", "failed", "cancelled")
LOG_KEEP = 400


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Job(BaseModel):
    id: str
    kind: str
    project_id: str | None = None
    queue: Literal["render", "general"] = "general"
    status: JobStatus = "queued"
    step: str | None = None
    progress: float = 0.0
    position: int | None = Field(None, description="place in the render queue while queued (1 = next)")
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    log: list[str] = Field(default_factory=list)
    result: Any = None
    error: dict[str, Any] | None = None


class _Record:
    def __init__(self, job: Job):
        self.job = job
        self.log: deque[str] = deque(maxlen=LOG_KEEP)
        self.future: Future[Any] | None = None
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()


class JobReporter:
    """engine.config.Reporter for one job: pipeline log()/step() calls land here."""

    def __init__(self, manager: JobManager, rec: _Record):
        self.m, self.rec = manager, rec

    def log(self, line: str) -> None:
        self.rec.log.append(line)
        self.m._publish(self.rec, {"type": "log", "line": line})

    def step(self, name: str, pct: float | None = None) -> None:
        j = self.rec.job
        j.step = name
        if pct is not None:
            j.progress = round(max(j.progress, min(100.0, float(pct))), 1)
        self.m._publish(self.rec, {"type": "step", "step": name, "progress": j.progress})


def _jsonable(x: Any) -> Any:
    if isinstance(x, BaseModel):
        return x.model_dump(mode="json", by_alias=True)
    return x


class JobManager:
    def __init__(self, general_workers: int = 2):
        self.pools = {"render": ThreadPoolExecutor(1, thread_name_prefix="cutroom-render"),
                      "general": ThreadPoolExecutor(general_workers, thread_name_prefix="cutroom-job")}
        self.records: dict[str, _Record] = {}
        self.lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ submit / run

    def submit(self, kind: str, fn: Callable[[], Any], project_id: str | None = None,
               queue: Literal["render", "general"] = "general",
               on_error: Callable[[BaseException], None] | None = None,
               on_done: Callable[[Any], None] | None = None) -> Job:
        job = Job(id=secrets.token_hex(6), kind=kind, project_id=project_id, queue=queue)
        rec = _Record(job)
        with self.lock:
            self.records[job.id] = rec
        rec.future = self.pools[queue].submit(self._run, rec, fn, on_error, on_done)
        return self.get(job.id)

    def _run(self, rec: _Record, fn: Callable[[], Any], on_error: Callable[[BaseException], None] | None,
             on_done: Callable[[Any], None] | None) -> Any:
        j = rec.job
        if j.status == "cancelled":
            return None
        j.status, j.started_at = "running", _now()
        self._publish(rec, {"type": "status", "status": "running"})
        rep = JobReporter(self, rec)

        def call() -> Any:
            with use_reporter(rep):
                return fn()

        try:
            result = contextvars.Context().run(call)       # each job gets a clean context (layout, reporter)
            j.result, j.status, j.progress = _jsonable(result), "done", 100.0
            if on_done:
                on_done(result)
        except BaseException as e:      # noqa: BLE001 - a job must never take the worker down
            if isinstance(e, EngineError):
                j.error = {**e.to_dict(), "status": e.status}
            else:
                j.error = {"code": "internal_error", "message": f"{type(e).__name__}: {e}", "hint": None,
                           "status": 500}
                for line in traceback.format_exc().splitlines()[-12:]:
                    rec.log.append(line)
            j.status = "failed"
            rep.log(f"FAILED: {j.error['message']}")
            if on_error:
                try:
                    on_error(e)
                except Exception:   # noqa: BLE001
                    pass
        finally:
            j.finished_at = _now()
            self._publish(rec, {"type": "status", "status": j.status, "error": j.error})
        return j.result

    # ------------------------------------------------------------ queries

    def get(self, job_id: str) -> Job:
        rec = self.records.get(job_id)
        if rec is None:
            raise EngineError(f"no job {job_id!r}", code="job_not_found", status=404)
        return self._snapshot(rec)

    def _snapshot(self, rec: _Record) -> Job:
        j = rec.job.model_copy()
        j.log = list(rec.log)
        if j.status == "queued" and j.queue == "render":
            with self.lock:
                ahead = [r for r in self.records.values()
                         if r.job.queue == "render" and r.job.status in ("queued", "running")
                         and r.job.created_at <= j.created_at]
            j.position = len(ahead)
        return j

    def list(self, project_id: str | None = None) -> list[Job]:
        with self.lock:
            recs = list(self.records.values())
        out = [self._snapshot(r) for r in recs if project_id is None or r.job.project_id == project_id]
        for j in out:
            j.log = j.log[-5:]
        return sorted(out, key=lambda j: j.created_at, reverse=True)

    def active(self, project_id: str, kinds: tuple[str, ...]) -> Job | None:
        with self.lock:
            for r in self.records.values():
                if r.job.project_id == project_id and r.job.kind in kinds and r.job.status in ("queued", "running"):
                    return r.job
        return None

    def cancel(self, job_id: str) -> Job:
        rec = self.records.get(job_id)
        if rec is None:
            raise EngineError(f"no job {job_id!r}", code="job_not_found", status=404)
        if rec.job.status != "queued" or not rec.future or not rec.future.cancel():
            raise EngineError(f"job {job_id} is {rec.job.status}; only queued jobs can be cancelled",
                              code="job_not_cancellable", status=409)
        rec.job.status, rec.job.finished_at = "cancelled", _now()
        self._publish(rec, {"type": "status", "status": "cancelled"})
        return self.get(job_id)

    async def wait(self, job_id: str) -> Job:
        rec = self.records.get(job_id)
        if rec is None:
            raise EngineError(f"no job {job_id!r}", code="job_not_found", status=404)
        if rec.future is not None and rec.job.status not in FINISHED:
            try:
                await asyncio.wrap_future(rec.future)
            except Exception:   # noqa: BLE001 - the job records its own error
                pass
        return self.get(job_id)

    # ------------------------------------------------------------ streaming

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        rec = self.records.get(job_id)
        if rec is None:
            raise EngineError(f"no job {job_id!r}", code="job_not_found", status=404)
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        rec.subscribers.add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        rec = self.records.get(job_id)
        if rec:
            rec.subscribers.discard(q)

    def _publish(self, rec: _Record, event: dict[str, Any]) -> None:
        if not rec.subscribers or self.loop is None:
            return
        event = {"job_id": rec.job.id, "status": rec.job.status, "progress": rec.job.progress,
                 "step": rec.job.step, "ts": _now().isoformat(), **event}
        for q in list(rec.subscribers):
            try:
                self.loop.call_soon_threadsafe(q.put_nowait, event)
            except RuntimeError:        # loop closed (server shutting down)
                pass

    def shutdown(self) -> None:
        for p in self.pools.values():
            p.shutdown(wait=False, cancel_futures=True)
