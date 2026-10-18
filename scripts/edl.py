"""Edit plan (work/<name>/edl.json): loading, validation, beat-synced timeline, captions, cut report.

No OpenCV / Whisper imports here, so plan.py stays light. See scripts/README.md for the format.
"""
import bisect
import difflib
import re

from common import ffprobe, load_transcript, read_json, resolve, style_for, tc, work_dir
from media import is_audio, is_image

SPEECH_GAP = 0.6
VO_PREROLL = 0.08      # a cued shot cuts in just before its word lands

# speed-ramp curves: [fraction of the shot, speed multiplier], smoothstep between points
RAMPS = {
    "slow-normal-slow": [[0, 0.35], [0.3, 1.0], [0.7, 1.0], [1, 0.35]],
    "normal-slow-normal": [[0, 1.0], [0.25, 0.35], [0.75, 0.35], [1, 1.0]],
    "in": [[0, 0.35], [0.5, 1.0], [1, 1.0]],           # slow-mo into normal speed
    "out": [[0, 1.0], [0.5, 1.0], [1, 0.35]],          # normal into slow-mo
    "fast-slow": [[0, 2.2], [0.35, 2.2], [0.5, 0.35], [1, 0.35]],
    "slow-fast": [[0, 0.35], [0.5, 0.35], [0.65, 2.2], [1, 2.2]],
}
RAMPS[True] = RAMPS["slow-normal-slow"]


def load(name):
    p = work_dir(name) / "edl.json"
    edl = read_json(p)
    if edl is None:
        raise SystemExit(f"no edit plan at {p} (run `ve draft` first, then save edl.json)")
    edl.setdefault("name", name)
    return edl


def _kind(seg):
    if seg.get("type"):
        return seg["type"]
    if seg.get("src") and is_image(seg["src"]):
        return "image"
    return "clip"


# ---------------------------------------------------------------- what is said where (visual cues)

def _word(w):
    return w.get("w", w.get("t", ""))


def _same(a, b):
    """Equal, or the same word with a plural / -ing / -ed ending ("squat" ~ "squats")."""
    if a == b:
        return True
    s, l = sorted((a, b), key=len)
    return len(s) >= 4 and l.startswith(s) and l[len(s):] in ("s", "es", "ing", "ed", "d", "'s")


def find_phrase(words, phrase, after=None, fuzzy=0.84):
    """First place `phrase` is said at or after time `after` -> (first word index, last word index, score) or None.
    Copes with word splits ("meal prep" / "mealprep"), plurals and near-misses in the transcript ("chess day")."""
    target = "".join(_norm(x) for x in str(phrase).split())
    if not target:
        return None
    toks = [_norm(_word(w)) for w in words]
    starts = [i for i, w in enumerate(words) if toks[i] and (after is None or w["s"] >= after - 1e-6)]
    for i in starts:
        acc = ""
        for j in range(i, min(len(words), i + 10)):
            acc += toks[j]
            if _same(acc, target):
                return i, j, 1.0
            if len(acc) > len(target) + 3:
                break
    if len(target) < 5 or fuzzy > 1:
        return None
    best = None
    for i in starts:
        acc = ""
        for j in range(i, min(len(words), i + 10)):
            acc += toks[j]
            if len(acc) > len(target) + 4:
                break
            r = difflib.SequenceMatcher(None, acc, target).ratio()
            if r >= fuzzy and (best is None or r > best[2] + 1e-9):
                best = (i, j, round(r, 2))
    return best


# ---------------------------------------------------------------- voiceover blocks

def vo_block(seg, t0, cfg):
    """A {"type": "vo"} segment placed at output time t0: its kept pieces and the words said, in output seconds."""
    src = seg["src"]
    tr = load_transcript(src) or {"words": []}
    dur_src = ffprobe(src)["duration"]
    keeps = seg.get("keep") or [{"in": seg.get("in", 0.0), "out": seg.get("out", dur_src)}]
    fillers = set(cfg["fillers"])
    pieces, words, off = [], [], 0.0
    for k in keeps:
        a, b = float(k["in"]), min(float(k["out"]), dur_src)
        at = t0 + off
        pieces.append({"at": round(at, 4), "in": a, "out": b})
        for w in tr["words"]:
            n = _norm(w["w"])
            if a <= (w["s"] + w["e"]) / 2 < b and n and n not in fillers:
                words.append({"w": w["w"], "s": round(at + max(w["s"], a) - a, 3),
                              "e": round(at + min(w["e"], b) - a, 3), "se": round(at + b - a, 3)})
        off += b - a
    return {"src": src, "start": t0, "dur": off, "end": t0 + off, "pieces": pieces, "words": words,
            "label": seg.get("label", ""), "captions": seg.get("captions", True), "gain_db": float(seg.get("gain_db", 0))}


