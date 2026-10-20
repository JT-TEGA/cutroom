"""Learned preferences: what the creator changes in Claude's plans, kept per content type and used to plan the next one.

Preference capture, not model training. The lifecycle of one project:

    plan      Claude's plan is kept as work/learn/proposed.json (the baseline)
    revise    the creator's hand edits so far are kept (work/learn/carried.json); Claude's revision is the new baseline
    render    on "Approve & render", diff(baseline, approved plan) -> edit notes (engine/edit_diff.py), recorded
              under the project's content type; the approved plan is kept (work/learn/approved.json) until Claude's
              next plan or revision, to see what the creator undoes before approving again

Store (per workspace, so per user): ``workspace/learned/<preset>.json``, mirrored to ``<preset>.md`` to read. A note
counts the projects it was seen in, minus the ones that edited against it. Only a hand edit to Claude's plan is a
sighting: when Claude already follows a note there is nothing to diff, so a note never confirms itself. A project
keeps its sighting until it is undone there (an edit the other way, see ``edit_diff.opposes``); approving it again
with no change keeps it. Seen in 2+ projects it becomes active and goes into the planning prompt (``prompt_text``);
seen once it stays pending. It goes off only when the creator turns it off, deletes it or edits against it. A note
whose topic the brief sets itself is paused for that project: brief > learned preferences > preset defaults.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from . import timeline as T
from .common import list_presets, read_json, write_json
from .config import EngineError, log, paths
from .edit_diff import Edit, diff, opposes
from .models import BriefData
from .project import ProjectStore, now

ACTIVE_AT = 2           # projects a pattern must be seen in before it's applied
STRONG_AT = 4           # ... and before the prompt calls it a strong habit
_lock = threading.Lock()


class LearnedPref(BaseModel):
    key: str
    topic: str
    rule: str
    projects: dict[str, str] = Field(default_factory=dict, description="project id -> what happened in that video")
    against: dict[str, str] = Field(default_factory=dict, description="project id -> the edit that went against it")
    enabled: bool = True
    first_seen: datetime = Field(default_factory=now)
    last_seen: datetime = Field(default_factory=now)

    @computed_field
    @property
    def count(self) -> int:
        """Videos it was seen in, minus videos that edited against it."""
        return max(0, len(self.projects) - len(self.against))

    @computed_field
    @property
    def status(self) -> Literal["active", "pending", "off"]:
        if not self.enabled:
            return "off"
        return "active" if self.count >= ACTIVE_AT else "pending"


class LearnedSet(BaseModel):
    preset: str
    prefs: list[LearnedPref] = Field(default_factory=list)

    def get(self, key: str) -> LearnedPref:
        p = next((p for p in self.prefs if p.key == key), None)
        if p is None:
            raise EngineError(f"no learned preference {key!r} for {self.preset}", code="pref_not_found", status=404)
        return p


class LearnedItem(LearnedPref):
    state: Literal["applied", "paused", "pending", "off"]
    paused_by: str | None = Field(None, description="the brief field that overrides it for this project")


class ProjectLearned(BaseModel):
    preset: str | None
    items: list[LearnedItem] = Field(default_factory=list)


# ---------------------------------------------------------------- the store

def _check_preset(preset: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", preset or ""):
        raise EngineError(f"not a preset name: {preset!r}", code="invalid_preset", status=422)
    return preset


def folder() -> Path:
    return paths().workspace / "learned"


def load(preset: str) -> LearnedSet:
    data = read_json(folder() / f"{_check_preset(preset)}.json")
    return LearnedSet.model_validate(data) if data else LearnedSet(preset=preset)


def save(ls: LearnedSet) -> LearnedSet:
    ls.prefs.sort(key=lambda p: (-p.count, p.key))
    write_json(folder() / f"{_check_preset(ls.preset)}.json", ls.model_dump(mode="json", exclude={"prefs": {
        "__all__": {"count", "status"}}}))
    (folder() / f"{ls.preset}.md").write_text(markdown(ls))
    return ls


def markdown(ls: LearnedSet) -> str:
    groups = [("Applied when planning (seen in 2+ videos)", "active"), ("Pending (seen once)", "pending"),
              ("Turned off", "off")]
    out = [f"# Learned from your edits: {ls.preset}", "",
           "What you changed in Claude's plans for this content type. Notes seen in 2+ videos go into the planning "
           "prompt; your brief always wins. Written by Cutroom: manage these in the app (Review the plan → Learned "
           "from you); edits to this file are overwritten.", ""]
    for title, status in groups:
        prefs = [p for p in ls.prefs if p.status == status]
        if not prefs:
            continue
        out += [f"## {title}", ""]
        for p in prefs:
            against = f", edited against in {len(p.against)}" if p.against else ""
            out.append(f"- {p.rule} — seen {len(p.projects)}×{against} ({p.topic})")
            out += [f"  - {pid}: {what}" for pid, what in p.projects.items()]
            out += [f"  - {pid} (against): {what}" for pid, what in p.against.items()]
        out.append("")
    if not ls.prefs:
        out.append("Nothing yet: approve a plan you changed and it shows up here.")
    return "\n".join(out).rstrip() + "\n"


def record(preset: str, pid: str, edits: list[Edit], undone: list[Edit] | None = None) -> LearnedSet:
    """One approval of a project. ``edits``: the creator's changes to Claude's plan (each one a sighting); ``undone``:
    what they changed since they last approved this project with the same plan from Claude (only used to see which
    of their own earlier edits they reverted). A project's earlier sightings stay unless undone (approving twice
    neither counts twice nor takes the vote back); an edit the other way undoes this project's sighting, or counts
    against a note other projects taught."""
    with _lock:
        ls = load(preset)
        seen = {e.key for e in edits}
        for e in edits:
            p = next((p for p in ls.prefs if p.key == e.key), None)
            if p is None:
                p = LearnedPref(key=e.key, topic=e.topic, rule=e.rule)
                ls.prefs.append(p)
            p.rule = e.rule                     # the latest wording (its numbers come from the newest video)
            p.projects[pid] = e.instance
            p.against.pop(pid, None)
            p.last_seen = now()
        for p in ls.prefs:
            if p.key in seen:
                continue
            hit = next((e for e in edits if opposes(p.key, e.key)), None)
            if hit and pid in p.projects:
                p.projects.pop(pid)             # this video now goes the other way
            elif hit:
                p.against[pid] = hit.instance
            elif pid in p.projects and any(opposes(p.key, u.key) for u in undone or []):
                p.projects.pop(pid)             # reverted by hand before approving again
            elif pid in p.against and any(u.key == p.key for u in undone or []):
                p.against.pop(pid)              # the edit against it was reverted
        ls.prefs = [p for p in ls.prefs if p.projects]
        return save(ls)


def set_enabled(preset: str, key: str, enabled: bool) -> LearnedSet:
    with _lock:
        ls = load(preset)
        ls.get(key).enabled = enabled
        return save(ls)


def delete(preset: str, key: str) -> LearnedSet:
    with _lock:
        ls = load(preset)
        ls.prefs.remove(ls.get(key))
        return save(ls)


# ---------------------------------------------------------------- applying them

def paused_topics(brief: BriefData) -> dict[str, str]:
    """Topics the brief sets itself -> the brief field that does. Learned notes on these topics are left out."""
    b = brief
    out: dict[str, str] = {}
    if b.captions:
        out["captions"] = "Captions"
    if b.end_card:
        out["end_card"] = "End card"
    if b.hook.strip():
        out["hook"] = "Hook"
    if b.labels.strip() or b.text_on_screen.strip():
        out["text"] = "Labels & stickers" if b.labels.strip() else "Text on screen"
    if b.pacing.strip() or b.beat_sync:
        out["timing"] = "Pacing" if b.pacing.strip() else "Beat sync"
    if b.target_length:
        out["length"] = "Target length"
    if b.pacing and re.search(r"\b(transition|flash|whip|zoom)", b.pacing, re.I):
        out["transitions"] = "Pacing"
    return out


def preset_of(brief: BriefData, tl: T.Timeline | None = None) -> str | None:
    name = ((tl.preset if tl else None) or brief.content_type or "").strip().lower()
    return name if name in list_presets() else None


def for_project(preset: str | None, brief: BriefData) -> ProjectLearned:
    """Every note for the project's content type, with what it does for this project."""
    if not preset:
        return ProjectLearned(preset=None)
    paused = paused_topics(brief)
    items = []
    for p in load(preset).prefs:
        state = {"off": "off", "pending": "pending"}.get(p.status) or ("paused" if p.topic in paused else "applied")
        items.append(LearnedItem(**p.model_dump(exclude={"count", "status"}), state=state,
                                 paused_by=paused.get(p.topic) if state == "paused" else None))
    return ProjectLearned(preset=preset, items=items)


