"""Learning from the creator's edits: diffing plans into edit notes, the per-preset store, the planning prompt, and
the brief overriding a learned note. The brain is mocked."""
from __future__ import annotations

import json

import pytest
from conftest import MockBrain, plan_reply
from fastapi.testclient import TestClient

from engine import learn
from engine import pipeline as P
from engine import timeline as T
from engine.edit_diff import Edit, diff, opposes
from engine.models import BriefData
from engine.project import ProjectStore
from server.app import create_app
from server.deps import Services
from server.jobs import JobManager


def tl(segments, **kw) -> T.Timeline:
    return T.parse({"segments": segments, **kw})


def keys(edits: list[Edit]) -> set[str]:
    return {e.key for e in edits}


def fake_view(t: T.Timeline, durs: list[float]) -> T.TimelineView:
    """A laid-out view with the given segment lengths (output seconds), one shot per segment."""
    shots, at = [], 0.0
    for i, (seg, d) in enumerate(zip(t.segments, durs)):
        shots.append(T.ResolvedShot(idx=i + 1, segment=i, kind="clip", src=seg.src, in_=0, out=d, start=at,
                                    end=at + d, duration=d, role="mute"))
        at += d
    return T.TimelineView(timeline=t, duration=at, shots=shots, overlays=[], captions={"enabled": True})


A, B, C = "inputs/clips/a.mp4", "inputs/clips/b.mp4", "inputs/clips/c.mp4"
TALK = {"src": "inputs/clips/talk.mp4", "talk": True, "text": "so here's my morning"}


# ---------------------------------------------------------------- diffing + rule inference

def test_unchanged_plan_has_no_edits() -> None:
    p = tl([{"src": A}, {"src": B}], text=[{"text": "Lekki", "style": "sticker", "on": "#1"}])
    assert diff(p, p.model_copy(deep=True)) == []


def test_reorder_becomes_a_general_order_rule_and_a_hook_rule() -> None:
    p = tl([{"src": A}, {"src": B}, TALK])
    f = tl([TALK, {"src": A}, {"src": B}])
    by = {e.key: e for e in diff(p, f)}
    assert by["order.talking-before-b-roll"].rule == "Puts talking shots before B-roll shots"
    assert by["order.talking-before-b-roll"].topic == "order"
    assert by["hook.talking"].rule == "Opens on a talking shot"
    assert "moved shot 3" in by["order.talking-before-b-roll"].instance


def test_deleting_the_closing_card_and_end_card() -> None:
    p = tl([{"src": A}, {"src": B}, {"type": "color", "color": "#000", "dur": 1}], end_card={"enabled": True})
    f = tl([{"src": A}, {"src": B}], end_card={"enabled": False})
    by = {e.key: e for e in diff(p, f)}
    assert by["shots.drop-closing-colour-card"].rule == "Drops the closing colour card"
    assert by["end_card.off"].rule == "Turns the end card off" and by["end_card.off"].topic == "end_card"


def test_swapping_a_photo_for_a_clip() -> None:
    p = tl([{"src": A}, {"src": "inputs/clips/p.jpg"}])
    f = tl([{"src": A}, {"src": C, "reason": "Swapped in by you"}])
    by = {e.key: e for e in diff(p, f)}
    assert by["footage.clip-over-photo"].rule == "Prefers clips over photos"
    assert "p.jpg → inputs/clips/c.mp4" in by["footage.clip-over-photo"].instance


def test_timing_infers_the_rule_not_just_the_instance() -> None:
    p = tl([{"src": A}, {"src": B}, {"src": C}])
    f = p.model_copy(deep=True)
    edits = {e.key: e for e in diff(p, f, fake_view(p, [2.5, 3.0, 3.0]), fake_view(f, [1.5, 1.2, 3.0]))}
    assert edits["timing.intro-shorter"].rule == "Shortens the intro shots to under 2 s"
    assert edits["timing.intro-shorter"].instance == "2.5 s → 1.5 s, 3.0 s → 1.2 s"
    # small nudges are noise
    assert diff(p, f, fake_view(p, [2.5, 3.0, 3.0]), fake_view(f, [2.4, 3.1, 3.0])) == []


