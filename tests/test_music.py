"""The song: where the edit starts in it (auto = the strongest part / the drop, or the creator's pick), and posting
with the in-app sound (whole-second start from the first frame, a second file without the music)."""
from __future__ import annotations

import json
import re
import subprocess

import pytest
from fastapi.testclient import TestClient

from engine import edl as E
from engine.beats import best_start
from engine.brief import analyse, parse_markdown
from engine.common import ffprobe
from engine.models import BriefData
from engine.project import ProjectStore
from engine.timeline import Music
from server.app import create_app
from server.deps import Services
from server.jobs import JobManager


def beat_track(bpm: float = 120.0, seconds: float = 60.0, drops: tuple[float, ...] = (), loud: tuple = ()) -> dict:
    """A beats_for() result without audio: a steady grid, energy 0.3 except the given loud stretches."""
    period = 60 / bpm
    beats = [round(k * period, 3) for k in range(int(seconds / period))]
    step = 0.25
    energy = [0.3] * int(seconds / step)
    for a, b in loud:
        for i in range(int(a / step), min(len(energy), int(b / step))):
            energy[i] = 1.0
    return {"bpm": bpm, "duration": seconds, "beats": beats, "downbeats": beats[::4], "drops": list(drops),
            "energy_step": step, "energy": energy, "peaks": [0.5] * 800}


# ---------------------------------------------------------------- picking the part of the song

def test_best_start_is_two_bars_before_the_drop() -> None:
    bt = beat_track(drops=(32.0,), loud=((32, 60),))
    b = best_start(bt, 15)
    assert b["reason"] == "drop" and b["drop"] == 32.0
    assert b["start"] == pytest.approx(32.0 - 8 * 0.5)          # 8 beats at 120 BPM


def test_best_start_without_a_drop_is_the_loudest_stretch_on_a_downbeat() -> None:
    bt = beat_track(loud=((20, 36),))
    b = best_start(bt, 15)
    assert b["reason"] == "loudest" and b["drop"] is None
    assert 19.9 <= b["start"] <= 21.1 and b["start"] in bt["downbeats"]


def test_best_start_short_edit_keeps_the_drop_inside_it() -> None:
    b = best_start(beat_track(drops=(32.0,), loud=((32, 60),)), 4)
    assert 32.0 - b["start"] <= 2.0 + 1e-6                        # a short lead-in, the drop still in the edit


def test_best_start_fits_the_edit_inside_the_song() -> None:
    b = best_start(beat_track(seconds=30, loud=((26, 30),)), 15)
    assert b["start"] + 15 <= 30.05


def _grid(monkeypatch: pytest.MonkeyPatch, music: dict, bt: dict, segs: list | None = None) -> dict:
    monkeypatch.setattr("engine.beats.beats_for", lambda src, force=False: bt)
    edl = {"music": {"src": "x.wav", **music}, "segments": segs or [], "target_length": 15}
    cfg = {"music_start": "best", "target_length": 15, "shot_min": 0.6, "shot_max": 1.8, "beat_every": 0,
           "beat_every_after_drop": 0, "fps": 30}
    return E.music_grid(edl, cfg, edl["segments"])


def test_music_start_best_and_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    bt = beat_track(drops=(32.0,), loud=((32, 60),))
    assert _grid(monkeypatch, {"start": "best"}, bt)["start"] == pytest.approx(28.0)
    g = _grid(monkeypatch, {"start": 41.6}, bt)
    assert g["start"] == pytest.approx(41.6) and g["beats"][0] >= -0.02