def prompt_text(items: list[LearnedItem]) -> str:
    """The applied notes as the planning prompt's "observed preferences" section ("" when there are none)."""
    applied = [x for x in items if x.state == "applied"]
    if not applied:
        return ""
    lines = [f"- {x.rule} (seen in {x.count} videos{', a strong habit' if x.count >= STRONG_AT else ''})"
             for x in sorted(applied, key=lambda x: -x.count)]
    return ("What this creator changed in your past plans for this content type, most frequent first. Follow them "
            "unless the brief says otherwise (brief > these > the preset's defaults). They never override a hard "
            "rule: 9:16, text readable for 1.2 s (cards 2.5 s), safe zones, B-roll at least 1 s, files from the "
            "input only.\n" + "\n".join(lines))


# ---------------------------------------------------------------- capture (called by the pipeline)

def _dir(cwd: Path) -> Path:
    return cwd / "work" / "learn"


def proposal(cwd: Path, tl: T.Timeline, fresh: bool) -> None:
    """Claude's plan becomes the baseline. fresh (a new plan, not a revision): forget hand edits carried over."""
    write_json(_dir(cwd) / "proposed.json", tl.to_edl())
    (_dir(cwd) / "approved.json").unlink(missing_ok=True)     # changes from here on are Claude's, not undos
    if fresh:
        (_dir(cwd) / "carried.json").unlink(missing_ok=True)