def test_text_captions_and_transitions() -> None:
    p = tl([{**TALK, "label": "hook"}, {"src": A, "transition": "flash"}, {"src": B}],
           text=[{"text": "MORNING *routine*", "style": "title", "on": "hook"},
                 {"text": "Lekki, 7PM", "style": "sticker", "on": "#2"},
                 {"text": "Day one of the plan", "style": "label", "on": "#3"}])
    f = tl([{**TALK, "label": "hook", "captions": False}, {"src": A}, {"src": B}],
           text=[{"text": "lekki, 7pm", "style": "sticker", "on": "shot-2"},
                 {"text": "Day one of the plan", "style": "lower3", "on": "#3"}])
    by = {e.key: e for e in diff(p, f)}
    assert by["text.none-on-hook"].rule == "Keeps text off the hook (the first 1-2 s)"
    assert by["text.lowercase"].instance == '"Lekki, 7PM" → "lekki, 7pm"'
    assert by["text.lower3-over-label"].rule == "Prefers the lower3 text style over label"
    assert by["captions.off-hook"].rule == "No captions on the hook"
    assert by["transitions.fewer"].instance == "took the flash off shot 2"


def test_captions_off_for_the_whole_edit() -> None:
    p = tl([TALK])
    f = tl([TALK], captions={"enabled": False})
    assert keys(diff(p, f)) == {"captions.off"}


# ---------------------------------------------------------------- the store

def edit(key="timing.intro-shorter", topic="timing", rule="Shortens the intro shots to under 2 s", what="x"):
    return Edit(key=key, topic=topic, rule=rule, instance=what)


def test_patterns_need_two_videos_and_reapproving_doesnt_double_count(cutroom_paths) -> None:
    learn.record("gym-vlog", "p1", [edit()])
    learn.record("gym-vlog", "p1", [edit()])          # the same project approved again
    p = learn.load("gym-vlog").get("timing.intro-shorter")
    assert (p.count, p.status) == (1, "pending")
    learn.record("gym-vlog", "p2", [edit(what="3.0 s → 1.4 s")])
    p = learn.load("gym-vlog").get("timing.intro-shorter")
    assert (p.count, p.status) == (2, "active") and p.projects["p2"] == "3.0 s → 1.4 s"
    # approving p1 again with no change (or Claude now doing it itself) keeps its vote: no change isn't an undo
    learn.record("gym-vlog", "p1", [])
    p = learn.load("gym-vlog").get("timing.intro-shorter")
    assert (p.count, p.status) == (2, "active") and p.enabled
    learn.record("gym-vlog", "p2", [edit("timing.intro-longer", rule="Holds the intro shots longer")])
    learn.record("gym-vlog", "p2", [])
    md = (cutroom_paths.workspace / "learned" / "gym-vlog.md").read_text()
    assert md.startswith("# Learned from your edits: gym-vlog")
    assert "## Pending (seen once)" in md and "- Shortens the intro shots to under 2 s — seen 1× (timing)" in md


def test_opposite_notes() -> None:
    assert opposes("end_card.off", "end_card.on") and opposes("timing.intro-shorter", "timing.intro-longer")
    assert opposes("footage.clip-over-photo", "footage.photo-over-clip")
    assert opposes("order.talking-before-b-roll", "order.b-roll-before-talking")
    assert opposes("text.none", "text.title-on-hook") and opposes("text.fewer-sticker", "text.add-sticker")
    assert opposes("transitions.fewer", "transitions.add-flash") and opposes("hook.talking", "hook.b-roll")
    assert not opposes("text.fewer-sticker", "text.add-label") and not opposes("hook.talking", "hook.different")
    assert not opposes("end_card.off", "captions.on") and not opposes("end_card.off", "end_card.off")


