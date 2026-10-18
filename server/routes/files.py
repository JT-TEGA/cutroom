"""Uploads: clips, photos (HEIC ok), voiceover and music, kept in edit order."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from engine.config import EngineError
from engine.project import ProjectFile

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
           svc: Services = Depends(services)) -> list[ProjectFile]:
    svc.store.get(pid)
    added: list[ProjectFile] = []
    try:
        for f in files:
            added.append(svc.store.add_file(pid, f.filename or "upload", f.file, kind=kind, folder=folder))
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