def _nudge(t, words, lo, hi, tol):
    """Move a cut onto the nearest word onset (cutting as a word starts reads as intentional)."""
    best = None
    for w in words:
        c = w["s"] - VO_PREROLL
        if lo < c < hi and abs(c - t) <= tol and (best is None or abs(c - t) < abs(best - t)):
            best = c
    return t if best is None else best


def vo_shots(blk, shots):
    """Where each B-roll shot sits in a voiceover block -> [(start, end, warning)] in block seconds.
    The first shot opens the block; "at" = seconds into the block; "cue" = when that phrase is said (searching
    forward from the previous shot); "dur" on a shot pushes the next one. Shots without an anchor share the time
    to the next anchor evenly, nudged onto word onsets."""
    D, t0, n = blk["dur"], blk["start"], len(shots)
    words = [{"w": w["w"], "s": w["s"] - t0} for w in blk["words"]]
    st, warn = [None] * n, [None] * n
    st[0], after = 0.0, 0.0
    for i, sh in enumerate(shots):
        if i and shots[i - 1].get("dur") is not None and st[i - 1] is not None:
            st[i] = st[i - 1] + float(shots[i - 1]["dur"])
        if i and sh.get("at") is not None:
            st[i] = float(sh["at"])
        elif sh.get("cue"):
            m = find_phrase(words, sh["cue"], after=after)
            if m is None:
                warn[i] = f'cue "{sh["cue"]}" not found in the voiceover' + (" after the previous shot" if after else "")
            else:
                ws = words[m[0]]["s"]
                if i:
                    st[i] = max(0.0, ws - VO_PREROLL)
                elif ws > 1.5:
                    warn[i] = f'cue "{sh["cue"]}" is said at {ws:.1f}s, but this is the first shot so it opens the block'
                after = ws + 0.01
        if st[i] is not None:
            after = max(after, st[i])
    last = 0.0
    for i in range(1, n):
        if st[i] is None:
            continue
        if st[i] < last + 0.3 or st[i] > D - 0.3:
            where = "past the end of the voiceover" if st[i] > D - 0.3 else "on top of the previous shot"
            warn[i] = (warn[i] + "; " if warn[i] else "") + f"lands {where} ({st[i]:.2f}s): spaced evenly instead"
            st[i] = None
            continue
        last = st[i]
    i = 0
    while i < n:
        j = i + 1
        while j < n and st[j] is None:
            j += 1
        end = st[j] if j < n else D
        step = (end - st[i]) / (j - i)
        for r in range(1, j - i):
            st[i + r] = _nudge(st[i] + r * step, words, st[i + r - 1] + 0.3, end - 0.3, min(0.35, step * 0.3))
        i = j
    out = []
    for i in range(n):
        e = st[i + 1] if i + 1 < n else D
        w = warn[i]
        if e - st[i] < 0.3:
            w = (w + "; " if w else "") + f"only {e - st[i]:.2f}s on screen"
        out.append((st[i], e, w))
    return out


def vo_blocks(items):
    """The voiceover blocks on a timeline, in order."""
    seen, out = set(), []
    for it in items:
        b = it.get("vo")
        if b is not None and id(b) not in seen:
            seen.add(id(b))
            out.append(b)
    return out


def zoom_max(z):
    if isinstance(z, (int, float)):
        return float(z)
    if isinstance(z, list) and z:
        return max(float(k[1]) for k in z)
    return 1.0


# ---------------------------------------------------------------- ramps

def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def ramp_curve(spec):
    if not spec or spec == "none":
        return None
    if isinstance(spec, list):
        return sorted(spec)
    if spec not in RAMPS:
        raise SystemExit(f"unknown ramp {spec!r}; use one of {[k for k in RAMPS if isinstance(k, str)]} or [[f, speed], ...]")
    return RAMPS[spec]