def test_editing_against_a_preference_reduces_then_removes_it(cutroom_paths) -> None:
    off = edit("end_card.off", "end_card", "Turns the end card off", "removed the end card")
    on = edit("end_card.on", "end_card", "Adds the handle end card", "turned the end card on")
    for pid in ("p1", "p2", "p3"):
        learn.record("gym-vlog", pid, [off])
    learn.record("gym-vlog", "p4", [on])             # a new video, edited the other way
    p = learn.load("gym-vlog").get("end_card.off")
    assert (p.count, p.status, p.against) == (2, "active", {"p4": "turned the end card on"})
    assert learn.load("gym-vlog").get("end_card.on").count == 1      # and that edit is a sighting of its own
    learn.record("gym-vlog", "p1", [on])             # p1 goes the other way now: its own sighting is undone
    p = learn.load("gym-vlog").get("end_card.off")
    assert (p.count, p.status) == (1, "pending") and "p1" not in p.projects
    # p2 turns the end card back on by hand before approving again (no change vs Claude's plan, but an undo)
    learn.record("gym-vlog", "p2", [], undone=[on])
    assert learn.load("gym-vlog").get("end_card.off").count == 0
    learn.record("gym-vlog", "p3", [on])
    assert "end_card.off" not in {p.key for p in learn.load("gym-vlog").prefs}
    md = (cutroom_paths.workspace / "learned" / "gym-vlog.md").read_text()
    assert "Adds the handle end card — seen 3×" in md


def test_against_is_withdrawn_when_reverted(cutroom_paths) -> None:
    off = edit("end_card.off", "end_card", "Turns the end card off")
    on = edit("end_card.on", "end_card", "Adds the handle end card")
    for pid in ("p1", "p2"):
        learn.record("gym-vlog", pid, [off])
    learn.record("gym-vlog", "p3", [on])
    assert learn.load("gym-vlog").get("end_card.off").count == 1
    learn.record("gym-vlog", "p3", [], undone=[off])
    assert learn.load("gym-vlog").get("end_card.off").count == 2


def test_presets_are_kept_apart(cutroom_paths) -> None:
    learn.record("gym-vlog", "p1", [edit()])
    learn.record("gym-vlog", "p2", [edit()])
    assert learn.load("fashion-bts").prefs == []
    assert learn.for_project("fashion-bts", BriefData()).items == []


def test_toggle_and_delete(cutroom_paths) -> None:
    for pid in ("p1", "p2"):
        learn.record("gym-vlog", pid, [edit()])
    learn.set_enabled("gym-vlog", "timing.intro-shorter", False)
    items = learn.for_project("gym-vlog", BriefData()).items
    assert items[0].state == "off" and learn.prompt_text(items) == ""
    learn.delete("gym-vlog", "timing.intro-shorter")
    assert learn.load("gym-vlog").prefs == []


# ---------------------------------------------------------------- applying them

def seed(preset: str, *edits: Edit) -> None:
    for pid in ("old-1", "old-2"):
        learn.record(preset, pid, list(edits))


def test_brief_field_overrides_a_conflicting_learned_pref(cutroom_paths) -> None:
    seed("gym-vlog", edit("captions.off", "captions", "Turns captions off"), edit())
    brief = BriefData(content_type="gym-vlog", captions="on")
    items = {x.key: x for x in learn.for_project("gym-vlog", brief).items}
    assert items["captions.off"].state == "paused" and items["captions.off"].paused_by == "Captions"
    assert items["timing.intro-shorter"].state == "applied"
    text = learn.prompt_text(list(items.values()))
    assert "Shortens the intro shots" in text and "Turns captions off" not in text
    # without the brief field, it applies
    assert "Turns captions off" in learn.prompt_text(learn.for_project("gym-vlog", BriefData()).items)


# ---------------------------------------------------------------- through the pipeline and the API

@pytest.fixture
def client(mock_brain: MockBrain, cutroom_paths):
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: mock_brain)
    with TestClient(create_app(svc)) as c:
        c.svc = svc                 # type: ignore[attr-defined]
        yield c


def planned(client: TestClient, media, **brief) -> str:
    pid = client.post("/projects", json={"name": "Dump", "brief": {"content_type": "photo-dump", "talking": "no",
                                                                    "idea": "a night out", **brief}}).json()["id"]
    for key, kind in (("clip_a", None), ("clip_b", None), ("music", "music")):
        with open(media[key], "rb") as f:
            client.post(f"/projects/{pid}/files", data={"kind": kind} if kind else {},
                        files=[("files", (media[key].name, f))])
    r = client.post(f"/projects/{pid}/plan", params={"wait": "true"})
    assert r.json()["status"] == "done", r.text
    return pid


