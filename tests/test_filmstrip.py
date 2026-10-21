"""The visual trimmer's filmstrip endpoint: frames sampled across a clip, built in the background, cached in the
project and served through /media/file. ffmpeg's frame extraction is mocked (ffprobe is real); the brain is mocked."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import MockBrain
from fastapi.testclient import TestClient

from engine import filmstrip as F
from engine.project import ProjectStore
from server.app import create_app
from server.deps import Services
from server.jobs import JobManager


@pytest.fixture
def client(mock_brain: MockBrain, cutroom_paths):
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: mock_brain)
    with TestClient(create_app(svc)) as c:
        c.svc = svc                 # type: ignore[attr-defined]
        yield c


@pytest.fixture
def ffmpeg(monkeypatch):
    """Fake frame extraction: writes as many tiny JPEGs as -frames:v asks for. calls: each ffmpeg command."""
    class Calls(list):
        pass
    calls = Calls()
    fail = calls.fail = {"on": False}     # type: ignore[attr-defined]

    def fake_run(cmd, **_):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        if fail["on"]:
            raise F.EngineError("ffmpeg exploded")
        n = int(cmd[cmd.index("-frames:v") + 1])
        pattern = Path(cmd[-1])
        for i in range(1, n + 1):
            (pattern.parent / (pattern.name % i)).write_bytes(b"\xff\xd8\xff\xd9")
    monkeypatch.setattr(F, "run", fake_run)
    return calls


def project(client: TestClient, media) -> str:
    pid = client.post("/projects", json={"name": "Strip", "brief": {"content_type": "photo-dump"}}).json()["id"]
    for key in ("clip_a", "photo"):
        with open(media[key], "rb") as f:
            client.post(f"/projects/{pid}/files", files=[("files", (media[key].name, f))])
    return pid


def clip_src(client, pid) -> str:
    return next(f["path"] for f in client.get(f"/projects/{pid}").json()["files"] if f["kind"] == "clip")


def poll(client, pid, src, **params):
    for _ in range(100):
        r = client.get(f"/projects/{pid}/filmstrip", params={"src": src, **params})
        if r.json()["status"] != "building":
            return r
        time.sleep(0.02)
    raise AssertionError("never finished building")


def test_built_in_the_background_then_cached(client, media, ffmpeg) -> None:
    pid = project(client, media)
    src = clip_src(client, pid)
    first = client.get(f"/projects/{pid}/filmstrip", params={"src": src})
    assert first.status_code == 200 and first.json()["status"] in ("building", "ready")
    body = poll(client, pid, src).json()
    assert body["status"] == "ready" and body["duration"] == pytest.approx(3.0, abs=0.1)
    # a 3 s clip: one frame per 0.5 s would be 6, the minimum is 8; evenly from the start
    ts = [f["t"] for f in body["frames"]]
    assert len(ts) == 8 and ts[0] == 0 and all(b > a for a, b in zip(ts, ts[1:])) and ts[-1] < body["duration"]
    assert ts[1] == pytest.approx(body["duration"] / 8, abs=0.01)
    assert len(ffmpeg) == 1 and "fps=" in " ".join(ffmpeg[0])
    # the frames come from the range-enabled file route
    path = body["frames"][3]["path"]
    assert path.startswith(f"{pid}/work/_cache/filmstrip/")
    r = client.get("/media/file", params={"path": path}, headers={"Range": "bytes=0-1"})
    assert r.status_code == 206 and r.content == b"\xff\xd8"
    # re-opening is instant: no second ffmpeg run
    for _ in range(3):
        assert client.get(f"/projects/{pid}/filmstrip", params={"src": src}).json()["status"] == "ready"
    assert len(ffmpeg) == 1
    # another count is another strip
    assert len(poll(client, pid, src, count=12).json()["frames"]) == 12


def test_refuses_what_isnt_a_clip_in_the_project(client, media, ffmpeg) -> None:
    pid = project(client, media)
    other = project(client, media)
    photo = next(f["path"] for f in client.get(f"/projects/{pid}").json()["files"] if f["kind"] == "photo")
    get = lambda src: client.get(f"/projects/{pid}/filmstrip", params={"src": src})  # noqa: E731
    assert get(f"../{other}/{clip_src(client, other)}").status_code == 403
    assert get("/etc/passwd").status_code == 403
    assert get("inputs/clips/nope.mp4").status_code == 404
    assert get(photo).status_code == 415
    assert client.get("/projects/nope/filmstrip", params={"src": "x.mp4"}).status_code == 404
    assert client.get(f"/projects/{pid}/filmstrip", params={"src": clip_src(client, pid), "count": 500}).status_code \
        == 422
    assert ffmpeg == []


def test_a_failed_build_says_so_and_can_be_retried(client, media, ffmpeg) -> None:
    pid = project(client, media)
    src = clip_src(client, pid)
    ffmpeg.fail["on"] = True
    body = poll(client, pid, src).json()
    assert body["status"] == "failed" and "ffmpeg exploded" in body["error"]
    ffmpeg.fail["on"] = False
    r = client.get(f"/projects/{pid}/filmstrip", params={"src": src, "wait": "true"})
    assert r.json()["status"] == "ready" and len(r.json()["frames"]) == 8


def test_cleaned_up_with_the_project(client, media, ffmpeg) -> None:
    pid = project(client, media)
    poll(client, pid, clip_src(client, pid))
    cache = client.svc.store.dir(pid) / "work" / "_cache" / "filmstrip"
    assert any(cache.iterdir())
    assert client.delete(f"/projects/{pid}").status_code in (200, 204)
    assert not cache.exists()


def test_the_plan_view_has_the_beats_to_snap_to(client, media) -> None:
    pid = client.post("/projects", json={"name": "Dump", "brief": {"content_type": "photo-dump", "talking": "no",
                                                                   "idea": "a night out"}}).json()["id"]
    for key, kind in (("clip_a", None), ("clip_b", None), ("music", "music")):
        with open(media[key], "rb") as f:
            client.post(f"/projects/{pid}/files", data={"kind": kind} if kind else {},
                        files=[("files", (media[key].name, f))])
    assert client.post(f"/projects/{pid}/plan", params={"wait": "true"}).json()["status"] == "done"
    music = client.get(f"/projects/{pid}/timeline").json()["music"]
    beats = music["beats"]
    assert music["beat_cut"] is True                    # photo-dump cuts on the beat
    assert len(beats) > 4 and all(b > a for a, b in zip(beats, beats[1:]))
    assert beats[1] - beats[0] == pytest.approx(60 / music["bpm"], abs=0.02)
