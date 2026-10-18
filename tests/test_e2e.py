"""Full run on tiny generated media, through the API, with a mocked brain:
create -> upload -> plan -> edit the plan -> render -> revise -> render again -> stream the result."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from engine.common import ffprobe
from engine.project import ProjectStore
from server.app import create_app
from server.deps import Services
from server.jobs import JobManager


@pytest.mark.slow
def test_plan_render_revise_end_to_end(mock_brain, cutroom_paths, media) -> None:
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: mock_brain)
    with TestClient(create_app(svc)) as c:
        pid = c.post("/projects", json={"name": "E2E dump", "brief": {
            "content_type": "photo-dump", "talking": "no", "idea": "gym then a walk", "target_length": "4s",
            "beat_sync": "every 2 beats", "labels": "Lekki, 7PM"}}).json()["id"]
        for key, kind in (("clip_a", None), ("clip_b", None), ("photo", None), ("music", "music")):
            with open(media[key], "rb") as f:
                r = c.post(f"/projects/{pid}/files", data={"kind": kind} if kind else {},
                           files=[("files", (media[key].name, f))])
            assert r.status_code == 201, r.text

        # plan: draft by the pipeline, final call by the (mock) brain
        r = c.post(f"/projects/{pid}/plan", params={"wait": "true"})
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["status"] == "done", job
        view = job["result"]
        assert view["problems"] == [] or all("start moved" in p for p in view["problems"])
        assert len(view["shots"]) == 3 and view["duration"] > 1
        assert view["shots"][0]["reason"] == "strongest moment first"
        assert view["overlays"][0]["text"] == "Lekki, 7PM"
        assert view["music"]["bpm"] == pytest.approx(120, abs=6)
        assert all(s["beat_synced"] for s in view["shots"])
        prompt = mock_brain.calls[-1].prompt
        assert "## Transcripts" in prompt and "## DRAFT plan (JSON)" in prompt and "photo-dump" in prompt
        assert "inputs/clips/gym-squats.mp4" in prompt
        steps = [line for line in job["log"] if line.startswith("  brain:")]
        assert steps, job["log"]
        p = c.get(f"/projects/{pid}").json()
        assert p["status"] == "planned" and p["plan_version"] == 1 and p["plan_summary"]

        # the creator edits the plan: smaller frame for a quick test render, and a different sticker
        tl = c.get(f"/projects/{pid}/timeline").json()["timeline"]
        tl["style"].update({"width": 540, "height": 960})
        tl["text"][0]["text"] = "Lekki, 9PM"
        r = c.put(f"/projects/{pid}/timeline", json=tl)
        assert r.status_code == 200, r.text
        assert r.json()["overlays"][0]["text"] == "Lekki, 9PM"
        bad = json.loads(json.dumps(tl))
        bad["segments"][0]["src"] = "inputs/clips/not-uploaded.mp4"
        r = c.put(f"/projects/{pid}/timeline", json=bad)
        assert r.status_code == 422 and "not-uploaded" in r.json()["error"]["message"]

        # render (one at a time, background queue)
        r = c.post(f"/projects/{pid}/render", json={"draft": True}, params={"wait": "true"})
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert res["version"] == 1 and res["video"].endswith("_v1.mp4")
        video = cutroom_paths.workspace / pid / res["video"]
        info = ffprobe(video)
        assert (info["width"], info["height"]) == (540, 960)
        assert info["duration"] == pytest.approx(view["duration"], abs=0.15) and info["has_audio"]
        assert (cutroom_paths.workspace / pid / "output" / "v1" / "contact.jpg").exists()
        assert (cutroom_paths.workspace / pid / "output" / "v1" / "edl.json").exists()

        # revise with notes, then render v2
        r = c.post(f"/projects/{pid}/revise", json={"notes": "make the sticker say 8PM"}, params={"wait": "true"})
        assert r.status_code == 200, r.text
        assert r.json()["result"]["overlays"][0]["text"] == "Lekki, 8PM"
        assert "make the sticker say 8PM" in mock_brain.calls[-1].prompt
        assert c.get(f"/projects/{pid}").json()["plan_version"] == 3
        r = c.post(f"/projects/{pid}/render", json={"draft": True}, params={"wait": "true"})
        assert r.json()["result"]["version"] == 2

        outs = c.get(f"/projects/{pid}/outputs").json()
        assert [o["version"] for o in outs] == [2, 1]
        r = c.get(outs[0]["video_url"], headers={"Range": "bytes=0-1023"})
        assert r.status_code == 206 and len(r.content) == 1024 and r.headers["content-type"] == "video/mp4"
        assert c.get(outs[0]["contact_sheet_url"]).headers["content-type"] == "image/jpeg"
        p = c.get(f"/projects/{pid}").json()
        assert p["status"] == "rendered" and [x["version"] for x in p["renders"]] == [1, 2]
        log = c.get(f"/projects/{pid}/log").text
        assert "brain plan.build" in log and "brain revise" in log
