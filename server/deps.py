"""Shared objects for the routes. Tests swap them out (a temp workspace, a fake brain)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request

from engine.brain import Brain, get_brain
from engine.project import ProjectStore

from .jobs import JobManager


@dataclass
class Services:
    store: ProjectStore = field(default_factory=ProjectStore)
    jobs: JobManager = field(default_factory=JobManager)
    brain_factory: Callable[[], Brain] = get_brain      # read settings per call, so a backend switch applies at once


def services(request: Request) -> Services:
    return request.app.state.services