def ramp_value(curve, f):
    if f <= curve[0][0]:
        return curve[0][1]
    for a, b in zip(curve, curve[1:]):
        if f <= b[0]:
            return a[1] + (b[1] - a[1]) * _smooth((f - a[0]) / max(1e-6, b[0] - a[0]))
    return curve[-1][1]


def ramp_mean(curve, steps=400):
    if not curve:
        return 1.0
    return sum(ramp_value(curve, (i + 0.5) / steps) for i in range(steps)) / steps


def source_offsets(it, fps):
    """Seconds into the source for every output frame of a clip item (handles speed + ramps)."""
    n, sp, curve = it["frames"], it["speed"], it.get("ramp")
    if not curve:
        return [k * sp / fps for k in range(n)]
    out, acc = [], 0.0
    dt = 1 / fps
    for k in range(n):
        out.append(acc)
        acc += sp * ramp_value(curve, (k + 0.5) / n) * dt
    return out


# ---------------------------------------------------------------- validation

def _check_src(where, sub, problems, probe):
    src = sub.get("src")
    if not src or not resolve(src).exists():
        problems.append(f"{where}: file not found: {src}")
        return
    if is_image(src):
        return
    info = probe.setdefault(src, ffprobe(src))
    a, b = sub.get("in", 0), sub.get("out")
    if b is not None and b <= a:
        problems.append(f"{where}: out ({b}) <= in ({a})")
    if b is not None and b > info["duration"] + 0.05:
        problems.append(f"{where}: out {b:.2f}s past end of {src} ({info['duration']:.2f}s)")


def validate(edl):
    problems, probe = [], {}
    has_music = bool((edl.get("music") or {}).get("src"))
    for i, seg in enumerate(edl.get("segments", []), 1):
        k = _kind(seg)
        if k in ("clip", "image") and seg.get("src") and is_audio(seg["src"]):
            problems.append(f"segment #{i}: {seg['src']} is audio: use {{\"type\": \"vo\", \"src\": ..., \"shots\": [...]}}")
        elif k in ("clip", "image"):
            _check_src(f"segment #{i}", seg, problems, probe)
        elif k == "vo":
            src = seg.get("src")
            if not src or not resolve(src).exists():
                problems.append(f"segment #{i}: voiceover not found: {src}")
            else:
                dur = probe.setdefault(src, ffprobe(src))["duration"]
                for j, kp in enumerate(seg.get("keep") or [], 1):
                    if float(kp["out"]) <= float(kp["in"]):
                        problems.append(f"segment #{i} keep {j}: out <= in")
                    elif float(kp["out"]) > dur + 0.05:
                        problems.append(f"segment #{i} keep {j}: out {kp['out']}s past the end of {src} ({dur:.2f}s)")
            if not seg.get("shots"):
                problems.append(f"segment #{i}: a voiceover block needs B-roll in \"shots\"")
            for j, sh in enumerate(seg.get("shots") or [], 1):
                sk = _kind(sh)
                if sk in ("clip", "image"):
                    _check_src(f"segment #{i} shot {j}", sh, problems, probe)
                elif sk != "color":
                    problems.append(f"segment #{i} shot {j}: unknown type {sk!r}")
        elif k == "compare":
            for side in ("a", "b"):
                if not isinstance(seg.get(side), dict):
                    problems.append(f"segment #{i}: compare needs \"a\" and \"b\"")
                else:
                    _check_src(f"segment #{i}.{side}", seg[side], problems, probe)
        elif k not in ("color", "vo"):
            problems.append(f"segment #{i}: unknown type {k!r}")
        if k in ("color",) and not seg.get("dur") and not seg.get("beats"):
            problems.append(f"segment #{i}: color needs \"dur\" or \"beats\"")
        if (seg.get("beats") or seg.get("to")) and not has_music:
            problems.append(f"segment #{i}: \"beats\"/\"to\" need a music track")
        if zoom_max(seg.get("zoom", 1.0)) < 1.0:
            problems.append(f"segment #{i}: zoom below 1.0 is not possible (crop can't zoom out)")
        if seg.get("ramp") is not None:
            try:
                ramp_curve(seg["ramp"])
            except SystemExit as e:
                problems.append(f"segment #{i}: {e}")
    for j, b in enumerate(edl.get("broll", []), 1):
        if not resolve(b.get("src", "")).exists():
            problems.append(f"broll #{j}: file not found: {b.get('src')}")
    m = edl.get("music")
    if m and m.get("src") and not resolve(m["src"]).exists():
        problems.append(f"music: file not found: {m['src']}")
    for s in edl.get("sfx", []) + ([edl["sfx_on_cuts"]] if edl.get("sfx_on_cuts") else []):
        if not resolve(s.get("src", "")).exists():
            problems.append(f"sfx: file not found: {s.get('src')}")
    for g in edl.get("graphics", []):
        if not resolve(g.get("src", "")).exists():
            problems.append(f"graphic: file not found: {g.get('src')}")
    return problems


