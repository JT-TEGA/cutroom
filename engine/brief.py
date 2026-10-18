#!/usr/bin/env python3
"""Read a brief, load its content-type preset, list the inputs, and flag anything missing or unclear.

  brief.py briefs/my-video.md

Writes work/<name>/brief.json (preset, talk, voiceover, visual cues, music, target length, brief overrides).
The GAPS list is the raw material for the single round of questions before editing.

Talking: yes | no | some | voiceover (a recording in voiceover/ over B-roll) | mixed (to camera + voiceover
+ music-only parts). Naming a voiceover file with talking "no" means voiceover; with "yes"/"some" it means mixed.

Two front ends share the analysis: ``parse_markdown()`` turns a briefs/*.md file into ``BriefData``; app projects
store ``BriefData`` directly. ``analyse()`` does the rest for both.
"""
import argparse
import re
from pathlib import Path

from .common import describe, die, ffprobe, list_presets, load_preset, parse_tc, rel, resolve, work_dir, write_json
from .config import layout, log
from .media import AUDIO_EXT, describe_media, expand, is_audio, is_image
from .models import BriefData, ClipRef

PLACEHOLDER = re.compile(r"^\(.*\)$|^\[.*\]$")
CHOICES = {"Reels / TikTok / both", "ORIGINAL / REFERENCE", "On / off", "yes / no", "yes / no / some parts",
           "yes / no / some parts / voiceover / mixed", "on / off / preset default"}
SCRIPT_FIELD = re.compile(r"^\s*[-*]\s*(voiceover file|visual cues)\s*:\s*(.*)$", re.I)
BEAT_PRESETS = {"photo-dump", "shoot-slideshow", "shoot-mashup", "transformation"}
GRADES = {"none", "warm", "clean-editorial", "punchy", "film"}
PATH_PREFIX = r"(?:raw|assets|voiceover|inputs)/"


# ---------------------------------------------------------------- markdown -> BriefData

def parse(text):
    title = re.search(r"^# Video Brief:\s*(.*)$", text, re.M)
    sections, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            cur = m.group(1).strip().lower()
            sections[cur] = []
        elif cur is not None and not PLACEHOLDER.match(line.strip()):   # skip the template's (hint) lines
            sections[cur].append(line)
    body = {k: "\n".join(v).strip() for k, v in sections.items()}
    fields = {}
    for sec in ("basics", "captions", "music & sound", "call to action"):
        for line in body.get(sec, "").splitlines():
            m = re.match(r"^\s*-\s*([^:]+):\s*(.*)$", line)
            if m:
                fields[m.group(1).strip().lower()] = m.group(2).strip()
            elif re.match(r"^\s*-\s*(on|off)\b", line, re.I) and sec == "captions":
                fields["captions"] = line.strip("- ").strip()
    title = title.group(1).strip() if title else ""
    return ("" if PLACEHOLDER.match(title) else title), body, fields


def blank(v):
    v = (v or "").strip()
    return not v or bool(PLACEHOLDER.match(v)) or v in CHOICES or v.lower() in ("preset default", "brand default")


def body_text(body, key, fields=()):
    """Section text without the named bullet fields ('- End card with my handle: on'). Only named fields are
    dropped, so a label like '- 6:30AM call time' stays."""
    def is_field(line):
        m = re.match(r"^\s*-\s*([^:]+):", line)
        return bool(m) and m.group(1).strip().lower() in fields
    return "\n".join(l for l in body.get(key, "").splitlines() if not is_field(l)).strip()


def clip_list(text):
    """Pull raw/... (and voiceover/..., inputs/...) paths and folders (+ optional time ranges) out of free text."""
    out = []
    for m in re.finditer(rf"({PATH_PREFIX}[^\s,;)\"'”’]*)(?:\s+(\d[\d:.]*)\s*[-–]\s*(\d[\d:.]*))?", text):
        path, a, b = m.group(1).rstrip("."), m.group(2), m.group(3)
        out.append({"src": path, "in": parse_tc(a) if a else None, "out": parse_tc(b) if b else None})
    return out


