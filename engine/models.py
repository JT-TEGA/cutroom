"""Typed data shared by the engine, the brain and the API: briefs, clips, clarifying questions, style specs."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TalkMode = Literal["yes", "no", "some", "voiceover", "mixed"]


class ClipRef(BaseModel):
    """A clip, photo or folder in edit order, optionally trimmed (source seconds)."""

    model_config = ConfigDict(populate_by_name=True)

    src: str
    in_: float | None = Field(None, alias="in")
    out: float | None = None


class BriefData(BaseModel):
    """The brief as structured fields. Mirrors briefs/_TEMPLATE.md; free text stays free text."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    title: str = ""
    # basics
    content_type: str | None = Field(None, description="preset name, e.g. gym-vlog")
    talking: str | None = Field(None, description="yes / no / some parts / voiceover / mixed")
    colour_grade: str | None = None
    platform: str | None = None
    target_length: str | None = Field(None, description='e.g. "30s" or "1 min"')
    goal: str | None = None
    mode: str | None = Field(None, description="ORIGINAL or REFERENCE")
    reference_url: str | None = None
    # the creative part
    idea: str = ""
    hook: str = ""
    script: str = ""
    voiceover_file: str | None = None
    visual_cues: list[str] = Field(default_factory=list, description='e.g. when I say "meal prep" show meal.mp4')
    clips: list[ClipRef] = Field(default_factory=list, description="edit order (CLI briefs; projects use files)")
    text_on_screen: str = ""
    labels: str = Field("", description="labels & stickers: timestamps, locations, sets/reps, macros, credits")
    captions: str | None = Field(None, description="on / off")
    caption_style: str | None = None
    track: str | None = Field(None, description="music file name or 'none'")
    music_start: float | None = Field(None, ge=0, description="seconds into the song where the edit starts; "
                                                              "empty = auto (the strongest part / the drop)")
    music_in_app: bool = Field(False, description="I'll add this song in Instagram/TikTok when posting: the track "
                                                  "is only used for the beat and the preview, and each render also "
                                                  "exports <name>_post.mp4 without it")
    music_vibe: str | None = None
    beat_sync: str | None = Field(None, description='"every beat" / "every 2 beats" / "on drops"')
    sound_effects: str | None = None
    pacing: str = ""
    call_to_action: str = ""
    end_card: str | None = Field(None, description="on / off")
    avoid: str = ""


class Question(BaseModel):
    """A clarifying question for the creator, asked before planning."""

    id: str = Field(description="short stable slug, e.g. 'music-track'")
    question: str
    why: str = Field("", description="what goes wrong without an answer")
    field: str | None = Field(None, description="the BriefData field the answer fills, if any")
    options: list[str] = Field(default_factory=list, description="suggested answers, if it is a choice")
    blocking: bool = Field(True, description="true = can't plan without it; false = an assumption is used")


class StyleSpec(BaseModel):
    """What a reference reel does, in editing terms (REFERENCE mode)."""

    hook: str
    pacing: str
    cuts_on_beat: bool | None = None
    avg_shot_seconds: float | None = None
    framing: str = ""
    caption_look: str = ""
    text: str = ""
    effects: str = ""
    music: str = ""
    grade: str = ""
    ending: str = ""
    style_overrides: dict[str, object] = Field(
        default_factory=dict,
        description="preset/brand settings keys to apply, e.g. {'beat_every': 1, 'grade': 'punchy'}")
    summary: str = ""