# ---------------------------------------------------------------- beat grid

def _near(t, ts, tol=0.05):
    if not ts:
        return False
    i = bisect.bisect_left(ts, t)
    return any(abs(ts[j] - t) <= tol for j in (i - 1, i) if 0 <= j < len(ts))


def _grid_from(bt, start, at, horizon=600):
    period = 60 / bt["bpm"]
    conv = lambda xs: [round(x - start + at, 4) for x in xs if x - start + at >= -0.02]
    beats = conv(bt["beats"])
    # music loops in the render, so keep the grid going past the end of the track
    last = beats[-1] if beats else at
    while last < horizon:
        last += period
        beats.append(round(last, 4))
    return {"bpm": bt["bpm"], "period": period, "start": start, "at": at, "beats": beats,
            "downbeats": conv(bt["downbeats"]), "drops": conv(bt["drops"])}


def auto_every(period, lo, hi):
    best = None
    for n in (1, 2, 3, 4, 6, 8):
        if lo - 1e-6 <= n * period <= hi + 1e-6:
            return n
        d = min(abs(n * period - lo), abs(n * period - hi))
        if best is None or d < best[0]:
            best = (d, n)
    return best[1]


def _beat_at(grid, i):
    b = grid["beats"]
    return b[i] if i < len(b) else b[-1] + (i - len(b) + 1) * grid["period"]


def _beat_dur(t, seg, grid, every, after_drop, cfg):
    if seg.get("to") == "drop":
        nxt = [d for d in grid["drops"] if d > t + 0.3]
        if nxt:
            return nxt[0] - t
    k = seg.get("beats")
    if k is None:
        k = every
        if after_drop and grid["drops"] and t >= grid["drops"][0] - 0.05:
            k = after_drop
    if k == "auto" or not k:
        k = auto_every(grid["period"], float(cfg["shot_min"]), float(cfg["shot_max"]))
    k = max(1, int(k))
    beats = grid["beats"]
    i = bisect.bisect_left(beats, t - 0.04)
    on_beat = i < len(beats) and abs(beats[i] - t) <= 0.04
    j = i + k if on_beat else i + k - 1
    end = _beat_at(grid, j)
    while end - t < 0.15:
        j += 1
        end = _beat_at(grid, j)
    return end - t


def _snap(t, dur, grid, tol=0.12):
    e = t + dur
    beats = grid["beats"]
    i = bisect.bisect_left(beats, e)
    near = min((beats[j] for j in (i - 1, i) if 0 <= j < len(beats)), key=lambda b: abs(b - e), default=e)
    return near - t if abs(near - e) <= tol and near - t > 0.2 else dur


