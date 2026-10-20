"""Learned preferences: what Cutroom picked up from the creator's edits, per content type (see engine/learn.py)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from engine import learn

from ..deps import Services, services

router = APIRouter(tags=["learned"])


class PrefPatch(BaseModel):
    enabled: bool


@router.get("/projects/{pid}/learned", response_model=learn.ProjectLearned)
def project_learned(pid: str, svc: Services = Depends(services)) -> learn.ProjectLearned:
    """The notes for this project's content type: applied, paused by the brief, pending (seen once) or off."""
    proj = svc.store.get(pid)
    return learn.for_project(learn.preset_of(proj.brief), proj.brief)


@router.get("/learned/{preset}", response_model=learn.LearnedSet)
def get_learned(preset: str) -> learn.LearnedSet:
    return learn.load(preset)


@router.patch("/learned/{preset}/{key}", response_model=learn.LearnedSet)
def patch_learned(preset: str, key: str, body: PrefPatch) -> learn.LearnedSet:
    """Turn a note off (it stays, and keeps counting) or back on."""
    return learn.set_enabled(preset, key, body.enabled)


@router.delete("/learned/{preset}/{key}", response_model=learn.LearnedSet)
def delete_learned(preset: str, key: str) -> learn.LearnedSet:
    """Forget a note. It can come back if you keep making the same change."""
    return learn.delete(preset, key)
