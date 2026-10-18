"""What the React app relies on: card summaries, shot -> segment mapping, thumbnails at a time, downloads, Finder,
voiceover previews, fonts, and the scripted demo brain."""
from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient
from test_api import client, new_project, upload  # noqa: F401 - the client fixture

from engine import timeline as T
from engine.brain.demo import DemoBrain, fields, section, shots_of
from engine.brain.schemas import AnalyseResult, PlanResult
from engine.common import transcript_path, write_json
from engine.config import legacy_layout, paths, use_layout


def test_project_summary_has_a_thumbnail_and_open_questions(client: TestClient, media) -> None:  # noqa: F811
    pid = new_project(client)
    assert client.get("/projects").json()[0]["thumbnail"] is None
    upload(client, pid, media["music"], kind="music")
    upload(client, pid, media["photo"])
    with client.app.state.services.store.edit(pid) as p:
        from engine.models import Question
        p.questions = [Question(id="a", question="?"), Question(id="b", question="?", blocking=False)]
    s = client.get("/projects").json()[0]
    assert s["thumbnail"] == f"{pid}/inputs/clips/fit-check.jpg"
    assert s["open_questions"] == 1 and s["latest_version"] is None
    client.patch(f"/projects/{pid}", json={"answers": {"a": "yes"}})
    assert client.get("/projects").json()[0]["open_questions"] == 0


def test_thumbnail_at_a_time_and_download(client: TestClient, media) -> None:  # noqa: F811
    pid = new_project(client)
    upload(client, pid, media["clip_a"])
    a = client.get("/media/thumbnail", params={"path": f"{pid}/inputs/clips/gym-squats.mp4", "t": 0.2})
    b = client.get("/media/thumbnail", params={"path": f"{pid}/inputs/clips/gym-squats.mp4", "t": 2.5})
    assert a.status_code == b.status_code == 200 and a.content != b.content
    late = client.get("/media/thumbnail", params={"path": f"{pid}/inputs/clips/gym-squats.mp4", "t": 99})
    assert late.status_code == 200                    # clamped to the clip, not an empty frame


def test_reveal_opens_the_file_manager(client: TestClient, monkeypatch) -> None:  # noqa: F811
    import engine.system as system
    calls = []
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **_: calls.append(cmd))
    pid = new_project(client)
    assert client.post(f"/projects/{pid}/reveal").status_code == 204
    assert calls and str(paths().workspace / pid) in calls[0][-1]
    r = client.post(f"/projects/{pid}/reveal", json={"version": 3})
    assert r.status_code == 404 and r.json()["error"]["code"] == "output_not_found"


def test_voiceover_info(client: TestClient, media, cutroom_paths) -> None:  # noqa: F811
    pid = new_project(client)
    assert client.get(f"/projects/{pid}/voiceover").json() == []
    upload(client, pid, media["music"], kind="voiceover", name="vo.wav")
    d = cutroom_paths.workspace / pid / "work"
    (d / "_cache" / "voice").mkdir(parents=True)
    write_json(d / "_cache" / "voice" / "x.json", {"src": "inputs/voiceover/vo.wav", "lufs_before": -31.2,
                                                   "lufs_after": -16.0})
    (d / "vo_preview.wav").write_bytes(b"RIFF")
    [vo] = client.get(f"/projects/{pid}/voiceover").json()
    assert vo["preview"] == f"{pid}/work/vo_preview.wav" and vo["stats"]["lufs_after"] == -16.0


def test_fonts_are_served_for_previews(client: TestClient) -> None:  # noqa: F811
    files = client.get("/settings").json()["font_files"]
    if not files:
        pytest.skip("no fonts installed (scripts/setup.sh downloads them)")
    family, name = next(iter(files.items()))
    assert client.get(f"/fonts/{name}").status_code == 200
    assert client.get("/fonts/..%2Fbrand.md").status_code == 404


def test_view_maps_shots_to_segments_and_overlays_to_their_index(media) -> None:
    root = paths().root
    shutil.copy(media["clip_a"], root / "raw" / "a.mp4")
    shutil.copy(media["photo"], root / "raw" / "p.jpg")
    shutil.copy(media["music"], root / "voiceover" / "vo.wav")
    with use_layout(legacy_layout()):
        tp = transcript_path("voiceover/vo.wav")
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(json.dumps({"duration": 4.0, "words": [
            {"w": "chest", "s": 0.2, "e": 0.6, "p": 0.9}, {"w": "day", "s": 0.6, "e": 0.9, "p": 0.9},
            {"w": "then", "s": 2.2, "e": 2.5, "p": 0.9}, {"w": "brunch", "s": 2.5, "e": 3.0, "p": 0.9}]}))
        v = T.view(T.parse({
            "talk": "voiceover", "end_card": {"enabled": False},
            "segments": [{"type": "image", "src": "raw/p.jpg", "dur": 1.0},
                         {"type": "vo", "src": "voiceover/vo.wav", "keep": [{"in": 0, "out": 3.2}],
                          "shots": [{"src": "raw/a.mp4", "in": 0}, {"type": "image", "src": "raw/p.jpg", "at": 2.0}]},
                         {"src": "raw/a.mp4", "in": 0.5, "out": 1.5}],
            "text": [{"text": "late", "style": "sticker", "start": 4.5},
                     {"text": "early", "style": "sticker", "on": "#1"}]}))
    assert [(s.segment, s.shot) for s in v.shots] == [(0, None), (1, 0), (1, 1), (2, None)]
    assert v.shots[1].heard == "chest day" and v.shots[2].heard == "then brunch"
    assert [(o.text, o.index) for o in v.overlays] == [("early", 1), ("late", 0)]