def _layout(segs, cfg, grid, edl):
    fps = cfg["fps"]
    bs = edl.get("beat_sync") or {}
    every = bs.get("every", cfg["beat_every"]) if grid else 0
    after_drop = bs.get("after_drop", cfg["beat_every_after_drop"]) if grid else 0
    snap = bool(grid) and (edl.get("music") or {}).get("snap_cuts", bool(every))
    items, t = [], 0.0
    moves = cfg["kb_moves"] or ["in"]
    n_img = 0

    def item(seg, kind, f0, f1, a, info, speed, curve, beat_driven):
        nonlocal n_img
        if kind == "image" and "kb" not in seg and float(cfg["kenburns"]) > 0:
            seg["kb"] = moves[n_img % len(moves)]       # light Ken Burns, cycling the preset's moves
        n_img += kind == "image"
        return {"idx": len(items) + 1, "kind": kind, "seg": seg, "src": seg.get("src"), "in": a, "out": 0.0,
                "speed": speed, "ramp": curve, "f0": f0, "frames": f1 - f0, "start": f0 / fps,
                "end": f1 / fps, "label": seg.get("label", ""), "trans_in": None, "warn": None,
                "info": info, "beat_synced": bool(beat_driven)}

    for seg in segs:
        kind = _kind(seg)
        if kind == "vo":          # voiceover: the words set the length, B-roll shots cut on cues
            f0 = round(t * fps)
            blk = vo_block(seg, f0 / fps, cfg)
            shots = [dict(sh) for sh in seg.get("shots") or []]
            spans = vo_shots(blk, shots)
            fs = []
            for s0, _, _ in spans:
                fs.append(max(round((blk["start"] + s0) * fps), fs[-1] + 1 if fs else f0))
            fs.append(max(round(blk["end"] * fps), fs[-1] + 1))
            for j, sh in enumerate(shots):
                k = _kind(sh)
                info = ffprobe(sh["src"]) if k == "clip" else None
                it = item(sh, k, fs[j], fs[j + 1], float(sh.get("in", 0)) if k == "clip" else 0.0, info,
                          float(sh.get("speed", 1.0)), ramp_curve(sh.get("ramp")), False)
                it["vo"], it["warn"] = blk, spans[j][2]
                items.append(it)
            t = fs[-1] / fps
            continue
        speed = float(seg.get("speed", 1.0))
        curve = ramp_curve(seg.get("ramp"))
        natural, a, info = None, 0.0, None
        if kind == "clip":
            info = ffprobe(seg["src"])
            a = float(seg.get("in", 0))
            if "out" in seg:
                natural = (float(seg["out"]) - a) / (speed * ramp_mean(curve))
        beat_driven = grid and ("beats" in seg or "to" in seg or (every and natural is None and "dur" not in seg))
        if "dur" in seg:
            dur = float(seg["dur"])
        elif beat_driven:
            dur = _beat_dur(t, seg, grid, every, after_drop, cfg)
        elif natural is not None:
            dur = _snap(t, natural, grid) if snap and not seg.get("talk") else natural   # never clip a word
        elif kind == "compare":
            dur = 3.0
        else:
            dur = (float(cfg["shot_min"]) + float(cfg["shot_max"])) / 2
        f0 = round(t * fps)
        f1 = max(f0 + 1, round((t + dur) * fps))
        items.append(item(seg, kind, f0, f1, a, info, speed, curve, beat_driven))
        t = f1 / fps

    # transitions + automatic speed ramps on drops
    for k, it in enumerate(items):
        seg = it["seg"]
        if k > 0:
            if "transition" in seg:
                tr = seg["transition"]
            else:
                tr = cfg["transition"]
                if seg.get("new_block") and cfg["transition_location"] != "cut":
                    tr = cfg["transition_location"]
                if grid and _near(it["start"], grid["downbeats"]) and cfg["transition_downbeat"] != "cut":
                    tr = cfg["transition_downbeat"]
                if grid and _near(it["start"], grid["drops"]) and cfg["transition_drop"] != "cut":
                    tr = cfg["transition_drop"]
            it["trans_in"] = None if tr in (None, "cut", "none") else tr
        if (grid and it["kind"] == "clip" and "ramp" not in seg and cfg["ramp_on_drop"] not in ("none", None)
                and not seg.get("talk") and _near(it["start"], grid["drops"], 0.06)):
            it["ramp"] = ramp_curve(cfg["ramp_on_drop"])

    # source ranges (now that durations and ramps are final)
    for it in items:
        if it["kind"] != "clip":
            continue
        src_len = (it["frames"] / fps) * it["speed"] * ramp_mean(it["ramp"])
        dur_src = it["info"]["duration"]
        a = it["in"]
        if a + src_len > dur_src + 0.02:
            a = max(0.0, dur_src - src_len)
            if a + src_len > dur_src + 0.02:
                it["warn"] = f"clip is {dur_src:.1f}s but the shot needs {src_len:.1f}s (last frame held)"
            elif abs(a - it["in"]) > 0.05:
                it["warn"] = f"start moved {tc(it['in'], 2)} -> {tc(a, 2)} to fit the clip"
        it["in"], it["out"] = round(a, 3), round(min(dur_src, a + src_len), 3)
    return items


