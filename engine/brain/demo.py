"""DemoBrain: scripted but believable answers, so the app can be shown end to end without calling Claude.

Switched on with CUTROOM_BRAIN=demo (``./cutroom --demo`` does that). Every task answers in the right shape, built
from what is in its prompt:

    brief.analyse   asks which of *your* clips should open the video (+ the end card), once; no questions after
    plan.build      the software's draft with a reason on every shot, the brief's labels placed on the shots
                    they describe, and editor's notes
    revise          applies simple notes: quoted text goes on the first label, flash / whip / zoom transitions,
                    end card on / off
    match.clips, reference.style_spec   minimal valid answers

Each call waits CUTROOM_DEMO_DELAY seconds (default 3) so the app's "Claude is planning" state is visible.
CUTROOM_DEMO_FAIL=usage_limit | not_logged_in makes every call fail like Claude Code would (to see the banners).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .base import Brain, BrainError, BrainRequest, BrainResponse
from .claude_code import LIMIT_HINT, LOGIN_HINT

TIME_RX = re.compile(r"\b\d{1,2}(:\d{2})?\s?(AM|PM|am|pm)\b")
SETS_RX = re.compile(r"^(.*?)\s*(\d+)\s*[x×]\s*(\d+)\s*$")
QUOTED_RX = re.compile(r"[\"“']([^\"”']{2,40})[\"”']")
STOP = {"the", "and", "with", "for", "from", "then", "this", "that", "your", "my", "pm", "am"}


def section(prompt: str, title: str) -> str:
    """The body of a '## title' section of a brain prompt ('' when missing or '(none)')."""
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", prompt, re.S | re.M)
    body = m.group(1).strip() if m else ""
    return "" if body == "(none)" else body


def fields(text: str) -> dict[str, str]:
    """'key: value' lines (indented lines continue the previous value) -> dict."""
    out: dict[str, str] = {}
    key = None
    for line in text.splitlines():
        m = re.match(r"^([a-z][a-z _]*):\s?(.*)$", line)
        if m and not line.startswith(" "):
            key = m.group(1).strip()
            out[key] = m.group(2).strip()
        elif key and line.strip():
            out[key] = (out[key] + "\n" + line.strip().lstrip("- ")).strip()
    return out


def nice(path: str) -> str:
    """inputs/clips/incline-bench.mp4 -> 'Incline bench'."""
    stem = re.sub(r"[-_]+", " ", Path(path).stem).strip()
    return stem[:1].upper() + stem[1:] if stem else path


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOP}


def shots_of(view: str) -> list[dict[str, Any]]:
    """Lines of the draft view ('#3 [label] 1.20-2.40s inputs/clips/x.mp4 0.00-1.20 (mute) VO "words"')."""
    out = []
    for line in view.splitlines():
        m = re.match(r"^#(\d+)(?: \[[^\]]*\])? ([\d.]+)-([\d.]+)s (.*)$", line)
        if not m:
            continue
        rest = m.group(4)
        src = next((t for t in rest.split() if "/" in t), None)
        heard = re.search(r'(?:VO|says) "(.*)"', rest)
        out.append({"idx": int(m.group(1)), "start": float(m.group(2)), "end": float(m.group(3)), "src": src,
                    "heard": heard.group(1) if heard else ""})
    return out


def plan_json(prompt: str, title: str) -> dict[str, Any]:
    body = section(prompt, title)
    if not body:
        raise BrainError(f"demo brain: no {title} in the prompt", code="brain_error")
    return json.loads(body)


def item_count(tl: dict[str, Any]) -> int:
    return sum(len(s.get("shots") or []) if s.get("type") == "vo" else 1 for s in tl.get("segments") or [])


class DemoBrain(Brain):
    name = "demo"

    def __init__(self, delay: float | None = None):
        self.delay = float(os.environ.get("CUTROOM_DEMO_DELAY", "3")) if delay is None else delay

    def status(self) -> dict[str, Any]:
        return {"backend": self.name, "model": "scripted", "ready": True}

    def complete(self, req: BrainRequest) -> BrainResponse:
        t0 = time.time()
        fail = os.environ.get("CUTROOM_DEMO_FAIL")
        handler = {"brief.analyse": (self.analyse, 1.0), "plan.build": (self.plan, 1.6), "revise": (self.revise, 1.2),
                   "match.clips": (self.match, 0.8), "reference.style_spec": (self.style_spec, 0.8)}.get(req.purpose)
        if handler is None:
            raise BrainError(f"demo brain has no answer for {req.purpose}", code="brain_error")
        time.sleep(self.delay * handler[1])
        if fail == "usage_limit":
            raise BrainError("Claude usage limit reached (resets 18:00).", code="usage_limit", status=429,
                             hint=LIMIT_HINT)
        if fail == "not_logged_in":
            raise BrainError("Claude Code is not logged in.", code="claude_not_logged_in", status=503,
                             hint=LOGIN_HINT)
        reply = handler[0](req.prompt)
        return BrainResponse(text=json.dumps(reply), duration_s=round(time.time() - t0, 2), model="demo", turns=1)

    # ------------------------------------------------------------ tasks

    def analyse(self, prompt: str) -> dict[str, Any]:
        brief = fields(section(prompt, "Brief"))
        auto = section(prompt, "Automatic check")
        assumed = [ln.strip()[2:] for ln in auto.split("assumptions so far:")[-1].splitlines()
                   if ln.strip().startswith("- ")] if "assumptions so far:" in auto else []
        if not brief.get("colour grade"):
            assumed.append("No colour grade given: using the preset's own grade.")
        if not brief.get("hook"):
            assumed.append("No hook written: opening on the strongest moment.")
        if section(prompt, "Previous answers"):
            return {"questions": [], "assumptions": assumed, "ready": True}

        files = [ln.split(" | ") for ln in section(prompt, "Uploaded files (edit order)").splitlines()]
        visual = [f[0].split(". ", 1)[-1] for f in files if len(f) > 1 and f[1] in ("clip", "photo")]
        preset = fields(auto).get("preset", "this")
        questions: list[dict[str, Any]] = []
        for gap in [ln.strip()[2:] for ln in auto.split("GAPS (automatic check):")[-1].splitlines()
                    if ln.strip().startswith("- ")] if "GAPS (automatic check):" in auto else []:
            questions.append({"id": re.sub(r"[^a-z0-9]+", "-", gap.lower())[:30].strip("-"), "question": gap,
                              "why": "The automatic check couldn't fill this in.", "blocking": True})
        if len(visual) >= 2:
            questions.append({
                "id": "opening-shot", "question": "Which moment should open the video?",
                "why": "The first 1-2 seconds decide whether people keep watching. I'd open on the most "
                       "striking shot rather than in time order.",
                "options": [nice(v) for v in visual[:3]], "blocking": True})
        if not brief.get("end card"):
            questions.append({
                "id": "end-card", "question": "Close on an end card with your handle?",
                "why": f"The {preset} preset leaves it off. Turn it on when the video is meant to grow the page.",
                "field": "end_card", "options": ["on", "off"], "blocking": False})
        return {"questions": questions[:4], "assumptions": assumed, "ready": not any(q["blocking"]
                                                                                     for q in questions)}

    def plan(self, prompt: str) -> dict[str, Any]:
        tl = plan_json(prompt, "DRAFT plan (JSON)")
        brief = fields(section(prompt, "Brief"))
        answers = section(prompt, "Answers to clarifying questions")
        view = shots_of(section(prompt, "Draft view (output seconds: what plays when)"))
        by_idx = {s["idx"]: s for s in view}
        n = item_count(tl)

        idx = 0
        for i, seg in enumerate(tl["segments"]):
            if seg.get("type") == "vo":
                seg.setdefault("reason", "Your voiceover leads; every B-roll shot lands on the words it shows.")
                for sh in seg.get("shots") or []:
                    idx += 1
                    heard = by_idx.get(idx, {}).get("heard", "")
                    if sh.get("cue"):
                        why = f'Cuts in as you say "{sh["cue"]}", so the picture matches the words.'
                    elif heard:
                        why = f'Covers "{heard[:60]}" with {nice(sh.get("src", "the shot"))}.'
                    else:
                        why = f"{nice(sh.get('src', 'Shot'))} keeps the picture moving between lines."
                    sh.setdefault("reason", why)
                continue
            idx += 1
            src = nice(seg.get("src") or "shot")
            if i == 0:
                why = f"Opens on {src}: the strongest moment goes first to stop the scroll."
            elif seg.get("talk"):
                why = "Your cleanest take of this line; the false start and pauses are cut."
            elif (seg.get("type") == "image") or str(seg.get("src", "")).lower().endswith((".jpg", ".jpeg", ".png",
                                                                                            ".heic")):
                why = f"{src} held on the beat with a slow push-in."
            elif seg.get("beats"):
                why = f"{src}: {seg['beats']} beats of the steadiest part, cut on the beat."
            else:
                why = f"{src}: the most usable stretch (in focus, no shake)."
            seg.setdefault("reason", why)

        notes = [f"Kept the draft's order: it already follows the {tl.get('preset') or 'preset'} structure."]
        if "opening" in answers.lower():
            pick = answers.split("->")[-1].strip().splitlines()[0] if "->" in answers else ""
            if pick:
                notes.insert(0, f"Opening on {pick}, as you asked.")
        text = list(tl.get("text") or [])
        if not text:
            labels = [x.strip() for x in re.split(r"[\n;,]", brief.get("labels", "")) if x.strip()]
            used: set[int] = set()
            for k, lab in enumerate(labels[:5]):
                item = self._label(lab)
                at = self._anchor(lab, view, used, k, len(labels), n)
                used.add(at)
                item["on"] = f"#{at}"
                text.append(item)
            if text:
                notes.append("Labels sit on the shot they describe and stay up for the whole shot (≥1.2 s).")
        tl["text"] = text
        tl["notes"] = list(tl.get("notes") or []) + notes
        talk = tl.get("talk") or "no"
        summary = {
            "voiceover": "Voiceover-led edit: each line of your voice memo has the shot that shows it, music ducks "
                         "under the voice and comes back up between lines.",
            "mixed": "To-camera, voiceover and music-only parts kept in brief order, B-roll matched to what you say.",
            "yes": "Talking edit: best takes kept, pauses and false starts cut, B-roll over the explanations.",
            "some": "Talking parts kept tight, the rest cut to the music.",
        }.get(talk, "Cut to the music: the strongest moments first, every change on the beat.")
        return {"timeline": tl, "summary": summary,
                "changes": [f"added {len(text)} label(s) from the brief", "a reason on every shot"]}

    def revise(self, prompt: str) -> dict[str, Any]:
        tl = plan_json(prompt, "Current edit plan (JSON)")
        notes = section(prompt, "Creator's notes")
        low = notes.lower()
        changes: list[str] = []
        quoted = QUOTED_RX.findall(notes)
        if quoted:
            if tl.get("text"):
                old = tl["text"][0].get("text")
                tl["text"][0]["text"] = quoted[0]
                changes.append(f'label "{old}" now says "{quoted[0]}"')
            else:
                tl["text"] = [{"text": quoted[0], "style": "sticker", "on": "#1"}]
                changes.append(f'added a "{quoted[0]}" sticker on the first shot')
        for tr in ("flash", "whip", "zoom"):
            if tr in low:
                shots = [sh for seg in tl["segments"] for sh in (seg.get("shots") or [] if seg.get("type") == "vo"
                                                                   else [seg])]
                for sh in shots[1:]:            # into every shot but the first (voiceover B-roll included)
                    sh["transition"] = tr
                if len(shots) > 1:
                    changes.append(f"{tr} transitions between shots")
                break
        if "end card" in low:
            on = not re.search(r"\b(no|off|remove|without|drop)\b", low)
            tl["end_card"] = {"enabled": on}
            changes.append("end card " + ("on" if on else "off"))
        if not changes:
            changes.append("noted for the next pass; nothing in the plan needed to move")
        tl["notes"] = list(tl.get("notes") or []) + [f"Revision: {notes.strip()[:120]}"]
        return {"timeline": tl, "summary": "Applied your notes: " + "; ".join(changes) + ".", "changes": changes}

    def match(self, prompt: str) -> dict[str, Any]:
        return {"matches": [], "unmatched": [], "notes": ["demo brain: B-roll left to the software's name matching"]}

    def style_spec(self, prompt: str) -> dict[str, Any]:
        return {"hook": "a face-to-camera line in the first second", "pacing": "fast: 0.6-1 s shots",
                "cuts_on_beat": True, "avg_shot_seconds": 0.8, "framing": "tight, centred",
                "caption_look": "white, bold, lower third", "summary": "Fast, beat-cut, minimal text.",
                "style_overrides": {"beat_every": 1}}

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _label(lab: str) -> dict[str, Any]:
        m = SETS_RX.match(lab)
        if m and m.group(1):
            return {"text": m.group(1).strip(), "sub": f"{m.group(2)} × {m.group(3)}", "style": "lower3"}
        if TIME_RX.search(lab):
            return {"text": lab, "style": "timestamp"}
        return {"text": lab, "style": "sticker"}

    @staticmethod
    def _anchor(lab: str, view: list[dict[str, Any]], used: set[int], k: int, total: int, n: int) -> int:
        """The shot a label belongs on: one whose file name or voiceover words share a word with it."""
        want = words(SETS_RX.sub(r"\1", lab))
        for s in view:
            if s["idx"] not in used and want & (words(nice(s["src"] or "")) | words(s["heard"])):
                return s["idx"]
        if TIME_RX.search(lab) and 1 not in used:
            return 1
        step = max(1, n // max(1, total))
        at = min(n, 1 + k * step)
        while at in used and at < n:
            at += 1
        return at
