"""Uploads: clips, photos (HEIC ok), voiceover and music, kept in edit order; voiceover takes recorded in the app."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from engine.config import EngineError
from engine.project import ProjectFile, Take

from ..deps import Services, services

router = APIRouter(tags=["files"])


class FilePatch(BaseModel):
    name: str | None = Field(None, description="new file name (extension kept)")
    position: int | None = Field(None, ge=0, description="move to this place in the edit order")
    trim_in: float | None = Field(None, ge=0, description="use the clip from this second")
    trim_out: float | None = Field(None, gt=0, description="...to this second")
    clear_trim: bool = False


class Reorder(BaseModel):
    order: list[str] = Field(description="every file id, in the new edit order")


@router.post("/projects/{pid}/files", response_model=list[ProjectFile], status_code=status.HTTP_201_CREATED)
def upload(pid: str, files: list[UploadFile] = File(..., description="one or more files"),
           kind: str | None = Form(None, description="clip | photo | voiceover | music (needed for audio)"),
           folder: str | None = Form(None, description="group photos/clips like a folder (capture order)"),
           take: str | None = Form(None, description="the recorded take this voiceover is (POST .../takes)"),
           svc: Services = Depends(services)) -> list[ProjectFile]:
    """A voiceover in a recording or video container (WebM/Ogg Opus, MP4...) is converted to .wav on the way in."""
    svc.store.get(pid)
    if take is not None:
        if kind != "voiceover" or len(files) != 1:
            raise EngineError("a take is uploaded on its own, as kind=voiceover", code="invalid_request", status=422)
        if take not in {t.id for t in svc.store.takes(pid)}:
            raise EngineError(f"no take {take!r} in project {pid}", code="take_not_found", status=404)
    added: list[ProjectFile] = []
    try:
        for f in files:
            added.append(svc.store.add_file(pid, f.filename or "upload", f.file, kind=kind, folder=folder, take=take))
    except EngineError:
        for a in added:                 # all or nothing
            svc.store.remove_file(pid, a.id)
        raise
    return added


@router.get("/projects/{pid}/files", response_model=list[ProjectFile])
def list_files(pid: str, svc: Services = Depends(services)) -> list[ProjectFile]:
    return svc.store.get(pid).files


@router.patch("/projects/{pid}/files", response_model=list[ProjectFile])
def reorder(pid: str, body: Reorder, svc: Services = Depends(services)) -> list[ProjectFile]:
    return svc.store.reorder(pid, body.order)


@router.patch("/projects/{pid}/files/{file_id}", response_model=ProjectFile)
def patch_file(pid: str, file_id: str, body: FilePatch, svc: Services = Depends(services)) -> ProjectFile:
    return svc.store.update_file(pid, file_id, name=body.name, position=body.position, trim_in=body.trim_in,
                                 trim_out=body.trim_out, clear_trim=body.clear_trim)


@router.delete("/projects/{pid}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(pid: str, file_id: str, svc: Services = Depends(services)) -> None:
    svc.store.remove_file(pid, file_id)


@router.get("/projects/{pid}/files/{file_id}/content", response_class=FileResponse,
            responses={206: {"description": "partial content (Range request)"}})
def file_content(pid: str, file_id: str, svc: Services = Depends(services)) -> FileResponse:
    """The uploaded file itself; supports HTTP Range so video and audio stream in a browser player."""
    proj = svc.store.get(pid)
    f = svc.store.get_file(proj, file_id)
    return FileResponse(svc.store.dir(pid) / f.path, filename=f.name)


# ---------------------------------------------------------------- voiceover takes recorded in the app

@router.get("/projects/{pid}/takes", response_model=list[Take])
def list_takes(pid: str, svc: Services = Depends(services)) -> list[Take]:
    """The takes recorded for this project (inputs/voiceover/takes/), oldest first. Play one with
    GET /media/file?path=<project id>/<take path>."""
    return svc.store.takes(pid)


@router.post("/projects/{pid}/takes", response_model=Take, status_code=status.HTTP_201_CREATED)
def add_take(pid: str, file: UploadFile = File(..., description="the recording: WebM/Ogg (Opus) or MP4 (AAC), "
                                                                 "as MediaRecorder makes it"),
             svc: Services = Depends(services)) -> Take:
    """Keep a recording as the next take. It isn't in the edit until it's used: upload it to POST .../files with
    kind=voiceover and take=<id>, like any voice memo."""
    return svc.store.add_take(pid, file.filename or "take.webm", file.file)


@router.delete("/projects/{pid}/takes/{take_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_take(pid: str, take_id: str, svc: Services = Depends(services)) -> None:
    """Delete a take. A voiceover already made from it stays in the project."""
    svc.store.remove_take(pid, take_id)