def script_parts(text):
    """Script section -> (script text, "Voiceover file" value, visual cue lines).
    Cue lines can follow on the same line or as indented bullets / lines that name a raw/ clip."""
    script, vo, cues, cur = [], "", [], None
    for line in text.splitlines():
        m = SCRIPT_FIELD.match(line)
        if m:
            cur = m.group(1).lower()
            if cur == "voiceover file":
                vo = m.group(2).strip()
            elif m.group(2).strip():
                cues.append(m.group(2).strip())
            continue
        if cur == "visual cues" and line.strip() and (re.search(r"\b(raw|assets|inputs)/", line) or re.match(r"^\s+[-*•]", line)):
            cues.append(line.strip())
            continue
        cur = None
        script.append(line)
    return "\n".join(script).strip(), vo, cues


def _val(fields, *keys):
    for k in keys:
        v = fields.get(k)
        if not blank(v):
            return v.strip()
    return None


def _song_start(v):
    """'0:42' / '42' / '1:02.5' -> seconds; 'auto' or anything else -> None (auto)."""
    if not v or not re.fullmatch(r"\d+(?::\d{1,2})?(?:\.\d+)?", v.strip()):
        return None
    return parse_tc(v)


def _yes(v):
    return bool(v) and v.strip().lower().startswith(("yes", "on", "true"))


def parse_markdown(text):
    """A briefs/*.md file -> BriefData (template hints and unanswered choices become empty)."""
    title, body, f = parse(text)
    script, vo, cues = script_parts(body.get("script / talking points", ""))
    clips = [ClipRef.model_validate(c) for c in clip_list(body.get("clips & order", ""))]
    sec = lambda k: "" if blank(body.get(k)) else body.get(k, "").strip()   # noqa: E731
    return BriefData(
        title=title,
        content_type=_val(f, "content type"),
        talking=_val(f, "talking in this video?"),
        colour_grade=_val(f, "colour grade", "color grade"),
        platform=_val(f, "platform"),
        target_length=_val(f, "target length"),
        goal=_val(f, "goal"),
        mode=_val(f, "mode"),
        reference_url=_val(f, "reference reel url (reference mode only)", "reference reel url"),
        idea=sec("the idea"),
        hook=sec("hook (first 2 seconds)"),
        script="" if blank(script) else script,
        voiceover_file=None if blank(vo) else vo,
        visual_cues=[c for c in cues if not blank(c)],
        clips=clips,
        text_on_screen=sec("text on screen"),
        labels=body_text(body, "labels & stickers"),
        captions=_val(f, "captions"),
        caption_style=_val(f, "style"),
        track=_val(f, "track"),
        music_start=_song_start(_val(f, "song starts at", "song start")),
        music_in_app=_yes(_val(f, "add the song in instagram/tiktok when posting", "in-app sound")),
        music_vibe=_val(f, "vibe / volume"),
        beat_sync=_val(f, "beat sync"),
        sound_effects=_val(f, "sound effects"),
        pacing=sec("pacing & effects"),
        call_to_action=body_text(body, "call to action", ("end card with my handle", "end card")),
        end_card=_val(f, "end card with my handle", "end card"),
        avoid=sec("avoid"),
    )


# ---------------------------------------------------------------- analysis (both front ends)

def _known_files():
    """Clip / photo file names in the clips folder -> relative path, so cues can name a bare file."""
    d = layout().dir("clips")
    if not d.exists():
        return {}
    return {f.name.lower(): rel(f) for f in d.rglob("*") if f.is_file() and not f.name.startswith(".")}


def parse_cues(lines, known=None):
    """'when I say "meal prep" show raw/meal.mp4' -> [{"say", "src", "in", "out"}], plus lines not understood.
    A bare file name ("show squats.mp4") works when that file is in the clips folder."""
    known = known or {}
    cues, bad = [], []
    for chunk in re.split(r"[;\n]+", "\n".join(lines)):
        c = chunk.strip(" -*•\t")
        if not c or blank(c):
            continue
        clips = [x for x in clip_list(c) if not x["src"].startswith(("voiceover/", "inputs/voiceover/"))]
        if not clips:
            for tok in re.findall(r"[\w\-.]+\.\w{2,5}\b", c):
                hit = known.get(tok.strip().lower())
                if hit:
                    clips = [{"src": hit, "in": None, "out": None}]
                    break
        m = (re.search(r"[\"“”]([^\"“”]+)[\"“”]", c) or re.search(r"(?:^|(?<=\s))[‘']([^'’]+)['’](?=\s|$|[,.;:])", c)
             or re.search(r"\b(?:say|says|said|saying|mention)\s+(.+?)\s*(?:,|->|→|=|:|\bshow\b|\buse\b|\bcut to\b|\bput\b)", c, re.I))
        if m and clips:
            cues.append({"say": m.group(1).strip(), "src": clips[0]["src"], "in": clips[0]["in"], "out": clips[0]["out"],
                         "line": c})
        else:
            bad.append(c)
    return cues, bad