def test_learned_notes_reach_the_planning_prompt(client, mock_brain, media) -> None:
    seed("photo-dump", edit("text.none-on-hook", "text", "Keeps text off the hook (the first 1-2 s)"),
         edit("captions.off", "captions", "Turns captions off"))
    learn.record("photo-dump", "old-3", [edit("transitions.fewer", "transitions", "Prefers straight cuts")])
    seed("gym-vlog", edit("end_card.off", "end_card", "Turns the end card off"))
    pid = planned(client, media, captions="on")
    prompt = next(c for c in mock_brain.calls if c.purpose == "plan.build").prompt
    sec = prompt.split("## The creator's observed preferences (learned from their edits)\n")[1].split("\n## ")[0]
    assert "- Keeps text off the hook (the first 1-2 s) (seen in 2 videos)" in sec
    assert "brief > these > the preset's defaults" in sec
    assert "Turns captions off" not in sec              # the brief sets captions
    assert "Prefers straight cuts" not in sec           # pending: seen once
    assert "end card" not in sec                        # another content type
    assert prompt.index("## Brand") < prompt.index("## The creator's observed") < prompt.index("## Clips")
    plan = next(c for c in mock_brain.calls if c.purpose == "plan.build").system
    assert "learned preferences < brief" in plan

    body = client.get(f"/projects/{pid}/learned").json()
    states = {x["key"]: (x["state"], x["paused_by"]) for x in body["items"]}
    assert body["preset"] == "photo-dump"
    assert states == {"text.none-on-hook": ("applied", None), "captions.off": ("paused", "Captions"),
                      "transitions.fewer": ("pending", None)}


def test_approving_an_edited_plan_records_edit_notes(client, mock_brain, media, monkeypatch) -> None:
    rendered = []

    def fake_render(name, draft=False, music=None):
        rendered.append(draft)
        return {"version": len(rendered), "output": "output/v1/x.mp4", "contact_sheet": "output/v1/contact.jpg",
                "duration": 1.0, "size_bytes": 1}
    monkeypatch.setattr(P.R, "render", fake_render)

    for n in (1, 2):
        pid = planned(client, media)
        tl_ = client.get(f"/projects/{pid}/timeline").json()["timeline"]
        assert tl_["text"][0]["on"] == "#1"                   # the mock brain's sticker on the hook
        tl_["text"] = []
        assert client.put(f"/projects/{pid}/timeline", json=tl_).status_code == 200
        # a draft render is only a check: nothing is learned
        client.post(f"/projects/{pid}/render", json={"draft": True}, params={"wait": "true"})
        if n == 1:
            assert learn.load("photo-dump").prefs == []
        r = client.post(f"/projects/{pid}/render", json={}, params={"wait": "true"})
        assert r.json()["status"] == "done", r.text
        p = learn.load("photo-dump").get("text.none")
        assert p.count == n and p.projects[pid] == '"Lekki, 7PM"'
    assert p.status == "active"
    assert any("learned (photo-dump): Prefers no text on screen" in line for line in r.json()["log"])

    # the panel's controls
    r = client.patch("/learned/photo-dump/text.none", json={"enabled": False})
    assert r.status_code == 200 and r.json()["prefs"][0]["status"] == "off"
    assert client.delete("/learned/photo-dump/text.none").json()["prefs"] == []
    assert client.delete("/learned/photo-dump/text.none").status_code == 404
    assert client.get("/learned/..%2Fetc").status_code in (404, 405, 422)     # never reaches the filesystem
    assert client.get("/learned/Not a preset").status_code == 422


def follows_learned(req) -> str:
    """plan.build that does what the learned notes say: no text when "Prefers no text on screen" is in the prompt."""
    reply = json.loads(plan_reply(req))
    if "Prefers no text on screen" in req.prompt:
        reply["timeline"]["text"] = []
    return json.dumps(reply)


@pytest.fixture
def approve(client, monkeypatch):
    monkeypatch.setattr(P.R, "render", lambda name, draft=False, music=None: {
        "version": 1, "output": "o.mp4", "contact_sheet": "c.jpg", "duration": 1.0, "size_bytes": 1})

    def go(pid: str) -> None:
        r = client.post(f"/projects/{pid}/render", json={}, params={"wait": "true"})
        assert r.json()["status"] == "done", r.text
    return go


