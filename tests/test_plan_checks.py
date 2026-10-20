"""A plan the renderer can't use is caught before rendering, with a message that names the item.

Regression: the brain added a sound effect as {"type": "camera-flash", "on": "hook"} (no file: the plan format never
showed what an sfx item is, and the brief asked for "a generic flash/shutter click sound"). It passed every check,
because an empty "src" resolves to the project folder, which exists, and the render died in the audio mix with
KeyError: 'src'."""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable

import pytest
from conftest import MockBrain, analyse_reply
from fastapi.testclient import TestClient
from test_api import upload

from engine import edl as E
from engine.config import project_layout, use_layout
from engine.project import ProjectStore
from server.app import create_app
from server.deps import Services
from server.jobs import JobManager

PHANTOM = {"type": "camera-flash", "on": "hook"}         # exactly what the brain wrote
SAYS = 'sound effect 1 ("camera-flash" on "hook") has no sound file ("src")'


def draft_of(prompt: str) -> dict:
    """The DRAFT plan in a plan.build prompt (a retry appends more after it)."""
    at = prompt.index("## DRAFT plan (JSON)\n") + len("## DRAFT plan (JSON)\n")
    return json.JSONDecoder().raw_decode(prompt[at:])[0]


def plan_with_sfx(sfx: list) -> Callable:
    def reply(req) -> str:
        tl = draft_of(req.prompt)
        tl["segments"][0]["label"] = "hook"
        tl["sfx"] = sfx
        return json.dumps({"timeline": tl, "summary": "A flash on the hook.",
                           "changes": ["camera-flash SFX on the hook"]})
    return reply


@pytest.fixture
def brain() -> MockBrain:
    return MockBrain({"brief.analyse": analyse_reply, "plan.build": plan_with_sfx([])})


@pytest.fixture
def client(brain: MockBrain, cutroom_paths):
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: brain)
    with TestClient(create_app(svc)) as c:
        yield c


def planned(client: TestClient, media) -> str:
    """A small BTS-style project with clips and a track, like the one that failed."""
    pid = client.post("/projects", json={"name": "Shoot BTS", "brief": {
        "content_type": "fashion-bts", "talking": "no", "idea": "raw BTS", "target_length": "4s",
        "sound_effects": "Add a generic flash/shutter click sound"}}).json()["id"]
    for key, kind in (("clip_a", None), ("clip_b", None), ("music", "music")):
        assert upload(client, pid, media[key], kind=kind).status_code == 201
    return pid


def saved_plan(cutroom_paths, pid: str, sfx: list) -> None:
    """Write the plan as the brain's (pre-fix) answer was saved: a labelled hook and the given sound effects."""
    f = cutroom_paths.workspace / pid / "work" / "edl.json"
    edl = json.loads(f.read_text())
    edl["segments"][0]["label"] = "hook"
    edl["sfx"] = sfx
    f.write_text(json.dumps(edl))


def test_every_item_without_a_file_is_named(cutroom_paths, media) -> None:
    root = cutroom_paths.root
    shutil.copy(media["clip_a"], root / "raw" / "a.mp4")
    shutil.copy(media["music"], root / "voiceover" / "vo.wav")
    with use_layout(project_layout(root)):
        ok = {"segments": [{"src": "raw/a.mp4", "in": 0, "out": 2, "label": "hook"}]}
        assert E.validate(ok) == []
        assert E.validate({**ok, "sfx": [{"src": "assets/sfx/click.wav", "on": "hook"}]}) == []
        problems = E.validate({
            "segments": [{"src": "raw/a.mp4", "in": 0, "out": 2, "label": "hook"}, {"in": 1, "out": 2},
                         {"type": "vo", "src": "voiceover/vo.wav", "keep": [{"in": 0.5}],
                          "shots": [{"src": "raw/a.mp4"}]}],
            "sfx": [PHANTOM, {"src": "", "at": 1.5}, {"src": "assets/sfx/shutter.wav", "cue": "flash"}],
            "sfx_on_cuts": {"gain_db": -8},
            "graphics": [{"at": 2}],
            "broll": [{"in": 1, "cue": "protein"}],
        })
    assert 'segment #2 has no file ("src")' in problems
    assert 'segment #3 keep 1: needs "in" and "out"' in problems
    assert any(p.startswith(SAYS + ": use one of assets/sfx/bass_hit.wav, assets/sfx/click.wav") for p in problems)
    assert any(p.startswith('sound effect 2 at 1.5s has no sound file ("src")') for p in problems)
    assert 'sound effect 3 at "flash": file not found: assets/sfx/shutter.wav' in problems
    assert any(p.startswith('the sound on every cut ("sfx_on_cuts") has no sound file') for p in problems)
    assert 'graphic 1 at 2s has no file ("src")' in problems
    assert 'b-roll 1 at "protein" has no file ("src")' in problems