def beat_rule(text):
    t = (text or "").lower()
    if not t or "preset" in t:
        return {}
    if "drop" in t:
        return {"beat_every": 4, "beat_every_after_drop": 1, "transition_drop": "flash"}
    if "every beat" in t or "each beat" in t:
        return {"beat_every": 1}
    m = re.search(r"every\s+(\d+)\s*beats?", t)
    if m:
        return {"beat_every": int(m.group(1))}
    if re.search(r"\bno\b|\boff\b|don't", t):
        return {"beat_every": 0}
    return {}


def talk_mode(text):
    t = "" if blank(text) else (text or "").lower()
    return "mixed" if "mix" in t else "voiceover" if re.search(r"voice|\bvo\b", t) else \
        "yes" if t.startswith("yes") else "no" if t.startswith("no") else \
        "some" if "some" in t else None


def _audio_files(kind):
    d = layout().dir(kind)
    return sorted(x for x in d.glob("*") if x.suffix.lower() in AUDIO_EXT and not x.name.startswith(".")) \
        if d.exists() else []


def analyse(brief, name, clips=None, auto_pick_music=False):
    """BriefData -> the brief.json dict the drafting step reads, with GAPS (blocking) and notes (assumptions).

    clips: edit order as [ClipRef | dict]; default ``brief.clips``. auto_pick_music: use the only file in the music
    folder when the brief names no track (app projects; the CLI's music/ folder is a library)."""
    lay = layout()
    vo_rel = lay.dirs.get("voiceover", "voiceover")
    music_rel = lay.dirs.get("music", "music")
    gaps, notes, overrides = [], [], {}
    clips = [c.model_dump(by_alias=True) if isinstance(c, ClipRef) else dict(c)
             for c in (brief.clips if clips is None else clips)]

    # content type -> preset
    ctype = (brief.content_type or "").strip().lower()
    presets = list_presets()
    preset = ctype if ctype in presets else None
    if blank(ctype):
        gaps.append(f"Content type not set ({' / '.join(presets)})")
    elif not preset:
        gaps.append(f"Unknown content type {ctype!r} ({' / '.join(presets)})")
    pcfg = load_preset(preset) if preset else {}

    talk = talk_mode(brief.talking)

    # voiceover file (Script section field, or listed in the clip order) + visual cues
    vo_field = brief.voiceover_file or ""
    vo_none = vo_field.strip().strip('"').lower() in ("none", "no", "n/a")
    vo = [] if blank(vo_field) or vo_none else clip_list(vo_field)
    if not vo and not blank(vo_field) and not vo_none:         # bare file name -> voiceover/<name>
        vo = [{"src": f"{vo_rel}/{x.strip()}", "in": None, "out": None} for x in re.split(r",", vo_field) if x.strip()]
    for c in clips:
        if is_audio(c["src"]) and not any(v["src"] == c["src"] and v["in"] == c["in"] for v in vo):
            vo.append(dict(c))
    vo_dir = _audio_files("voiceover")
    if not vo and talk in ("voiceover", "mixed") and not vo_none:
        if len(vo_dir) == 1:
            vo = [{"src": rel(vo_dir[0]), "in": None, "out": None}]
            notes.append(f"voiceover file not named: using {rel(vo_dir[0])} (the only voiceover file)")
        else:
            gaps.append(f"Talking is {talk} but which voiceover file? "
                        + (f"({vo_rel}/ has: {', '.join(x.name for x in vo_dir)})" if vo_dir else f"({vo_rel}/ is empty)"))
    if vo and talk in (None, "no"):
        notes.append(f"voiceover given, talking was {talk or 'not set'}: treating as voiceover")
        talk = "voiceover"
    elif vo and talk in ("yes", "some"):
        notes.append(f"voiceover given and talking is {talk}: treating as mixed (to camera + voiceover)")
        talk = "mixed"
    for v in vo:
        if not resolve(v["src"]).exists():
            gaps.append(f"Voiceover not found: {v['src']}"
                        + (f" ({vo_rel}/ has: {', '.join(x.name for x in vo_dir)})" if vo_dir else f" ({vo_rel}/ is empty)"))
        else:
            v["info"] = describe(ffprobe(v["src"]))
    cues, bad_cues = parse_cues(brief.visual_cues, _known_files())
    for c in cues:
        if not resolve(c["src"]).exists():
            gaps.append(f"Visual cue clip not found: {c['src']} ({c['line']})")
    for b in bad_cues:
        gaps.append(f"Visual cue not understood: {b!r} (write: when I say \"phrase\" show <clip file>)")
    if talk is None:
        talk = pcfg.get("talk_default", "some")
        notes.append(f"talking not set: using preset default ({talk})")

    grade = (brief.colour_grade or "").strip().lower()
    if not blank(grade):
        if grade in GRADES or grade.endswith(".cube"):
            overrides["grade"] = grade
        else:
            gaps.append(f"Colour grade {grade!r} not known (warm / clean-editorial / punchy / film / none, or a .cube LUT)")

    mode = (brief.mode or "").upper()
    if blank(mode) or ("ORIGINAL" in mode and "REFERENCE" in mode):
        notes.append("Mode not set: assuming ORIGINAL")
    url = brief.reference_url or ""
    is_ref = "REFERENCE" in mode and "ORIGINAL" not in mode
    if is_ref and blank(url):
        gaps.append("REFERENCE mode but no reference reel URL")

    tl = brief.target_length or ""
    target = None
    if blank(tl):
        notes.append(f"target length not set: preset typical is {pcfg.get('target_length', 30)}s")
    else:
        m = re.search(r"(\d+(?:\.\d+)?)", tl)
        target = float(m.group(1)) * (60 if "min" in tl.lower() else 1) if m else None
    if blank(brief.idea):
        gaps.append("No idea described")
    if blank(brief.hook):
        notes.append("no hook given: will open on the strongest moment")

    clips_dir = lay.dir("clips")
    raw_files = sorted(x for x in clips_dir.glob("*") if not x.name.startswith(".")) if clips_dir.exists() else []
    if not clips:
        gaps.append("No clips listed under 'Clips & order'" + (f" ({lay.dirs.get('clips', 'raw')}/ has: "
                                                                 f"{', '.join(x.name for x in raw_files)})" if raw_files
                                                                else f" and {lay.dirs.get('clips', 'raw')}/ is empty"))
    n_photos = n_videos = 0
    for c in clips:
        if is_audio(c["src"]):
            c["info"] = "voiceover"
            continue
        rp = resolve(c["src"])
        if not rp.exists():
            gaps.append(f"Not found: {c['src']}")
            continue
        if rp.is_dir():
            inner = expand([c["src"]])
            ph = sum(is_image(x[0]) for x in inner)
            c["info"] = f"folder: {ph} photos, {len(inner) - ph} clips, capture order"
            n_photos += ph
            n_videos += len(inner) - ph
            if not inner:
                gaps.append(f"Folder {c['src']} has no photos or clips")
        else:
            c["info"] = describe_media(c["src"])
            if is_image(c["src"]):
                n_photos += 1
            else:
                n_videos += 1
                info = ffprobe(c["src"])
                if c["out"] and c["out"] > info["duration"] + 0.05:
                    gaps.append(f"{c['src']}: range ends at {c['out']}s but clip is {info['duration']:.1f}s")

    if talk != "no" and blank(brief.script):
        notes.append("no script: will keep the best takes of whatever I say")

    track = brief.track or ""
    music = None
    music_files = [x for x in lay.dir("music").glob("*") if x.is_file() and not x.name.startswith(".")] \
        if lay.dir("music").exists() else []
    if blank(track):
        if auto_pick_music and len(music_files) == 1:
            music = rel(music_files[0])
            notes.append(f"music track not named: using {music_files[0].name} (the only music file)")
        elif preset in BEAT_PRESETS:
            gaps.append(f"{preset} is cut to the beat: which music track?"
                        + (f" ({', '.join(x.name for x in music_files)})" if music_files else " (no music uploaded)"))
        else:
            notes.append("no music track named")
    elif track.lower() != "none":
        cand = resolve(track) if "/" in track else lay.dir("music") / track
        if cand.exists():
            music = rel(cand)
        else:
            have = ", ".join(x.name for x in music_files) or f"{music_rel}/ is empty"
            gaps.append(f"Music file not found: {track} ({have})")
    overrides.update(beat_rule(brief.beat_sync))
    if brief.music_start is not None:
        overrides["music_start"] = round(float(brief.music_start), 3)
    if brief.music_in_app:
        if music:
            notes.append("posting with the in-app sound: the track sets the beat and the preview; each render also "
                         "exports a copy without it, with the start time to pick in Instagram/TikTok")
        elif preset not in BEAT_PRESETS:
            notes.append("posting with the in-app sound but no track uploaded: upload the same song so the cuts land "
                         "on its beat")

    cap = "" if blank(brief.captions) else (brief.captions or "").lower()
    if cap.startswith("off"):
        overrides["captions"] = "off"
    elif cap.startswith("on"):
        overrides["captions"] = "talking"
    elif talk != "no" and str(pcfg.get("captions", "talking")) in ("off", "False"):
        overrides["captions"] = "talking"
        notes.append(f"captions on for the {'voiceover' if talk == 'voiceover' else 'talking'} parts "
                     f"({preset} has them off when nobody talks; 'Captions: off' in the brief keeps them off)")
    ec = "" if blank(brief.end_card) else (brief.end_card or "").lower()
    if ec.startswith("on"):
        overrides["end_card"] = True
    elif ec.startswith("off"):
        overrides["end_card"] = False

    return {"name": name, "title": brief.title, "preset": preset, "talk": talk, "voiceover": vo, "cues": cues,
            "script": brief.script, "music": music, "music_in_app": bool(brief.music_in_app and music),
            "target_length": target,
            "style_overrides": overrides, "fields": brief.model_dump(mode="json", by_alias=True),
            "clips": clips, "labels": brief.labels, "gaps": gaps, "notes": notes,
            "mode": "REFERENCE" if is_ref else "ORIGINAL", "reference_url": url,
            "counts": {"clips": n_videos, "photos": n_photos, "voiceover": len(vo)}}


