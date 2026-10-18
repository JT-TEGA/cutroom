#!/usr/bin/env python3
"""Draft an edit plan from clips, photos, folders and voiceovers, using the content-type preset.

  autocut.py --name my-video raw/intro.mp4 raw/fit.mp4@0:05-0:12 raw/shoot-oct/
  autocut.py --name my-video --preset photo-dump --music music/track.mp3 raw/oct-dump/
  autocut.py --name my-video --talk voiceover --vo voiceover/vo.m4a raw/gym/

Per input (folders expand to everything inside, in capture order):
  talking clip   -> silences, um/uh/erm and long pauses cut (word timestamps, cut points in quiet spots)
  no-talk clip   -> NO-TALK mode: best moments by sharpness / steadiness / exposure / action / faces
  photo          -> one shot (Ken Burns, blurred fill if not vertical)
  voiceover      -> cleaned, cut like talking, then B-roll laid over it: the brief's visual cues first
                    ("when I say X show raw/y.mp4"), then clips whose file/folder name is said, then the rest in
                    brief order. Voiceover mode: every clip goes under the voiceover. Mixed: a voiceover takes the
                    clips listed right after it (it goes before the first B-roll clip if it isn't in the list);
                    clips it doesn't need stay as music-only shots.
Visual cues said to camera become B-roll cutaways over the talking.
Preset + brief (work/<name>/brief.json) decide pacing, beat sync, transitions, ambient sound, end card.
Writes work/<name>/edl.draft.json (+ broll.jpg: one frame per B-roll clip, to match clips to what's said),
work/<name>/vo_preview.wav (the voiceover cleaned and cut), and prints what was kept / cut and why.
"""
import argparse
import re
import wave
from pathlib import Path

import numpy as np

from . import contact_sheet, moments, voice
from . import edl as E
from .common import (
    describe,
    die,
    ffprobe,
    load_transcript,
    parse_clip_spec,
    read_json,
    rel,
    resolve,
    style_for,
    tc,
    work_dir,
    write_json,
)
from .config import log, step
from .media import capture_time, describe_media, expand, is_audio, is_image
from .transcribe import extract_wav

SOFT_FILLERS = {"like", "basically", "literally", "actually", "so", "right", "okay", "ok"}
SOFT_PHRASES = [("you", "know"), ("i", "mean"), ("kind", "of"), ("sort", "of")]
HOOK_FIRST = {"lifestyle-outing", "photo-dump", "fashion-bts", "shoot-mashup"}


def norm(w):
    return re.sub(r"[^\w']", "", w.lower())


class Energy:
    """10 ms RMS envelope of the clip, used to drop cut points into the quietest spot."""

    def __init__(self, src):
        with wave.open(str(extract_wav(src))) as f:
            x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32)
        hop = 160  # 10 ms @ 16 kHz
        n = len(x) // hop
        self.rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1) + 1e-9) if n else np.zeros(1)

    def quietest(self, lo, hi):
        i0, i1 = max(0, int(lo * 100)), min(len(self.rms), int(hi * 100) + 1)
        if i1 <= i0:
            return (lo + hi) / 2
        return (i0 + int(np.argmin(self.rms[i0:i1]))) / 100 + 0.005


