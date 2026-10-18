#!/usr/bin/env python3
"""Read a brief, load its content-type preset, list the inputs, and flag anything missing or unclear.

  brief.py briefs/my-video.md

Writes work/<name>/brief.json (preset, talk, voiceover, visual cues, music, target length, brief overrides).
The GAPS list is the raw material for the single round of questions before editing.

Talking: yes | no | some | voiceover (a recording in voiceover/ over B-roll) | mixed (to camera + voiceover
+ music-only parts). Naming a voiceover file with talking "no" means voiceover; with "yes"/"some" it means mixed.
"""
import argparse
import re
from pathlib import Path

from common import ROOT, describe, ffprobe, list_presets, load_preset, parse_tc, rel, resolve, work_dir, write_json
from media import AUDIO_EXT, describe_media, expand, is_audio, is_image

PLACEHOLDER = re.compile(r"^\(.*\)$|^\[.*\]$")
CHOICES = {"Reels / TikTok / both", "ORIGINAL / REFERENCE", "On / off", "yes / no / some parts",
           "yes / no / some parts / voiceover / mixed", "on / off / preset default"}
SCRIPT_FIELD = re.compile(r"^\s*[-*]\s*(voiceover file|visual cues)\s*:\s*(.*)$", re.I)
BEAT_PRESETS = {"photo-dump", "shoot-slideshow", "shoot-mashup", "transformation"}
GRADES = {"none", "warm", "clean-editorial", "punchy", "film"}


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
    return (title.group(1).strip() if title else ""), body, fields


def blank(v):
    v = (v or "").strip()
    return not v or bool(PLACEHOLDER.match(v)) or v in CHOICES or "preset default" == v.lower()


def body_text(body, key):
    """Section text without bullet fields like '- End card ...'."""
    return "\n".join(l for l in body.get(key, "").splitlines() if not re.match(r"^\s*-\s*[^:]+:", l)).strip()


def clip_list(text):
    """Pull raw/... (and voiceover/...) paths and folders (+ optional time ranges) out of free text."""
    out = []
    for m in re.finditer(r"((?:raw|assets|voiceover)/[^\s,;)\"'”’]*)(?:\s+(\d[\d:.]*)\s*[-–]\s*(\d[\d:.]*))?", text):
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
        if cur == "visual cues" and line.strip() and (re.search(r"\b(raw|assets)/", line) or re.match(r"^\s+[-*•]", line)):
            cues.append(line.strip())
            continue
        cur = None
        script.append(line)
    return "\n".join(script).strip(), vo, cues


