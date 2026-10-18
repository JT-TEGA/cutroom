"""revise(): the creator's notes applied to the edit plan, everything else left alone."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import BriefData
from ..settings import load_app
from ..timeline import Timeline, TimelineView
from .base import Brain, BrainRequest, ask
from .context import brief_text, clips_text, prompt, section, transcript_text, view_text
from .plan import PLAN_SCHEMA, file_check
from .schemas import PlanResult


def revise(brain: Brain, timeline: Timeline, user_notes: str, *, cwd: Path, brief: BriefData,
           clip_info: list[dict[str, Any]], transcripts: dict[str, dict[str, Any] | None], known_files: set[str],
           current_view: TimelineView | None = None) -> PlanResult:
    parts = [
        section("Creator's notes", user_notes),
        section("Brief", brief_text(brief)),
        section("Clips", clips_text(clip_info)),
        section("Transcripts (source seconds)", "\n\n".join(transcript_text(s, t) for s, t in transcripts.items())),
    ]
    if current_view:
        parts.append(section("Current timeline view (output seconds)", view_text(current_view)))
    parts.append(section("Current edit plan (JSON)", timeline.model_dump_json(by_alias=True, exclude_none=True)))
    s = load_app()
    req = BrainRequest(purpose="revise", system=prompt("revise"), prompt="\n".join(parts), cwd=cwd,
                       timeout=s.brain_timeout_s, max_turns=s.brain_max_turns)
    res = ask(brain, req, PlanResult, check=file_check(known_files), schema_hint=PLAN_SCHEMA)
    res.timeline.name = res.timeline.name or timeline.name
    res.timeline.preset = res.timeline.preset or timeline.preset
    return res
