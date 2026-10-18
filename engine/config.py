"""Where things live, and the per-job context the pipeline runs in.

Two kinds of configuration:

* ``Paths``: shared resources (presets, brand.md, fonts, SFX, models, workspace). Defaults sit in the repo; any of
  them can be moved with an environment variable (``CUTROOM_PRESETS``, ``CUTROOM_BRAND``, ...) or with
  ``configure()`` (the tests point everything at temporary folders this way).
* ``Layout``: where *one video's* files are. The chat-era CLI uses the repo itself (``raw/``, ``work/<name>/``,
  ``output/``); an app project uses ``workspace/<id>/`` (``inputs/``, ``work/``, ``output/vN/``). The active
  layout is a context variable, so background jobs for different projects can run side by side.

Pipeline code reports progress through ``log()`` / ``step()``; with no reporter attached they print, so the CLI
behaves as before.
"""
from __future__ import annotations

import contextvars
import json
import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterator, Protocol

REPO = Path(__file__).resolve().parent.parent
ENGINE = Path(__file__).resolve().parent


class EngineError(Exception):
    """An error with a message meant for the person using the app (and an HTTP status for the API)."""

    code = "engine_error"
    status = 400

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None, hint: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.hint = hint

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


# ---------------------------------------------------------------- shared resources

@dataclass(frozen=True)
class Paths:
    root: Path              # the repo; also the base for relative paths in the chat-era CLI
    presets: Path           # presets/*.md
    brand: Path             # brand.md (the settings block is the brand config)
    fonts: Path             # assets/fonts
    sfx: Path               # assets/sfx
    models: Path            # face detection model
    overlay: Path           # overlay.html + render_overlays.js
    workspace: Path         # app projects
    env_file: Path          # .env (only read by the Anthropic API backend)

    @classmethod
    def from_env(cls) -> Paths:
        root = Path(os.environ.get("CUTROOM_ROOT", REPO)).expanduser().resolve()

        def p(var: str, default: Path) -> Path:
            return Path(os.environ.get(var, default)).expanduser().resolve()

        return cls(
            root=root,
            presets=p("CUTROOM_PRESETS", root / "presets"),
            brand=p("CUTROOM_BRAND", root / "brand.md"),
            fonts=p("CUTROOM_FONTS", root / "assets" / "fonts"),
            sfx=p("CUTROOM_SFX", root / "assets" / "sfx"),
            models=p("CUTROOM_MODELS", root / "scripts" / "models"),
            overlay=p("CUTROOM_OVERLAY", ENGINE / "overlay"),
            workspace=p("CUTROOM_WORKSPACE", root / "workspace"),
            env_file=p("CUTROOM_ENV_FILE", root / ".env"),
        )

    @property
    def face_model(self) -> Path:
        return self.models / "face_detection_yunet_2023mar.onnx"


_paths: Paths | None = None


def paths() -> Paths:
    global _paths
    if _paths is None:
        _paths = Paths.from_env()
    return _paths


def configure(**overrides: Path | str) -> Paths:
    """Replace some shared paths (e.g. ``configure(workspace=tmp)``). Returns the new config."""
    global _paths
    _paths = replace(paths(), **{k: Path(v).resolve() for k, v in overrides.items()})
    return _paths


def reset_paths() -> None:
    global _paths
    _paths = None


# ---------------------------------------------------------------- one video's files

@dataclass(frozen=True)
class Layout:
    base: Path                      # relative media paths ("raw/a.mp4", "inputs/clips/a.mp4") resolve here
    work_root: Path                 # work files
    cache: Path                     # transcripts, beat grids, cleaned voice, thumbnails...
    output: Path                    # renders
    per_name: bool = True           # CLI: work/<name>/; project: work/ (one video per project)
    versioned: bool = False         # project: output/v1/, v2/...; CLI: output/<name>.mp4, old ones archived
    dirs: dict[str, str] = field(default_factory=dict)   # where clips / voiceover / music are, relative to base

    def work(self, name: str) -> Path:
        return self.work_root / name if self.per_name else self.work_root

    def dir(self, kind: str) -> Path:
        return self.base / self.dirs.get(kind, kind)

    def to_env(self) -> str:
        return json.dumps({k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(self).items()})

    @classmethod
    def from_env(cls, s: str) -> Layout:
        d = json.loads(s)
        for k in ("base", "work_root", "cache", "output"):
            d[k] = Path(d[k])
        return cls(**d)


def legacy_layout() -> Layout:
    """The chat-era layout: the repo's raw/, voiceover/, music/, work/<name>/ and output/."""
    root = paths().root
    return Layout(base=root, work_root=root / "work", cache=root / "work" / "_cache", output=root / "output",
                  dirs={"clips": "raw", "voiceover": "voiceover", "music": "music"})


def project_layout(project_dir: Path) -> Layout:
    d = Path(project_dir).resolve()
    return Layout(base=d, work_root=d / "work", cache=d / "work" / "_cache", output=d / "output",
                  per_name=False, versioned=True,
                  dirs={"clips": "inputs/clips", "voiceover": "inputs/voiceover", "music": "inputs/music"})


_layout: contextvars.ContextVar[Layout | None] = contextvars.ContextVar("cutroom_layout", default=None)


def layout() -> Layout:
    lay = _layout.get()
    if lay is not None:
        return lay
    env = os.environ.get("CUTROOM_LAYOUT")      # set for subprocesses (transcription)
    return Layout.from_env(env) if env else legacy_layout()


@contextmanager
def use_layout(lay: Layout) -> Iterator[Layout]:
    token = _layout.set(lay)
    try:
        yield lay
    finally:
        _layout.reset(token)


def subprocess_env() -> dict[str, str]:
    """Environment for a pipeline subprocess (python -m engine.transcribe ...): same layout, engine importable."""
    env = dict(os.environ)
    env["CUTROOM_LAYOUT"] = layout().to_env()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH", "")]))
    env.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    env["PYTHONUNBUFFERED"] = "1"
    return env


PY = sys.executable


# ---------------------------------------------------------------- progress

class Reporter(Protocol):
    def log(self, line: str) -> None: ...
    def step(self, name: str, pct: float | None = None) -> None: ...


_reporter: contextvars.ContextVar[Reporter | None] = contextvars.ContextVar("cutroom_reporter", default=None)


@contextmanager
def use_reporter(rep: Reporter) -> Iterator[Reporter]:
    token = _reporter.set(rep)
    try:
        yield rep
    finally:
        _reporter.reset(token)


def log(*args: object, sep: str = " ", end: str = "\n", file: object = None, flush: bool = False) -> None:
    """print() for pipeline code: goes to the job's log when one is attached, else to the terminal."""
    rep = _reporter.get()
    if rep is None:
        print(*args, sep=sep, end=end, file=file, flush=flush)  # type: ignore[call-overload]
        return
    text = sep.join(str(a) for a in args)
    for line in text.replace("\r", "\n").splitlines():
        if line.strip():
            rep.log(line.rstrip())


def step(name: str, pct: float | None = None) -> None:
    """Announce a pipeline stage (and overall % done, 0-100) to the attached reporter."""
    rep = _reporter.get()
    if rep is not None:
        rep.step(name, pct)


def job_log(message: str) -> None:
    """Append a line to the active video's job log (work/jobs.log): brain calls, durations, failures."""
    lay = layout()
    path = lay.work_root / ("_jobs.log" if lay.per_name else "jobs.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")


def which(binary: str) -> str | None:
    return shutil.which(binary)
