"""Media serving: renders and workspace files with HTTP Range (browser players stream them), and thumbnails."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from engine.config import EngineError, paths

from ..deps import Services, services
from .projects import output_file

router = APIRouter(tags=["media"])
RANGE_DOC = {206: {"description": "partial content (Range request)"}}


def workspace_path(path: str) -> Path:
    """A path relative to the workspace (e.g. <project-id>/output/v1/contact.jpg), refusing anything outside it."""
    root = paths().workspace.resolve()
    p = (root / path).resolve()
    if not p.is_relative_to(root) or p == root:
        raise EngineError("path must be inside the workspace", code="forbidden_path", status=403)
    if not p.is_file():
        raise EngineError(f"not found: {path}", code="file_not_found", status=404)
    return p


@router.get("/projects/{pid}/outputs/{version}/video", response_class=FileResponse, responses=RANGE_DOC)
def output_video(pid: str, version: int, download: bool = Query(False, description="as an attachment (save as)"),
                 svc: Services = Depends(services)) -> FileResponse:
    p = output_file(svc, pid, version, "video")
    return FileResponse(p, media_type="video/mp4", filename=p.name,
                        content_disposition_type="attachment" if download else "inline")


@router.get("/projects/{pid}/outputs/{version}/contact", response_class=FileResponse)
def output_contact(pid: str, version: int, svc: Services = Depends(services)) -> FileResponse:
    return FileResponse(output_file(svc, pid, version, "contact"), media_type="image/jpeg")


@router.get("/media/file", response_class=FileResponse, responses=RANGE_DOC)
def media_file(path: str = Query(..., description="relative to the workspace, e.g. <id>/work/vo_preview.wav")) \
        -> FileResponse:
    """Any file in the workspace (inputs, renders, voiceover preview...), range-enabled."""
    return FileResponse(workspace_path(path), content_disposition_type="inline")


@router.get("/media/thumbnail", response_class=FileResponse)
def thumbnail(path: str = Query(..., description="clip or photo, relative to the workspace"),
              w: int = Query(320, ge=64, le=1080, description="width in pixels"),
              t: float | None = Query(None, ge=0, description="seconds into a clip (default: ~10% in)")) \
        -> FileResponse:
    """A JPEG thumbnail of a clip (a frame ~10% in, or at t) or photo (HEIC included). Cached next to the project."""
    from engine.common import ffprobe, run
    from engine.config import project_layout, use_layout
    from engine.media import AUDIO_EXT, is_image, photo_path

    src = workspace_path(path)
    if src.suffix.lower() in AUDIO_EXT:
        raise EngineError("audio files have no thumbnail", code="no_thumbnail", status=415)
    rel = src.relative_to(paths().workspace.resolve())
    proj_dir = paths().workspace / rel.parts[0]
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_size}|{int(st.st_mtime)}|{w}|{t}".encode()).hexdigest()[:16]
    out = proj_dir / "work" / "_cache" / "thumbs" / f"{key}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        with use_layout(project_layout(proj_dir)):
            if is_image(src):
                from PIL import Image
                with Image.open(photo_path(src)) as im:
                    im = im.convert("RGB")
                    im.thumbnail((w, w * 4))
                    im.save(out, "JPEG", quality=82)
            else:
                info = ffprobe(src)
                if not info.get("has_video"):
                    raise EngineError("no video stream to thumbnail", code="no_thumbnail", status=415)
                at = min(1.0, info["duration"] * 0.1) if t is None else min(t, max(0.0, info["duration"] - 0.05))
                run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", src,
                     "-frames:v", "1", "-vf", f"scale={w}:-2", "-q:v", "4", out])
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})