def parse_cues(lines):
    """'when I say "meal prep" show raw/meal.mp4' -> [{"say", "src", "in", "out"}], plus lines not understood."""
    cues, bad = [], []
    for chunk in re.split(r"[;\n]+", "\n".join(lines)):
        c = chunk.strip(" -*•\t")
        if not c or blank(c):
            continue
        clips = [x for x in clip_list(c) if not x["src"].startswith("voiceover/")]
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief")
    a = ap.parse_args()
    p = resolve(a.brief)
    if not p.exists():
        raise SystemExit(f"brief not found: {a.brief}")
    name = p.stem
    title, body, f = parse(p.read_text())
    gaps, notes, overrides = [], [], {}

    # content type -> preset
    ctype = (f.get("content type") or "").strip().lower()
    presets = list_presets()
    preset = ctype if ctype in presets else None
    if blank(ctype):
        gaps.append(f"Content type not set ({' / '.join(presets)})")
    elif not preset:
        gaps.append(f"Unknown content type {ctype!r} ({' / '.join(presets)})")
    pcfg = load_preset(preset) if preset else {}

    talk_raw = "" if blank(f.get("talking in this video?")) else f.get("talking in this video?", "").lower()
    talk = "mixed" if "mix" in talk_raw else "voiceover" if re.search(r"voice|\bvo\b", talk_raw) else \
        "yes" if talk_raw.startswith("yes") else "no" if talk_raw.startswith("no") else \
        "some" if "some" in talk_raw else None

    # voiceover file (Script section field, or listed in the clip order) + visual cues
    script, vo_field, cue_lines = script_parts(body.get("script / talking points", ""))
    vo_none = vo_field.strip().strip('"').lower() in ("none", "no", "n/a")
    vo = [] if blank(vo_field) or vo_none else clip_list(vo_field)
    if not vo and not blank(vo_field) and not vo_none:         # bare file name -> voiceover/<name>
        vo = [{"src": f"voiceover/{x.strip()}", "in": None, "out": None} for x in re.split(r",", vo_field) if x.strip()]
    clips = clip_list(body.get("clips & order", ""))
    for c in clips:
        if is_audio(c["src"]) and not any(v["src"] == c["src"] and v["in"] == c["in"] for v in vo):
            vo.append(dict(c))
    vo_dir = sorted(x for x in (ROOT / "voiceover").glob("*") if x.suffix.lower() in AUDIO_EXT) \
        if (ROOT / "voiceover").exists() else []
    if not vo and talk in ("voiceover", "mixed") and not vo_none:
        if len(vo_dir) == 1:
            vo = [{"src": rel(vo_dir[0]), "in": None, "out": None}]
            notes.append(f"voiceover file not named: using {rel(vo_dir[0])} (the only file in voiceover/)")
        else:
            gaps.append(f"Talking is {talk} but which voiceover file? "
                        + (f"(voiceover/ has: {', '.join(x.name for x in vo_dir)})" if vo_dir else "(voiceover/ is empty)"))
    if vo and talk in (None, "no"):
        notes.append(f"voiceover given, talking was {talk or 'not set'}: treating as voiceover")
        talk = "voiceover"
    elif vo and talk in ("yes", "some"):
        notes.append(f"voiceover given and talking is {talk}: treating as mixed (to camera + voiceover)")
        talk = "mixed"
    for v in vo:
        if not resolve(v["src"]).exists():
            gaps.append(f"Voiceover not found: {v['src']}"
                        + (f" (voiceover/ has: {', '.join(x.name for x in vo_dir)})" if vo_dir else " (voiceover/ is empty)"))
        else:
            v["info"] = describe(ffprobe(v["src"]))
    cues, bad_cues = parse_cues(cue_lines)
    for c in cues:
        if not resolve(c["src"]).exists():
            gaps.append(f"Visual cue clip not found: {c['src']} ({c['line']})")
    for b in bad_cues:
        gaps.append(f"Visual cue not understood: {b!r} (write: when I say \"phrase\" show raw/clip.mp4)")
    if talk is None:
        talk = pcfg.get("talk_default", "some")
        notes.append(f"talking not set: using preset default ({talk})")

    grade = (f.get("colour grade") or f.get("color grade") or "").strip().lower()
    if not blank(grade):
        if grade in GRADES or grade.endswith(".cube"):
            overrides["grade"] = grade
        else:
            gaps.append(f"Colour grade {grade!r} not known (warm / clean-editorial / punchy / film / none, or a .cube LUT)")

    mode = (f.get("mode") or "").upper()
    if blank(mode) or ("ORIGINAL" in mode and "REFERENCE" in mode):
        notes.append("Mode not set: assuming ORIGINAL")
    url = f.get("reference reel url (reference mode only)", "")
    is_ref = "REFERENCE" in mode and "ORIGINAL" not in mode
    if is_ref and blank(url):
        gaps.append("REFERENCE mode but no reference reel URL")

    tl = f.get("target length", "")
    target = None
    if blank(tl):
        notes.append(f"target length not set: preset typical is {pcfg.get('target_length', 30)}s")
    else:
        m = re.search(r"(\d+(?:\.\d+)?)", tl)
        target = float(m.group(1)) * (60 if "min" in tl.lower() else 1) if m else None
    if blank(body.get("the idea")):
        gaps.append("No idea described")
    if blank(body.get("hook (first 2 seconds)")):
        notes.append("no hook given: will open on the strongest moment")

    raw_files = sorted(x for x in (ROOT / "raw").glob("*") if not x.name.startswith("."))
    if not clips:
        gaps.append("No clips listed under 'Clips & order'" + (f" (raw/ has: {', '.join(x.name for x in raw_files)})" if raw_files else " and raw/ is empty"))
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

    if talk != "no" and blank(script):
        notes.append("no script: will keep the best takes of whatever I say")

    track = f.get("track", "")
    music = None
    if blank(track):
        if preset in BEAT_PRESETS:
            gaps.append(f"{preset} is cut to the beat: which track in music/?")
        else:
            notes.append("no music track named")
    elif track.lower() != "none":
        cand = resolve(track) if "/" in track else resolve(f"music/{track}")
        if cand.exists():
            music = rel(cand)
        else:
            have = ", ".join(x.name for x in (ROOT / "music").glob("*") if x.is_file()) or "music/ is empty"
            gaps.append(f"Music file not found: {track} ({have})")
    overrides.update(beat_rule(f.get("beat sync")))

    cap = "" if blank(f.get("captions")) else f.get("captions", "").lower()
    if cap.startswith("off"):
        overrides["captions"] = "off"
    elif cap.startswith("on"):
        overrides["captions"] = "talking"
    elif talk != "no" and str(pcfg.get("captions", "talking")) in ("off", "False"):
        overrides["captions"] = "talking"
        notes.append(f"captions on for the {'voiceover' if talk == 'voiceover' else 'talking'} parts "
                     f"({preset} has them off when nobody talks; 'Captions: off' in the brief keeps them off)")
    ec = "" if blank(f.get("end card with my handle")) else f.get("end card with my handle", "").lower()
    if ec.startswith("on"):
        overrides["end_card"] = True
    elif ec.startswith("off"):
        overrides["end_card"] = False

    labels = body_text(body, "labels & stickers")
    out = {"name": name, "title": title, "preset": preset, "talk": talk, "voiceover": vo, "cues": cues,
           "script": script, "music": music, "target_length": target,
           "style_overrides": overrides, "fields": f, "sections": body, "clips": clips, "labels": labels,
           "gaps": gaps, "notes": notes, "mode": "REFERENCE" if is_ref else "ORIGINAL", "reference_url": url}
    write_json(work_dir(name) / "brief.json", out)

    print(f"BRIEF {name}: {title or '(untitled)'}")
    print(f"  type {preset or '?'}  talking {talk}  mode {out['mode']}" + (f"  ref {url}" if is_ref else ""))
    print(f"  length {target or '-'}s  platform {f.get('platform', '') or '-'}  music {music or track or '-'}")
    if overrides:
        print(f"  brief overrides preset: {overrides}")
    print(f"  inputs: {n_videos} clips, {n_photos} photos" + (f", {len(vo)} voiceover" if vo else ""))
    for v in vo:
        rng = f" {v['in']}-{v['out']}s" if v["in"] is not None else ""
        print(f"    VO {v['src']}{rng}  [{v.get('info', 'MISSING')}]")
    for c in cues:
        rng = f" {c['in']}-{c['out']}s" if c["in"] is not None else ""
        print(f"    cue: when I say \"{c['say']}\" -> {c['src']}{rng}")
    for i, c in enumerate(clips, 1):
        rng = f" {c['in']}-{c['out']}s" if c["in"] is not None else ""
        print(f"    {i}. {c['src']}{rng}  [{c.get('info', 'MISSING')}]")
    if labels:
        print(f"  labels: {labels[:160]}")
    for n in notes:
        print(f"  note: {n}")
    print("\nGAPS:" if gaps else "\nGAPS: none")
    for g in gaps:
        print(f"  - {g}")


if __name__ == "__main__":
    main()