def analyse(src, a, b, cfg):
    info = ffprobe(src)
    a = a or 0.0
    b = min(b or info["duration"], info["duration"])
    tr = load_transcript(src) if info["has_audio"] else {"words": []}
    words = [w for w in tr["words"] if w["e"] > a and w["s"] < b]
    fillers = set(cfg["fillers"])
    events = []  # (kind, word)
    for w in words:
        events.append(("filler" if norm(w["w"]) in fillers or not norm(w["w"]) else "word", w))

    if not any(k == "word" for k, _ in events):
        return info, [{"in": a, "out": b, "text": "", "note": "no speech: B-roll / visual"}], [], []

    # Group spoken words into runs; break on long pauses or on a filler.
    runs, cur, last_e = [], [], None
    for kind, w in events:
        if kind == "filler":
            if cur:
                runs.append(cur)
            cur, last_e = [], None
            continue
        if cur and w["s"] - last_e > cfg["max_pause"]:
            runs.append(cur)
            cur = []
        cur.append(w)
        last_e = w["e"]
    if cur:
        runs.append(cur)

    en = Energy(src)
    filler_words = [w for k, w in events if k == "filler"]
    keeps = []
    for i, run in enumerate(runs):
        s, e = run[0]["s"] - cfg["cut_pad_in"], run[-1]["e"] + cfg["cut_pad_out"]
        # never reach into an adjacent filler or the neighbouring run
        prev_limit = max([f["e"] for f in filler_words if f["e"] <= run[0]["s"]] + [a])
        next_limit = min([f["s"] for f in filler_words if f["s"] >= run[-1]["e"]] + [b])
        if i > 0:
            prev_limit = max(prev_limit, (runs[i - 1][-1]["e"] + run[0]["s"]) / 2)
        if i < len(runs) - 1:
            next_limit = min(next_limit, (run[-1]["e"] + runs[i + 1][0]["s"]) / 2)
        s = max(s, prev_limit, a)
        e = min(e, next_limit, b)
        s = max(prev_limit, a, en.quietest(s - 0.04, min(s + 0.02, run[0]["s"])))
        e = min(next_limit, b, en.quietest(max(e - 0.02, run[-1]["e"]), e + 0.05))
        keeps.append({"in": round(s, 3), "out": round(e, 3), "text": " ".join(w["w"] for w in run)})

    # merge keeps separated by tiny gaps: a 2-3 frame cut saves nothing and reads as a glitch
    merged = []
    for k in keeps:
        if merged and k["in"] - merged[-1]["out"] < 0.12:
            merged[-1]["out"] = k["out"]
            merged[-1]["text"] += " " + k["text"]
        else:
            merged.append(k)

    # removed ranges with reasons
    removed, t = [], a
    for k in merged + [{"in": b, "out": b}]:
        if k["in"] - t > 0.05:
            inside = [w for w in words if w["s"] >= t - 0.02 and w["e"] <= k["in"] + 0.02]
            fills = [w for w in inside if norm(w["w"]) in fillers]
            if fills:
                why = "filler " + ", ".join(f'"{f["w"]}"' for f in fills)
                quiet = (k["in"] - t) - sum(f["e"] - f["s"] for f in fills)
                if quiet > 0.5:
                    why += f" + {quiet:.1f}s silence"
            elif inside:
                why = "words: " + " ".join(w["w"] for w in inside)
            else:
                why = f"silence {k['in'] - t:.1f}s"
            removed.append({"in": round(t, 3), "out": round(k["in"], 3), "why": why})
        t = max(t, k["out"])

    # things worth a human look: stutters + soft fillers (not auto-cut)
    flags, kw = [], [w for k, w in events if k == "word"]
    for i in range(len(kw) - 1):
        n0, n1 = norm(kw[i]["w"]), norm(kw[i + 1]["w"])
        if n0 and n0 == n1 and kw[i + 1]["s"] - kw[i]["e"] < 0.6:
            flags.append(f"{tc(kw[i]['s'])} repeat \"{kw[i]['w']} {kw[i + 1]['w']}\" (false start?)")
        if (n0, n1) in SOFT_PHRASES:
            flags.append(f"{tc(kw[i]['s'])} soft filler \"{kw[i]['w']} {kw[i + 1]['w']}\"")
    for w in kw:
        if norm(w["w"]) in SOFT_FILLERS:
            flags.append(f"{tc(w['s'])} soft filler \"{w['w']}\"")
        if w["p"] < 0.4:
            flags.append(f"{tc(w['s'])} unsure word \"{w['w']}\" (p={w['p']:.2f}) - check caption")
    return info, merged, removed, sorted(flags)




def speech_in(src, info, a, b, cfg):
    """True if the clip (range) has real talking, not just noise or song lyrics."""
    if not info["has_audio"]:
        return False
    tr = load_transcript(src)
    if not tr:
        return False
    fillers = set(cfg["fillers"])
    ws = [w for w in tr["words"] if w["s"] >= (a or 0) - 0.1 and w["e"] <= (b or 1e9) + 0.1
          and norm(w["w"]) and norm(w["w"]) not in fillers]
    return len(ws) >= 3 and float(np.mean([w["p"] for w in ws])) > 0.5