# ---------------------------------------------------------------- demo brain

def test_demo_brain_prompt_helpers() -> None:
    p = "## Brief\ntitle: 5AM\nlabels:\n  5:30AM\n  Lekki\n## Next\n(none)\n"
    assert fields(section(p, "Brief")) == {"title": "5AM", "labels": "5:30AM\nLekki"}
    assert section(p, "Next") == "" and section(p, "Missing") == ""
    assert shots_of('#2 [hook] 1.00-2.50s inputs/clips/a.mp4 0.00-1.50 (mute) VO "chest day"') == [
        {"idx": 2, "start": 1.0, "end": 2.5, "src": "inputs/clips/a.mp4", "heard": "chest day"}]


def test_demo_brain_asks_once_then_is_ready() -> None:
    b = DemoBrain(delay=0)
    p = ("## Brief\ncontent type: gym-vlog\n\n## Automatic check\npreset: gym-vlog\n\n"
         "## Uploaded files (edit order)\n1. inputs/clips/incline-bench.mp4 | clip | 4s\n"
         "2. inputs/clips/brunch.mp4 | clip | 4s\n3. inputs/voiceover/vo.m4a | voiceover | 12s\n")
    res = AnalyseResult.model_validate(b.analyse(p))
    q = {x.id: x for x in res.questions}
    assert q["opening-shot"].options == ["Incline bench", "Brunch"] and q["opening-shot"].blocking
    assert q["end-card"].field == "end_card" and not res.ready
    again = AnalyseResult.model_validate(b.analyse(p + "\n## Previous answers\n- Which moment? -> Brunch\n"))
    assert again.questions == [] and again.ready


def test_demo_brain_plan_and_revise_return_valid_plans() -> None:
    b = DemoBrain(delay=0)
    draft = {"talk": "voiceover", "preset": "gym-vlog", "segments": [
        {"src": "inputs/clips/alarm.mp4", "in": 0, "out": 1},
        {"type": "vo", "src": "inputs/voiceover/vo.m4a",
         "shots": [{"src": "inputs/clips/incline-bench.mp4", "cue": "incline bench"},
                   {"src": "inputs/clips/brunch.mp4", "at": 2}]}]}
    p = ("## Brief\nlabels: 5:30AM, Incline bench 4x10, Lekki brunch\n\n"
         "## Draft view (output seconds: what plays when)\n"
         "#1 0.00-1.00s inputs/clips/alarm.mp4 0.00-1.00 (mute)\n"
         '#2 1.00-2.00s inputs/clips/incline-bench.mp4 0.00-1.00 (mute) VO "incline bench first"\n'
         '#3 2.00-3.00s inputs/clips/brunch.mp4 0.00-1.00 (mute) VO "then brunch"\n'
         f"## DRAFT plan (JSON)\n{json.dumps(draft)}\n")
    res = PlanResult.model_validate(b.plan(p))
    tl = res.timeline
    assert all(s.reason for s in tl.segments) and all(sh.reason for sh in tl.segments[1].shots)
    assert [(t.text, t.style, t.on) for t in tl.text] == [
        ("5:30AM", "timestamp", "#1"), ("Incline bench", "lower3", "#2"), ("Lekki brunch", "sticker", "#3")]
    assert tl.text[1].sub == "4 × 10" and res.summary

    p2 = (f'## Creator\'s notes\nmake the first label say "5AM" and use flash cuts, end card on\n\n'
          f"## Current edit plan (JSON)\n{tl.model_dump_json(by_alias=True, exclude_none=True)}\n")
    rev = PlanResult.model_validate(b.revise(p2))
    assert rev.timeline.text[0].text == "5AM"
    assert rev.timeline.segments[0].transition is None and rev.timeline.end_card.enabled is True
    assert [sh.transition for sh in rev.timeline.segments[1].shots] == ["flash", "flash"]
    assert "flash" in rev.summary


def test_demo_mode_is_reported(client: TestClient, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setenv("CUTROOM_BRAIN", "demo")
    s = client.get("/system/status", params={"claude": "false"}).json()
    assert s["demo"] is True and s["brain"]["backend"] == "demo" and s["brain"]["ready"] is True
