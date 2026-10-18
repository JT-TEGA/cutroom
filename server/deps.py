"""Shared objects for the routes. Tests swap them out (a temp workspace, a fake brain)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request

from engine.brain import Brain, get_brain
from engine.photos import PhotosLibrary
from engine.photos import from_env as photos_from_env
from engine.project import ProjectStore

from .jobs import JobManager


@dataclass
class Services:
    store: ProjectStore = field(default_factory=ProjectStore)
    jobs: JobManager = field(default_factory=JobManager)
    brain_factory: Callable[[], Brain] = get_brain      # read settings per call, so a backend switch applies at once
    photos: PhotosLibrary = field(default_factory=photos_from_env)   # the Mac Photos library (read on first use)


def services(request: Request) -> Services:
    return request.app.state.services
