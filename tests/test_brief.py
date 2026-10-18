"""Brief parsing: markdown -> BriefData, and the gap check that decides what to ask."""
from __future__ import annotations

import shutil
from pathlib import Path

from engine import brief as B
from engine.config import paths
from engine.models import BriefData, ClipRef

REPO = Path(__file__).resolve().parent.parent

FULL = """# Video Brief: Chest day vlog
## Basics
- Content type: gym-vlog
- Talking in this video?: some parts
- Colour grade: warm
- Platform: Reels
- Target length: 45s
- Goal: show my routine
- Mode: ORIGINAL
- Reference reel URL (REFERENCE mode only):
## The idea
Morning session at the gym, then a meal.
## Hook (first 2 seconds)
The heaviest set.
## Script / talking points
Today is chest day. We start with incline bench.
- Voiceover file: none
- Visual cues: when I say "incline" show raw/incline.mp4
## Clips & order
1. raw/intro.mp4 0:02-0:09 2. raw/incline.mp4 3. raw/meal/
## Text on screen
0:00 'chest day' small
## Labels & stickers
- 6:30AM pre-workout
- Incline bench 4x10
## Captions
- On
- Style: brand default
## Music & sound
- Track: beat.wav
- Vibe / volume: low under voice
- Beat sync: every 2 beats
- Sound effects: none
## Pacing & effects
Whip between parts of the day.
## Call to action
Follow for part 2.
- End card with my handle: on
## Avoid
Slow-mo.
"""


def test_parse_full_brief() -> None:
    b = B.parse_markdown(FULL)
    assert b.title == "Chest day vlog"
    assert b.content_type == "gym-vlog"
    assert b.talking == "some parts"
    assert b.colour_grade == "warm"
    assert b.target_length == "45s"
    assert b.reference_url is None                      # empty field -> None
    assert b.script == "Today is chest day. We start with incline bench."
    assert b.voiceover_file == "none"
    assert b.visual_cues == ['when I say "incline" show raw/incline.mp4']
    assert [c.src for c in b.clips] == ["raw/intro.mp4", "raw/incline.mp4", "raw/meal/"]
    assert (b.clips[0].in_, b.clips[0].out) == (2.0, 9.0)
    assert b.labels.splitlines() == ["- 6:30AM pre-workout", "- Incline bench 4x10"]
    assert b.captions == "On" and b.caption_style is None  # "brand default" is not a choice
    assert b.track == "beat.wav" and b.beat_sync == "every 2 beats"
    assert b.call_to_action == "Follow for part 2."
    assert b.end_card == "on"
    assert b.avoid == "Slow-mo."


def test_template_is_all_blanks() -> None:
    b = B.parse_markdown((REPO / "briefs" / "_TEMPLATE.md").read_text())
    assert b.title == ""
    for field in ("content_type", "talking", "colour_grade", "platform", "target_length", "mode", "track",
                  "beat_sync", "end_card", "voiceover_file"):
        assert getattr(b, field) is None, field
    assert b.clips == [] and b.visual_cues == [] and b.idea == ""


def test_beat_rules_and_talk_modes() -> None:
    assert B.beat_rule("cut on every beat") == {"beat_every": 1}
    assert B.beat_rule("every 4 beats") == {"beat_every": 4}
    assert B.beat_rule("on drops")["beat_every_after_drop"] == 1
    assert B.beat_rule("preset default") == {}
    assert B.talk_mode("some parts") == "some"
    assert B.talk_mode("voiceover") == "voiceover"
    assert B.talk_mode("mixed") == "mixed"
    assert B.talk_mode("yes / no / some parts") is None    # unanswered template choice


def test_analyse_finds_critical_gaps(media) -> None:
    root = paths().root
    shutil.copy(media["clip_a"], root / "raw" / "a.mp4")
    b = BriefData(content_type="photo-dump", talking="no", clips=[ClipRef(src="raw/a.mp4")])
    out = B.analyse(b, "t")
    assert out["preset"] == "photo-dump" and out["talk"] == "no"
    assert any("cut to the beat" in g for g in out["gaps"])          # beat preset without music
    assert any("No idea" in g for g in out["gaps"])
    out2 = B.analyse(BriefData(idea="x", clips=[ClipRef(src="raw/missing.mp4")]), "t")
    assert any("Content type not set" in g for g in out2["gaps"])
    assert any("Not found: raw/missing.mp4" in g for g in out2["gaps"])


def test_analyse_ok_brief_and_overrides(media) -> None:
    root = paths().root
    shutil.copy(media["clip_a"], root / "raw" / "a.mp4")
    shutil.copy(media["music"], root / "music" / "beat.wav")
    b = BriefData(content_type="photo-dump", talking="no", idea="dump", track="beat.wav", colour_grade="punchy",
                  beat_sync="every beat", end_card="on", clips=[ClipRef(src="raw/a.mp4", out=2.0)])
    out = B.analyse(b, "t")
    assert out["gaps"] == []
    assert out["music"] == "music/beat.wav"
    assert out["style_overrides"] == {"grade": "punchy", "beat_every": 1, "end_card": True}


def test_voiceover_with_talking_means_mixed(media) -> None:
    root = paths().root
    shutil.copy(media["clip_a"], root / "raw" / "a.mp4")
    shutil.copy(media["clip_a"], root / "voiceover" / "vo.m4a")
    b = BriefData(content_type="gym-vlog", talking="yes", idea="x", voiceover_file="vo.m4a",
                  clips=[ClipRef(src="raw/a.mp4")])
    out = B.analyse(b, "t")
    assert out["talk"] == "mixed"
    assert out["voiceover"][0]["src"] == "voiceover/vo.m4a"


def test_cue_with_bare_file_name() -> None:
    cues, bad = B.parse_cues(['when I say "squats" show squats.mp4', "something vague"],
                             known={"squats.mp4": "inputs/clips/squats.mp4"})
    assert cues[0]["say"] == "squats" and cues[0]["src"] == "inputs/clips/squats.mp4"
    assert bad == ["something vague"]
