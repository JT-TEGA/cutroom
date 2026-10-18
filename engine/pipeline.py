"""The editing workflow for app projects: what used to happen in chat, as functions.

    analyse(store, pid, brain)        brief check + clarifying questions
    plan(store, pid, brain)           transcribe -> clean voiceover -> match B-roll -> draft -> brain plan -> edl.json
    save_timeline(store, pid, tl)     the creator's own edits to the plan
    render(store, pid)                output/vN/ video + contact sheet
    revise(store, pid, notes, brain)  notes -> updated plan
    reference(store, pid, brain)      REFERENCE mode style spec

Each runs inside the project's layout, reports progress through config.step()/log(), and keeps project.json's
status in step. Long-running: call them from a background job.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import autocut, contact_sheet, voice
from . import brief as B
from . import edl as E
from . import render as R
from . import timeline as T
from .brain import Brain
from .brain import brief as brain_brief
from .brain import match as brain_match
from .brain import plan as brain_plan
from .brain import reference as brain_reference
from .brain import revise as brain_revise
from .brain.context import answers_text
from .brain.schemas import AnalyseResult, ClipMatchResult
from .common import list_presets, load_transcript, read_json, style_for, transcribe_subprocess, write_json
from .config import EngineError, job_log, log, progress_span, step
from .models import StyleSpec
from .project import Project, ProjectStore, RenderInfo

# ---------------------------------------------------------------- helpers

def _analysis(store: ProjectStore, proj: Project) -> dict[str, Any]:
    a = B.analyse(proj.brief, proj.id, clips=store.clip_refs(proj), auto_pick_music=True)
    if proj.style_spec and proj.style_spec.style_overrides:     # reference style < the brief's own overrides
        a["style_overrides"] = {**proj.style_spec.style_overrides, **a["style_overrides"]}
    B.write(a)
    return a


def _file_info(proj: Project, talking: dict[str, bool] | None = None) -> list[dict[str, Any]]:
    out = []
    for f in proj.files:
        d = f.model_dump(include={"path", "kind", "info", "trim_in", "trim_out"})
        if talking and f.path in talking:
            d["talking"] = talking[f.path]
        out.append(d)
    return out


def _known(proj: Project) -> set[str]:
    return {f.path for f in proj.files}


def _clip_specs(store: ProjectStore, proj: Project) -> list[str]:
    specs = []
    for c in store.clip_refs(proj):
        rng = f"@{c.in_ or ''}-{c.out or ''}" if (c.in_ is not None or c.out is not None) else ""
        specs.append(c.src + rng)
    return specs


def _transcripts(proj: Project, talk: str) -> dict[str, dict[str, Any] | None]:
    """Cached transcripts of the clips (to camera) and voiceovers worth showing the brain."""
    out: dict[str, dict[str, Any] | None] = {}
    for f in proj.files:
        if f.kind == "voiceover" or (f.kind == "clip" and talk in ("yes", "some", "mixed") and f.has_audio):
            out[f.path] = load_transcript(f.path, auto=False)
    return out


def _set_status(store: ProjectStore, pid: str, status: str, error: dict[str, Any] | None = None) -> None:
    with store.edit(pid) as p:
        p.status = status  # type: ignore[assignment]
        p.last_error = error


def _save_plan(store: ProjectStore, pid: str, tl: T.Timeline, summary: str | None = None) -> T.TimelineView:
    """Write work/edl.json (the previous plan kept in work/plans/) and bump the plan version."""
    wd = store.dir(pid) / "work"
    cur = wd / "edl.json"
    proj = store.get(pid)
    if cur.exists():
        (wd / "plans").mkdir(exist_ok=True)
        shutil.copy2(cur, wd / "plans" / f"edl_v{proj.plan_version}.json")
    tl.name = pid
    write_json(cur, tl.to_edl())
    with store.edit(pid) as p:
        p.plan_version += 1
        if summary is not None:
            p.plan_summary = summary
        if p.status not in ("rendering",):
            p.status = "planned"
        p.last_error = None
    return T.view(tl)


def failed(store: ProjectStore, pid: str, err: BaseException) -> None:
    """Record a failed job on the project (called by the job runner)."""
    info = err.to_dict() if isinstance(err, EngineError) else {"code": "internal_error", "message": str(err)}
    try:
        _set_status(store, pid, "error", info)
        with store.context(pid):
            job_log(f"FAILED: {info['code']}: {info['message'][:300]}")
    except EngineError:
        pass


# ---------------------------------------------------------------- analyse

def analyse(store: ProjectStore, pid: str, brain: Brain) -> AnalyseResult:
    proj = store.get(pid)
    with store.context(pid) as cwd:
        step("check the brief", 10)
        a = _analysis(store, proj)
        step("ask the brain", 30)
        res = brain_brief.analyse(brain, proj.brief, a, _file_info(proj), cwd=cwd, questions=proj.questions,
                                  answers=proj.answers, presets=list_presets())
        res.assumptions = res.assumptions or a["notes"]      # the brain saw the notes and restates what still holds
    with store.edit(pid) as p:
        p.questions, p.assumptions = res.questions, res.assumptions
        if p.status in ("new", "error"):
            p.status = "analysed"
        p.last_error = None
    step("done", 100)
    return res


# ---------------------------------------------------------------- reference mode

def reference(store: ProjectStore, pid: str, brain: Brain, url: str | None = None,
              cookies: str | None = None) -> StyleSpec:
    from . import reference as ref
    proj = store.get(pid)
    url = url or proj.brief.reference_url
    if not url:
        raise EngineError("no reference reel URL in the brief", code="no_reference_url", status=422)
    with store.context(pid) as cwd:
        stats = ref.analyse(pid, url, cookies)
        rd = cwd / "work" / "reference"
        step("brain: style spec", 85)
        spec = brain_reference.style_spec(brain, [rd / "hook.jpg", rd / "shots.jpg"], stats.get("transcript", ""),
                                          stats=stats, cwd=cwd)
        write_json(cwd / "work" / "style_spec.json", spec.model_dump())
    with store.edit(pid) as p:
        p.style_spec = spec
    step("done", 100)
    return spec


# ---------------------------------------------------------------- plan

def _needs_match(proj: Project, a: dict[str, Any]) -> bool:
    """Voiceover edit with B-roll whose file names don't say what it shows (IMG_1234.MOV)."""
    if a["talk"] not in ("voiceover", "mixed") or not a["voiceover"]:
        return False
    return any(f.kind in ("clip", "photo") and not autocut.name_keywords(f.path) for f in proj.files)


