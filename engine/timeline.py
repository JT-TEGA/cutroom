"""The edit plan (timeline) as typed data, and the resolved view the API returns.

``Timeline`` is the existing work/<name>/edl.json format with Pydantic validation on top: the fields the app and
the brain care about are typed, everything else the renderer understands passes through untouched (extra="allow").
Times in ``segments`` are *source* seconds; overlay times are *output* seconds or anchored with "on" / "cue".

``view()`` lays the plan out (beat sync, voiceover cues, end card) and returns ``TimelineView``: every shot with its
output start/end, source in/out, transition, sound role and the reason it is there.
"""
from __future__ import annotations

import re
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import edl as E
from .common import style_for
from .config import EngineError

TEXT_STYLES = ("sticker", "timestamp", "lower3", "card", "macros", "credits", "label", "title", "big",
               "title-minimal", "title-serif", "lower", "caption")
TRANSITIONS = ("cut", "flash", "whip", "zoom")
KB_MOVES = ("in", "out", "left", "right", "up", "down", "none")
GRADES = ("none", "warm", "clean-editorial", "punchy", "film")
RAMP_NAMES = tuple(k for k in E.RAMPS if isinstance(k, str))

Ramp = Union[str, bool, list[list[float]]]
Zoom = Union[float, list[list[Union[float, str]]]]


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


def _check_ramp(v: Any) -> Any:
    if isinstance(v, str) and v not in RAMP_NAMES and v != "none":
        raise ValueError(f"unknown ramp {v!r}; use one of {', '.join(RAMP_NAMES)} or [[fraction, speed], ...]")
    return v


def _check_zoom(v: Any) -> Any:
    if E.zoom_max(v) < 1.0:
        raise ValueError("zoom below 1.0 is not possible (crop can't zoom out)")
    return v


class Keep(_Model):
    """A voiceover source range that stays in (fillers and silences between keeps are cut)."""

    in_: float = Field(alias="in", ge=0)
    out: float
    text: str | None = None

    @model_validator(mode="after")
    def _order(self) -> Keep:
        if self.out <= self.in_:
            raise ValueError(f"keep out ({self.out}) must be after in ({self.in_})")
        return self


class Shot(_Model):
    """A B-roll shot inside a voiceover block, or one side of a before/after compare."""

    type: Literal["clip", "image", "color"] | None = None
    src: str | None = None
    in_: float | None = Field(None, alias="in", ge=0)
    out: float | None = None
    cue: str | None = Field(None, description="cut to this shot as the phrase is said")
    at: float | None = Field(None, description="or: seconds into the voiceover block")
    dur: float | None = Field(None, gt=0)
    ambient: bool | None = None
    color: str | None = None
    reason: str | None = None
    why: str | None = None
    ramp: Ramp | None = None
    zoom: Zoom | None = None

    @field_validator("ramp")
    @classmethod
    def check_ramp(cls, v: Any) -> Any:
        return _check_ramp(v)

    @field_validator("zoom")
    @classmethod
    def check_zoom(cls, v: Any) -> Any:
        return _check_zoom(v)

    @model_validator(mode="after")
    def _needs(self) -> Shot:
        if self.type != "color" and not self.src:
            raise ValueError("a shot needs a src")
        if self.in_ is not None and self.out is not None and self.out <= self.in_:
            raise ValueError(f"out ({self.out}) must be after in ({self.in_})")
        return self


