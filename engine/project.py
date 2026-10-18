"""Projects: one video each, in workspace/<project-id>/.

    project.json      brief (structured), files in edit order, questions/answers, status, renders, timestamps
    inputs/clips/     clips and photos (folders from an imported brief keep their name)
    inputs/voiceover/ voice memos
    inputs/music/     tracks
    work/             transcripts, drafts, edl.json (the plan), contact sheets, jobs.log
    output/v1, v2...  renders: video, contact sheet, render.json and the plan that made it

A markdown brief still works: ``import_markdown()`` creates a project and copies its media in.
"""
from __future__ import annotations

import re
import secrets
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Literal

from pydantic import BaseModel, Field

from .config import EngineError, legacy_layout, paths, project_layout, use_layout
from .media import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT
from .models import BriefData, ClipRef, Question, StyleSpec

FileKind = Literal["clip", "photo", "voiceover", "music"]
Status = Literal["new", "analysed", "planning", "planned", "rendering", "rendered", "error"]
KIND_DIR = {"clip": "inputs/clips", "photo": "inputs/clips", "voiceover": "inputs/voiceover", "music": "inputs/music"}
SUPPORTED = sorted(VIDEO_EXT | IMAGE_EXT | AUDIO_EXT)


def now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectFile(BaseModel):
    id: str
    name: str
    path: str = Field(description="relative to the project folder")
    kind: FileKind
    folder: str | None = None
    size: int = 0
    trim_in: float | None = None
    trim_out: float | None = None
    info: str = ""
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool | None = None
    added_at: datetime = Field(default_factory=now)


class InAppSound(BaseModel):
    """Posting with the song added in Instagram/TikTok: what to pick there."""

    song: str = Field(description="the uploaded track's file name")
    start: float = Field(description="where to start the song in the app (seconds, a whole second)")
    start_label: str = Field(description='the same as the app shows it, e.g. "0:42"')
    voice: bool = Field(description="the post file has talking or a voiceover: turn the in-app song down under it")
    song_duration: float | None = None
    warning: str | None = Field(None, description="e.g. the song ends before the video")


class RenderInfo(BaseModel):
    version: int
    video: str
    contact_sheet: str | None = None
    duration: float
    size_bytes: int
    draft: bool = False
    plan_version: int | None = None
    audio: dict[str, Any] = Field(default_factory=dict)
    post_video: str | None = Field(None, description="the copy without the music, to post with the in-app sound")
    in_app: InAppSound | None = None
    created_at: datetime = Field(default_factory=now)


class Project(BaseModel):
    id: str
    name: str
    status: Status = "new"
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    brief: BriefData = Field(default_factory=BriefData)
    files: list[ProjectFile] = Field(default_factory=list, description="edit order")
    questions: list[Question] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict, description="question id -> answer")
    assumptions: list[str] = Field(default_factory=list)
    style_spec: StyleSpec | None = None
    plan_version: int = 0
    plan_summary: str | None = None
    renders: list[RenderInfo] = Field(default_factory=list)
    last_error: dict[str, Any] | None = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    status: Status
    content_type: str | None
    files: int
    renders: int
    created_at: datetime
    updated_at: datetime
    thumbnail: str | None = Field(None, description="first clip or photo, relative to the workspace "
                                                    "(for GET /media/thumbnail)")
    latest_version: int | None = Field(None, description="newest render")
    duration: float | None = Field(None, description="length of the newest render (seconds)")
    open_questions: int = Field(0, description="blocking questions still without an answer")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40].strip("-") or "video"


def safe_name(name: str) -> str:
    n = re.sub(r"\s+", "_", Path(name).name.strip())
    n = re.sub(r"[^\w.\-]", "_", n).lstrip(".")
    return n or "file"