def test_render_stops_before_any_work_with_a_plain_message(client: TestClient, media, cutroom_paths) -> None:
    pid = planned(client, media)
    assert client.post(f"/projects/{pid}/plan", params={"wait": "true"}).json()["status"] == "done"
    saved_plan(cutroom_paths, pid, [PHANTOM])           # the plan as it was saved before the fix
    r = client.post(f"/projects/{pid}/render", json={"draft": True}, params={"wait": "true"})
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "invalid_plan" and "KeyError" not in err["message"]
    assert err["message"].startswith("This plan can't be rendered yet:\n  - " + SAYS)
    assert "assets/sfx/click.wav" in err["message"] and err["hint"]
    assert not list((cutroom_paths.workspace / pid / "work").glob("segments/*"))      # no shot was rendered
    p = client.get(f"/projects/{pid}").json()
    assert p["status"] == "error" and p["last_error"]["code"] == "invalid_plan"


def test_the_plan_screen_keeps_the_plan_and_says_what_to_fix(client: TestClient, media, cutroom_paths) -> None:
    pid = planned(client, media)
    assert client.post(f"/projects/{pid}/plan", params={"wait": "true"}).json()["status"] == "done"
    saved_plan(cutroom_paths, pid, [PHANTOM])
    view = client.get(f"/projects/{pid}/timeline").json()
    assert view["shots"] and view["duration"] > 0                  # still laid out...
    assert any(p.startswith(SAYS) for p in view["problems"])      # ...with what's wrong

    # a manual save with the phantom is refused; with a real sound it saves and the problem is gone
    tl = view["timeline"]
    r = client.put(f"/projects/{pid}/timeline", json=tl)
    assert r.status_code == 422 and SAYS in r.json()["error"]["message"]
    tl["sfx"] = [{"src": "assets/sfx/click.wav", "on": "hook"}]
    r = client.put(f"/projects/{pid}/timeline", json=tl)
    assert r.status_code == 200, r.text
    assert not any("sound effect" in p for p in r.json()["problems"])


def test_the_brain_knows_the_sounds_and_its_phantom_is_sent_back(client: TestClient, brain: MockBrain, media,
                                                                   cutroom_paths) -> None:
    def first_phantom_then_click(req) -> str:
        fixed = "has no sound file" in req.prompt
        return plan_with_sfx([{"src": "assets/sfx/click.wav", "on": "hook"} if fixed else PHANTOM])(req)
    brain.handlers["plan.build"] = first_phantom_then_click

    pid = planned(client, media)
    r = client.post(f"/projects/{pid}/plan", params={"wait": "true"})
    assert r.status_code == 200 and r.json()["status"] == "done", r.text
    calls = [c for c in brain.calls if c.purpose == "plan.build"]
    assert len(calls) == 2
    first, retry = calls
    assert "## Sound effects (for \"sfx\")\n- assets/sfx/bass_hit.wav" in first.prompt
    assert "assets/sfx/click.wav: short dry click: a camera shutter" in first.prompt
    assert re.search(r'every `sfx` item needs `"src"`', first.system)
    assert SAYS in retry.prompt
    edl = json.loads((cutroom_paths.workspace / pid / "work" / "edl.json").read_text())
    assert edl["sfx"] == [{"src": "assets/sfx/click.wav", "on": "hook"}]


@pytest.mark.slow
def test_a_kit_sound_on_the_hook_renders(client: TestClient, brain: MockBrain, media) -> None:
    brain.handlers["plan.build"] = plan_with_sfx([{"src": "assets/sfx/click.wav", "on": "hook"}])
    pid = planned(client, media)
    assert client.post(f"/projects/{pid}/plan", params={"wait": "true"}).json()["status"] == "done"
    tl = client.get(f"/projects/{pid}/timeline").json()["timeline"]
    tl["style"].update({"width": 540, "height": 960})
    assert client.put(f"/projects/{pid}/timeline", json=tl).status_code == 200
    r = client.post(f"/projects/{pid}/render", json={"draft": True}, params={"wait": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["audio"]["sfx"] == 1