def music_grid(edl, cfg, segs):
    m = edl.get("music") or {}
    if not m.get("src"):
        return None
    from beats import beats_for   # librosa only when there is music
    bt = beats_for(m["src"])
    at = float(m.get("at", 0))
    start = m.get("start", cfg["music_start"])
    downs = bt["downbeats"] or bt["beats"] or [0.0]
    if isinstance(start, (int, float)):
        return _grid_from(bt, float(start), at)
    start = str(start)
    if start == "auto":
        return _grid_from(bt, downs[0], at)
    if start.startswith("drop"):
        drops = bt["drops"]
        if not drops:
            return _grid_from(bt, downs[0], at)   # no drop found: just start on a downbeat
        beats = bt["beats"]
        di = min(range(len(beats)), key=lambda j: abs(beats[j] - drops[0]))
        if start == "drop":
            # put the first drop exactly where the segment marked "on_drop" (or "to": drop's end) begins
            target = next((k for k, s in enumerate(segs) if s.get("on_drop")), None)
            if target is None:
                return _grid_from(bt, downs[0], at)
            g0 = _grid_from(bt, beats[di], 0.0)
            pre = _layout(segs[:target], cfg, g0, edl)
            T = pre[-1]["end"] if pre else 0.0
            K = int(round(T / g0["period"]))
            if di - K >= 0:
                return _grid_from(bt, beats[di - K], at)
            return _grid_from(bt, 0.0, at + T - drops[0])   # not enough music before the drop: delay it
        n = int(start.split("-", 1)[1]) if "-" in start else 16
        return _grid_from(bt, beats[max(0, di - n)], at)
    raise SystemExit(f"music start {start!r} not understood (number, auto, drop, drop-16)")


def build_timeline(edl, cfg=None):
    """Segments -> frame-accurate output timeline. Returns (items, grid)."""
    cfg = cfg or style_for(edl)
    segs = [dict(s) for s in edl.get("segments", [])]
    grid = music_grid(edl, cfg, segs)
    items = _layout(segs, cfg, grid, edl)
    ec = end_card_cfg(edl, cfg)
    if ec:
        fps = cfg["fps"]
        t = items[-1]["end"] if items else 0.0
        f0, f1 = round(t * fps), round((t + ec["seconds"]) * fps)
        slow_push = {"zoom": [[0, 1.0], [ec["seconds"], 1.05]], "crop": "center"}
        items.append({"idx": len(items) + 1, "kind": "endcard", "seg": slow_push, "src": None, "in": 0, "out": 0,
                      "speed": 1.0, "ramp": None, "f0": f0, "frames": f1 - f0, "start": f0 / fps, "end": f1 / fps,
                      "label": "end card", "endcard": ec, "trans_in": None, "warn": None, "info": None,
                      "beat_synced": False})
    _anchor_cues(edl, items, cfg)
    return items, grid


def _anchor_cues(edl, items, cfg):
    """Overlays with "cue": "<phrase>" start when that phrase is said (to camera or in a voiceover)."""
    cued = [(key, x) for key in ("text", "broll", "sfx", "graphics", "flash") for x in edl.get(key) or []
            if isinstance(x, dict) and x.get("cue")]
    if not cued:
        return
    words = caption_words(edl, items, cfg, for_audio=True)
    for key, x in cued:
        m, after = None, None
        for _ in range(int(x.get("nth", 1))):
            m = find_phrase(words, x["cue"], after=after)
            if m is None:
                break
            after = words[m[0]]["s"] + 0.01
        pre = VO_PREROLL if key in ("broll", "graphics") else 0.0
        x["_cue_s"] = None if m is None else round(max(0.0, words[m[0]]["s"] - pre), 3)


def end_card_cfg(edl, cfg):
    ec = edl.get("end_card") or {}
    if not ec.get("enabled", cfg["end_card"]):
        return None
    logo = ec.get("logo", cfg["end_card_logo"])
    return {
        "seconds": float(ec.get("seconds", cfg["end_card_seconds"])),
        "handle": ec.get("handle", cfg["handle"]),
        "text": ec.get("text", cfg["end_card_text"]) or "",
        "logo": logo if logo and resolve(logo).exists() else None,
        "background": ec.get("background", cfg["end_card_background"]),
    }


def main_end(items):
    body = [it for it in items if it["kind"] != "endcard"]
    return body[-1]["end"] if body else 0.0