class Segment(_Model):
    """One entry of the plan: a clip, photo, before/after compare, colour card, or voiceover block with B-roll."""

    type: Literal["clip", "image", "compare", "color", "vo"] | None = Field(
        None, description="omitted = clip (or image, from the file extension)")
    src: str | None = None
    in_: float | None = Field(None, alias="in", ge=0, description="source seconds")
    out: float | None = Field(None, description="source seconds; omit to let the beat grid set the length")
    dur: float | None = Field(None, gt=0, description="output seconds (overrides out / beats)")
    beats: int | None = Field(None, ge=1, description="length in music beats")
    to: Literal["drop"] | None = None
    label: str | None = Field(None, description="name other items can anchor to with \"on\"")
    text: str | None = Field(None, description="what is said in this piece (talking)")
    talk: bool | None = None
    captions: bool | None = None
    transition: Literal["cut", "flash", "whip", "zoom"] | None = Field(None, description="into this shot")
    speed: float | None = Field(None, gt=0)
    ramp: Ramp | None = None
    zoom: Zoom | None = None
    crop: str | dict[str, float] | None = None
    fit: Literal["crop", "blur", "auto"] | None = None
    kb: Literal["in", "out", "left", "right", "up", "down", "none"] | None = None
    ambient: bool | None = None
    audio: bool | None = None
    reason: str | None = Field(None, description="why this shot is here / why it was cut this way")
    # voiceover block
    keep: list[Keep] | None = None
    shots: list[Shot] | None = None
    # compare
    a: Shot | None = None
    b: Shot | None = None
    mode: Literal["swipe", "split"] | None = None
    labels: list[str] | None = None
    on_drop: bool | None = None
    color: str | None = None

    @field_validator("ramp")
    @classmethod
    def check_ramp(cls, v: Any) -> Any:
        return _check_ramp(v)

    @field_validator("zoom")
    @classmethod
    def check_zoom(cls, v: Any) -> Any:
        return _check_zoom(v)

    @model_validator(mode="after")
    def _by_type(self) -> Segment:
        k = self.type or "clip"
        if k in ("clip", "image", "vo") and not self.src:
            raise ValueError(f"a {k} segment needs a src")
        if k == "vo" and not self.shots:
            raise ValueError('a voiceover block needs B-roll in "shots"')
        if k == "compare" and (self.a is None or self.b is None):
            raise ValueError('a compare needs "a" (before) and "b" (after)')
        if k == "color" and not (self.dur or self.beats):
            raise ValueError('a color card needs "dur" or "beats"')
        if self.in_ is not None and self.out is not None and self.out <= self.in_:
            raise ValueError(f"out ({self.out}) must be after in ({self.in_})")
        return self


class TextOverlay(_Model):
    """Text on screen. Anchor with "on" (a label or "#3"), "cue" (when a phrase is said) or start/end seconds."""

    text: str | None = None
    style: str | None = Field(None, description="one of: " + ", ".join(TEXT_STYLES))
    sub: str | None = None
    on: str | None = None
    cue: str | None = None
    nth: int | None = Field(None, ge=1)
    start: float | Literal["end"] | None = None
    at: float | None = None
    end: float | Literal["end"] | None = None
    dur: float | None = Field(None, gt=0)
    offset: float | None = None
    x: float | None = Field(None, ge=0, le=1)
    y: float | None = Field(None, ge=0, le=1)
    items: list[Any] | None = None
    lines: list[str] | None = None
    fill: bool | None = None

    @field_validator("style")
    @classmethod
    def _style(cls, v: str | None) -> str | None:
        if v is not None and v not in TEXT_STYLES:
            raise ValueError(f"unknown text style {v!r}; use one of {', '.join(TEXT_STYLES)}")
        return v

    @model_validator(mode="after")
    def _has_content(self) -> TextOverlay:
        if not (self.text or self.items or self.lines):
            raise ValueError('text overlay needs "text" (or "items" / "lines")')
        return self


class BRoll(_Model):
    """A cutaway over to-camera talking (the voice keeps playing)."""

    src: str
    in_: float | None = Field(None, alias="in", ge=0)
    out: float | None = None
    cue: str | None = None
    on: str | None = None
    start: float | None = None
    dur: float | None = Field(None, gt=0)
    reason: str | None = None


class Music(_Model):
    src: str
    start: float | str | None = Field(None, description='seconds, "auto", "drop" or "drop-16"')
    level_db: float | None = None
    snap_cuts: bool | None = None

    @field_validator("start")
    @classmethod
    def _start(cls, v: float | str | None) -> float | str | None:
        if isinstance(v, str) and not re.fullmatch(r"auto|drop(-\d+)?", v):
            raise ValueError(f'music start {v!r} not understood (seconds, "auto", "drop", "drop-16")')
        return v


class Captions(_Model):
    enabled: bool | None = None
    replace: dict[str, str] = Field(default_factory=dict, description="fix caption words: {heard: shown}")
    hide: list[list[float]] = Field(default_factory=list)


class EndCard(_Model):
    enabled: bool | None = None


