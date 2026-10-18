"""match.clips(): which B-roll clip shows which voiceover phrase (contact sheets only when names don't say)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..edl import find_phrase
from ..settings import load_app
from .base import Brain, BrainRequest, ask
from .context import clips_text, prompt, section, transcript_text
from .schemas import ClipMatchResult


def clips(brain: Brain, voiceover_transcript: dict[str, Any], clips: list[dict[str, Any]],
          contact_sheets: list[Path], *, cwd: Path, voiceover_src: str = "voiceover",
          cues: list[str] | None = None) -> ClipMatchResult:
    known = {c["path"] for c in clips}
    words = voiceover_transcript.get("words") or []

    def check(res: ClipMatchResult) -> list[str]:
        probs = [f"unknown clip {m.src!r}" for m in res.matches if m.src not in known]
        probs += [f'phrase "{m.phrase}" is not in the transcript (copy the words exactly)'
                  for m in res.matches if words and find_phrase(words, m.phrase) is None]
        return probs

    sheets = "\n".join(str(p.resolve()) for p in contact_sheets)
    text = "\n".join([
        section("Voiceover transcript (seconds)", transcript_text(voiceover_src, voiceover_transcript)),
        section("Clips", clips_text(clips)),
        section("Visual cues from the brief", "\n".join(cues or [])),
        section("Contact sheets (open with Read only if file names don't say what a clip shows)", sheets),
    ])
    s = load_app()
    req = BrainRequest(purpose="match.clips", system=prompt("match"), prompt=text, cwd=cwd, readable=["work/**"],
                       images=contact_sheets, timeout=s.brain_timeout_s, max_turns=max(4, s.brain_max_turns))
    return ask(brain, req, ClipMatchResult, check=check)