def _match(store: ProjectStore, proj: Project, a: dict[str, Any], brain: Brain, cwd: Path) -> ClipMatchResult | None:
    visual = [f for f in proj.files if f.kind in ("clip", "photo")]
    sheets = []
    for i in range(0, len(visual), 15):
        chunk = visual[i:i + 15]
        out = cwd / "work" / (f"broll_{i // 15 + 1}.jpg" if len(visual) > 15 else "broll.jpg")
        contact_sheet.board([(f.path, None if f.kind == "photo" else (f.duration or 0) * 0.4) for f in chunk], out)
        sheets.append(out)
    vo_src = a["voiceover"][0]["src"]
    tr = load_transcript(vo_src) or {"words": []}
    res = brain_match.clips(brain, tr, _file_info(proj), sheets, cwd=cwd, voiceover_src=vo_src,
                            cues=proj.brief.visual_cues)
    write_json(cwd / "work" / "match.json", res.model_dump(by_alias=True))
    # matches become visual cues for the draft (on top of the brief's own)
    have = {c["say"].lower() for c in a["cues"]}
    for m in res.matches:
        if m.phrase.lower() not in have:
            a["cues"].append({"say": m.phrase, "src": m.src, "in": m.in_, "out": None, "line": f"match: {m.reason}"})
    B.write(a)
    return res


def plan(store: ProjectStore, pid: str, brain: Brain) -> T.TimelineView:
    proj = store.get(pid)
    if not any(f.kind in ("clip", "photo") for f in proj.files):
        raise EngineError("upload some clips or photos first", code="no_clips", status=422)
    _set_status(store, pid, "planning")
    with store.context(pid) as cwd:
        step("check the brief", 2)
        if proj.brief.mode and "REFERENCE" in proj.brief.mode.upper() and proj.brief.reference_url \
                and not proj.style_spec:
            with progress_span(2, 8):
                reference(store, pid, brain)
            proj = store.get(pid)
        a = _analysis(store, proj)
        talk = a["talk"]

        # 1. transcribe what is said to camera (subprocess: whisper never shares a process with OpenCV)
        cam = [f.path for f in proj.files if f.kind == "clip" and f.has_audio]
        if talk in ("yes", "some", "mixed") and cam:
            step("transcribe", 8)
            transcribe_subprocess(cam)
        # 2. voiceover: clean-up + transcript
        for v in a["voiceover"]:
            step("clean the voiceover", 25)
            cfg = style_for({"preset": a["preset"], "style": a["style_overrides"]})
            if voice.wanted(cfg, "vo"):
                _, stats = voice.clean(v["src"], cfg)
                log(f"  voiceover cleaned: {voice.summary(stats)}")
            load_transcript(v["src"])
        # 3. B-roll with meaningless names: the brain looks at a contact sheet
        matches = None
        if _needs_match(proj, a):
            step("match b-roll to the voiceover", 35)
            matches = _match(store, proj, a, brain, cwd)
        # 4. the software's draft (cuts, moments, beat sync, B-roll placement)
        step("draft", 45)
        with progress_span(45, 72):
            draft_edl = autocut.draft(pid, _clip_specs(store, proj))
        if not draft_edl.get("segments"):
            raise EngineError("the rough cut came out empty: no clip had a usable stretch", code="empty_draft",
                              status=422, hint="The clips may be too blurry, dark or shaky. Add steadier clips or "
                                               "photos, then plan again.")
        draft = T.parse(draft_edl)
        try:
            draft_view = T.view(draft)
        except EngineError as e:
            log(f"  ! draft view: {e.message}")
            draft_view = None
        # 5. the brain turns the draft into the plan
        step("brain: build the plan", 75)
        talking = {f.path: bool((load_transcript(f.path, auto=False) or {}).get("words")) for f in proj.files
                   if f.kind == "clip" and talk in ("yes", "some", "mixed")}
        res = brain_plan.build(
            brain, proj.brief, _transcripts(proj, talk), _file_info(proj, talking), a["preset"],
            draft=draft, draft_view=draft_view, analysis=a, cwd=cwd, known_files=_known(proj),
            answers=answers_text(proj.questions, proj.answers), style_spec=proj.style_spec, matches=matches)
        write_json(cwd / "work" / "plan_changes.json", {"summary": res.summary, "changes": res.changes})
        step("save", 97)
        view = _save_plan(store, pid, res.timeline, res.summary)
    step("done", 100)
    return view