def resolve_span(item, items, default_dur=1.5):
    """An overlay item's [start, end] in output seconds. Supports {"on": "<label>|#n"}."""
    total = main_end(items)
    if item.get("cue"):
        if item.get("_cue_s") is None:
            raise SystemExit(f'cue "{item["cue"]}" is not said anywhere in the edit: {item}')
        s = item["_cue_s"] + float(item.get("offset", 0))
        e = s + float(item["dur"]) if "dur" in item else (float(item["end"]) if "end" in item else s + default_dur)
        return s, e
    if "on" in item:
        ref = item["on"]
        tgt = next((it for it in items if (str(ref).startswith("#") and it["idx"] == int(str(ref)[1:]))
                    or (it["label"] and it["label"] == ref)), None)
        if tgt is None:          # a voiceover block's label spans the whole block
            blk = [it for it in items if it.get("vo") is not None and it["vo"]["label"] and it["vo"]["label"] == ref]
            if not blk:
                raise SystemExit(f"overlay item refers to unknown segment {ref!r}: {item}")
            tgt = {"start": blk[0]["start"], "end": blk[-1]["end"]}
        s = tgt["start"] + float(item.get("offset", 0))
        e = s + float(item["dur"]) if "dur" in item else tgt["end"]
        return s, e
    s = item.get("start", item.get("at", 0))
    s = total if s == "end" else float(s)
    if "dur" in item:
        e = s + float(item["dur"])
    else:
        e = item.get("end", s + default_dur)
        e = total if e == "end" else float(e)
    return s, e


# ---------------------------------------------------------------- speech, roles, captions

def _norm(w):
    return re.sub(r"[^\w']", "", w.lower())


def transcript(src, edl):
    """Cached transcript of a clip; transcribes on demand unless no clip has talking in this video."""
    if edl.get("talk") in ("no", "voiceover"):
        return None
    return load_transcript(src, auto=True)


def has_speech(it, edl, cfg):
    seg = it["seg"]
    if seg.get("talk") is not None:
        return bool(seg["talk"])
    if it["kind"] != "clip" or not (it["info"] or {}).get("has_audio"):
        return False
    tr = transcript(it["src"], edl)
    if not tr:
        return False
    fillers = set(cfg["fillers"])
    n = sum(1 for w in tr["words"] if it["in"] <= (w["s"] + w["e"]) / 2 < it["out"] and _norm(w["w"]) not in fillers)
    return n >= 2


def seg_role(it, edl, cfg):
    """What this shot's own sound does in the mix: voice | ambient | mute."""
    seg = it["seg"]
    if it["kind"] != "clip" or seg.get("audio") is False or not (it["info"] or {}).get("has_audio"):
        return "mute"
    slow = it["speed"] < 1.0 or it.get("ramp")
    if slow and seg.get("audio") is not True:
        return "mute"
    if it.get("vo") is not None:        # B-roll under a voiceover: its own sound only if asked for
        return "ambient" if seg.get("ambient") or seg.get("audio") is True else "mute"
    if has_speech(it, edl, cfg):
        return "voice"
    if seg.get("ambient") or seg.get("audio") is True:
        return "ambient"
    has_music = bool((edl.get("music") or {}).get("src"))
    if not has_music or cfg["music_mode"] == "mix":
        return "ambient"
    return "mute"


def captions_enabled(edl, cfg):
    cap = edl.get("captions") or {}
    return cap.get("enabled", cfg["captions"] != "off")


def caption_words(edl, items, cfg, for_audio=False):
    """Spoken words on the output timeline: to-camera talking + voiceovers. for_audio=True ignores caption hiding."""
    cap = edl.get("captions") or {}
    replace = {k.lower(): v for k, v in (cap.get("replace") or {}).items()}
    fillers = set(cfg["fillers"])
    hide = [] if for_audio else (cap.get("hide") or [])
    out = []

    def add(raw, s, e, se):
        n = _norm(raw)
        if not n or n in fillers or any(a <= s < b for a, b in hide):
            return
        text = replace.get(n, replace.get(raw.lower(), raw))
        text = re.sub(r"[.,;:]+$", "", text.strip())
        out.append({"t": text, "s": round(s, 3), "e": round(e, 3), "se": se, "brk": bool(re.search(r"[.?!,]$", raw))})

    for it in items:
        if it["kind"] != "clip" or it.get("vo") is not None or seg_role(it, edl, cfg) != "voice":
            continue
        if it["seg"].get("captions") is False and not for_audio:
            continue
        tr = transcript(it["src"], edl)
        if not tr:
            continue
        for w in tr["words"]:
            if it["in"] <= (w["s"] + w["e"]) / 2 < it["out"]:
                s = it["start"] + (max(w["s"], it["in"]) - it["in"]) / it["speed"]
                e = it["start"] + (min(w["e"], it["out"]) - it["in"]) / it["speed"]
                add(w["w"], s, min(e, it["end"]), it["end"])
    for blk in vo_blocks(items):
        if blk["captions"] is not False or for_audio:
            for w in blk["words"]:
                add(w["w"], w["s"], w["e"], w["se"])
    out.sort(key=lambda w: w["s"])
    return out