def write(out):
    """Save brief.json for the drafting step."""
    write_json(work_dir(out["name"]) / "brief.json", out)


def show(out):
    n = out["counts"]
    log(f"BRIEF {out['name']}: {out['title'] or '(untitled)'}")
    log(f"  type {out['preset'] or '?'}  talking {out['talk']}  mode {out['mode']}"
        + (f"  ref {out['reference_url']}" if out["mode"] == "REFERENCE" else ""))
    f = out["fields"]
    log(f"  length {out['target_length'] or '-'}s  platform {f.get('platform') or '-'}  "
        f"music {out['music'] or f.get('track') or '-'}"
        + (f" from {f['music_start']}s" if f.get("music_start") is not None else "")
        + (" (posting with the in-app sound)" if out.get("music_in_app") else ""))
    if out["style_overrides"]:
        log(f"  brief overrides preset: {out['style_overrides']}")
    log(f"  inputs: {n['clips']} clips, {n['photos']} photos" + (f", {n['voiceover']} voiceover" if n["voiceover"] else ""))
    for v in out["voiceover"]:
        rng = f" {v['in']}-{v['out']}s" if v["in"] is not None else ""
        log(f"    VO {v['src']}{rng}  [{v.get('info', 'MISSING')}]")
    for c in out["cues"]:
        rng = f" {c['in']}-{c['out']}s" if c["in"] is not None else ""
        log(f"    cue: when I say \"{c['say']}\" -> {c['src']}{rng}")
    for i, c in enumerate(out["clips"], 1):
        rng = f" {c['in']}-{c['out']}s" if c["in"] is not None else ""
        log(f"    {i}. {c['src']}{rng}  [{c.get('info', 'MISSING')}]")
    if out["labels"]:
        log(f"  labels: {out['labels'][:160]}")
    for n_ in out["notes"]:
        log(f"  note: {n_}")
    log("\nGAPS:" if out["gaps"] else "\nGAPS: none")
    for g in out["gaps"]:
        log(f"  - {g}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief")
    a = ap.parse_args()
    p = resolve(a.brief)
    if not p.exists():
        die(f"brief not found: {a.brief}", code="file_not_found", status=404)
    out = analyse(parse_markdown(p.read_text()), Path(p).stem)
    write(out)
    show(out)


if __name__ == "__main__":
    main()
