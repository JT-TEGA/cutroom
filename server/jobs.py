"""In-process background jobs: brain calls, transcription and renders never block the API.

Two queues: "render" has one worker (one render at a time, the rest wait their turn); "general" has a small pool
for analyse / plan / revise. Every job streams events (status, step + % done, log lines) to WebSocket subscribers
and keeps its last log lines for GET /jobs/{id}.

Job records are saved to the project's work/jobs.json on every status change (and at most once a second while a
job reports progress), so a server restart doesn't lose them. restore() at startup reads them back; a job that was
queued or running when the server stopped is marked "interrupted" and can be retried.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import secrets
import threading
import time
import traceback
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from engine.config import EngineError, paths, use_reporter

JobStatus = Literal["queued", "running", "done", "failed", "cancelled", "interrupted"]
FINISHED = ("done", "failed", "cancelled", "interrupted")
RETRYABLE = ("failed", "cancelled", "interrupted")
LOG_KEEP = 400
LOG_SAVED = 100         # log lines kept per job in jobs.json
FINISHED_SAVED = 50     # finished jobs kept per project in jobs.json (unfinished ones are always kept)
SAVE_EVERY_S = 1.0      # progress updates are saved at most this often


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
    params: dict[str, Any] = Field(default_factory=dict, description="what the job was asked to do (retry reuses it)")
    retry_of: str | None = Field(None, description="the job this one retries")


class _Record:
    def __init__(self, job: Job):
        self.job = job
        self.log: deque[str] = deque(maxlen=LOG_KEEP)
        self.future: Future[Any] | None = None
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.saved_at = 0.0


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
        if time.monotonic() - self.rec.saved_at >= SAVE_EVERY_S:
            self.m._save(self.rec)


def _jsonable(x: Any) -> Any:
    if isinstance(x, BaseModel):
        return x.model_dump(mode="json", by_alias=True)
    return x


class JobManager:
    def __init__(self, general_workers: int = 2, root: Path | None = None):
        self.pools = {"render": ThreadPoolExecutor(1, thread_name_prefix="cutroom-render"),
                      "general": ThreadPoolExecutor(general_workers, thread_name_prefix="cutroom-job")}
        self.records: dict[str, _Record] = {}
        self.lock = threading.Lock()
        self.save_lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.root = Path(root or paths().workspace)

    # ------------------------------------------------------------ submit / run

    def submit(self, kind: str, fn: Callable[[], Any], project_id: str | None = None,
               queue: Literal["render", "general"] = "general",
               on_error: Callable[[BaseException], None] | None = None,
               on_done: Callable[[Any], None] | None = None,
               params: dict[str, Any] | None = None, retry_of: str | None = None) -> Job:
        job = Job(id=secrets.token_hex(6), kind=kind, project_id=project_id, queue=queue, params=params or {},
                  retry_of=retry_of)
        rec = _Record(job)
        with self.lock:
            self.records[job.id] = rec
        self._save(rec)
        rec.future = self.pools[queue].submit(self._run, rec, fn, on_error, on_done)
        return self.get(job.id)

    def _run(self, rec: _Record, fn: Callable[[], Any], on_error: Callable[[BaseException], None] | None,
             on_done: Callable[[Any], None] | None) -> Any:
        j = rec.job
        if j.status == "cancelled":
            return None
        j.status, j.started_at = "running", _now()
        self._save(rec)
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
            self._save(rec)
            self._publish(rec, {"type": "status", "status": j.status, "error": j.error})
        return j.result

    # ------------------------------------------------------------ on disk

    def _file(self, project_id: str | None) -> Path:
        return self.root / project_id / "work" / "jobs.json" if project_id else self.root / "jobs.json"

    def _save(self, rec: _Record) -> None:
        """Write the jobs of rec's project to its jobs.json (whole file, atomically)."""
        pid = rec.job.project_id
        f = self._file(pid)
        if pid and not (self.root / pid / "project.json").exists():
            return                                      # project deleted: don't bring its folder back
        with self.save_lock:
            with self.lock:
                recs = sorted((r for r in self.records.values() if r.job.project_id == pid),
                              key=lambda r: r.job.created_at)
            finished = [r for r in recs if r.job.status in FINISHED]
            drop = {id(r) for r in finished[:-FINISHED_SAVED]}
            try:
                out = []
                for r in recs:
                    if id(r) not in drop:
                        d = r.job.model_dump(mode="json", exclude={"position"})
                        d["log"] = list(r.log)[-LOG_SAVED:]
                        out.append(d)
                f.parent.mkdir(parents=True, exist_ok=True)
                tmp = f.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(out, indent=1))
                tmp.replace(f)
            except (OSError, ValueError, TypeError):
                return                                  # saving the record mustn't fail the job itself
            rec.saved_at = time.monotonic()

    def restore(self) -> list[Job]:
        """Load the saved jobs (call once at startup). Jobs that were queued or running when the server stopped
        are marked "interrupted"; returns those."""
        files = [self._file(None), *sorted(self.root.glob("*/work/jobs.json"))]
        interrupted: list[_Record] = []
        for f in files:
            try:
                saved = json.loads(f.read_text()) if f.exists() else []
            except (OSError, ValueError):
                continue
            for d in saved if isinstance(saved, list) else []:
                try:
                    job = Job.model_validate(d)
                except ValueError:
                    continue
                if job.id in self.records:
                    continue
                rec = _Record(job)
                rec.log.extend(job.log)
                job.log = []
                if job.status in ("queued", "running"):
                    ran = job.status == "running"
                    job.status, job.finished_at = "interrupted", _now()
                    job.error = {"code": "interrupted", "status": 503, "hint": "Retry it to run it again.",
                                 "message": "The server stopped while this job was running." if ran
                                 else "The server stopped before this job started."}
                    rec.log.append(f"INTERRUPTED: {job.error['message']}")
                    interrupted.append(rec)
                with self.lock:
                    self.records[job.id] = rec
        for pid in {r.job.project_id for r in interrupted}:
            self._save(next(r for r in interrupted if r.job.project_id == pid))
        return [self.get(r.job.id) for r in interrupted]

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
        self._save(rec)
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