def beat_period(music):
    if not music:
        return None
    from .beats import beats_for
    return 60 / beats_for(music)["bpm"]


# ---------------------------------------------------------------- inputs

def broll_entry(path, s=None, e=None):
    """A no-talk clip (scored for its best moments) or a photo."""
    ct = capture_time(path)
    if is_image(path):
        return {"kind": "photo", "src": rel(resolve(path)), "t": ct}
    info = ffprobe(path)
    an = moments.analyse(path)
    return {"kind": "moments", "src": rel(resolve(path)), "t": ct, "info": info, "an": an,
            "range": (s or 0.0, min(e or info["duration"], info["duration"])), "usable": moments.usable_seconds(an)}


def vo_entry(path, s, e, cfg):
    """A voiceover: cleaned (cached), fillers / silences / long pauses cut like talking."""
    if not resolve(path).exists():
        die(f"voiceover not found: {path}")
    info = ffprobe(path)
    _, keeps, removed, flags = analyse(path, s, e, cfg)
    if not any(k["text"] for k in keeps):
        die(f"no speech found in {path}")
    stats = voice.clean(path, cfg)[1] if voice.wanted(cfg, "vo") else None
    en = {"kind": "vo", "src": rel(resolve(path)), "t": None, "info": info, "keeps": keeps, "removed": removed,
          "flags": flags, "range": (s or 0.0, min(e or info["duration"], info["duration"])), "clean": stats}
    en["seg"] = {"type": "vo", "src": en["src"], "keep": [{"in": k["in"], "out": k["out"], "text": k["text"]} for k in keeps]}
    en["words"] = E.vo_block(en["seg"], 0.0, cfg)["words"]
    return en


def talk_words(en, cfg):
    """Words kept in a to-camera clip: [(word, keep index)] in source time."""
    tr = load_transcript(en["src"]) or {"words": []}
    fillers = set(cfg["fillers"])
    out = []
    for w in tr["words"]:
        mid = (w["s"] + w["e"]) / 2
        k = next((i for i, kp in enumerate(en["keeps"]) if kp["in"] <= mid < kp["out"]), None)
        if k is not None and norm(w["w"]) and norm(w["w"]) not in fillers:
            out.append(dict(w, keep=k))
    return out


GENERIC = {"img", "vid", "video", "mov", "clip", "raw", "final", "copy", "edit", "export", "dsc", "pxl", "mvi",
           "gopr", "trim", "take", "part", "broll", "shot", "the", "and", "with", "iphone", "camera", "screen",
           "recording", "untitled", "new", "test", "day", "today", "vlog", "slomo", "cinematic", "portrait"}


def name_keywords(src):
    """Words in a clip's file / folder name that could be said ("raw/leg-day/squats_2.mp4" -> squats, leg)."""
    p = Path(src)
    out = []
    for part in [p.stem] + [d for d in p.parent.parts if d not in ("raw", ".", "")]:
        part = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)
        for t in re.split(r"[^A-Za-z]+", part):
            t = t.lower()
            if len(t) >= 3 and t not in GENERIC and t not in out:
                out.append(t)
    return out


# ---------------------------------------------------------------- voiceover: lay B-roll over what is said

def pick_in(x, length, cfg, fixed=None):
    """In point for a shot of `length` s from a B-roll clip: its best moment not used yet."""
    if x["kind"] == "photo":
        return None
    used = x.setdefault("wins", [])
    if fixed is not None:
        used.append((fixed, fixed + length))
        return round(fixed, 2)
    ws = moments.windows(x["an"], max(length * 1.1, 0.5), len(used) + 3, cfg["shake_ok"], *x["range"])
    free = [w for w in ws if all(w["out"] <= a or w["in"] >= b for a, b in used)]
    w = max(free or ws, key=lambda w: w["score"]) if (free or ws) else {"in": x["range"][0]}
    used.append((w["in"], w["in"] + length))
    return w["in"]


