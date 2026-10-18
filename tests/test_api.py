"""The HTTP API with a mocked brain: projects, files, config, errors, streaming, jobs + WebSocket."""
from __future__ import annotations

import io
import json
import time

import pytest
from conftest import MockBrain, analyse_reply
from fastapi.testclient import TestClient

from engine.brain import BrainError
from engine.project import ProjectStore
from server.app import create_app
from server.deps import Services
from server.jobs import JobManager


@pytest.fixture
def client(mock_brain: MockBrain, cutroom_paths):
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: mock_brain)
    with TestClient(create_app(svc)) as c:
        c.brain = mock_brain           # type: ignore[attr-defined]
        yield c


def new_project(client: TestClient, **brief) -> str:
    r = client.post("/projects", json={"name": "Lekki dump", "brief": {"content_type": "photo-dump",
                                                                        "talking": "no", "idea": "a night out",
                                                                        **brief}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client: TestClient, pid: str, path, kind: str | None = None, name: str | None = None):
    data = {"kind": kind} if kind else {}
    with open(path, "rb") as f:
        return client.post(f"/projects/{pid}/files", data=data, files=[("files", (name or path.name, f))])


def test_project_crud(client: TestClient) -> None:
    pid = new_project(client)
    assert pid.startswith("lekki-dump-")
    assert [p["id"] for p in client.get("/projects").json()] == [pid]
    r = client.patch(f"/projects/{pid}", json={"name": "Lekki night", "brief": {"track": "beat.wav"},
                                               "answers": {"music-track": "beat.wav"}})
    body = r.json()
    assert body["name"] == "Lekki night" and body["brief"]["track"] == "beat.wav"
    assert body["brief"]["content_type"] == "photo-dump" and body["answers"] == {"music-track": "beat.wav"}
    r = client.patch(f"/projects/{pid}", json={"brief": {"colour": "red"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_brief"
    assert client.delete(f"/projects/{pid}").status_code == 204
    r = client.get(f"/projects/{pid}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "project_not_found"


def test_import_markdown_brief(client: TestClient, cutroom_paths, media) -> None:
    import shutil
    root = cutroom_paths.root
    shutil.copy(media["clip_a"], root / "raw" / "intro.mp4")
    (root / "raw" / "shoot").mkdir()
    shutil.copy(media["photo"], root / "raw" / "shoot" / "a.jpg")
    shutil.copy(media["music"], root / "music" / "beat.wav")
    (root / "briefs" / "night.md").write_text(
        "# Video Brief: Night out\n## Basics\n- Content type: photo-dump\n- Talking in this video?: no\n"
        "## The idea\nfun\n## Clips & order\n1. raw/intro.mp4 0:00.5-0:02.5 2. raw/shoot/\n"
        "## Music & sound\n- Track: beat.wav\n")
    r = client.post("/projects/import", json={"path": "briefs/night.md"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["name"] == "Night out" and p["brief"]["track"] == "beat.wav"
    kinds = [(f["kind"], f["path"], f["trim_in"]) for f in p["files"]]
    assert kinds == [("clip", "inputs/clips/intro.mp4", 0.5), ("photo", "inputs/clips/shoot/a.jpg", None),
                     ("music", "inputs/music/beat.wav", None)]
    assert client.post("/projects/import", json={"path": "../etc/passwd.md"}).status_code == 422


def test_file_upload_list_reorder_rename_delete(client: TestClient, media) -> None:
    pid = new_project(client)
    r = upload(client, pid, media["clip_a"])
    assert r.status_code == 201, r.text
    clip = r.json()[0]
    assert clip["kind"] == "clip" and clip["duration"] == pytest.approx(3.0, abs=0.1) and "vertical" in clip["info"]
    photo = upload(client, pid, media["photo"]).json()[0]
    music = upload(client, pid, media["music"], kind="music").json()[0]
    assert photo["kind"] == "photo" and music["path"] == "inputs/music/beat.wav"
    ids = [f["id"] for f in client.get(f"/projects/{pid}/files").json()]
    assert ids == [clip["id"], photo["id"], music["id"]]
    r = client.patch(f"/projects/{pid}/files", json={"order": [photo["id"], clip["id"], music["id"]]})
    assert [f["id"] for f in r.json()] == [photo["id"], clip["id"], music["id"]]
    r = client.patch(f"/projects/{pid}/files/{clip['id']}", json={"name": "squats", "trim_in": 0.5, "trim_out": 2})
    assert r.json()["name"] == "squats.mp4" and r.json()["path"] == "inputs/clips/squats.mp4"
    assert client.patch(f"/projects/{pid}/files/{clip['id']}", json={"trim_in": 3, "trim_out": 1}).status_code == 422
    assert client.delete(f"/projects/{pid}/files/{photo['id']}").status_code == 204
    assert len(client.get(f"/projects/{pid}/files").json()) == 2


def test_upload_errors_are_clear(client: TestClient, media) -> None:
    pid = new_project(client)
    r = client.post(f"/projects/{pid}/files", files=[("files", ("notes.pdf", io.BytesIO(b"%PDF"), "application/pdf"))])
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file"
    assert ".mp4" in r.json()["error"]["hint"]
    r = upload(client, pid, media["music"])                      # audio, but voiceover or music?
    assert r.status_code == 422 and r.json()["error"]["code"] == "audio_kind_needed"
    broken = ("broken.mp4", io.BytesIO(b"not a video"), "video/mp4")
    r = client.post(f"/projects/{pid}/files", files=[("files", broken)])
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_media"
    assert client.get(f"/projects/{pid}/files").json() == []     # nothing half-saved


def test_range_requests_and_thumbnails(client: TestClient, media) -> None:
    pid = new_project(client)
    clip = upload(client, pid, media["clip_a"]).json()[0]
    photo = upload(client, pid, media["photo"]).json()[0]
    r = client.get(f"/projects/{pid}/files/{clip['id']}/content", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert r.headers["content-range"].startswith("bytes 0-99/")
    assert client.get(f"/projects/{pid}/files/{clip['id']}/content").headers["accept-ranges"] == "bytes"
    for f in (clip, photo):
        r = client.get("/media/thumbnail", params={"path": f"{pid}/{f['path']}", "w": 160})
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    r = client.get("/media/file", params={"path": f"{pid}/{clip['path']}"}, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and len(r.content) == 10
    assert client.get("/media/file", params={"path": "../../etc/hosts"}).status_code == 403
    assert client.get("/media/thumbnail", params={"path": f"{pid}/nope.mp4"}).status_code == 404


def test_presets_settings_and_status(client: TestClient) -> None:
    presets = client.get("/presets").json()
    assert {"photo-dump", "gym-vlog"} <= {p["name"] for p in presets}
    assert client.get("/presets/gym-vlog").json()["settings"]["text_style"] == "timestamp"
    r = client.put("/presets/gym-vlog", json={"settings": {"beat_every": 4}})
    assert r.json()["settings"]["beat_every"] == 4
    assert client.put("/presets/gym-vlog", json={"settings": {"nope": 1}}).status_code == 422
    s = client.get("/settings").json()
    assert s["brand"]["handle"].startswith("@") and s["app"]["brain_backend"] == "claude-code"
    assert "Inter" in s["fonts_available"]
    r = client.put("/settings", json={"brand": {"handle": "@tega", "emphasis_color": "#00FF88"},
                                      "app": {"brain_timeout_s": 200}})
    assert r.json()["brand"]["handle"] == "@tega" and r.json()["app"]["brain_timeout_s"] == 200
    assert client.put("/settings", json={"brand": {"emphasis_color": "green"}}).status_code == 422
    st = client.get("/system/status", params={"claude": "false"}).json()
    ids = {c["id"] for c in st["checks"]}
    assert {"ffmpeg", "ffprobe", "node", "python", "whisper_model", "fonts"} <= ids
    assert next(c for c in st["checks"] if c["id"] == "ffmpeg")["ok"] is True


def test_analyse_returns_questions(client: TestClient, media) -> None:
    pid = new_project(client)
    upload(client, pid, media["clip_a"])
    r = client.post(f"/projects/{pid}/analyse", params={"wait": "true"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done" and job["progress"] == 100
    assert job["result"]["questions"][0]["id"] == "music-track" and job["result"]["ready"] is False
    assert any("cut to the beat" in g for g in [client.brain.calls[0].prompt])   # gaps reach the brain
    p = client.get(f"/projects/{pid}").json()
    assert p["status"] == "analysed" and p["questions"][0]["field"] == "track"
    assert "brain brief.analyse [mock" in client.get(f"/projects/{pid}/log").text


def test_brain_errors_surface_through_the_api(client: TestClient, media) -> None:
    def limit(_):
        raise BrainError("Claude usage limit reached (resets Mon 14:00).", code="usage_limit", status=429,
                         hint="Wait for your Claude usage limit to reset")
    client.brain.handlers["brief.analyse"] = limit
    pid = new_project(client)
    r = client.post(f"/projects/{pid}/analyse", params={"wait": "true"})
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "usage_limit" and "resets" in err["message"] and err["hint"]
    assert r.json()["job"]["status"] == "failed"
    p = client.get(f"/projects/{pid}").json()
    assert p["status"] == "error" and p["last_error"]["code"] == "usage_limit"


def test_background_job_and_websocket_progress(client: TestClient, media) -> None:
    def slow(r):
        time.sleep(0.4)
        return analyse_reply(r)
    client.brain.handlers["brief.analyse"] = slow
    pid = new_project(client)
    r = client.post(f"/projects/{pid}/analyse")
    assert r.status_code == 202
    job_id = r.json()["id"]
    events = []
    with client.websocket_connect(f"/ws/jobs/{job_id}") as ws:
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] in ("result", "error") or (ev["type"] == "snapshot" and ev["job"]["status"] == "done"):
                break
    kinds = [e["type"] for e in events]
    assert kinds[0] == "snapshot" and kinds[-1] == "result"        # the brain takes 0.4 s: events stream live
    assert "step" in kinds and "log" in kinds and "status" in kinds
    assert events[-1]["job"]["status"] == "done"
    assert any(e.get("type") == "step" and e.get("progress", 0) > 0 for e in events)
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "done" and any("brain: brief.analyse" in line for line in job["log"])
    assert client.get("/jobs", params={"project_id": pid}).json()[0]["id"] == job_id
    with client.websocket_connect("/ws/jobs/nope") as ws:
        assert ws.receive_json()["error"]["code"] == "job_not_found"


def test_jobs_survive_a_restart_and_interrupted_ones_can_be_retried(client: TestClient, media, cutroom_paths) -> None:
    pid = new_project(client)
    upload(client, pid, media["clip_a"])
    done = client.post(f"/projects/{pid}/analyse", params={"wait": "true"}).json()
    f = cutroom_paths.workspace / pid / "work" / "jobs.json"
    saved = json.loads(f.read_text())
    assert [(j["id"], j["status"]) for j in saved] == [(done["id"], "done")]
    assert any("brain: brief.analyse" in line for line in saved[0]["log"])
    base = {**saved[0], "result": None, "finished_at": None, "log": []}
    saved += [{**base, "id": "aaaaaaaaaaaa", "kind": "render", "queue": "render", "status": "running",   # was busy
               "params": {"draft": True}},
              {**base, "id": "bbbbbbbbbbbb", "status": "queued", "started_at": None}]                  # was waiting
    f.write_text(json.dumps(saved))
    client.post("/projects", json={"name": "Elsewhere"})

    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: client.brain)
    with TestClient(create_app(svc)) as c:                      # the server starts again
        jobs = {j["id"]: j for j in c.get("/jobs", params={"project_id": pid}).json()}
        assert jobs[done["id"]]["status"] == "done" and jobs[done["id"]]["result"]["questions"]
        render, queued = jobs["aaaaaaaaaaaa"], jobs["bbbbbbbbbbbb"]
        assert render["status"] == queued["status"] == "interrupted" and render["finished_at"]
        assert "while this job was running" in render["error"]["message"] and render["params"] == {"draft": True}
        assert "before this job started" in queued["error"]["message"]
        p = c.get(f"/projects/{pid}").json()
        assert p["status"] == "error" and p["last_error"]["code"] == "interrupted"
        assert {j["id"]: j["status"] for j in json.loads(f.read_text())}["aaaaaaaaaaaa"] == "interrupted"

        r = c.post(f"/jobs/{done['id']}/retry")
        assert r.status_code == 409 and r.json()["error"]["code"] == "job_not_retryable"
        r = c.post("/jobs/bbbbbbbbbbbb/retry")
        assert r.status_code == 202 and r.json()["retry_of"] == "bbbbbbbbbbbb" and r.json()["kind"] == "analyse"
        assert svc.jobs.get(r.json()["id"]).status in ("queued", "running", "done")
        import asyncio
        again = asyncio.run(svc.jobs.wait(r.json()["id"]))
        assert again.status == "done" and c.get(f"/projects/{pid}").json()["status"] == "analysed"


def test_render_and_plan_need_their_inputs(client: TestClient) -> None:
    pid = new_project(client)
    r = client.post(f"/projects/{pid}/render")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_plan"
    r = client.post(f"/projects/{pid}/plan", params={"wait": "true"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_clips"
    assert client.get(f"/projects/{pid}/timeline").status_code == 404
    assert json.loads(client.get(f"/projects/{pid}/outputs").text) == []
