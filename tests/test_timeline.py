"""Timeline (edit plan) schema validation and the semantic check."""
from __future__ import annotations

import shutil

import pytest

from engine import timeline as T
from engine.config import EngineError, legacy_layout, paths, use_layout

README_EXAMPLE = {
    "name": "oct-dump", "preset": "photo-dump", "talk": "no",
    "style": {"grade": "warm", "beat_every": 1},
    "beat_sync": {"every": 2},
    "segments": [
        {"src": "raw/a.mp4", "in": 1.2, "out": 3.3, "label": "hook", "talk": True, "text": "what is said",
         "crop": "face", "fit": "crop", "zoom": [[0, 1.0], [0.6, 1.15, "cut"]], "speed": 1.0},
        {"src": "raw/b.mp4", "in": 4.0, "beats": 2, "ambient": True},
        {"src": "raw/c.mp4", "in": 0.5, "beats": 4, "ramp": "fast-slow", "transition": "flash"},
        {"type": "image", "src": "raw/shoot/IMG_1.HEIC", "kb": "in"},
        {"src": "raw/d.mp4", "in": 2.0, "to": "drop"},
        {"type": "compare", "a": {"src": "raw/week1.jpg"}, "b": {"src": "raw/week12.mp4", "in": 1.0},
         "mode": "swipe", "labels": ["Week 1", "Week 12"], "beats": 8, "on_drop": True, "label": "reveal"},
        {"type": "color", "color": "#000000", "dur": 0.8},
        {"type": "vo", "src": "voiceover/vo.m4a", "label": "session",
         "keep": [{"in": 0.99, "out": 2.56, "text": "so today is chest day."}],
         "shots": [{"src": "raw/chest.mp4", "in": 3.1, "cue": "chest day"},
                   {"type": "image", "src": "raw/plate.jpg", "at": 4.2}]},
    ],
    "text": [
        {"text": "Lekki, 7PM", "style": "sticker", "on": "#2"},
        {"style": "macros", "text": "This bowl", "items": ["Protein 40g", "Carbs 55g"], "on": "#5"},
        {"style": "credits", "lines": ["Photographer — @name"], "on": "last"},
        {"text": "Incline bench", "sub": "4 × 10", "style": "lower3", "cue": "four sets", "dur": 2},
    ],
    "music": {"src": "music/track.mp3", "start": "drop", "level_db": -14, "snap_cuts": True},
    "broll": [{"src": "raw/shake.mp4", "in": 1.0, "cue": "protein shake", "dur": 2}],
    "captions": {"enabled": True, "replace": {"6 .30": "6:30"}, "hide": []},
    "end_card": {"enabled": False},
    "notes": ["Dropped take 1: stumbled"],
    "sfx_on_cuts": None,
}


def test_readme_example_validates_and_round_trips() -> None:
    tl = T.parse(README_EXAMPLE)
    edl = tl.to_edl()
    assert edl["segments"][0]["in"] == 1.2               # "in" alias survives
    assert edl["segments"][7]["keep"][0]["in"] == 0.99
    assert edl["segments"][1]["ambient"] is True
    assert edl["segments"][0]["crop"] == "face"          # renderer keys pass through
    assert "sfx_on_cuts" not in edl                      # nulls dropped
    assert T.parse(edl).to_edl() == edl


@pytest.mark.parametrize("bad, expect", [
    ({"segments": []}, "at least 1 item"),
    ({"segments": [{"src": "a.mp4", "in": 3, "out": 1}]}, "must be after in"),
    ({"segments": [{"type": "vo", "src": "v.m4a"}]}, "needs B-roll"),
    ({"segments": [{"type": "compare", "a": {"src": "x.jpg"}}]}, "compare needs"),
    ({"segments": [{"type": "color"}]}, "needs \"dur\" or \"beats\""),
    ({"segments": [{"in": 1}]}, "needs a src"),
    ({"segments": [{"src": "a.mp4", "ramp": "wobble"}]}, "unknown ramp"),
    ({"segments": [{"src": "a.mp4", "zoom": 0.8}]}, "zoom below 1.0"),
    ({"segments": [{"src": "a.mp4", "transition": "spin"}]}, "transition"),
    ({"segments": [{"src": "a.mp4"}], "text": [{"text": "x", "style": "huge"}]}, "unknown text style"),
    ({"segments": [{"src": "a.mp4"}], "text": [{"style": "sticker"}]}, "needs \"text\""),
    ({"segments": [{"src": "a.mp4"}], "text": [{"text": "x", "y": 1.4}]}, "text.0.y"),
    ({"segments": [{"src": "a.mp4"}], "music": {"src": "m.mp3", "start": "chorus"}}, "music start"),
    ({"segments": [{"src": "a.mp4"}], "style": {"grade": "sepia"}}, "unknown grade"),
    ({"segments": [{"src": "a.mp4"}], "talk": "maybe"}, "talk"),
])
def test_invalid_plans_are_rejected_with_paths(bad: dict, expect: str) -> None:
    with pytest.raises(EngineError) as e:
        T.parse(bad)
    assert e.value.status == 422 and e.value.code == "invalid_plan"
    assert expect in e.value.message


def test_check_finds_missing_files_and_unsaid_cues(media) -> None:
    root = paths().root
    shutil.copy(media["clip_a"], root / "raw" / "a.mp4")
    with use_layout(legacy_layout()):
        assert T.check(T.parse({"segments": [{"src": "raw/a.mp4", "in": 0, "out": 2}]})) == []
        probs = T.check(T.parse({"segments": [{"src": "raw/nope.mp4", "in": 0, "out": 1}]}))
        assert any("file not found" in p for p in probs)
        probs = T.check(T.parse({"segments": [{"src": "raw/a.mp4", "in": 0, "out": 9}]}))
        assert any("past end" in p for p in probs)
        probs = T.check(T.parse({"segments": [{"src": "raw/a.mp4", "in": 0, "out": 2}],
                                 "text": [{"text": "x", "on": "nowhere"}]}))
        assert any("unknown segment" in p for p in probs)


def test_view_lays_out_output_times(media) -> None:
    root = paths().root
    shutil.copy(media["clip_a"], root / "raw" / "a.mp4")
    shutil.copy(media["photo"], root / "raw" / "p.jpg")
    with use_layout(legacy_layout()):
        v = T.view(T.parse({"talk": "no", "end_card": {"enabled": False},
                            "segments": [{"src": "raw/a.mp4", "in": 0.5, "out": 2.0, "label": "hook",
                                          "reason": "best moment"},
                                         {"type": "image", "src": "raw/p.jpg", "dur": 1.0, "transition": "flash"}],
                            "text": [{"text": "hi", "style": "sticker", "on": "hook"}]}))
    assert [s.kind for s in v.shots] == ["clip", "image"]
    assert v.shots[0].start == 0 and v.shots[0].end == pytest.approx(1.5, abs=0.04)
    assert v.shots[0].reason == "best moment" and v.shots[0].label == "hook"
    assert v.shots[1].transition == "flash"
    assert v.duration == pytest.approx(2.5, abs=0.05)
    assert v.overlays[0].text == "hi" and v.overlays[0].start == 0
    assert v.captions["words"] == 0               # captions are on for talking, and nobody talks
