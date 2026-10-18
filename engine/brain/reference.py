"""reference.style_spec(): a reference reel's style (frames + transcript + measured stats) as a spec."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import StyleSpec
from ..settings import load_app
from .base import Brain, BrainRequest, ask
from .context import prompt, section

ALLOWED = {"beat_every", "shot_min", "shot_max", "transition", "transition_location", "grade", "grain", "vignette",
           "handheld", "kenburns", "text_style", "caption_case", "caption_position", "caption_max_words",
           "caption_weight", "caption_animation", "music_mode", "end_card"}


def style_spec(brain: Brain, frames: list[Path], transcript: str, *, stats: dict[str, Any], cwd: Path) -> StyleSpec:
    def check(spec: StyleSpec) -> list[str]:
        bad = sorted(set(spec.style_overrides) - ALLOWED)
        return [f"style_overrides: unknown key(s) {', '.join(bad)}"] if bad else []

    slim = {k: v for k, v in stats.items() if k not in ("transcript", "cuts")}
    text = "\n".join([
        section("Measured stats", json.dumps(slim, indent=1)),
        section("Transcript", transcript[:4000]),
        section("Contact sheets (open both with Read)", "\n".join(str(p.resolve()) for p in frames)),
    ])
    s = load_app()
    req = BrainRequest(purpose="reference.style_spec", system=prompt("style_spec"), prompt=text, cwd=cwd,
                       readable=["work/**"], images=frames, timeout=s.brain_timeout_s,
                       max_turns=max(4, s.brain_max_turns))
    return ask(brain, req, StyleSpec, check=check)
