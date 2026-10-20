"""brief.analyse(): clarifying questions before editing (or none)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import BriefData, Question
from ..settings import load_app
from .base import Brain, BrainRequest, ask
from .context import analysis_text, brief_text, clips_text, preset_text, prompt, section, sfx_text
from .schemas import AnalyseResult


def analyse(brain: Brain, brief: BriefData, analysis: dict[str, Any], files: list[dict[str, Any]], *, cwd: Path,
            questions: list[Question] | None = None, answers: dict[str, str] | None = None,
            presets: list[str] | None = None) -> AnalyseResult:
    """The brief + the automatic gap check + the uploaded files -> questions worth asking now (all at once)."""
    prev = "\n".join(f"- {q}: {a}" for q, a in (answers or {}).items())
    if questions and answers:
        by_id = {q.id: q.question for q in questions}
        prev = "\n".join(f"- {by_id.get(k, k)} -> {v}" for k, v in answers.items())
    text = "\n".join([
        section("Brief", brief_text(brief)),
        section("Automatic check", analysis_text(analysis)),
        section("Uploaded files (edit order)", clips_text(files)),
        section("Sound effects every project has (assets/sfx/)", sfx_text()),
        section("Content-type presets", ", ".join(presets or [])),
        section("Preset for this content type", preset_text(analysis.get("preset"))),
        section("Previous answers", prev),
    ])
    s = load_app()
    req = BrainRequest(purpose="brief.analyse", system=prompt("analyse"), prompt=text, cwd=cwd,
                       timeout=min(s.brain_timeout_s, 180), max_turns=2)
    res = ask(brain, req, AnalyseResult)
    res.ready = not any(q.blocking for q in res.questions)
    return res
