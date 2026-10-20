"""Compact text for brain prompts: transcripts, clip metadata, brief, preset. Never raw media.

Everything here is plain text sections, so a prompt reads like a well-organised handover note.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common import load_brand, tc
from ..config import paths
from ..models import BriefData

PROMPTS = Path(__file__).parent / "prompts"


def prompt(*names: str) -> str:
    """System prompt = the shared editor rules + the task file(s)."""
    return "\n\n".join((PROMPTS / f"{n}.md").read_text().strip() for n in ("editor", *names))


def section(title: str, body: str | None) -> str:
    body = (body or "").strip()
    return f"## {title}\n{body if body else '(none)'}\n"


def brief_text(b: BriefData) -> str:
    d = b.model_dump(mode="json", by_alias=True, exclude={"clips"})
    lines = []
    for k, v in d.items():
        if v in (None, "", []):
            continue
        label = k.replace("_", " ")
        if isinstance(v, list):
            lines.append(f"{label}:\n" + "\n".join(f"  - {x}" for x in v))
        elif "\n" in str(v):
            lines.append(f"{label}:\n  " + str(v).replace("\n", "\n  "))
        else:
            lines.append(f"{label}: {v}")
    return "\n".join(lines)


def answers_text(questions: list[Any], answers: dict[str, str]) -> str:
    if not answers:
        return ""
    q = {x.id: x.question for x in questions}
    return "\n".join(f"- {q.get(k, k)} -> {v}" for k, v in answers.items())


def preset_text(name: str | None) -> str:
    if not name:
        return "(no preset: content type not set)"
    p = paths().presets / f"{name}.md"
    return p.read_text().strip() if p.exists() else f"(unknown preset {name})"


def brand_text() -> str:
    b = load_brand()
    return (f"handle {b['handle']}; end card {'on' if b['end_card'] else 'off'} by default "
            f"({b['end_card_seconds']}s); captions {b['caption_font']} {b['caption_weight']}, {b['caption_case']}; "
            f"emphasis colour {b['emphasis_color']}; default text style {b['text_style']}; grade {b['grade']}")


SFX_HINTS = {"whoosh": "air swish, for a fast cut or whip", "bass_hit": "low boom, for a drop or reveal",
             "pop": "short pop, for a sticker or text appearing", "riser": "1.6s build-up into a drop",
             "click": "short dry click: a camera shutter, a tap"}


def sfx_text() -> str:
    """The sound effects a plan can use (assets/sfx/): the only way to add a sound besides an uploaded file."""
    from ..edl import sfx_kit
    kit = sfx_kit()
    if not kit:
        return "none: only uploaded audio files can be used as sound effects"
    return "\n".join(f"- {s}" + (f": {SFX_HINTS[Path(s).stem]}" if Path(s).stem in SFX_HINTS else "") for s in kit)


def analysis_text(a: dict[str, Any]) -> str:
    vo = ", ".join(v["src"] for v in a.get("voiceover") or []) or "none"
    cues = "\n".join(f'  - when "{c["say"]}" is said -> {c["src"]}' for c in a.get("cues") or [])
    lines = [f"preset: {a.get('preset') or '?'}", f"talking: {a.get('talk')}", f"mode: {a.get('mode')}",
             f"music: {a.get('music') or 'none'}", f"voiceover: {vo}",
             f"target length: {a.get('target_length') or 'preset default'}s",
             f"brief overrides: {json.dumps(a.get('style_overrides') or {})}"]
    if a.get("music_in_app"):
        lines.append("posting with the in-app sound: the creator adds this song in Instagram/TikTok, so the track only "
                     "sets the beat; keep music.start and music.in_app as they are")
    if cues:
        lines.append("visual cues:\n" + cues)
    if a.get("gaps"):
        lines.append("GAPS (automatic check):\n" + "\n".join(f"  - {g}" for g in a["gaps"]))
    if a.get("notes"):
        lines.append("assumptions so far:\n" + "\n".join(f"  - {n}" for n in a["notes"]))
    return "\n".join(lines)


def clips_text(files: list[dict[str, Any]]) -> str:
    """One line per input: path, kind, what it is (duration, size, fps, audio), trims, talking."""
    out = []
    for i, f in enumerate(files, 1):
        bits = [f"{i}. {f['path']}", f["kind"], f.get("info") or ""]
        if f.get("trim_in") is not None or f.get("trim_out") is not None:
            bits.append(f"use {f.get('trim_in') or 0}-{f.get('trim_out') or 'end'}s")
        if f.get("talking") is not None:
            bits.append("talking" if f["talking"] else "no speech")
        out.append(" | ".join(b for b in bits if b))
    return "\n".join(out)


def transcript_text(src: str, tr: dict[str, Any] | None, gap: float = 0.35, max_chars: int = 6000) -> str:
    """Phrase lines with source times, split at pauses, unsure words marked (?), fillers kept (so false starts and
    stumbles are visible)."""
    if not tr:
        return f"### {src}\n(not transcribed)"
    words = tr.get("words") or []
    head = f"### {src} ({tc(tr.get('duration', 0))}, {len(words)} words)"
    if not words:
        return head + "\n(no speech)"
    lines, cur, start, prev = [], [], None, None
    for w in words:
        if prev is not None and w["s"] - prev > gap:
            lines.append(f"[{start:.2f}-{prev:.2f}] {' '.join(cur)}")
            cur, start = [], None
        if start is None:
            start = w["s"]
        cur.append(w["w"] if w.get("p", 1) > 0.5 else f"{w['w']}(?)")
        prev = w["e"]
    if cur:
        lines.append(f"[{start:.2f}-{prev:.2f}] {' '.join(cur)}")
    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[:max_chars] + "\n... (truncated)"
    return head + "\n" + body


def view_text(view: Any) -> str:
    """A TimelineView as short lines (what plays when, and what is heard over it)."""
    rows = []
    for s in view.shots:
        what = f"{s.src} {s.in_:.2f}-{s.out:.2f}" if s.kind == "clip" else f"{s.kind} {s.src or ''}"
        extra = f' VO "{s.heard}"' if s.heard else (f' says "{s.said}"' if s.said else "")
        lab = f" [{s.label}]" if s.label else ""
        rows.append(f"#{s.idx}{lab} {s.start:.2f}-{s.end:.2f}s {what} ({s.role}){extra}"
                    + (f"  !! {s.warning}" if s.warning else ""))
    for o in view.overlays:
        rows.append(f"   {o.kind.upper()} {o.start:.2f}-{o.end:.2f}s {o.style or ''} {o.text or o.src or ''}")
    rows.append(f"total {view.duration:.2f}s" + (f" (target {view.target_length:g}s)" if view.target_length else ""))
    return "\n".join(rows)
