"""Import from the Mac Photos app: library status (and what to do without access), albums, items, thumbnails, and
importing originals into a project as a background job."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from engine.photos import ItemPage, PhotoAlbum, PhotosStatus, import_items

from ..deps import Services, services
from ..jobs import Job
from .projects import STARTERS, _guard, _respond

router = APIRouter(tags=["photos"])


class PhotosImport(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500, description="item ids (Photos UUIDs), in the order to add")
    live_video: bool = Field(False, description="Live Photos: import the video part instead of the still")


@router.get("/photos/status", response_model=PhotosStatus)
def status(svc: Services = Depends(services)) -> PhotosStatus:
    """Whether the Photos library can be read. The first call starts reading it in the background ("loading");
    poll until "ready". "no_access" comes with the System Settings steps in hint, and the app to give access to."""
    return svc.photos.status()


@router.post("/photos/refresh", response_model=PhotosStatus)
def refresh(svc: Services = Depends(services)) -> PhotosStatus:
    """Read the library again: after granting access ("Check again"), or to see new photos."""
    return svc.photos.refresh()


@router.get("/photos/albums", response_model=list[PhotoAlbum])
def albums(svc: Services = Depends(services)) -> list[PhotoAlbum]:
    """Your albums with how many photos and videos are in each, and an item to use as the cover."""
    return svc.photos.albums()


@router.get("/photos/items", response_model=ItemPage)
def items(album: str | None = Query(None, description="an album id; omit for everything, newest first"),
          kind: Literal["all", "photo", "video"] = "all",
          since: date | None = Query(None, description="taken on or after this day"),
          until: date | None = Query(None, description="taken on or before this day"),
          favorites: bool = False,
          offset: int = Query(0, ge=0), limit: int = Query(120, ge=1, le=500),
          svc: Services = Depends(services)) -> ItemPage:
    """Recent items (newest first) or an album's items (in its order), filtered by kind and date."""
    lo = datetime.combine(since, time.min).astimezone() if since else None
    hi = datetime.combine(until, time.max).astimezone() if until else None
    return svc.photos.items(album=album, kind=kind, since=lo, until=hi, favorites=favorites, offset=offset,
                            limit=limit)


@router.get("/photos/thumbnail/{item_id}", response_class=FileResponse)
def thumbnail(item_id: str, w: int = Query(320, ge=64, le=1080), svc: Services = Depends(services)) -> FileResponse:
    """A JPEG preview of a photo or video (from Photos' own previews, so iCloud-only items have one too)."""
    return FileResponse(svc.photos.thumbnail(item_id, w), media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})


def start_photos_import(svc: Services, pid: str, params: dict[str, Any], retry_of: str | None = None) -> Job:
    _guard(svc, pid, ("photos-import",))
    for i in params["ids"]:
        svc.photos.item(i)            # unknown ids fail now, not half-way through the job
    return svc.jobs.submit("photos-import", lambda: import_items(svc.store, pid, svc.photos, params["ids"],
                                                                 bool(params.get("live_video"))),
                           project_id=pid, params=params, retry_of=retry_of)


STARTERS["photos-import"] = start_photos_import


@router.post("/projects/{pid}/photos/import", response_model=Job, status_code=202, tags=["files"])
async def import_photos(pid: str, body: PhotosImport, wait: bool = False,
                        svc: Services = Depends(services)) -> JSONResponse:
    """Export the originals of these items into the project (iCloud-only ones are downloaded through Photos; Live
    Photos as stills unless live_video). Result: {"added": [file], "skipped": [{id, name, reason}]}."""
    return await _respond(svc, start_photos_import(svc, pid, body.model_dump()), wait)