class Timeline(_Model):
    """The edit plan. Saved as work/edl.json and rendered as is."""

    name: str | None = None
    preset: str | None = None
    talk: Literal["yes", "no", "some", "voiceover", "mixed"] | None = None
    target_length: float | None = None
    style: dict[str, Any] = Field(default_factory=dict, description="brief overrides of preset / brand settings")
    beat_sync: dict[str, Any] | None = None
    segments: list[Segment] = Field(min_length=1)
    text: list[TextOverlay] = Field(default_factory=list)
    broll: list[BRoll] = Field(default_factory=list)
    music: Music | None = None
    captions: Captions = Field(default_factory=Captions)
    end_card: EndCard | None = None
    graphics: list[dict[str, Any]] = Field(default_factory=list)
    flash: list[Any] = Field(default_factory=list)
    sfx: list[dict[str, Any]] = Field(default_factory=list)
    sfx_on_cuts: dict[str, Any] | None = None
    sources: list[dict[str, Any]] | None = None
    notes: list[str] = Field(default_factory=list, description="judgement calls, each with its reason")

    @field_validator("style")
    @classmethod
    def _grade(cls, v: dict[str, Any]) -> dict[str, Any]:
        g = v.get("grade")
        if isinstance(g, str) and not (g in GRADES or g.startswith("custom:") or g.endswith(".cube")):
            raise ValueError(f"unknown grade {g!r}; use {', '.join(GRADES)}, custom:<ffmpeg filters> or a .cube LUT")
        return v

    def to_edl(self) -> dict[str, Any]:
        """The plain dict the renderer reads ("in" keys, no nulls)."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


def parse(data: dict[str, Any]) -> Timeline:
    """dict -> Timeline, raising EngineError (HTTP 422) with readable field paths."""
    try:
        return Timeline.model_validate(data)
    except ValidationError as e:
        raise EngineError("the edit plan is not valid:\n  - " + "\n  - ".join(validation_lines(e)),
                          code="invalid_plan", status=422) from e


def validation_lines(e: ValidationError, limit: int = 20) -> list[str]:
    out = []
    for err in e.errors()[:limit]:
        loc = ".".join(str(x) for x in err["loc"]) or "(plan)"
        out.append(f"{loc}: {err['msg']}")
    return out


# ---------------------------------------------------------------- resolved view

class ResolvedShot(BaseModel):
    idx: int
    segment: int = Field(0, description="index of the segment in timeline.segments that this shot comes from")
    shot: int | None = Field(None, description="index in that voiceover block's shots (None: the segment itself)")
    kind: str
    src: str | None
    in_: float = Field(serialization_alias="in")
    out: float
    start: float
    end: float
    duration: float
    label: str | None = None
    transition: str | None = None
    role: str = Field(description="what the shot's own sound does: voice | ambient | mute")
    speed: float = 1.0
    ramp: bool = False
    beat_synced: bool = False
    voiceover: str | None = None
    heard: str | None = Field(None, description="voiceover words heard over this shot")
    said: str | None = Field(None, description="words said to camera in this shot")
    reason: str | None = None
    warning: str | None = None


class ResolvedOverlay(BaseModel):
    kind: Literal["text", "broll", "graphic", "sfx", "flash"]
    index: int | None = Field(None, description="position in the plan's list for this kind (text, broll...)")
    start: float
    end: float
    text: str | None = None
    style: str | None = None
    src: str | None = None


class TimelineView(BaseModel):
    timeline: Timeline
    duration: float
    target_length: float | None = None
    shots: list[ResolvedShot]
    overlays: list[ResolvedOverlay]
    captions: dict[str, Any]
    music: dict[str, Any] | None = None
    end_card: dict[str, Any] | None = None
    problems: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def check(tl: Timeline) -> list[str]:
    """Problems the schema can't see: missing files, ranges past the end of a clip, unknown anchors, cues not said."""
    edl = tl.to_edl()
    problems = E.validate(edl)
    if problems:
        return problems
    try:
        cfg = style_for(edl)
        items, _ = E.build_timeline(edl, cfg)
        for key in ("text", "broll", "graphics", "sfx"):
            for x in edl.get(key) or []:
                E.resolve_span(x, items)
    except EngineError as e:
        return [e.message]
    return []


