"""Filmstrips for the visual trimmer: frames sampled evenly across a whole clip, built once in the background.

    strip(proj_dir, src)    -> Filmstrip: "ready" with its frames, or "building" (a build is started if none runs)

One ffmpeg pass per clip writes ``work/_cache/filmstrip/<key>/f_001.jpg ...`` and then ``strip.json`` (written last,
so a half-built strip is never served). The key covers the clip's size and mtime, the frame count and width, so a
replaced file gets a new strip and re-opening a shot is instant. The cache lives in the project folder, so deleting
the project deletes it. Frames are served by GET /media/file (range-enabled, workspace-confined).
"""
from __future__ import annotations

import hashlib
import math
import shutil
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .common import ffprobe, read_json, run, write_json
from .config import EngineError, project_layout, use_layout
from .media import AUDIO_EXT, is_image

STEP_S = 0.5            # about one frame every half second ...
MIN_FRAMES = 8          # ... at least this many ...
MAX_FRAMES = 120        # ... at most this many
_lock = threading.Lock()
_building: dict[str, threading.Thread] = {}


class Frame(BaseModel):
    t: float = Field(description="seconds into the clip")
    path: str = Field(description="relative to the workspace (for GET /media/file)")


class Filmstrip(BaseModel):
    src: str
    status: Literal["ready", "building", "failed"]
    duration: float = Field(description="the clip's length in seconds")
    frames: list[Frame] = Field(default_factory=list)
    error: str | None = None


def frame_count(duration: float, count: int | None = None) -> int:
    if count:
        return max(2, min(MAX_FRAMES, count))
    return max(MIN_FRAMES, min(MAX_FRAMES, math.ceil(duration / STEP_S)))


def clip_path(proj_dir: Path, src: str) -> Path:
    """A video in the project, by its plan path (inputs/clips/a.mp4). Refuses anything outside the project folder,
    photos and audio."""
    root = proj_dir.resolve()
    p = (root / src).resolve()
    if not p.is_relative_to(root) or p == root:
        raise EngineError("the clip must be inside the project", code="forbidden_path", status=403)
    if not p.is_file():
        raise EngineError(f"not found: {src}", code="file_not_found", status=404)
    if is_image(p) or p.suffix.lower() in AUDIO_EXT:
        raise EngineError("only video clips have a filmstrip", code="no_filmstrip", status=415)
    return p


def _dir(proj_dir: Path, clip: Path, n: int, w: int) -> Path:
    st = clip.stat()
    key = hashlib.sha1(f"{clip}|{st.st_size}|{int(st.st_mtime)}|{n}|{w}".encode()).hexdigest()[:16]
    return proj_dir / "work" / "_cache" / "filmstrip" / key


def _build(proj_dir: Path, clip: Path, out: Path, n: int, w: int, duration: float) -> None:
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        with use_layout(project_layout(proj_dir)):
            # frame k is the one nearest k * duration / n: evenly across the clip, first frame at 0
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", clip, "-an",
                 "-vf", f"fps={n / duration:.6f},scale={w}:-2", "-frames:v", n, "-q:v", 5, tmp / "f_%03d.jpg"])
        files = sorted(tmp.glob("f_*.jpg"))
        if not files:
            raise EngineError("ffmpeg made no frames", code="filmstrip_failed")
        shutil.rmtree(out, ignore_errors=True)
        tmp.rename(out)
        rel = out.relative_to(proj_dir.parent)
        write_json(out / "strip.json", {"duration": duration, "frames": [
            {"t": round(min(i * duration / n, duration), 3), "path": f"{rel.as_posix()}/{f.name}"}
            for i, f in enumerate(files)]})
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        out.mkdir(parents=True, exist_ok=True)
        (out / "error.txt").write_text(getattr(e, "message", None) or str(e))
    finally:
        with _lock:
            _building.pop(str(out), None)


def strip(proj_dir: Path, src: str, count: int | None = None, w: int = 120, wait: bool = False) -> Filmstrip:
    """The clip's filmstrip if it's built; else start building it (once) and say so. wait=True builds it now."""
    clip = clip_path(proj_dir, src)
    with use_layout(project_layout(proj_dir)):
        info = ffprobe(clip)
    if not info.get("has_video"):
        raise EngineError("no video stream in this clip", code="no_filmstrip", status=415)
    duration = float(info["duration"])
    n = frame_count(duration, count)
    out = _dir(proj_dir, clip, n, w)
    done = read_json(out / "strip.json")
    if done:
        return Filmstrip(src=src, status="ready", duration=duration, frames=done["frames"])
    if (out / "error.txt").exists():
        err = (out / "error.txt").read_text()
        if not wait:
            return Filmstrip(src=src, status="failed", duration=duration, error=err)
        shutil.rmtree(out, ignore_errors=True)          # asked again explicitly: try once more
    with _lock:
        th = _building.get(str(out))
        if th is None:
            th = threading.Thread(target=_build, args=(proj_dir, clip, out, n, w, duration), daemon=True,
                                  name=f"filmstrip {src}")
            _building[str(out)] = th
            th.start()
    if wait:
        th.join()
        return strip(proj_dir, src, count, w)
    return Filmstrip(src=src, status="building", duration=duration)


__all__ = ["Filmstrip", "Frame", "clip_path", "frame_count", "strip"]