def test_in_app_starts_on_a_whole_second_from_the_first_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    bt = beat_track(drops=(32.25,), loud=((32, 60),))
    g = _grid(monkeypatch, {"start": 41.6, "in_app": True}, bt)
    assert g["start"] == 42.0 and g["at"] == 0.0
    # music that came in after an intro: in the app the song plays from the first frame, so it starts earlier
    g = _grid(monkeypatch, {"start": 30.4, "at": 2.0, "in_app": True}, bt)
    assert g["start"] == 28.0 and g["at"] == 0.0
    # the beats keep their place in the song: a beat at song time b plays at b - start
    assert any(abs(b - (32.0 - 28.0)) < 1e-3 for b in g["beats"])


def test_timeline_music_accepts_best_and_in_app() -> None:
    m = Music.model_validate({"src": "a.wav", "start": "best", "in_app": True})
    assert m.start == "best" and m.in_app
    with pytest.raises(ValueError):
        Music.model_validate({"src": "a.wav", "start": "loudest"})


# ---------------------------------------------------------------- the brief

def test_markdown_brief_song_start_and_in_app() -> None:
    md = ("# Video Brief: Lekki night\n## Basics\n- Content type: photo-dump\n## The idea\nnight out\n"
          "## Music & sound\n- Track: beat.wav\n- Song starts at: 0:42\n"
          "- Add the song in Instagram/TikTok when posting: yes\n")
    b = parse_markdown(md)
    assert b.music_start == 42.0 and b.music_in_app is True
    tmpl = parse_markdown(md.replace("0:42", "(auto = the strongest part / the drop, or a time in the song like 0:42)")
                          .replace(": yes", ": yes / no"))
    assert tmpl.music_start is None and tmpl.music_in_app is False


def test_analyse_turns_the_choices_into_overrides(cutroom_paths, media) -> None:
    import shutil
    shutil.copy(media["music"], cutroom_paths.root / "music" / "beat.wav")
    shutil.copy(media["photo"], cutroom_paths.root / "raw" / "fit-check.jpg")
    b = BriefData(content_type="photo-dump", idea="x", track="beat.wav", music_start=12.5, music_in_app=True,
                  clips=[{"src": "raw/fit-check.jpg"}])
    a = analyse(b, "t")
    assert a["style_overrides"]["music_start"] == 12.5 and a["music_in_app"] is True
    assert any("in-app sound" in n for n in a["notes"])


# ---------------------------------------------------------------- through the API, with a render

def _volume(path) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-map", "0:a", "-af", "volumedetect", "-f", "null",
                        "-"], capture_output=True, text=True)
    return float(re.search(r"max_volume: (-?[\d.]+) dB", r.stderr).group(1))