def view(tl: Timeline) -> TimelineView:
    """Lay the plan out (beat grid, voiceover cues, end card) -> every shot's output time and why it's there."""
    edl = tl.to_edl()
    problems = E.validate(edl)
    if problems:
        return TimelineView(timeline=tl, duration=0.0, shots=[], overlays=[], captions={}, problems=problems,
                            notes=tl.notes, target_length=tl.target_length)
    cfg = style_for(edl)
    items, grid = E.build_timeline(edl, cfg)
    total = items[-1]["end"] if items else 0.0
    # the layout makes one item per segment, or one per shot of a voiceover block: which segment is each from?
    owners: list[tuple[int, int | None]] = []
    for si, s in enumerate(edl["segments"]):
        owners += [(si, j) for j in range(len(s.get("shots") or []))] if s.get("type") == "vo" else [(si, None)]
    shots, overlays, warn = [], [], []
    for n, it in enumerate(items):
        if it["kind"] == "endcard":
            continue
        seg = it["seg"]
        blk = it.get("vo")
        heard = None
        if blk is not None:
            heard = " ".join(w["w"] for w in blk["words"] if it["start"] - 0.02 <= w["s"] < it["end"] - 0.02) or None
        si, sj = owners[n] if n < len(owners) else (len(edl["segments"]) - 1, None)
        shots.append(ResolvedShot(
            idx=it["idx"], segment=si, shot=sj, kind=it["kind"], src=it["src"], in_=round(float(it["in"]), 3),
            out=round(float(it["out"]), 3), start=round(it["start"], 3), end=round(it["end"], 3),
            duration=round(it["end"] - it["start"], 3), label=it["label"] or None, transition=it["trans_in"],
            role=E.seg_role(it, edl, cfg), speed=it["speed"], ramp=bool(it["ramp"]), beat_synced=it["beat_synced"],
            voiceover=blk["src"] if blk else None, heard=heard, said=seg.get("text") if seg.get("talk") else None,
            reason=seg.get("reason") or seg.get("why") or seg.get("note"), warning=it.get("warn")))
        if it.get("warn"):
            warn.append(f"#{it['idx']}: {it['warn']}")

    def span(x: dict[str, Any], default: float = 1.5) -> tuple[float, float] | None:
        try:
            s, e = E.resolve_span(x, items, default)
            return round(s, 3), round(min(float(e), total), 3)
        except EngineError as err:
            warn.append(err.message)
            return None

    for i, x in enumerate(edl.get("text", [])):
        r = span(x)
        if r:
            what = " / ".join(filter(None, [x.get("text"), x.get("sub")])) or " | ".join(
                str(i) for i in (x.get("items") or x.get("lines") or []))
            overlays.append(ResolvedOverlay(kind="text", index=i, start=r[0], end=r[1], text=what,
                                            style=x.get("style")))
    for i, b in enumerate(edl.get("broll", [])):
        r = span(dict(b, dur=b.get("dur", 2.0)))
        if r:
            overlays.append(ResolvedOverlay(kind="broll", index=i, start=r[0], end=r[1], src=b["src"]))
    for i, g in enumerate(edl.get("graphics", [])):
        r = span(g, 2.0)
        if r:
            overlays.append(ResolvedOverlay(kind="graphic", index=i, start=r[0], end=r[1], src=g.get("src")))
    for i, s in enumerate(edl.get("sfx", [])):
        r = span(s, 0.5)
        if r:
            overlays.append(ResolvedOverlay(kind="sfx", index=i, start=r[0], end=r[1], src=s.get("src")))
    overlays.sort(key=lambda o: o.start)

    cap: dict[str, Any] = {"enabled": E.captions_enabled(edl, cfg)}
    if cap["enabled"]:
        ec = next((i for i in items if i["kind"] == "endcard"), None)
        words = E.caption_words(edl, items, cfg)
        pages = E.caption_pages(words, cfg, ec["start"] if ec else total)
        cap.update({"words": len(words), "pages": len(pages), "font": cfg["caption_font"],
                    "replace": (edl.get("captions") or {}).get("replace", {})})
    music = None
    if grid:
        music = {"src": edl["music"]["src"], "bpm": grid["bpm"], "starts_at": round(grid["start"], 3),
                 "drops": [d for d in grid["drops"] if d <= total]}
    ec_item = next((i for i in items if i["kind"] == "endcard"), None)
    end_card = None
    if ec_item:
        end_card = {"start": round(ec_item["start"], 3), "end": round(ec_item["end"], 3),
                    "handle": ec_item["endcard"]["handle"]}
    return TimelineView(timeline=tl, duration=round(total, 3), target_length=tl.target_length, shots=shots,
                        overlays=overlays, captions=cap, music=music, end_card=end_card, problems=warn,
                        notes=tl.notes)
