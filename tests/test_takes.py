"""Voiceovers recorded in the app: browser recordings converted to .wav on upload, takes kept until one is used, and a
used take treated exactly like an imported voice memo downstream."""
from __future__ import annotations

import subprocess
from pathlib import Path

import media_factory
import pytest
from fastapi.testclient import TestClient
from test_api import client, new_project, upload  # noqa: F401

from engine import pipeline, voice
from engine.common import ffprobe, style_for
from engine.project import ProjectStore


@pytest.fixture(scope="module")
def takes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("takes")
    return {f: media_factory.recording(d / f"take.{f}", fmt=f) for f in ("webm", "ogg", "mp4")}


def record(client: TestClient, pid: str, path: Path, name: str | None = None):  # noqa: F811
    with open(path, "rb") as f:
        return client.post(f"/projects/{pid}/takes", files=[("file", (name or path.name, f))])


@pytest.mark.parametrize("fmt", ["webm", "ogg", "mp4"])
def test_an_uploaded_browser_recording_is_converted_to_wav(client: TestClient, takes, cutroom_paths, fmt) -> None:  # noqa: F811
    pid = new_project(client)
    r = upload(client, pid, takes[fmt], kind="voiceover", name=f"take-1.{fmt}")
    assert r.status_code == 201, r.text
    [vo] = r.json()
    assert vo["kind"] == "voiceover" and vo["name"] == "take-1.wav" and vo["path"] == "inputs/voiceover/take-1.wav"
    d = cutroom_paths.workspace / pid / "inputs" / "voiceover"
    assert sorted(x.name for x in d.iterdir() if x.is_file()) == ["take-1.wav"]       # nothing else left behind
    info = ffprobe(d / "take-1.wav")
    assert (info["sample_rate"], info["channels"], info["has_video"]) == (48000, 1, False)
    assert vo["duration"] == pytest.approx(2.5, abs=0.1) and vo["has_audio"]


def test_a_bad_recording_is_refused_cleanly(client: TestClient, cutroom_paths, tmp_path) -> None:  # noqa: F811
    pid = new_project(client)
    junk = tmp_path / "take.webm"
    junk.write_bytes(b"\x1aE\xdf\xa3 not really a webm")
    r = upload(client, pid, junk, kind="voiceover")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_media"
    assert "can't read this recording" in r.json()["error"]["message"]
    assert not [x for x in (cutroom_paths.workspace / pid / "inputs" / "voiceover").iterdir() if x.is_file()]
    assert client.get(f"/projects/{pid}/files").json() == []


def test_takes_are_kept_until_one_is_used(client: TestClient, takes, cutroom_paths) -> None:  # noqa: F811
    pid = new_project(client)
    r = record(client, pid, takes["webm"])
    assert r.status_code == 201, r.text
    t1 = r.json()
    # remuxed, so the review player gets a duration and can seek (the recording itself has neither)
    assert t1["id"] == "take-1" and t1["path"] == "inputs/voiceover/takes/take-1.webm"
    assert t1["duration"] == pytest.approx(2.5, abs=0.1) and len(t1["peaks"]) == 120 and max(t1["peaks"]) == 1
    t2 = record(client, pid, takes["mp4"], name="take.mp4").json()             # Safari: MP4 kept as .m4a
    assert t2["id"] == "take-2" and t2["path"].endswith("take-2.m4a")
    assert client.get(f"/projects/{pid}/files").json() == []                  # takes aren't in the edit

    # they survive a refresh (and a server restart): the folder is the record
    assert [t["id"] for t in client.get(f"/projects/{pid}/takes").json()] == ["take-1", "take-2"]
    assert [t.id for t in ProjectStore(cutroom_paths.workspace).takes(pid)] == ["take-1", "take-2"]
    r = client.get("/media/file", params={"path": f"{pid}/{t1['path']}"}, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206

    # "Use this": the take goes through the files endpoint like any voice memo, and is converted
    take = client.get("/media/file", params={"path": f"{pid}/{t1['path']}"}).content
    r = client.post(f"/projects/{pid}/files", data={"kind": "voiceover", "take": "take-1"},
                    files=[("files", ("take-1.webm", take))])
    assert r.status_code == 201, r.text
    [vo] = r.json()
    assert (vo["name"], vo["kind"], vo["take"]) == ("take-1.wav", "voiceover", "take-1")

    # deleting a take leaves the voiceover made from it, and its number isn't given out again
    assert client.delete(f"/projects/{pid}/takes/take-1").status_code == 204
    assert not (cutroom_paths.workspace / pid / t1["path"]).exists()
    assert [f["name"] for f in client.get(f"/projects/{pid}/files").json()] == ["take-1.wav"]
    assert client.delete(f"/projects/{pid}/takes/take-1").json()["error"]["code"] == "take_not_found"
    assert record(client, pid, takes["ogg"]).json()["id"] == "take-3"


def test_take_errors(client: TestClient, takes, tmp_path) -> None:  # noqa: F811
    pid = new_project(client)
    r = record(client, pid, takes["webm"], name="notes.txt")
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file"
    silent = tmp_path / "take.wav"
    subprocess.run(media_factory.FF + ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.1", str(silent)],
                   check=True)
    r = record(client, pid, silent)
    assert r.status_code == 422 and r.json()["error"]["code"] == "empty_take"
    assert client.get(f"/projects/{pid}/takes").json() == []
    with open(takes["webm"], "rb") as f:
        r = client.post(f"/projects/{pid}/files", data={"kind": "voiceover", "take": "take-9"},
                        files=[("files", ("take-9.webm", f))])
    assert r.status_code == 404 and r.json()["error"]["code"] == "take_not_found"
    record(client, pid, takes["webm"])
    with open(takes["webm"], "rb") as f:
        r = client.post(f"/projects/{pid}/files", data={"kind": "music", "take": "take-1"},
                        files=[("files", ("take-1.webm", f))])
    assert r.status_code == 422


def test_a_used_take_is_a_voiceover_downstream(client: TestClient, takes, cutroom_paths) -> None:  # noqa: F811
    """Talking not set + a recorded take = a voiceover edit; the take gets the same clean-up as a voice memo."""
    pid = client.post("/projects", json={"name": "Morning", "brief": {"content_type": "gym-vlog"}}).json()["id"]
    upload(client, pid, media_factory.clip(cutroom_paths.root / "raw" / "squats.mp4", 3.0))
    record(client, pid, takes["webm"])
    with open(takes["webm"], "rb") as f:
        client.post(f"/projects/{pid}/files", data={"kind": "voiceover", "take": "take-1"},
                    files=[("files", ("take-1.webm", f))])
    store = ProjectStore(cutroom_paths.workspace)
    proj = store.get(pid)
    with store.context(pid):
        a = pipeline._analysis(store, proj)
        assert a["talk"] == "voiceover"
        assert [v["src"] for v in a["voiceover"]] == ["inputs/voiceover/take-1.wav"]
        out, stats = voice.clean(a["voiceover"][0]["src"], style_for({"preset": a["preset"]}))
    assert out.exists() and stats["src"] == "inputs/voiceover/take-1.wav"
    assert stats["lufs_after"] == pytest.approx(-16, abs=1.5)
