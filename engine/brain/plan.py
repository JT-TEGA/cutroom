"""plan.build(): brief + transcripts + clip info + preset (+ the software's draft) -> the edit plan."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import BriefData, StyleSpec
from ..settings import load_app
from ..timeline import Timeline, TimelineView, check
from .base import Brain, BrainRequest, ask
from .context import (
    PROMPTS,
    analysis_text,
    brand_text,
    brief_text,
    clips_text,
    preset_text,
    prompt,
    section,
    transcript_text,
    view_text,
)
from .schemas import ClipMatchResult, PlanResult

PLAN_SCHEMA = ('{"timeline": <edit plan object, format below>, "summary": string, "changes": [string]}\n\n'
               + (PROMPTS / "edit_plan.md").read_text())


def srcs(tl: Timeline) -> set[str]:
    """Every media path an edit plan refers to."""
    out: set[str] = set()
    for seg in tl.segments:
        out.update(x for x in (seg.src, seg.a.src if seg.a else None, seg.b.src if seg.b else None) if x)
        out.update(sh.src for sh in seg.shots or [] if sh.src)
    out.update(b.src for b in tl.broll)
    if tl.music:
        out.add(tl.music.src)
    out.update(str(x.get("src")) for x in [*tl.sfx, *tl.graphics, *([tl.sfx_on_cuts] if tl.sfx_on_cuts else [])]
               if x.get("src"))
    return out


def file_check(known: set[str]):
    """Plan check: only uploaded files (or shared assets/), then the full timeline check."""
    def run(res: PlanResult) -> list[str]:
        bad = sorted(s for s in srcs(res.timeline) if s not in known and not s.startswith("assets/"))
        if bad:
            return [f"unknown file {b!r}: use only the input files" for b in bad]
        return check(res.timeline)
    return run


def build(brain: Brain, brief: BriefData, transcripts: dict[str, dict[str, Any] | None],
          clip_info: list[dict[str, Any]], preset: str | None, *, draft: Timeline, draft_view: TimelineView | None,
          analysis: dict[str, Any], cwd: Path, known_files: set[str], answers: str = "",
          style_spec: StyleSpec | None = None, matches: ClipMatchResult | None = None) -> PlanResult:
    parts = [
        section("Brief", brief_text(brief)),
        section("Answers to clarifying questions", answers),
        section("Automatic brief check", analysis_text(analysis)),
        section("Content-type preset", preset_text(preset)),
        section("Brand", brand_text()),
        section("Clips (edit order)", clips_text(clip_info)),
        section("Transcripts (source seconds)", "\n\n".join(transcript_text(s, t) for s, t in transcripts.items())),
    ]
    if style_spec:
        parts.append(section("Reference reel style spec (copy this; the brief still wins)",
                             style_spec.model_dump_json(indent=1)))
    if matches and matches.matches:
        parts.append(section("Clip-to-phrase match-up from the contact sheets",
                             "\n".join(f'- "{m.phrase}" -> {m.src} ({m.reason})' for m in matches.matches)))
    if draft_view:
        parts.append(section("Draft view (output seconds: what plays when)", view_text(draft_view)))
    parts.append(section("DRAFT plan (JSON)", draft.model_dump_json(by_alias=True, exclude_none=True)))
    s = load_app()
    req = BrainRequest(purpose="plan.build", system=prompt("plan"), prompt="\n".join(parts), cwd=cwd,
                       timeout=s.brain_timeout_s, max_turns=s.brain_max_turns)
    res = ask(brain, req, PlanResult, check=file_check(known_files), schema_hint=PLAN_SCHEMA)
    tl = res.timeline
    tl.name = tl.name or draft.name
    tl.preset = tl.preset or draft.preset
    tl.talk = tl.talk or draft.talk
    tl.target_length = tl.target_length or draft.target_length
    return res