def plan_block(en, queue, cues, cfg):
    """B-roll shots for a voiceover block. Anchors: brief cues, then clips whose name is said; the time between
    anchors is filled with the next clips in brief order (reused if they run out)."""
    words = en["words"]
    D = sum(k["out"] - k["in"] for k in en["keeps"])
    lo, hi = float(cfg["vo_shot_min"]), float(cfg["vo_shot_max"])
    target = (lo + hi) / 2
    anchors = []

    def fits(t):
        return all(abs(t - a["t"]) >= lo for a in anchors)

    for c in cues:
        if c.get("where") is en and not c.get("done"):
            m = E.find_phrase(words, c["say"])
            if m and fits(words[m[0]]["s"]):
                anchors.append({"t": words[m[0]]["s"], "say": c["say"], "x": c["entry"], "fixed": c.get("in"),
                                "why": f'cue "{c["say"]}"' + (f" (heard \"{' '.join(w['w'] for w in words[m[0]:m[1] + 1])}\")"
                                                              if m[2] < 1 else "")})
                c["done"] = True
    taken = {id(a["x"]) for a in anchors}
    for x in queue:
        if id(x) in taken:
            continue
        for kw in name_keywords(x["src"]):
            m = E.find_phrase(words, kw, fuzzy=2)
            if m and fits(words[m[0]]["s"]):
                anchors.append({"t": words[m[0]]["s"], "say": kw, "x": x, "why": f'file name "{kw}"'})
                taken.add(id(x))
                break
    anchors.sort(key=lambda a: a["t"])
    if anchors and anchors[0]["t"] < lo:
        anchors[0]["t"] = 0.0                       # said in the first second: it opens the block
    pts = ([] if anchors and anchors[0]["t"] == 0.0 else [(0.0, None)]) + [(a["t"], a) for a in anchors]

    fresh = [x for x in queue if id(x) not in taken]
    pool = [a["x"] for a in anchors] + fresh
    if not pool:
        die(f"no B-roll for the voiceover {en['src']}: list clips after it in the brief, or add visual cues")
    shots, reuse_i = [], 0

    def filler(prev):
        nonlocal reuse_i
        if fresh:
            x = fresh.pop(0)
            return x, "brief order"
        cands = sorted(pool, key=lambda x: -(x.get("usable", 0)))
        for _ in range(len(cands)):
            x = cands[reuse_i % len(cands)]
            reuse_i += 1
            if x is not prev or len(cands) == 1:
                return x, "reused: ran out of clips"
        return cands[0], "reused: ran out of clips"

    prev = None
    for i, (p, a) in enumerate(pts):
        q = pts[i + 1][0] if i + 1 < len(pts) else D
        n = max(1, int(round((q - p) / target)))
        for r in range(n):
            if r == 0 and a:
                x, extra = a["x"], {"cue": a["say"], "why": a["why"]}
            else:
                x, why = filler(prev)
                extra = {"why": why}
            x["used"] = True
            sh = {"type": "image", "src": x["src"]} if x["kind"] == "photo" else \
                {"src": x["src"], "in": pick_in(x, (q - p) / n, cfg, a.get("fixed") if r == 0 and a else None)}
            shots.append(sh | extra)
            prev = x
    for x in queue:
        x.setdefault("used", False)
    return dict(en["seg"], shots=shots)


def cutaways(entries, cues, cfg):
    """Visual cues said to camera -> B-roll over the talking, from that word for up to vo_shot_max."""
    out = []
    for c in cues:
        en = c.get("where")
        if c.get("done") or not en or en["kind"] != "talk":
            continue
        ws = en["words"]
        m = E.find_phrase(ws, c["say"])
        w = ws[m[0]]
        k = w["keep"]
        rem = (en["keeps"][k]["out"] - w["s"]) + sum(kp["out"] - kp["in"] for kp in en["keeps"][k + 1:])
        dur = round(min(float(cfg["vo_shot_max"]), max(1.0, rem - 0.1)), 2)
        x = c["entry"]
        x["used"] = True
        b = {"src": x["src"], "cue": c["say"], "dur": dur, "why": f'cue "{c["say"]}" said to camera'}
        if x["kind"] != "photo":
            b["in"] = pick_in(x, dur, cfg, c.get("in"))
        out.append(b)
        c["done"] = True
    return out