def drop_text(client, pid: str) -> None:
    tl_ = client.get(f"/projects/{pid}/timeline").json()["timeline"]
    tl_["text"] = []
    assert client.put(f"/projects/{pid}/timeline", json=tl_).status_code == 200


NO_TEXT = edit("text.none", "text", "Prefers no text on screen beyond what the brief asks for")


def test_reapproving_an_unchanged_video_keeps_the_count(client, mock_brain, media, approve) -> None:
    first = planned(client, media)
    drop_text(client, first)
    approve(first)
    approve(first)                                  # approved again, nothing changed
    assert learn.load("photo-dump").get("text.none").count == 1
    second = planned(client, media)
    drop_text(client, second)
    approve(second)
    assert learn.load("photo-dump").get("text.none").status == "active"
    # the first video is planned again from scratch: Claude now follows the note, so there's nothing to change
    mock_brain.handlers["plan.build"] = follows_learned
    assert client.post(f"/projects/{first}/plan", params={"wait": "true"}).json()["status"] == "done"
    assert client.get(f"/projects/{first}/timeline").json()["timeline"]["text"] == []
    approve(first)
    approve(first)
    p = learn.load("photo-dump").get("text.none")
    assert (p.count, p.status, p.enabled) == (2, "active", True) and set(p.projects) == {first, second}


def test_an_applied_preference_does_not_confirm_itself(client, mock_brain, media, approve) -> None:
    seed("photo-dump", NO_TEXT)
    mock_brain.handlers["plan.build"] = follows_learned
    pid = planned(client, media)
    assert json.loads((client.svc.store.dir(pid) / "work" / "plan_changes.json").read_text())["learned"] == \
        ["text.none"]                               # it was applied ...
    assert client.get(f"/projects/{pid}/timeline").json()["timeline"]["text"] == []
    for _ in range(3):
        approve(pid)                                # ... and kept, which is not a sighting
    p = learn.load("photo-dump").get("text.none")
    assert p.count == 2 and pid not in p.projects and p.status == "active"


def test_editing_against_an_applied_preference_counts_against_it(client, mock_brain, media, approve) -> None:
    seed("photo-dump", NO_TEXT)
    mock_brain.handlers["plan.build"] = follows_learned
    pid = planned(client, media)
    tl_ = client.get(f"/projects/{pid}/timeline").json()["timeline"]
    tl_["text"] = [{"text": "Lekki, 7PM", "style": "sticker", "on": "#1"}]     # the creator puts a title back
    assert client.put(f"/projects/{pid}/timeline", json=tl_).status_code == 200
    approve(pid)
    p = learn.load("photo-dump").get("text.none")
    assert (p.count, p.status) == (1, "pending") and p.against == {pid: '"Lekki, 7PM"'}
    assert learn.load("photo-dump").get("text.title-on-hook").count == 1
    items = learn.for_project("photo-dump", BriefData()).items
    assert "Prefers no text" not in learn.prompt_text(items)        # not applied to the next plan any more


def test_undoing_your_own_edit_before_approving_again(client, mock_brain, media, approve) -> None:
    pid = planned(client, media)
    original = client.get(f"/projects/{pid}/timeline").json()["timeline"]
    drop_text(client, pid)
    approve(pid)
    assert learn.load("photo-dump").get("text.none").count == 1
    assert client.put(f"/projects/{pid}/timeline", json=original).status_code == 200    # changed my mind
    approve(pid)
    assert learn.load("photo-dump").prefs == []


def test_hand_edits_survive_a_revision(client, mock_brain, media, monkeypatch) -> None:
    monkeypatch.setattr(P.R, "render", lambda name, draft=False, music=None: {
        "version": 1, "output": "o.mp4", "contact_sheet": "c.jpg", "duration": 1.0, "size_bytes": 1})
    pid = planned(client, media)
    tl_ = client.get(f"/projects/{pid}/timeline").json()["timeline"]
    tl_["segments"].pop()
    assert client.put(f"/projects/{pid}/timeline", json=tl_).status_code == 200
    # Claude revises (its own changes are not the creator's), then the creator approves
    assert client.post(f"/projects/{pid}/revise", json={"notes": "8PM"}, params={"wait": "true"}).json()["status"] \
        == "done"
    client.post(f"/projects/{pid}/render", json={}, params={"wait": "true"})
    got = {p.key for p in learn.load("photo-dump").prefs}
    assert "shots.drop-closing-clip" in got and not any(k.startswith("text.") for k in got)
    proposed = json.loads((client.svc.store.dir(pid) / "work" / "learn" / "proposed.json").read_text())
    assert proposed["text"][0]["text"] == "Lekki, 8PM"