@pytest.mark.slow
def test_post_with_in_app_sound_end_to_end(mock_brain, cutroom_paths, media) -> None:
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: mock_brain)
    with TestClient(create_app(svc)) as c:
        pid = c.post("/projects", json={"name": "In-app", "brief": {
            "content_type": "photo-dump", "talking": "no", "idea": "gym", "target_length": "4s",
            "beat_sync": "every 2 beats"}}).json()["id"]
        for key, kind in (("clip_a", None), ("clip_b", None), ("photo", None), ("music", "music")):
            with open(media[key], "rb") as f:
                r = c.post(f"/projects/{pid}/files", data={"kind": kind} if kind else {},
                           files=[("files", (media[key].name, f))])
            assert r.status_code == 201, r.text

        # the Music step: waveform, BPM, the auto start; then the creator picks 2.4s and posts with the app's sound
        m = c.get(f"/projects/{pid}/music").json()
        assert m["name"] == "beat.wav" and m["bpm"] == pytest.approx(120, abs=6) and len(m["peaks"]) == 800
        assert m["start"] is None and m["in_app"] is False and m["length"] == 4.0
        assert m["auto_reason"] in ("drop", "loudest") and 0 <= m["auto_start"] <= m["duration"]
        r = c.patch(f"/projects/{pid}", json={"brief": {"music_start": 2.4, "music_in_app": True}})
        assert r.status_code == 200, r.text
        m = c.get(f"/projects/{pid}/music").json()
        assert m["start"] == 2.4 and m["in_app"] is True and m["auto_start"] == round(m["auto_start"])

        assert c.post(f"/projects/{pid}/plan", params={"wait": "true"}).json()["status"] == "done"
        view = c.get(f"/projects/{pid}/timeline").json()
        assert view["music"]["in_app"] is True and view["music"]["starts_at"] == 2.0     # a whole second
        tl = view["timeline"]
        assert tl["music"].get("start") in (None, "best")      # the plan keeps its own start; the pick is applied
        tl["style"].update({"width": 360, "height": 640})
        squats = next(s for s in tl["segments"] if s.get("src", "").endswith("gym-squats.mp4"))
        squats["audio"] = True                                # this clip keeps its own sound (a 440 Hz tone)
        assert c.put(f"/projects/{pid}/timeline", json=tl).status_code == 200

        job = c.post(f"/projects/{pid}/render", json={"draft": True}, params={"wait": "true"}).json()
        assert job["status"] == "done", job
        res = job["result"]
        assert res["post_video"].endswith("_v1_post.mp4")
        card = res["in_app"]
        assert card == {"song": "beat.wav", "start": 2.0, "start_label": "0:02", "voice": False,
                        "song_duration": pytest.approx(12.0, abs=0.1), "warning": None}
        ws = cutroom_paths.workspace / pid
        main, post = ws / res["video"], ws / res["post_video"]
        assert ffprobe(post)["duration"] == pytest.approx(ffprobe(main)["duration"], abs=0.1)
        assert ffprobe(post)["width"] == 360 and ffprobe(post)["has_audio"]
        # the post copy keeps the clip's own sound and drops the music: quieter overall, never silent here
        assert -40 < _volume(post) and _volume(main) > -6
        rj = json.loads((ws / "output" / "v1" / "render.json").read_text())
        assert rj["music_start"] == 2.0

        outs = c.get(f"/projects/{pid}/outputs").json()
        assert outs[0]["video"].endswith("_v1.mp4") and outs[0]["post_video"].endswith("_v1_post.mp4")
        assert outs[0]["in_app"]["start_label"] == "0:02"
        r = c.get(outs[0]["post_video_url"], params={"download": "true"})
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        assert c.get(f"/projects/{pid}").json()["renders"][0]["in_app"]["start"] == 2.0

        # without the in-app choice there's one file again
        c.patch(f"/projects/{pid}", json={"brief": {"music_in_app": False, "music_start": None}})
        res = c.post(f"/projects/{pid}/render", json={"draft": True}, params={"wait": "true"}).json()["result"]
        assert res["post_video"] is None and res["in_app"] is None
        assert c.get(f"/projects/{pid}/outputs").json()[0]["post_video"] is None


def test_music_endpoint_without_music(cutroom_paths, mock_brain) -> None:
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: mock_brain)
    with TestClient(create_app(svc)) as c:
        pid = c.post("/projects", json={"name": "No song"}).json()["id"]
        r = c.get(f"/projects/{pid}/music")
        assert r.status_code == 404 and r.json()["error"]["code"] == "no_music"
        r = c.patch(f"/projects/{pid}", json={"brief": {"music_start": -3}})
        assert r.status_code == 422


def test_in_app_card_voice_reminder_and_song_too_short(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.render import in_app_card
    monkeypatch.setattr("engine.beats.beats_for", lambda src, force=False: {"duration": 50.0})
    edl = {"music": {"src": "inputs/music/song.mp3"}}
    card = in_app_card(edl, {"start": 42.0}, 6.0, voice=True)
    assert card["song"] == "song.mp3" and card["start_label"] == "0:42" and card["voice"] is True
    assert card["warning"] is None
    card = in_app_card(edl, {"start": 42.0}, 15.0, voice=False)
    assert "ends 0:50 in" in card["warning"]
    assert in_app_card(edl, {"start": 75.0}, 1.0, voice=False)["start_label"] == "1:15"