def kind_for(name: str, kind: str | None = None) -> FileKind:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXT:
        auto: str | None = "clip"
    elif ext in IMAGE_EXT:
        auto = "photo"
    elif ext in AUDIO_EXT:
        auto = None
    else:
        raise EngineError(f"{name}: unsupported file type {ext or '(none)'}", code="unsupported_file", status=415,
                          hint="Supported: " + " ".join(SUPPORTED))
    if kind:
        if kind not in KIND_DIR:
            raise EngineError(f"unknown file kind {kind!r} (clip, photo, voiceover, music)", code="invalid_kind",
                              status=422)
        if auto and kind in ("voiceover", "music") and auto == "photo":
            raise EngineError(f"{name} is a photo, not {kind}", code="invalid_kind", status=422)
        if auto is None and kind in ("clip", "photo"):
            raise EngineError(f"{name} is audio: upload it as voiceover or music", code="invalid_kind", status=422)
        return kind  # type: ignore[return-value]
    if auto is None:
        raise EngineError(f"{name} is audio: say whether it's a voiceover or music (kind=voiceover|music)",
                          code="audio_kind_needed", status=422)
    return auto  # type: ignore[return-value]


class ProjectStore:
    _locks: dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, root: Path | None = None):
        self.root = Path(root or paths().workspace)

    # ------------------------------------------------------------ basics

    def dir(self, pid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", pid or ""):
            raise EngineError(f"no project {pid!r}", code="project_not_found", status=404)
        return self.root / pid

    def layout(self, pid: str):
        return project_layout(self.dir(pid))

    @contextmanager
    def context(self, pid: str) -> Iterator[Path]:
        """Run pipeline code against this project's folders."""
        with use_layout(self.layout(pid)):
            yield self.dir(pid)

    def _lock(self, pid: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(pid, threading.RLock())

    def exists(self, pid: str) -> bool:
        try:
            return (self.dir(pid) / "project.json").exists()
        except EngineError:
            return False

    def get(self, pid: str) -> Project:
        p = self.dir(pid) / "project.json"
        if not p.exists():
            raise EngineError(f"no project {pid!r}", code="project_not_found", status=404)
        return Project.model_validate_json(p.read_text())

    def save(self, proj: Project) -> Project:
        proj.updated_at = now()
        d = self.dir(proj.id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "project.json.tmp"
        tmp.write_text(proj.model_dump_json(indent=2))
        tmp.replace(d / "project.json")
        return proj

    @contextmanager
    def edit(self, pid: str) -> Iterator[Project]:
        """Load, change and save a project under its lock: `with store.edit(pid) as p: p.status = ...`."""
        with self._lock(pid):
            proj = self.get(pid)
            yield proj
            self.save(proj)

    def list(self) -> list[ProjectSummary]:
        out = []
        if self.root.exists():
            for f in self.root.glob("*/project.json"):
                try:
                    p = Project.model_validate_json(f.read_text())
                except ValueError:
                    continue
                visual = next((x for x in p.files if x.kind in ("clip", "photo")), None)
                last = max(p.renders, key=lambda r: r.version, default=None)
                out.append(ProjectSummary(id=p.id, name=p.name, status=p.status, content_type=p.brief.content_type,
                                          files=len(p.files), renders=len(p.renders), created_at=p.created_at,
                                          updated_at=p.updated_at,
                                          thumbnail=f"{p.id}/{visual.path}" if visual else None,
                                          latest_version=last.version if last else None,
                                          duration=last.duration if last else None,
                                          open_questions=sum(1 for q in p.questions
                                                             if q.blocking and not p.answers.get(q.id))))
        return sorted(out, key=lambda s: s.updated_at, reverse=True)

    def create(self, name: str, brief: BriefData | None = None) -> Project:
        name = (name or (brief.title if brief else "") or "Untitled video").strip()
        pid = f"{slugify(name)}-{secrets.token_hex(2)}"
        while self.exists(pid):
            pid = f"{slugify(name)}-{secrets.token_hex(2)}"
        brief = brief or BriefData()
        if not brief.title:
            brief.title = name
        proj = Project(id=pid, name=name, brief=brief)
        d = self.dir(pid)
        for sub in ("inputs/clips", "inputs/voiceover", "inputs/music", "work", "output"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        return self.save(proj)

    def delete(self, pid: str) -> None:
        self.get(pid)
        with self._lock(pid):
            shutil.rmtree(self.dir(pid))

    # ------------------------------------------------------------ files

    def _target(self, pid: str, kind: FileKind, name: str, folder: str | None) -> Path:
        base = self.dir(pid) / KIND_DIR[kind]
        if folder:
            base = base / safe_name(folder)
        base.mkdir(parents=True, exist_ok=True)
        stem, ext = Path(name).stem, Path(name).suffix
        cand, n = base / name, 2
        while cand.exists():
            cand, n = base / f"{stem}-{n}{ext}", n + 1
        return cand

    def _probe(self, pid: str, path: Path, kind: FileKind) -> dict[str, Any]:
        """Check the file really is media of that kind; returns metadata for ProjectFile."""
        from .common import describe, ffprobe
        from .media import describe_media, photo_size
        with self.context(pid):
            if kind == "photo":
                try:
                    w, h = photo_size(path)
                except Exception as e:
                    raise EngineError(f"{path.name}: can't read this photo", code="unsupported_media", status=422,
                                      hint=str(e)[:200]) from e
                return {"info": describe_media(path), "width": w, "height": h}
            info = ffprobe(path)
            if kind == "clip" and not info.get("has_video"):
                raise EngineError(f"{path.name} has no video stream", code="unsupported_media", status=422)
            if kind in ("voiceover", "music") and not info.get("has_audio"):
                raise EngineError(f"{path.name} has no audio", code="unsupported_media", status=422)
            return {"info": describe(info), "duration": round(info["duration"], 3),
                    "width": info.get("width"), "height": info.get("height"), "fps": info.get("fps"),
                    "has_audio": info.get("has_audio")}

    def add_file(self, pid: str, filename: str, stream: IO[bytes] | Path, kind: str | None = None,
                 folder: str | None = None, trim_in: float | None = None, trim_out: float | None = None,
                 position: int | None = None) -> ProjectFile:
        """Copy an upload (a stream) or a local file into the project and check it's usable media."""
        self.get(pid)
        name = safe_name(filename)
        k = kind_for(name, kind)
        dest = self._target(pid, k, name, folder)
        tmp = dest.with_name(dest.name + ".part")
        try:
            if isinstance(stream, Path):
                shutil.copy2(stream, tmp)
            else:
                with tmp.open("wb") as f:
                    shutil.copyfileobj(stream, f, length=1024 * 1024)
            tmp.replace(dest)
            meta = self._probe(pid, dest, k)
        except BaseException:
            tmp.unlink(missing_ok=True)
            dest.unlink(missing_ok=True)
            raise
        pf = ProjectFile(id=secrets.token_hex(4), name=dest.name, path=str(dest.relative_to(self.dir(pid))), kind=k,
                         folder=safe_name(folder) if folder else None, size=dest.stat().st_size,
                         trim_in=trim_in, trim_out=trim_out, **meta)
        with self.edit(pid) as proj:
            if position is None or position >= len(proj.files):
                proj.files.append(pf)
            else:
                proj.files.insert(max(0, position), pf)
        return pf

    def get_file(self, proj: Project, file_id: str) -> ProjectFile:
        for f in proj.files:
            if f.id == file_id:
                return f
        raise EngineError(f"no file {file_id!r} in project {proj.id}", code="file_not_found", status=404)

    def remove_file(self, pid: str, file_id: str) -> None:
        with self.edit(pid) as proj:
            f = self.get_file(proj, file_id)
            (self.dir(pid) / f.path).unlink(missing_ok=True)
            proj.files = [x for x in proj.files if x.id != file_id]

    def update_file(self, pid: str, file_id: str, name: str | None = None, position: int | None = None,
                    trim_in: float | None = None, trim_out: float | None = None,
                    clear_trim: bool = False) -> ProjectFile:
        with self.edit(pid) as proj:
            f = self.get_file(proj, file_id)
            if name and safe_name(name) != f.name:
                new = safe_name(name)
                if Path(new).suffix.lower() != Path(f.name).suffix.lower():
                    new += Path(f.name).suffix
                src = self.dir(pid) / f.path
                dest = src.with_name(new)
                if dest.exists():
                    raise EngineError(f"a file called {new} already exists", code="name_taken", status=409)
                src.rename(dest)
                f.name, f.path = new, str(dest.relative_to(self.dir(pid)))
            if clear_trim:
                f.trim_in = f.trim_out = None
            if trim_in is not None:
                f.trim_in = trim_in
            if trim_out is not None:
                f.trim_out = trim_out
            if f.trim_in is not None and f.trim_out is not None and f.trim_out <= f.trim_in:
                raise EngineError("trim_out must be after trim_in", code="invalid_trim", status=422)
            if position is not None:
                proj.files.remove(f)
                proj.files.insert(max(0, min(position, len(proj.files))), f)
            return f

    def reorder(self, pid: str, order: list[str]) -> list[ProjectFile]:
        with self.edit(pid) as proj:
            ids = [f.id for f in proj.files]
            if sorted(order) != sorted(ids):
                raise EngineError("order must list every file id exactly once", code="invalid_order", status=422)
            by_id = {f.id: f for f in proj.files}
            proj.files = [by_id[i] for i in order]
            return proj.files

    def clip_refs(self, proj: Project) -> list[ClipRef]:
        """Edit order for the drafting step: clips, photos and voiceovers, trims applied (music is separate)."""
        return [ClipRef(src=f.path, in_=f.trim_in, out=f.trim_out) for f in proj.files if f.kind != "music"]

    # ------------------------------------------------------------ markdown briefs

    def import_markdown(self, brief: str | Path, copy_media: bool = True, name: str | None = None) -> Project:
        """briefs/*.md (a path, or the text itself) -> a new project, with the media it names copied in."""
        from .brief import parse_markdown
        from .media import capture_time, expand

        root = paths().root
        if isinstance(brief, Path) or (isinstance(brief, str) and "\n" not in brief and brief.endswith(".md")):
            p = Path(brief)
            p = p if p.is_absolute() else root / p
            if not p.exists():
                raise EngineError(f"brief not found: {brief}", code="file_not_found", status=404)
            text, default_name = p.read_text(), p.stem
        else:
            text, default_name = str(brief), ""
        data = parse_markdown(text)
        clips, data.clips = data.clips, []
        proj = self.create(name or data.title or default_name, data)
        if not copy_media:
            return proj

        missing, moved = [], {}
        with use_layout(legacy_layout()):
            for c in clips:
                src = root / c.src
                if not src.exists():
                    missing.append(c.src)
                    continue
                if src.is_dir():
                    for path, _, _ in sorted(expand([c.src]), key=lambda x: (capture_time(x[0]), x[0])):
                        f = self.add_file(proj.id, Path(path).name, root / path, folder=src.name)
                        moved[path] = f.path
                elif src.suffix.lower() in AUDIO_EXT:
                    f = self.add_file(proj.id, src.name, src, kind="voiceover")
                    moved[c.src] = f.path
                else:
                    f = self.add_file(proj.id, src.name, src, trim_in=c.in_, trim_out=c.out)
                    moved[c.src] = f.path
            if data.voiceover_file and data.voiceover_file.lower() not in ("none", "no", "n/a"):
                vo = data.voiceover_file.strip()
                src = root / (vo if "/" in vo else f"voiceover/{vo}")
                if src.exists() and not any(Path(m).name == src.name for m in moved.values()):
                    f = self.add_file(proj.id, src.name, src, kind="voiceover")
                    moved[str(src.relative_to(root))] = f.path
                elif not src.exists():
                    missing.append(vo)
            if data.track and data.track.lower() != "none":
                src = root / (data.track if "/" in data.track else f"music/{data.track}")
                if src.exists():
                    self.add_file(proj.id, src.name, src, kind="music")
                else:
                    missing.append(data.track)

        with self.edit(proj.id) as p:
            if p.brief.voiceover_file and "/" in p.brief.voiceover_file:
                p.brief.voiceover_file = Path(p.brief.voiceover_file).name
            if p.brief.track and "/" in p.brief.track:
                p.brief.track = Path(p.brief.track).name
            for old, new in sorted(moved.items(), key=lambda kv: -len(kv[0])):
                p.brief.visual_cues = [cue.replace(old, new) for cue in p.brief.visual_cues]
            if missing:
                p.assumptions.append("not found when importing: " + ", ".join(missing))
        return self.get(proj.id)