# ---------------------------------------------------------------- the plan screen's edits (lib/timeline-edit.ts)

def test_plan_screen_edits_stay_renderable_and_are_learned(client, media, approve) -> None:
    """Each edit the plan screen makes, in the shape it saves it: the save runs the pre-render check, a broken one is
    refused, and approving the edited plan turns each kind of edit into a note."""
    from engine import edl as E
    pid = planned(client, media)
    view = client.get(f"/projects/{pid}/timeline").json()
    tl_ = view["timeline"]
    a, b = tl_["segments"][0], tl_["segments"][1]

    def put(t):
        return client.put(f"/projects/{pid}/timeline", json=t)

    # trim (trimShot) and length in seconds (setDuration)
    a.update({"in": 0.2, "out": 1.0})
    for k in ("dur", "beats", "to"):
        a.pop(k, None)
    for k in ("out", "beats", "to"):
        b.pop(k, None)
    left = 3.0 - b.get("in", 0)                     # the editor only allows what's left of the 3 s clip
    b["dur"] = round(left - 0.1, 2)
    # text on a shot (addText), captions off on a part (setCaptions), the end card the other way (setEndCard)
    b["label"] = "shot-2"
    tl_["text"].append({"text": "Street walk", "style": "label", "on": "shot-2"})
    a["captions"] = False
    had_card = view["end_card"] is not None
    tl_["end_card"] = {"enabled": not had_card}
    r = put(tl_)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["problems"] == [] and (saved["end_card"] is not None) is (not had_card)
    assert [round(s["duration"], 2) for s in saved["shots"]][:2] == [0.8, b["dur"]]
    assert any(o["kind"] == "text" and o["text"] == "Street walk" for o in saved["overlays"])
    with client.svc.store.context(pid) as cwd:
        assert E.validate(json.loads((cwd / "work" / "edl.json").read_text())) == []    # what render checks first

    # what the editor refuses is refused by the server too (nothing is saved)
    bad = json.loads(json.dumps(tl_))
    bad["segments"][0]["out"] = 9.0                 # the clip is 3 s long
    r = put(bad)
    assert r.status_code == 422 and "past end" in r.text
    bad["segments"][0].update({"in": 1.0, "out": 0.5})
    assert put(bad).status_code == 422
    bad = json.loads(json.dumps(tl_))
    bad["text"][-1]["on"] = "no-such-shot"
    assert put(bad).status_code == 422
    assert client.get(f"/projects/{pid}/timeline").json()["timeline"]["segments"][0]["out"] == 1.0

    approve(pid)
    got = {p.key for p in learn.load("photo-dump").prefs}
    assert ("end_card.on" if not had_card else "end_card.off") in got
    assert "captions.off-hook" in got and "text.add-label" in got
    assert not any(k.startswith(("hook.", "order.")) for k in got), got     # a trim isn't a new hook or a move


def test_trimming_a_shot_is_not_read_as_a_new_hook() -> None:
    """The first shot and a later one come from the same clip; trimming the first to start near the other's moment
    is still a trim of the first shot."""
    p = tl([{"src": B, "in": 2.2}, {"src": A, "in": 2.4}, {"src": B, "in": 0.4}])
    f = tl([{"src": B, "in": 0.2, "out": 1.0}, {"src": A, "in": 2.4}, {"src": B, "in": 0.4}])
    edits = diff(p, f, fake_view(p, [2.0, 2.0, 2.0]), fake_view(f, [0.8, 2.0, 2.0]))
    assert keys(edits) == {"timing.intro-shorter"}
    # a real reorder of the same clip's shots is still a move
    moved = tl([{"src": A, "in": 2.4}, {"src": B, "in": 2.2}, {"src": B, "in": 0.4}])
    assert "hook.b-roll" not in keys(diff(p, moved)) and any(k.startswith("hook.") for k in keys(diff(p, moved)))