def caption_pages(words, cfg, stop_at):
    pages, cur = [], []
    maxw, maxc = int(cfg["caption_max_words"]), int(cfg["caption_max_chars"])
    for w in words:
        if w["s"] >= stop_at:
            break
        if cur:
            chars = sum(len(x["t"]) + 1 for x in cur) + len(w["t"])
            gap = w["s"] - cur[-1]["e"]
            if len(cur) >= maxw or chars > maxc or gap > 0.4 or cur[-1]["brk"]:
                pages.append(cur)
                cur = []
        cur.append(w)
    if cur:
        pages.append(cur)
    out = []
    for i, p in enumerate(pages):
        nxt = pages[i + 1][0]["s"] if i + 1 < len(pages) else None
        e = p[-1]["e"] + 0.35
        if nxt is not None and nxt - p[-1]["e"] < SPEECH_GAP:
            e = nxt
        if nxt is None or nxt >= p[-1]["se"]:
            e = min(e, p[-1]["se"])          # don't hang a caption over the next shot
        e = min(e, nxt if nxt is not None else e, stop_at)
        out.append({"id": i, "s": round(p[0]["s"], 3), "e": round(e, 3),
                    "words": [{"t": w["t"], "s": w["s"], "e": w["e"]} for w in p]})
    return out


def speech_spans(words, bridge=SPEECH_GAP):
    spans = []
    for w in words:
        if spans and w["s"] - spans[-1][1] < bridge:
            spans[-1][1] = w["e"]
        else:
            spans.append([w["s"], w["e"]])
    return spans


# ---------------------------------------------------------------- cut report

def removed_report(edl):
    """Per source: ranges not used anywhere in the edit, with the words that were in them."""
    cfg = style_for(edl)
    fillers = set(cfg["fillers"])
    used = {}
    for seg in edl.get("segments", []) + edl.get("broll", []):
        if seg.get("src") and _kind(seg) == "clip" and "out" in seg:
            used.setdefault(seg["src"], []).append((float(seg.get("in", 0)), float(seg["out"])))
        if _kind(seg) == "vo" and seg.get("src"):
            for k in seg.get("keep") or [{"in": seg.get("in", 0.0), "out": seg.get("out", ffprobe(seg["src"])["duration"])}]:
                used.setdefault(seg["src"], []).append((float(k["in"]), float(k["out"])))
    sources = edl.get("sources") or [{"src": s, "in": min(a for a, _ in r), "out": max(b for _, b in r)}
                                     for s, r in used.items()]
    report = []
    for src in sources:
        if is_image(src["src"]):
            continue
        ranges = sorted(used.get(src["src"], []))
        tr = load_transcript(src["src"], auto=False) or {"words": []}
        t, gaps = src["in"], []
        for a, b in ranges + [(src["out"], src["out"])]:
            if a - t > 0.08:
                gaps.append((t, a))
            t = max(t, b)
        for a, b in gaps:
            ws = [w for w in tr["words"] if (w["s"] + w["e"]) / 2 >= a and (w["s"] + w["e"]) / 2 < b]
            if not ws:
                why = f"silence / not picked ({b - a:.1f}s)"
            elif all(_norm(w["w"]) in fillers for w in ws):
                why = "filler: " + " ".join(w["w"] for w in ws)
            else:
                why = "words: \"" + " ".join(w["w"] for w in ws) + "\""
            report.append({"src": src["src"], "in": a, "out": b, "why": why})
    return report


def fmt_span(a, b):
    return f"{tc(a)}-{tc(b)}"