def _view(tl: T.Timeline) -> T.TimelineView | None:
    try:
        return T.view(tl)
    except EngineError:
        return None


def _edits(cwd: Path, current: T.Timeline) -> list[Edit]:
    """The hand edits since Claude's last plan or revision, plus those carried over from before a revision."""
    carried = {e["key"]: Edit.model_validate(e) for e in read_json(_dir(cwd) / "carried.json", [])}
    base = read_json(_dir(cwd) / "proposed.json")
    if base is None:
        return list(carried.values())
    proposed = T.parse(base)
    for e in diff(proposed, current, _view(proposed), _view(current)):
        if e.key in carried:
            carried[e.key].instance += "; " + e.instance
        else:
            carried[e.key] = e
    return list(carried.values())


def carry(cwd: Path, current: T.Timeline) -> None:
    """Before a revision: keep the hand edits made so far (Claude's revision becomes the next baseline)."""
    if (_dir(cwd) / "proposed.json").exists():
        write_json(_dir(cwd) / "carried.json", [e.model_dump() for e in _edits(cwd, current)])


def capture(store: ProjectStore, pid: str) -> list[Edit]:
    """The approved plan vs Claude's: record the edit notes under the project's content type."""
    proj = store.get(pid)
    with store.context(pid) as cwd:
        data = read_json(cwd / "work" / "edl.json")
        if data is None or not (_dir(cwd) / "proposed.json").exists():
            return []
        final = T.parse(data)
        preset = preset_of(proj.brief, final)
        if not preset:
            return []
        edits = _edits(cwd, final)
        before = read_json(_dir(cwd) / "approved.json")
        undone = []
        if before is not None:
            prev = T.parse(before)
            undone = diff(prev, final, _view(prev), _view(final))
        record(preset, pid, edits, undone)
        write_json(_dir(cwd) / "approved.json", final.to_edl())
        for e in edits:
            log(f"  learned ({preset}): {e.rule} [{e.instance}]")
    return edits


__all__ = ["ACTIVE_AT", "LearnedItem", "LearnedPref", "LearnedSet", "ProjectLearned", "capture", "carry", "delete",
           "for_project", "load", "paused_topics", "preset_of", "prompt_text", "proposal", "record", "set_enabled"]