# ---------------------------------------------------------------- the creator's own edits

def get_timeline(store: ProjectStore, pid: str) -> T.TimelineView:
    store.get(pid)
    with store.context(pid) as cwd:
        data = read_json(cwd / "work" / "edl.json")
        if data is None:
            raise EngineError("this project has no plan yet: run plan first", code="no_plan", status=404)
        return T.view(T.parse(data))


def save_timeline(store: ProjectStore, pid: str, tl: T.Timeline) -> T.TimelineView:
    proj = store.get(pid)
    with store.context(pid):
        bad = sorted(s for s in brain_plan.srcs(tl) if s not in _known(proj) and not s.startswith("assets/"))
        if bad:
            raise EngineError("the plan uses files that aren't in this project: " + ", ".join(bad),
                              code="invalid_plan", status=422)
        problems = T.check(tl)
        if problems:
            raise EngineError("the plan has problems:\n  - " + "\n  - ".join(problems), code="invalid_plan",
                              status=422)
        return _save_plan(store, pid, tl)


# ---------------------------------------------------------------- render

def render(store: ProjectStore, pid: str, draft: bool = False) -> RenderInfo:
    proj = store.get(pid)
    if not (store.dir(pid) / "work" / "edl.json").exists():
        raise EngineError("this project has no plan yet: run plan first", code="no_plan", status=409)
    _set_status(store, pid, "rendering")
    with store.context(pid):
        res = R.render(pid, draft=draft)
    info = RenderInfo(version=res["version"], video=res["output"], contact_sheet=res["contact_sheet"],
                      duration=round(res["duration"], 3), size_bytes=res["size_bytes"], draft=draft,
                      plan_version=proj.plan_version, audio=res.get("audio") or {})
    with store.edit(pid) as p:
        p.renders.append(info)
        p.status = "rendered"
        p.last_error = None
    return info


# ---------------------------------------------------------------- revise

def revise(store: ProjectStore, pid: str, notes: str, brain: Brain) -> T.TimelineView:
    if not notes.strip():
        raise EngineError("notes are empty", code="empty_notes", status=422)
    proj = store.get(pid)
    with store.context(pid) as cwd:
        data = read_json(cwd / "work" / "edl.json")
        if data is None:
            raise EngineError("this project has no plan yet: run plan first", code="no_plan", status=409)
        current = T.parse(data)
        try:
            cur_view = T.view(current)
        except EngineError:
            cur_view = None
        step("brain: apply the notes", 20)
        res = brain_revise.revise(brain, current, notes, cwd=cwd, brief=proj.brief, clip_info=_file_info(proj),
                                  transcripts=_transcripts(proj, current.talk or "some"), known_files=_known(proj),
                                  current_view=cur_view)
        write_json(cwd / "work" / "revisions" / f"rev_{proj.plan_version + 1}.json",
                   {"notes": notes, "summary": res.summary, "changes": res.changes})
        step("save", 95)
        view = _save_plan(store, pid, res.timeline, res.summary)
    step("done", 100)
    return view


def outputs(store: ProjectStore, pid: str) -> list[dict[str, Any]]:
    """Rendered versions on disk (newest first)."""
    proj = store.get(pid)
    d = store.dir(pid) / "output"
    by_version = {r.version: r for r in proj.renders}
    out = []
    for vd in sorted((x for x in d.glob("v*") if x.is_dir() and x.name[1:].isdigit()),
                     key=lambda x: -int(x.name[1:])):
        n = int(vd.name[1:])
        video = next(iter(sorted(vd.glob("*.mp4"))), None)
        if video is None:
            continue
        r = by_version.get(n)
        out.append({"version": n, "video": str(video.relative_to(store.dir(pid))),
                    "contact_sheet": str((vd / "contact.jpg").relative_to(store.dir(pid)))
                    if (vd / "contact.jpg").exists() else None,
                    "size_bytes": video.stat().st_size, "duration": r.duration if r else None,
                    "draft": r.draft if r else None, "plan_version": r.plan_version if r else None,
                    "created_at": r.created_at if r else None})
    return out


__all__ = ["analyse", "plan", "render", "revise", "reference", "save_timeline", "get_timeline", "outputs", "failed",
           "E"]