def draft(name, clips, preset=None, talk=None, vo=None, music=None, length=None, max_pause=None):
    """Draft an edit plan -> the edl dict (also saved as work/<name>/edl.draft.json).

    clips: specs in brief order ("raw/a.mp4", "raw/a.mp4@0:05-0:12", folders, voiceover files).
    preset / talk / music / length default to work/<name>/brief.json; vo=None takes the brief's voiceovers."""
    brief = read_json(work_dir(name) / "brief.json") or {}
    preset = preset or brief.get("preset")
    cfg = style_for({"preset": preset, "style": brief.get("style_overrides") or {}})
    if max_pause is not None:
        cfg["max_pause"] = max_pause
    talk = talk or brief.get("talk") or cfg["talk_default"]
    music = music or brief.get("music")
    target = length or brief.get("target_length") or float(cfg["target_length"])
    every = cfg["beat_every"] if music else 0
    period = beat_period(music) if music else None
    if period and every:
        from .edl import auto_every
        k = auto_every(period, float(cfg["shot_min"]), float(cfg["shot_max"])) if every == "auto" else int(every)
        shot = k * period
    else:
        shot = (float(cfg["shot_min"]) + float(cfg["shot_max"])) / 2

    specs = expand(clips)
    vo_specs = [parse_clip_spec(v) for v in vo] if vo is not None else \
        [(v["src"], v.get("in"), v.get("out")) for v in brief.get("voiceover") or []]
    listed = {(rel(resolve(p)), s) for p, s, _ in specs if is_audio(p)}
    vo_extra = [v for v in vo_specs if (rel(resolve(v[0])), v[1]) not in listed]
    if (listed or vo_extra) and talk == "no":
        talk = "voiceover"
    elif (listed or vo_extra) and talk in ("yes", "some"):
        talk = "mixed"
    if talk in ("voiceover", "mixed") and not (listed or vo_extra):
        die(f"talking is {talk} but there's no voiceover: name it in the brief or pass --vo voiceover/<file>")
    cues = [dict(c) for c in brief.get("cues") or []]
    log(f"draft {name}: preset {preset or '-'}, talking {talk}, target {target:g}s, "
          f"{'music ' + str(music) if music else 'no music'}, ~{shot:.2f}s per no-talk shot")

    # 1. classify every input
    entries = []
    for k, (path, s, e) in enumerate(specs):
        step(f"analyse {Path(path).name}", 5 + 60 * k / max(1, len(specs)))
        if not resolve(path).exists():
            die(f"not found: {path}")
        if is_audio(path):
            entries.append(vo_entry(path, s, e, cfg))
            continue
        if is_image(path):
            entries.append(broll_entry(path))
            continue
        info = ffprobe(path)
        if talk in ("yes", "some", "mixed") and speech_in(path, info, s, e, cfg):
            _, keeps, removed, flags = analyse(path, s, e, cfg)
            en = {"kind": "talk", "src": rel(resolve(path)), "t": capture_time(path), "info": info, "keeps": keeps,
                  "removed": removed, "flags": flags,
                  "range": (s or 0.0, min(e or info["duration"], info["duration"]))}
            en["words"] = talk_words(en, cfg)
            entries.append(en)
        else:
            entries.append(broll_entry(path, s, e))
    if vo_extra:        # voiceover not placed in the clip order: up front (voiceover) / at the first B-roll (mixed)
        new = [vo_entry(p, s, e, cfg) for p, s, e in vo_extra]
        pos = 0 if talk == "voiceover" else \
            next((i for i, en in enumerate(entries) if en["kind"] in ("moments", "photo")), len(entries))
        entries[pos:pos] = new

    # visual cues: where each phrase is said, and which clip it shows (reserved for that moment)
    cue_notes = []
    for c in cues:
        for en in entries:
            if en["kind"] in ("vo", "talk") and E.find_phrase(en["words"], c["say"]):
                c["where"] = en
                break
        if not c.get("where"):
            cue_notes.append(f'cue "{c["say"]}" -> {c["src"]}: not said anywhere, so not used')
            continue
        src = rel(resolve(c["src"]))
        x = next((x for x in entries if x["kind"] in ("moments", "photo") and x["src"] == src), None)
        if x is None:
            x = broll_entry(c["src"], c.get("in"), c.get("out"))
            cue_notes.append(f'cue clip {c["src"]} is not in the clip list: used for its cue only')
        x["reserved"] = True
        c["entry"] = x

    # 2. voiceovers take their B-roll
    step("lay b-roll over the voiceover", 68)
    free = lambda x: x["kind"] in ("moments", "photo") and not x.get("used") and not x.get("reserved")
    for k, en in enumerate(entries):
        if en["kind"] != "vo":
            continue
        if talk == "voiceover":
            queue = [x for x in entries if free(x)]
        else:
            queue = []
            for x in entries[k + 1:]:
                if x["kind"] in ("talk", "vo"):
                    break
                if free(x):
                    queue.append(x)
            queue = queue or [x for x in entries if free(x)]
        en["block"] = plan_block(en, queue, cues, cfg)
    broll = cutaways(entries, cues, cfg)
    for c in cues:
        if c.get("where") and not c.get("done"):
            cue_notes.append(f'cue "{c["say"]}": two cues too close together, this one was dropped')

    # 3. how many music-only shots fit the target length
    talk_total = sum(k["out"] - k["in"] for en in entries if en["kind"] in ("talk", "vo") for k in en["keeps"])
    end_card = float(cfg["end_card_seconds"]) if cfg["end_card"] else 0.0
    left = [en for en in entries if free(en)]
    unused = left if talk == "voiceover" else []
    if talk == "voiceover":
        left = []
    left_ids, unused_ids = {id(x) for x in left}, {id(x) for x in unused}
    n_photos = sum(en["kind"] == "photo" for en in left)
    mom = [en for en in left if en["kind"] == "moments"]
    budget = max(0.0, target - talk_total - end_card - n_photos * shot)
    n_shots = max(len(mom) and 1, int(round(budget / shot))) if mom else 0
    alloc = {id(en): 0 for en in mom}
    if mom and cfg["one_per_clip"]:          # e.g. one clean shot per exercise
        alloc = {id(en): 1 for en in mom}
    elif mom:
        order = sorted(mom, key=lambda en: -en["usable"])
        for en in order[:n_shots]:
            alloc[id(en)] = 1
        rest = n_shots - sum(alloc.values())
        total_usable = sum(en["usable"] for en in mom) or 1
        for en in order:
            if rest <= 0:
                break
            extra = min(rest, max(0, int(en["usable"] / (shot + 0.3)) - alloc[id(en)]),
                        int(round(n_shots * en["usable"] / total_usable)))
            alloc[id(en)] += extra
            rest -= extra

    # 4. segments in input order
    segs, sources, prev_t = [], [], None
    beat_sync = bool(music and every)
    for en in entries:
        if en["kind"] == "vo":
            sources.append({"src": en["src"], "in": en["range"][0], "out": en["range"][1]})
            segs.append(en["block"])
            continue
        if en["kind"] in ("moments", "photo") and id(en) not in left_ids:
            continue
        new_block = prev_t is not None and abs(en["t"] - prev_t) > 30 * 60
        prev_t = en["t"]
        first = len(segs)
        if en["kind"] == "photo":
            seg = {"type": "image", "src": en["src"]}
            if not beat_sync:
                seg["dur"] = round(shot, 2)
            segs.append(seg)
        elif en["kind"] == "talk":
            sources.append({"src": en["src"], "in": en["range"][0], "out": en["range"][1]})
            for k in en["keeps"]:
                segs.append({"src": en["src"], "in": k["in"], "out": k["out"], "text": k["text"], "talk": True})
        else:
            n = alloc.get(id(en), 0)
            if not n:
                continue
            ws = moments.windows(en["an"], max(shot, float(cfg["shot_min"])) * 1.25, n, cfg["shake_ok"], *en["range"])
            for w in ws:
                seg = {"src": en["src"], "in": w["in"], "talk": False, "score": w["score"], "loud_db": w["loud_db"]}
                if not beat_sync:
                    seg["out"] = round(w["in"] + shot, 3)
                segs.append(seg)
        if new_block and len(segs) > first:
            segs[first]["new_block"] = True

    # 5. preset structure (talking and voiceover parts keep their order and length)
    moment_segs = [s for s in segs if s.get("talk") is False]
    is_vo = lambda s: s.get("type") == "vo"
    if preset in HOOK_FIRST and moment_segs and segs and not segs[0].get("talk") and not is_vo(segs[0]):
        best = max(moment_segs, key=lambda s: s["score"])
        segs.remove(best)
        segs.insert(0, best)
    if segs:
        head = segs[0]["shots"][0] if is_vo(segs[0]) else segs[0]
        head.setdefault("label", "hook")
    last = segs[-1] if segs else {}
    if beat_sync and cfg["hold_last_beats"] and segs and "dur" not in last and not last.get("talk") and not is_vo(last):
        segs[-1]["beats"] = int(cfg["hold_last_beats"])      # land on a held final shot
        segs[-1].setdefault("label", "last")
    share = float(cfg["ambient_share"])
    if music and cfg["music_mode"] == "lead" and share > 0:
        loud = sorted((s for s in moment_segs if s["loud_db"] > -60), key=lambda s: -s["loud_db"])
        for s in loud[: max(1, int(round(len(moment_segs) * share)))]:
            s["ambient"] = True
    edl_music = {"src": music, "start": cfg["music_start"]} if music else None
    if edl_music and brief.get("music_in_app"):
        edl_music["in_app"] = True
    visual = [s for s in segs if not s.get("talk") and not is_vo(s)]
    if preset == "transformation" and len(visual) >= 2:
        before, after = visual[0], visual[-1]
        side = lambda s: {k: v for k, v in s.items() if k in ("src", "in", "type")}
        segs = [s for s in segs if s is not after]
        before["label"] = "before"
        segs.append({"type": "compare", "a": side(before), "b": side(after), "mode": cfg["compare_mode"],
                     "labels": ["Before", "After"], "beats": 8, "on_drop": True, "label": "reveal"})
        if edl_music and not isinstance(cfg["music_start"], (int, float)):     # a start the creator picked wins
            edl_music["start"] = "drop"

    for s in segs:
        for k in ("score", "loud_db"):
            s.pop(k, None)
    notes = list(cue_notes)
    if unused:
        notes.append("not used (the voiceover is covered): " + ", ".join(x["src"] for x in unused))
    edl = {
        "name": name, "preset": preset, "talk": talk, "target_length": target,
        "style": brief.get("style_overrides") or {},
        "sources": sources, "segments": segs,
        "broll": broll, "graphics": [], "text": [], "flash": [], "sfx": [],
        "captions": {"enabled": cfg["captions"] != "off" and talk != "no", "replace": {}},
        "music": edl_music,
        "end_card": {"enabled": bool(cfg["end_card"])},
        "notes": notes,
    }
    if beat_sync:
        edl["beat_sync"] = {"every": every}

    # 6. report
    wd = work_dir(name)
    n_vo = 0
    for en in entries:
        if en["kind"] == "photo":
            if id(en) in left_ids or en.get("used"):
                log(f"  PHOTO  {en['src']}  [{describe_media(en['src'])}]")
        elif en["kind"] in ("talk", "vo"):
            kept = sum(k["out"] - k["in"] for k in en["keeps"])
            log(f"\n== {'VOICEOVER' if en['kind'] == 'vo' else 'TALK'} {en['src']}  [{describe(en['info'])}]  keeps {kept:.1f}s")
            ev = [("KEEP", k["in"], k["out"], f'"{k["text"]}"') for k in en["keeps"]]
            ev += [("cut ", r["in"], r["out"], r["why"]) for r in en["removed"]]
            for kind, i, o, txt in sorted(ev, key=lambda x: x[1]):
                log(f"  {kind} {tc(i, 2)}-{tc(o, 2)}  {txt}")
            for f in en["flags"]:
                log(f"  ? {f}")
            if en["kind"] == "vo":
                n_vo += 1
                if en["clean"]:
                    log(f"  cleaned: {voice.summary(en['clean'])}")
                pv = voice.preview(en["src"], en["keeps"], wd / f"vo_preview{'' if n_vo == 1 else '_' + str(n_vo)}.wav", cfg)
                log(f"  listen: {rel(pv)}  (cleaned + cut, as it will sound)")
                blk = E.vo_block(en["block"], 0.0, cfg)
                log("  MATCH-UP (what you say -> what we see):")
                for sh, (s0, e0, warn) in zip(en["block"]["shots"], E.vo_shots(blk, en["block"]["shots"])):
                    heard = " ".join(w["w"] for w in blk["words"] if s0 - 0.02 <= w["s"] < e0 - 0.02)
                    at = f" @{tc(sh['in'], 1)}" if "in" in sh else ""
                    log(f"    {tc(s0, 1)}-{tc(e0, 1)}  {sh['src']}{at}  \"{heard}\"  <- {sh.get('why', '')}"
                          + (f"  !! {warn}" if warn else ""))
        else:
            picked = [s for s in segs if s.get("src") == en["src"] and s.get("talk") is False]
            if picked or id(en) not in unused_ids:
                log(f"  CLIP   {en['src']}  [{describe(en['info'])}]  usable {en['usable']:.1f}s, "
                      f"picked {', '.join(tc(s['in'], 1) for s in picked) or ('under the voiceover' if en.get('used') else 'nothing')}")
    for b in broll:
        log(f"  CUTAWAY {b['src']} over the talking when you say \"{b['cue']}\" ({b['dur']:.1f}s)")
    for n in notes:
        log(f"  ! {n}")
    ids = {id(x) for x in entries}
    pool = [x for x in entries if x["kind"] in ("moments", "photo")] + \
        [c["entry"] for c in cues if c.get("entry") and id(c["entry"]) not in ids]
    if (n_vo or cues) and pool:
        board = contact_sheet.board([(x["src"], None if x["kind"] == "photo" else
                                      (moments.windows(x["an"], 0.5, 1, True, *x["range"]) or [{"in": x["range"][0]}])[0]["in"])
                                     for x in pool], wd / "broll.jpg")
        log(f"  B-roll overview (one frame per clip, for matching clips to what's said): {rel(board)}")
    step("draft", 95)
    out = write_json(wd / "edl.draft.json", edl)
    log(f"\n{sum(len(s['shots']) if is_vo(s) else 1 for s in segs)} shots, talking {talk_total:.1f}s"
          + (f", cuts every {every} beat(s)" if beat_sync else ""))
    log(f"draft -> {rel(out)}   (review, add labels/text, save as edl.json)")
    return edl


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="video name, e.g. oct-dump")
    ap.add_argument("clips", nargs="+", help="raw/file.mp4, raw/file.mp4@0:05-0:12, raw/photo.heic, a folder, "
                                             "or voiceover/vo.m4a where the voiceover goes")
    ap.add_argument("--preset", help="content type (default: from the brief)")
    ap.add_argument("--talk", choices=["yes", "no", "some", "voiceover", "mixed"],
                    help="talking in this video? (default: brief/preset)")
    ap.add_argument("--vo", nargs="*", help="voiceover file(s), file@0:00-0:20 ok (default: from the brief)")
    ap.add_argument("--music", help="music track (default: from the brief)")
    ap.add_argument("--length", type=float, help="target length in seconds")
    ap.add_argument("--max-pause", type=float, help="longest pause kept inside a phrase (s)")
    a = ap.parse_args()
    draft(a.name, a.clips, a.preset, a.talk, a.vo, a.music, a.length, a.max_pause)


if __name__ == "__main__":
    main()
