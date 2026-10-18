#!/usr/bin/env python3
"""Render work/<name>/edl.json -> output/<name>.mp4 + output/<name>_contact.jpg

  render.py my-video            # full quality
  render.py my-video --draft    # quicker encode for checking
  render.py my-video --no-sheet

Stages (each cached, so a revision only redoes what changed):
  1. shots:   decode (time-remapped for speed/ramps) -> face-aware 9:16 framing, Ken Burns, zoom,
              handheld drift, whip/zoom transitions, split/swipe compares -> work/<name>/segments
  2. overlay: captions, labels, stickers, cards, end card rendered by Puppeteer (transparent PNGs)
  3. audio:   voice (to camera + cleaned voiceover) / ambient / music (ducked) / SFX, loudness-normalised
  4. export:  colour grade + grain under the text layer -> H.264/AAC MP4, then the contact sheet
"""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import wave

import cv2
import numpy as np

from . import contact_sheet, voice
from . import edl as E
from .common import (
    FF,
    die,
    ffprobe,
    file_key,
    need,
    rel,
    resolve,
    run,
    run_streaming,
    style_for,
    tc,
    work_dir,
    write_json,
)
from .config import layout, log, paths, step
from .facetrack import at as face_at
from .facetrack import still_face, track_for
from .media import is_image, photo_path

VERSION = 3          # bump to invalidate cached segments after changing render code
SR = 48000
VOICE_REF_LUFS = -16.0
TAG709 = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
TRANS_FRAMES = 6

# colour grades: (filters that work on YUV, filters that need RGB)
GRADES = {
    "none": ([], []),
    "warm": (["eq=contrast=1.04:saturation=1.10:gamma=0.98"],
             ["colortemperature=temperature=5200:mix=0.6:pl=0.3"]),
    "clean-editorial": (["eq=contrast=1.06:saturation=0.90:brightness=0.012"],
                        ["colorbalance=rs=-0.015:bs=0.02:rh=0.01:bh=-0.01", "curves=all='0/0.025 0.5/0.5 1/0.985'"]),
    "punchy": (["eq=contrast=1.16:saturation=1.25:gamma=0.97", "unsharp=5:5:0.45"], ["vibrance=intensity=0.18"]),
    "film": (["eq=saturation=0.86"],
             ["curves=all='0/0.07 0.25/0.25 0.5/0.5 0.75/0.76 1/0.93'", "colorbalance=rs=0.035:bs=-0.03:rh=0.02:bh=-0.035"]),
}


def h(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def even(x):
    return max(2, int(round(x / 2)) * 2)


def hex_bgr(c):
    c = c.lstrip("#")
    return (int(c[4:6], 16), int(c[2:4], 16), int(c[0:2], 16))


def ease(x):
    x = min(1.0, max(0.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


# ------------------------------------------------------------------ frame sources

def decode_size(info, fit, zmax, W, H):
    """Decode only as big as the framing needs (saves a lot on 4K footage)."""
    sw, sh = info["width"], info["height"]
    A = W / H
    if fit in ("blur", "auto"):
        need_scale = max((W * zmax / sw) if sw / sh >= A else (H * zmax / sh), W * zmax / min(sw, sh * A) if fit == "auto" else 0)
    else:
        need_scale = W * zmax / min(sw, sh * A)
    f = min(1.0, need_scale * 1.05)
    return even(sw * f), even(sh * f)


def _decode(src, info, t_in, span, dec_fps, size):
    """Yield BGR frames at a constant dec_fps from t_in (HDR -> SDR via VideoToolbox, rotation handled)."""
    w, hh = size
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    seek = ["-ss", f"{t_in:.3f}", "-t", f"{span:.3f}"]
    tail = f"fps={dec_fps:.4f}"

    def sw_cmd():
        return base + seek + ["-i", str(resolve(src)), "-an", "-vf", f"{tail},scale={w}:{hh}:flags=lanczos,format=bgr24",
                              "-f", "rawvideo", "-"]

    def hdr_cmd():
        rot = info.get("rotation", 0)
        cw, ch = (hh, w) if rot in (90, 270) else (w, hh)
        dl = "p010le" if "10" in (info.get("pix_fmt") or "") else "nv12"
        rotf = {90: ",transpose=clock", 270: ",transpose=cclock", 180: ",hflip,vflip"}.get(rot, "")
        vf = (f"scale_vt=w={cw}:h={ch}:color_matrix=bt709:color_primaries=bt709:color_transfer=bt709,"
              f"hwdownload,format={dl},format=yuv420p{rotf},{tail},format=bgr24")
        return base + ["-noautorotate", "-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox_vld"] \
            + seek + ["-i", str(resolve(src)), "-an", "-vf", vf, "-f", "rawvideo", "-"]

    size_b = w * hh * 3
    cmds = [hdr_cmd(), sw_cmd()] if info.get("hdr") else [sw_cmd()]
    for attempt, cmd in enumerate(cmds):
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        got = 0
        try:
            while True:
                buf = p.stdout.read(size_b)
                if len(buf) < size_b:
                    break
                got += 1
                yield np.frombuffer(buf, np.uint8).reshape(hh, w, 3)
        finally:
            p.stdout.close()
            p.kill()
            p.wait()
        if got == 0 and attempt + 1 < len(cmds):
            log(f"    ! HDR tone-mapping failed for {src}, falling back to plain conversion")
            continue
        if got == 0:
            raise RuntimeError(f"could not decode {src} at {t_in:.2f}s: {p.stderr.read().decode()[-400:]}")
        return


def clip_frames(src, info, t_in, offsets, size, fps_out, blend=True):
    """One frame per entry of `offsets` (seconds after t_in, non-decreasing). Uses the source's real
    frames for slow-mo (60/120 fps clips) and blends neighbours when there aren't enough."""
    src_fps = float(info.get("fps") or 30)
    steps = [b - a for a, b in zip(offsets, offsets[1:]) if b - a > 1e-6]
    need_fps = 1.0 / min(steps) if steps else fps_out
    dec_fps = max(1.0, min(src_fps, need_fps))
    do_blend = blend and need_fps > dec_fps * 1.2
    gen = _decode(src, info, t_in, offsets[-1] + 3.0 / dec_fps, dec_fps, size)
    buf, last = {}, [-1, None, False]   # last index, last frame, eof

    def get(j):
        while last[0] < j and not last[2]:
            f = next(gen, None)
            if f is None:
                last[2] = True
                break
            last[0] += 1
            buf[last[0]] = f
            last[1] = f
            for k in [k for k in buf if k < last[0] - 1]:
                del buf[k]
        return buf.get(j, last[1])

    for off in offsets:
        x = off * dec_fps
        j0 = int(x)
        frac = x - j0
        if do_blend and 0.12 < frac < 0.88:
            a, b = get(j0), get(j0 + 1)
            yield a if b is None or a is b else cv2.addWeighted(a, 1 - frac, b, frac, 0)
        else:
            yield get(j0 if frac < 0.5 else j0 + 1)
    gen.close()


def load_still(src, max_side=3200):
    img = cv2.imread(str(photo_path(src)), cv2.IMREAD_COLOR)   # HEIC etc. converted; EXIF orientation applied
    if img is None:
        raise RuntimeError(f"could not read image {src}")
    s = max_side / max(img.shape[:2])
    if s < 1:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return img


# ------------------------------------------------------------------ framing

def zoom_at(spec, t):
    """Number, or keyframes [[t, z], [t, z, "cut"], ...] (t = seconds into the shot)."""
    if isinstance(spec, (int, float)):
        return float(spec)
    if not spec:
        return 1.0
    ks = sorted(spec, key=lambda k: k[0])
    if t <= ks[0][0]:
        return float(ks[0][1])
    for a, b in zip(ks, ks[1:]):
        if t < b[0]:
            if len(b) > 2 and b[2] == "cut":
                return float(a[1])
            x = (t - a[0]) / max(1e-6, b[0] - a[0])
            x = x * x * (3 - 2 * x)
            return float(a[1]) + (float(b[1]) - float(a[1])) * x
    return float(ks[-1][1])


def _noise(t, seed, f1, f2):
    r = np.random.default_rng(seed)
    p1, p2 = r.uniform(0, 2 * math.pi, 2)
    return 0.6 * math.sin(2 * math.pi * f1 * t + p1) + 0.4 * math.sin(2 * math.pi * f2 * t + p2)


def compose(img, seg, t_rel, t_src, track, W, H, cfg, kind="clip", p=0.0, zmul=1.0, seed=0):
    """Frame a source image into W x H: fit (crop / blur / auto), face, zoom, Ken Burns, handheld."""
    dh, dw = img.shape[:2]
    z = zoom_at(seg.get("zoom", 1.0), t_rel) * zmul
    fx = fy = 0.0                        # Ken Burns pan, fraction of the spare room (-0.5..0.5)
    kb = seg.get("kb")
    if kb and kb != "none":
        amt = float(seg.get("kb_amount", cfg["kenburns"]))
        e = ease(p)
        if kb == "in":
            z *= 1 + amt * e
        elif kb == "out":
            z *= 1 + amt * (1 - e)
        else:
            z *= 1 + amt
            fx = {"left": 0.5 - e, "right": e - 0.5}.get(kb, 0.0)
            fy = {"up": 0.5 - e, "down": e - 0.5}.get(kb, 0.0)
    hh = float(seg.get("handheld", cfg["handheld"]))
    if hh:
        z *= 1 + 0.035 * hh
    fit = seg.get("fit") or (cfg["photo_fit"] if kind == "image" else "crop")
    if fit == "auto":
        fit = "crop" if dh > dw * 1.05 else "blur"
    crop = seg.get("crop", "face")
    face = face_at(track, t_src) if (crop == "face" and track) else None
    if isinstance(crop, dict):
        face = (float(crop.get("x", 0.5)), float(crop.get("y", 0.5)), None)

    if fit == "blur":
        small = cv2.resize(img, (max(2, W // 12), max(2, H // 12)), interpolation=cv2.INTER_AREA)
        bg = cv2.GaussianBlur(small, (0, 0), 3)
        bg = (cv2.resize(bg, (W, H), interpolation=cv2.INTER_LINEAR) * 0.55).astype(np.uint8)
        s = min(W / dw, H / dh) * z
        cx = (face[0] if face and z > 1 else 0.5) * dw
        ox = W / 2 - cx * s + fx * 0.08 * W
        oy = (H - dh * s) / 2 + fy * 0.08 * H
        M = np.float32([[s, 0, ox], [0, s, oy]])
        M = _handheld(M, t_rel, hh, W, H, seed)
        return cv2.warpAffine(img, M, (W, H), dst=bg, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)

    A = W / H
    if dw / dh > A:
        ch0, cw0 = dh, dh * A
    else:
        cw0, ch0 = dw, dw / A
    cw, ch = cw0 / z, ch0 / z
    if face:
        cx = face[0] * dw
        cy = face[1] * dh + (0.12 * ch if face[2] is not None else 0)
    else:
        cx, cy = dw / 2, dh / 2
    cx += fx * (dw - cw)
    cy += fy * (dh - ch)
    x0 = min(max(cx - cw / 2, 0), dw - cw)
    y0 = min(max(cy - ch / 2, 0), dh - ch)
    s = W / cw
    M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
    M = _handheld(M, t_rel, hh, W, H, seed)
    flags = cv2.INTER_CUBIC if s > 1.3 else cv2.INTER_LINEAR
    return cv2.warpAffine(img, M, (W, H), flags=flags, borderMode=cv2.BORDER_REPLICATE)


def _handheld(M, t, amount, W, H, seed):
    if not amount:
        return M
    ang = 0.45 * amount * _noise(t, seed, 0.55, 1.3)
    tx = 0.010 * amount * W * _noise(t, seed + 1, 0.7, 1.7)
    ty = 0.008 * amount * H * _noise(t, seed + 2, 0.5, 1.1)
    R = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0)
    R[0, 2] += tx
    R[1, 2] += ty
    M3 = np.vstack([M, [0, 0, 1]])
    return (np.vstack([R, [0, 0, 1]]) @ M3)[:2].astype(np.float32)


def whip(frame, shift, blur):
    W = frame.shape[1]
    M = np.float32([[1, 0, shift], [0, 1, 0]])
    out = cv2.warpAffine(frame, M, (W, frame.shape[0]), borderMode=cv2.BORDER_REFLECT)
    k = int(blur) | 1
    if k > 2:
        out = cv2.blur(out, (k, 1))
    return out


def encoder(out, W, H, fps, crf=12, preset="veryfast"):
    cmd = FF + ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                "-vf", f"scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,{TAG709}",
                "-c:v", "libx264", "-preset", preset, "-crf", str(crf), str(out)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def needs_reframe(info, W, H, zmax):
    return abs(info["width"] / info["height"] - W / H) > 0.02 or zmax > 1.0


def source_for(sub, kind, n, fps, W, H, cfg, offsets=None, t_in=0.0):
    """(frame generator, face track) for a clip or photo framed into W x H."""
    zmax = E.zoom_max(sub.get("zoom", 1.0)) * (1 + float(cfg["kenburns"])) * (1 + 0.035 * float(cfg["handheld"]))
    if kind == "image":
        img = load_still(sub["src"])
        track = None
        if sub.get("crop", "face") == "face":
            f = still_face(img)
            track = {"t": [0.0], "x": [f[0]], "y": [f[1]], "size": [f[2]]} if f else None
        return (img for _ in range(n)), track
    info = ffprobe(sub["src"])
    track = track_for(sub["src"]) if sub.get("crop", "face") == "face" and needs_reframe(info, W, H, zmax) else None
    fit = sub.get("fit", "crop")
    size = decode_size(info, fit, zmax, W, H)
    offsets = offsets if offsets is not None else [k * float(sub.get("speed", 1.0)) / fps for k in range(n)]
    return clip_frames(sub["src"], info, t_in, offsets, size, fps, sub.get("blend", True)), track


def render_video(it, out, cfg, still=None, trans_out=None):
    W, H, fps = cfg["width"], cfg["height"], cfg["fps"]
    seg, kind, n = it["seg"], it["kind"], it["frames"]
    seed = int(h([seg.get("src"), it["idx"]])[:6], 16)
    enc = encoder(out, W, H, fps)
    try:
        if kind == "compare":
            frames = compare_frames(it, cfg)
        else:
            if kind == "clip":
                offs = E.source_offsets(it, fps)
                gen, track = source_for(seg, kind, n, fps, W, H, cfg, offs, it["in"])
            elif kind == "image":
                gen, track = source_for(seg, kind, n, fps, W, H, cfg)
                offs = [0.0] * n
            else:
                img = still if kind == "endcard" else np.full((H, W, 3), hex_bgr(seg.get("color", "#000000")), np.uint8)
                gen, track, offs = (img for _ in range(n)), None, [0.0] * n
            frames = (compose(img, seg, i / fps, it["in"] + offs[i], track, W, H, cfg,
                              kind=kind, p=i / max(1, n - 1), zmul=_trans_zoom(i, n, it["trans_in"], trans_out), seed=seed)
                      for i, img in enumerate(gen))
        k = TRANS_FRAMES
        for i, frame in enumerate(frames):
            if it["trans_in"] == "whip" and i < k:
                q = (i + 1) / (k + 1)
                frame = whip(frame, (1 - q) ** 2 * 0.6 * W, 1 + 90 * (1 - q))
            if trans_out == "whip" and i >= n - k:
                r = (i - (n - k) + 1) / (k + 1)
                frame = whip(frame, -(r ** 2) * 0.6 * W, 1 + 90 * r)
            enc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
    if enc.returncode:
        raise RuntimeError(f"encode failed for segment #{it['idx']}")


def _trans_zoom(i, n, tin, tout, k=TRANS_FRAMES):
    z = 1.0
    if tin == "zoom" and i < k:
        z *= 1 + 0.28 * (1 - (i + 1) / (k + 1)) ** 2
    if tout == "zoom" and i >= n - k:
        z *= 1 + 0.22 * ((i - (n - k) + 1) / (k + 1)) ** 2
    return z


def compare_frames(it, cfg):
    """Before/after: split screen (lr / tb) or a swipe reveal with a divider line."""
    W, H, fps = cfg["width"], cfg["height"], cfg["fps"]
    seg, n = it["seg"], it["frames"]
    mode = seg.get("mode", cfg["compare_mode"])
    split = seg.get("split", "lr")
    tw, th = ((W // 2, H) if split == "lr" else (W, H // 2)) if mode == "split" else (W, H)
    sides = []
    for side in ("a", "b"):
        sub = dict(seg[side])
        kind = "image" if is_image(sub["src"]) else "clip"
        t_in = float(sub.get("in", 0))
        if kind == "clip":
            info = ffprobe(sub["src"])
            sp = float(sub.get("speed", 1.0))
            t_in = min(t_in, max(0.0, info["duration"] - n * sp / fps))
        gen, track = source_for(sub, kind, n, fps, tw, th, cfg, t_in=t_in)
        sides.append((gen, sub, track, kind, t_in))
    at, dur = float(seg.get("swipe_at", 0.15)), float(seg.get("swipe_dur", 0.45))
    for i in range(n):
        t = i / fps
        fr = [compose(next(g), sub, t, t_in + t, track, tw, th, cfg, kind=kind, p=i / max(1, n - 1))
              for g, sub, track, kind, t_in in sides]
        if mode == "split":
            frame = np.hstack(fr) if split == "lr" else np.vstack(fr)
            if split == "lr":
                frame[:, W // 2 - 2:W // 2 + 2] = 255
            else:
                frame[H // 2 - 2:H // 2 + 2, :] = 255
        else:
            q = ease((t - at) / dur)
            x = int(round(W * (1 - q)))
            frame = fr[0].copy()
            frame[:, x:] = fr[1][:, x:]
            if 0 < q < 1:
                frame[:, max(0, x - 3):x + 3] = 255
        yield frame


def render_audio(it, out, cfg, role):
    """A shot's own sound (to-camera voice or ambient), time-stretched to the shot."""
    fps = cfg["fps"]
    D = it["frames"] / fps
    seg = it["seg"]
    if role == "mute":
        run(FF + ["-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-t", f"{D:.4f}", "-c:a", "pcm_s16le", out])
        return
    af = []
    sp = it["speed"] * E.ramp_mean(it.get("ramp"))
    while sp > 2.0:
        af.append("atempo=2.0")
        sp /= 2.0
    while sp < 0.5:
        af.append("atempo=0.5")
        sp /= 0.5
    if abs(sp - 1) > 1e-3:
        af.append(f"atempo={sp:.5f}")
    if seg.get("gain_db"):
        af.append(f"volume={seg['gain_db']}dB")
    af += [f"aresample={SR}", "afade=t=in:d=0.012", "apad", f"atrim=0:{D:.5f}",
           f"afade=t=out:st={max(0, D - 0.015):.5f}:d=0.015"]
    src = voice.source(it["src"], cfg, "cam") if role == "voice" else resolve(it["src"])
    run(FF + ["-ss", f"{it['in']:.3f}", "-t", f"{it['out'] - it['in'] + 0.2:.3f}", "-i", src,
              "-vn", "-af", ",".join(af), "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", out])


def last_frame(mp4):
    info = ffprobe(mp4)
    W, H = info["width"], info["height"]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-sseof", "-0.2", "-i", str(mp4),
                        "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(r.stdout[-W * H * 3:], np.uint8).reshape(H, W, 3).copy()


def end_card_bg(prev_mp4, ec, cfg):
    W, H = cfg["width"], cfg["height"]
    bg = ec["background"]
    if bg == "blur" and prev_mp4:
        img = last_frame(prev_mp4)
        small = cv2.resize(img, (W // 8, H // 8), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), 6)
        return (cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR) * 0.42).astype(np.uint8)
    color = bg if isinstance(bg, str) and bg.startswith("#") else "#000000"
    return np.full((H, W, 3), hex_bgr(color), np.uint8)


# ------------------------------------------------------------------ overlay

WEIGHTS = {"thin": 100, "extralight": 200, "light": 300, "regular": 400, "medium": 500, "semibold": 600,
           "bold": 700, "extrabold": 800, "black": 900, "heavy": 900, "italic": 400}


def font_faces():
    faces = []
    for f in sorted(paths().fonts.glob("*")):
        if f.suffix.lower() not in (".ttf", ".otf", ".woff", ".woff2"):
            continue
        family = re.split(r"[-\[_]", f.stem)[0]
        variable = "[" in f.stem or "variable" in f.stem.lower()
        style = f.stem.split("-")[-1].lower() if "-" in f.stem else "regular"
        italic = "italic" in style
        w = style.replace("italic", "") or "regular"
        weight = "100 900" if variable else str(WEIGHTS.get(w, 400))
        faces.append({"family": family, "url": f.resolve().as_uri(), "weight": weight,
                      "style": "italic" if italic else "normal"})
    return faces


def overlay_spec(edl, items, cfg, total_frames):
    ec_item = next((it for it in items if it["kind"] == "endcard"), None)
    stop = ec_item["start"] if ec_item else items[-1]["end"]
    texts = []
    end = items[-1]["end"]
    for x in edl.get("text", []):
        s, e = E.resolve_span(x, items)
        if "dur" not in x and "end" not in x:   # long enough to read, even on a half-second shot
            long = x.get("style") in ("card", "macros", "credits")
            e = max(e, s + float(cfg["card_min_seconds"] if long else cfg["text_min_seconds"]))
        e = min(e, end)
        texts.append({k: v for k, v in x.items() if k not in ("start", "end", "on", "dur", "offset")} | {"s": s, "e": e})
    # labels on before/after compares
    for it in items:
        seg = it["seg"]
        labs = seg.get("labels") if it["kind"] == "compare" else None
        if not labs:
            continue
        mode = seg.get("mode", cfg["compare_mode"])
        s, e = it["start"], it["end"]
        if mode == "split" and seg.get("split", "lr") == "lr":
            texts += [{"text": labs[0], "style": "label", "x": 0.25, "y": 0.1, "s": s, "e": e},
                      {"text": labs[1], "style": "label", "x": 0.75, "y": 0.1, "s": s, "e": e}]
        elif mode == "split":
            texts += [{"text": labs[0], "style": "label", "y": 0.06, "s": s, "e": e},
                      {"text": labs[1], "style": "label", "y": 0.56, "s": s, "e": e}]
        else:
            mid = s + float(seg.get("swipe_at", 0.15)) + float(seg.get("swipe_dur", 0.45)) / 2
            texts += [{"text": labs[0], "style": "label", "y": 0.12, "s": s, "e": mid, "anim": "none"},
                      {"text": labs[1], "style": "label", "y": 0.12, "s": mid, "e": e, "anim": "pop"}]
    pages = []
    if E.captions_enabled(edl, cfg):
        words = E.caption_words(edl, items, cfg)
        full_cards = [(x["s"], x["e"]) for x in texts if x.get("style") == "card" and x.get("fill")]
        words = [w for w in words if not any(a <= w["s"] < b for a, b in full_cards)]
        pages = E.caption_pages(words, cfg, stop)
    flashes = []
    for f in edl.get("flash", []):
        flashes.append(E.resolve_span(f, items)[0] if isinstance(f, dict) else float(f))
    flashes += [it["start"] for it in items if it["trans_in"] == "flash"]
    endcard = None
    if ec_item:
        ec = ec_item["endcard"]
        endcard = {"s": ec_item["start"], "e": ec_item["end"], "handle": ec["handle"], "text": ec["text"],
                   "logo": resolve(ec["logo"]).resolve().as_uri() if ec["logo"] else None}
    keys = [k for k in cfg if k.startswith(("caption_", "title_", "label_", "accent_"))] + ["text_style", "emphasis_color"]
    return {"width": cfg["width"], "height": cfg["height"], "fps": cfg["fps"], "frames": total_frames,
            "fonts": font_faces(), "style": {k: cfg[k] for k in keys},
            "captions": pages, "texts": texts, "flashes": sorted(flashes), "endcard": endcard}


def render_overlay(spec, wd):
    od = wd / "overlay"
    od.mkdir(exist_ok=True)
    html, js = paths().overlay / "overlay.html", paths().overlay / "render_overlays.js"
    code = [html.read_text(), js.read_text()]
    key = h([spec, code])
    frames = od / "frames"
    if (od / "done").exists() and (od / "done").read_text() == key and (frames / "f_00000.png").exists():
        log("  overlay: cached")
        return frames
    write_json(od / "spec.json", spec)
    env = dict(os.environ, NODE_PATH=str(paths().root / "node_modules"))
    n = max(1, spec["frames"])

    def on_line(line):
        m = re.search(r"overlay frame (\d+)/(\d+)", line)
        if m:
            step("overlay", 65 + 15 * int(m.group(1)) / n)
        else:
            log(line)
    run_streaming(["node", js, od / "spec.json", frames], on_line=on_line, cwd=str(paths().root), env=env)
    (od / "done").write_text(key)
    return frames


# ------------------------------------------------------------------ audio

def read_pcm(path):
    with wave.open(str(path)) as f:
        x = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768
        return x.reshape(-1, f.getnchannels())


def decode_f32(src, extra_in=(), extra_out=()):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *extra_in, "-i", str(resolve(src)), *extra_out,
                        "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2).copy()


def lufs(x):
    if len(x) < SR // 2 or np.abs(x).max() < 1e-4:
        return None
    r = subprocess.run(["ffmpeg", "-hide_banner", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                        "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       input=x.astype(np.float32).tobytes(), capture_output=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr.decode())
    if not m:
        return None
    v = float(json.loads(m.group(0))["input_i"])
    return v if v > -70 else None


def db(x):
    return 10 ** (x / 20)


def _ctrl(spans, n, at, attack=12, release=35):
    """0..1 control curve: 1 inside spans, eased in before and out after (10 ms steps)."""
    k = int(0.01 * SR)
    c = np.zeros(n // k + 2, np.float32)
    for s, e in spans:
        c[max(0, int((s - at) * 100)):max(0, int((e - at) * 100))] = 1.0
    for i in range(len(c) - 2, -1, -1):
        c[i] = max(c[i], c[i + 1] * np.exp(-1 / attack))
    for i in range(1, len(c)):
        c[i] = max(c[i], c[i - 1] * np.exp(-1 / release))
    return np.interp(np.arange(n) / k, np.arange(len(c)), c).astype(np.float32)


def voiceover_bus(items, cfg, n):
    """Voiceover blocks on the timeline (cleaned, fillers/silences cut, levelled to the voice reference)."""
    blocks = E.vo_blocks(items)
    if not blocks:
        return None, None
    bus = np.zeros((n, 2), np.float32)
    f = int(0.01 * SR)
    cleaned = []
    for b in blocks:
        path = voice.source(b["src"], cfg, "vo")
        cleaned.append(voice.wanted(cfg, "vo"))
        x = decode_f32(path) * db(b["gain_db"])
        end = int(round(b["end"] * SR))
        for p in b["pieces"]:
            c = x[int(round(p["in"] * SR)):int(round(p["out"] * SR))].copy()
            if len(c) > 2 * f:          # cut points sit in quiet spots; 10 ms fades keep them click-free
                c[:f] *= np.linspace(0, 1, f)[:, None]
                c[-f:] *= np.linspace(1, 0, f)[:, None]
            a = int(round(p["at"] * SR))
            k = max(0, min(len(c), n - a, end - a))
            bus[a:a + k] += c[:k]
    lv = lufs(bus)
    if lv is not None:
        bus *= db(VOICE_REF_LUFS - lv)
    return bus, {"blocks": len(blocks), "cleaned": all(cleaned), "lufs_in": lv}


def mix_audio(edl, items, cfg, seg_wavs, roles, wd, total_frames, post=False):
    """The final mix -> (audio_final.wav, notes, audio_post.wav or None).

    post: also master a mix without the music (original sounds, voice and SFX) for posting with the song added in
    Instagram/TikTok; it is levelled on its own, so the voice sits where it would in any other render."""
    fps = cfg["fps"]
    n = int(round(total_frames / fps * SR))
    voice = np.zeros((n, 2), np.float32)
    amb = np.zeros((n, 2), np.float32)
    amb_spans = []
    for it, wav, role in zip(items, seg_wavs, roles):
        if role == "mute":
            continue
        x = read_pcm(wav)
        a = int(round(it["f0"] / fps * SR))
        b = min(n, a + int(round(it["frames"] / fps * SR)))
        chunk = x[: b - a] if len(x) >= b - a else np.pad(x, ((0, b - a - len(x)), (0, 0)))
        (voice if role == "voice" else amb)[a:b] = chunk
        if role == "ambient":
            amb_spans.append((it["start"], it["end"]))
    iv, ia = lufs(voice), lufs(amb)
    if iv is not None:
        voice *= db(VOICE_REF_LUFS - iv)
    if ia is not None:
        amb *= db(float(cfg["ambient_lufs"]) - ia)
    vo, vo_notes = voiceover_bus(items, cfg, n)
    if vo is not None:
        voice += vo
        if ia is not None and cfg["duck"]:       # B-roll with real sound sits under the voiceover
            vo_words = [w for b in E.vo_blocks(items) for w in b["words"]]
            amb *= np.power(10.0, -float(cfg["duck_db"]) * _ctrl(E.speech_spans(vo_words), n, 0.0) / 20)[:, None]
        iv = lufs(voice)
    mix = voice + amb
    bed_bus = np.zeros_like(mix)
    notes = {"voice_lufs": iv, "ambient_lufs": ia, "voiceover": vo_notes}

    m = edl.get("music")
    if m and m.get("src"):
        at = float(m.get("at", 0))
        start = float(m.get("_start", m.get("start", 0)) or 0)
        a = max(0, int(at * SR))
        bed = decode_f32(m["src"], extra_in=["-stream_loop", "-1"], extra_out=["-ss", f"{start:.3f}", "-t", f"{(n - a) / SR:.3f}"])
        bed = bed[: n - a]
        im = lufs(bed)
        words = E.caption_words(edl, items, cfg, for_audio=True) if iv is not None else []
        duck_db, amb_duck = float(m.get("duck_db", cfg["duck_db"])), float(cfg["ambient_duck_db"])
        duck = m.get("duck", cfg["duck"])
        if iv is not None:
            target = VOICE_REF_LUFS + float(m.get("level_db", cfg["music_under_voice_db"])) + (duck_db if duck else 0)
        elif cfg["music_mode"] == "mix" and ia is not None:
            target = float(cfg["ambient_lufs"]) + float(m.get("level_db", cfg["music_under_ambient_db"]))
            amb_duck = 0.0
        else:
            target = float(m.get("level_lufs", cfg["music_alone_lufs"]))
        g = db(target - im) if im is not None else 1.0
        env_db = np.zeros(len(bed), np.float32)
        if duck and iv is not None:
            env_db -= duck_db * _ctrl(E.speech_spans(words), len(bed), at)
        if amb_spans and amb_duck:
            env_db -= amb_duck * _ctrl(amb_spans, len(bed), at, attack=6, release=20)
        env = g * np.power(10.0, env_db / 20)
        fi, fo = float(m.get("fade_in", 0.0)), float(m.get("fade_out", 1.0))
        if fi > 0:
            k = min(len(env), int(fi * SR))
            env[:k] *= np.linspace(0, 1, k)
        if fo > 0:
            k = min(len(env), int(fo * SR))
            env[-k:] *= np.linspace(1, 0, k)
        bed_bus[a:a + len(bed)] += bed * env[:, None]
        notes.update(music_lufs=im, music_target=round(target, 1), ducked=bool(duck and iv is not None))

    sfx = list(edl.get("sfx", []))
    soc = edl.get("sfx_on_cuts")
    if soc:
        for it in items[1:]:
            sfx.append({"src": soc["src"], "at": it["start"] + float(soc.get("offset", -0.05)),
                        "gain_db": soc.get("gain_db", -8)})
    for s in sfx:
        t, _ = E.resolve_span(s, items)
        x = decode_f32(s["src"]) * db(float(s.get("gain_db", -6)))
        a = max(0, int(t * SR))
        b = min(n, a + len(x))
        if b > a:
            mix[a:b] += x[: b - a]
    notes["sfx"] = len(sfx)

    out = master(mix + bed_bus, wd / "audio_final.wav", cfg)
    post_out = master(mix, wd / "audio_post.wav", cfg) if post else None
    return out, notes, post_out


def master(x, out, cfg):
    """Loudness-normalise a mix (two-pass loudnorm) -> 16-bit WAV at out. Silence stays silence."""
    raw = out.with_suffix(".f32")
    raw.write_bytes(x.astype(np.float32).tobytes())
    I, TP = cfg["loudness_lufs"], cfg["true_peak_db"]
    base = ["-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", raw]
    r = run(["ffmpeg", "-hide_banner"] + base + ["-af", f"loudnorm=I={I}:TP={TP}:LRA=11:print_format=json",
                                                 "-f", "null", "-"])
    mm = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    mm = json.loads(mm.group(0)) if mm else {}
    if mm and float(mm["input_i"]) > -70:
        ln = (f"loudnorm=I={I}:TP={TP}:LRA=11:measured_I={mm['input_i']}:measured_TP={mm['input_tp']}:"
              f"measured_LRA={mm['input_lra']}:measured_thresh={mm['input_thresh']}:offset={mm['target_offset']}:linear=true")
        run(FF + base + ["-af", f"{ln},aresample={SR}", "-c:a", "pcm_s16le", out])
    else:   # silent video
        run(FF + base + ["-c:a", "pcm_s16le", out])
    raw.unlink()
    return out


# ------------------------------------------------------------------ export

def grade_chain(cfg):
    g = str(cfg.get("grade") or "none")
    if g.startswith("custom:"):
        yuv, rgb = [g[7:]], []
    elif g.endswith(".cube"):
        yuv, rgb = [], [f"lut3d=file='{resolve(g.replace('lut:', ''))}'"]
    elif g in GRADES:
        yuv, rgb = GRADES[g]
    else:
        die(f"unknown grade {g!r}; use {', '.join(GRADES)}, custom:<ffmpeg filters> or a .cube LUT")
    chain = list(yuv)
    if rgb:
        chain += ["scale=in_color_matrix=bt709:in_range=tv,format=gbrp"] + rgb + \
                 ["scale=out_color_matrix=bt709:out_range=tv,format=yuv444p"]
    if cfg.get("vignette"):
        chain.append("vignette=angle=PI/5")
    if float(cfg.get("grain") or 0) > 0:
        chain.append(f"noise=c0s={max(1, int(round(float(cfg['grain']) * 22)))}:c0f=t+u")
    return chain


def export(out, wd, seg_mp4s, overlay_dir, broll, graphics, audio, cfg, total_frames, draft):
    fps = cfg["fps"]
    lst = wd / "segments.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_mp4s))
    inputs = ["-f", "concat", "-safe", "0", "-i", lst,
              "-framerate", str(fps), "-start_number", "0", "-i", overlay_dir / "f_%05d.png"]
    g = ["[0:v]setpts=PTS-STARTPTS,format=yuv444p[c0]"]
    cur, idx = "c0", 2
    for k, (mp4, s, e) in enumerate(broll):
        inputs += ["-i", mp4]
        g.append(f"[{idx}:v]setpts=PTS-STARTPTS+{s:.4f}/TB,format=yuv444p[b{k}]")
        g.append(f"[{cur}][b{k}]overlay=eof_action=pass:enable='between(t,{s:.4f},{e - 0.5 / fps:.4f})'[cb{k}]")
        cur, idx = f"cb{k}", idx + 1
    chain = grade_chain(cfg)
    if chain:
        g.append(f"[{cur}]{','.join(chain)},format=yuv444p[graded]")
        cur = "graded"
    for k, gr in enumerate(graphics):
        src = resolve(gr["src"])
        still = is_image(src)
        inputs += (["-loop", "1", "-t", f"{gr['e'] - gr['s']:.3f}", "-i", src] if still else ["-i", src])
        sc = f",scale={int(gr['w'])}:-2" if gr.get("w") else ""
        g.append(f"[{idx}:v]format=rgba{sc},scale=out_color_matrix=bt709:out_range=tv,format=yuva444p,"
                 f"setpts=PTS-STARTPTS+{gr['s']:.4f}/TB[g{k}]")
        g.append(f"[{cur}][g{k}]overlay=x={gr.get('x', '(W-w)/2')}:y={gr.get('y', '(H-h)/2')}:format=yuv444:"
                 f"eof_action=pass:enable='between(t,{gr['s']:.4f},{gr['e']:.4f})'[cg{k}]")
        cur, idx = f"cg{k}", idx + 1
    g.append("[1:v]format=rgba,scale=out_color_matrix=bt709:out_range=tv,format=yuva444p[ov]")
    g.append(f"[{cur}][ov]overlay=0:0:format=yuv444:eof_action=pass,format=yuv420p,{TAG709}[vout]")
    inputs += ["-i", audio]
    preset, crf = ("veryfast", 23) if draft else ("medium", cfg["video_crf"])
    run(FF + inputs + ["-filter_complex", ";".join(g), "-map", "[vout]", "-map", f"{idx}:a",
                       "-frames:v", str(total_frames), "-r", str(fps),
                       "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-profile:v", "high",
                       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", str(cfg["audio_bitrate"]), "-ar", str(SR),
                       "-movflags", "+faststart", "-shortest", out])
    return out


def export_post(video, audio, out, cfg):
    """The same picture with another sound: the video stream is copied, so this takes a second."""
    run(FF + ["-i", video, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
              "-b:a", str(cfg["audio_bitrate"]), "-ar", str(SR), "-movflags", "+faststart", "-shortest", out])
    return out


def post_path(video):
    """output/v2/name_v2.mp4 -> output/v2/name_v2_post.mp4 (the file to post with the in-app sound)."""
    return video.with_name(f"{video.stem}_post{video.suffix}")


def in_app_card(edl, grid, duration, voice):
    """What to tell the creator when they post with the in-app sound: which song, where to start it, and whether
    their voice is in the file (then the app's music should go down under it)."""
    from .beats import beats_for
    src = edl["music"]["src"]
    start = grid["start"]
    song = float(beats_for(src)["duration"])
    card = {"song": os.path.basename(src), "start": start, "start_label": tc_whole(start), "voice": bool(voice),
            "song_duration": song, "warning": None}
    if start + duration > song + 0.5:
        card["warning"] = (f"The song ends {tc_whole(song)} in, before the video does: pick an earlier start so the "
                           f"in-app song lasts the whole video.")
    return card


def tc_whole(t):
    """42.0 -> "0:42", 75 -> "1:15" (how Instagram and TikTok show a song position)."""
    t = int(round(t))
    return f"{t // 60}:{t % 60:02d}"


def targets(name, wd):
    """Where this render goes -> (video, contact sheet, version or None).

    CLI layout: output/<name>.mp4, the previous one archived to work/<name>/versions/ (as before).
    Project layout: a fresh output/vN/ folder per render, so every version stays playable."""
    lay = layout()
    if lay.versioned:
        nums = [int(d.name[1:]) for d in lay.output.glob("v*") if d.is_dir() and d.name[1:].isdigit()]
        n = max(nums, default=0) + 1
        vd = lay.output / f"v{n}"
        vd.mkdir(parents=True, exist_ok=True)
        return vd / f"{name}_v{n}.mp4", vd / "contact.jpg", n
    lay.output.mkdir(parents=True, exist_ok=True)
    out = lay.output / f"{name}.mp4"
    if out.exists():
        vd = wd / "versions"
        vd.mkdir(exist_ok=True)
        n = len(list(vd.glob(f"{name}_v*.mp4"))) + 1
        shutil.move(out, vd / f"{name}_v{n}.mp4")
        if post_path(out).exists():
            shutil.move(post_path(out), vd / f"{name}_v{n}_post.mp4")
        sheet = lay.output / f"{name}_contact.jpg"
        if sheet.exists():
            shutil.move(sheet, vd / f"{name}_v{n}_contact.jpg")
    return out, lay.output / f"{name}_contact.jpg", None


# ------------------------------------------------------------------ main

def render(name, draft=False, sheet=True, music=None):
    """Render work/<name>/edl.json (or the project's plan) -> dict with the output paths, duration and audio notes.

    music: settings that win over the plan's music block, e.g. {"start": 42.0, "in_app": True} (the app passes the
    creator's choices from the Music step). With "in_app" the render also writes <name>_post.mp4 without the music."""
    need("ffmpeg")
    need("node")
    t_start = time.time()
    step("prepare", 1)
    wd = work_dir(name)
    edl = E.load(name)
    if music and edl.get("music"):
        edl["music"] = {**edl["music"], **music}
    in_app = bool((edl.get("music") or {}).get("in_app") and (edl.get("music") or {}).get("src"))
    problems = E.validate(edl)
    if problems:
        die("edit plan has problems:\n  - " + "\n  - ".join(problems), code="invalid_plan", status=422)
    cfg = style_for(edl)
    W, H, fps = cfg["width"], cfg["height"], cfg["fps"]
    items, grid = E.build_timeline(edl, cfg)
    if grid:
        edl["music"]["_start"] = grid["start"]
        edl["music"]["at"] = grid["at"]
    total_frames = items[-1]["f0"] + items[-1]["frames"]
    log(f"render {name}: {len(items)} shots, {total_frames / fps:.2f}s, {W}x{H}@{fps}"
          + (f", preset {edl['preset']}" if edl.get("preset") else "")
          + (f", music {grid['bpm']} BPM from {tc(grid['start'])}" if grid else ""))
    for it in items:
        if it.get("warn"):
            log(f"  ! #{it['idx']}: {it['warn']}")

    # 1. shots
    sd = work_dir(name, "segments")
    seg_mp4s, seg_wavs, roles, prev_mp4 = [], [], [], None
    look = {k: cfg[k] for k in ("kenburns", "handheld", "photo_fit", "compare_mode")}
    for k, it in enumerate(items):
        step(f"shot {k + 1}/{len(items)}", 3 + 57 * k / len(items))
        nxt = items[k + 1] if k + 1 < len(items) else None
        trans_out = nxt["trans_in"] if nxt and nxt["trans_in"] in ("whip", "zoom") else None
        seg = {kk: v for kk, v in it["seg"].items()
               if kk not in ("label", "text", "note", "captions", "labels", "why", "reason", "cue", "at")}
        if it["kind"] in ("clip", "image"):
            src_key = file_key(it["src"])
        elif it["kind"] == "compare":
            src_key = [file_key(seg["a"]["src"]), file_key(seg["b"]["src"])]
        elif it["kind"] == "endcard":
            src_key = str(prev_mp4) + json.dumps(it["endcard"]["background"])
        else:
            src_key = None
        role = E.seg_role(it, edl, cfg)
        roles.append(role)
        vkey = h([VERSION, "v", src_key, seg, it["in"], it["out"], it["speed"], it["ramp"], it["frames"],
                  W, H, fps, it["trans_in"], trans_out, look])
        clean_key = voice.settings_key(cfg) if role == "voice" and voice.wanted(cfg, "cam") else None
        akey = h([VERSION, "a", src_key, role, seg.get("gain_db"), it["in"], it["out"], it["speed"], it["ramp"],
                  it["frames"], fps, clean_key])
        mp4, wav = sd / f"v_{vkey}.mp4", sd / f"a_{akey}.wav"
        label = (f"#{it['idx']} {it['kind']} {it['src'] or ''} {tc(it['in'])}-{tc(it['out'])}" if it["kind"] == "clip"
                 else f"#{it['idx']} {it['kind']} {it['src'] or ''}")
        if not mp4.exists():
            t0 = time.time()
            still = end_card_bg(prev_mp4, it["endcard"], cfg) if it["kind"] == "endcard" else None
            tmp = mp4.with_suffix(".tmp.mp4")
            render_video(it, tmp, cfg, still, trans_out)
            tmp.rename(mp4)
            log(f"  {label}: {it['frames']} frames in {time.time() - t0:.1f}s")
        if not wav.exists():
            render_audio(it, wav, cfg, role)
        seg_mp4s.append(mp4)
        seg_wavs.append(wav)
        prev_mp4 = mp4

    broll = []
    step("b-roll", 60)
    for k, b in enumerate(edl.get("broll", [])):
        span = dict(b)
        if "out" in b and "dur" not in b and "end" not in b:
            span["dur"] = (float(b["out"]) - float(b.get("in", 0))) / float(b.get("speed", 1))
        s, e = E.resolve_span(span, items)
        n = round((e - s) * fps)
        it = {"idx": f"b{k + 1}", "kind": "clip", "seg": b, "src": b["src"], "in": float(b.get("in", 0)),
              "out": float(b.get("in", 0)) + (e - s) * float(b.get("speed", 1)), "speed": float(b.get("speed", 1)),
              "ramp": E.ramp_curve(b.get("ramp")), "frames": n, "trans_in": None}
        key = h([VERSION, "b", file_key(b["src"]), {k2: v for k2, v in b.items() if k2 not in ("at", "on", "start")},
                 it["in"], it["out"], n, W, H, fps, look])
        mp4 = sd / f"b_{key}.mp4"
        if not mp4.exists():
            tmp = mp4.with_suffix(".tmp.mp4")
            render_video(it, tmp, cfg)
            tmp.rename(mp4)
            log(f"  broll {b['src']} @ {tc(s)}: {n} frames")
        broll.append((mp4, s, s + n / fps))

    graphics = []
    for gr in edl.get("graphics", []):
        dflt = 2.0 if is_image(gr["src"]) else (ffprobe(gr["src"])["duration"] or 2.0)
        s, e = E.resolve_span(gr, items, default_dur=dflt)
        graphics.append(gr | {"s": s, "e": e})

    # 2. overlay layer
    step("overlay", 65)
    spec = overlay_spec(edl, items, cfg, total_frames)
    write_json(wd / "captions.json", spec["captions"])
    overlay_dir = render_overlay(spec, wd)

    # 3. audio
    step("audio", 80)
    audio, anotes, post_audio = mix_audio(edl, items, cfg, seg_wavs, roles, wd, total_frames, post=in_app)

    # 4. export
    step("export", 88)
    out, sheet_path, version = targets(name, wd)
    post_out = post_path(out) if post_audio else None
    try:
        export(out, wd, seg_mp4s, overlay_dir, broll, graphics, audio, cfg, total_frames, draft)
        if post_out:
            step("export: copy without the music", 95)
            export_post(out, post_audio, post_out, cfg)
    except BaseException:
        if version is not None:
            shutil.rmtree(out.parent, ignore_errors=True)
        raise
    info = ffprobe(out)
    ec = next((it for it in items if it["kind"] == "endcard"), None)
    sheet_out = None
    if sheet:
        step("contact sheet", 97)
        sheet_out, _ = contact_sheet.make(out, sheet_path, end_card=(ec["end"] - ec["start"]) if ec else 0)
    result = {
        "output": rel(out), "contact_sheet": rel(sheet_out) if sheet_out else None, "version": version,
        "draft": draft, "size_bytes": out.stat().st_size, "elapsed_s": round(time.time() - t_start, 1),
        "duration": info["duration"], "audio": anotes, "grade": cfg["grade"],
        "music_start": grid["start"] if grid else None, "bpm": grid["bpm"] if grid else None,
        "beats": [b for b in grid["beats"] if b <= info["duration"]] if grid else [],
        "drops": grid["drops"] if grid else [],
        "timeline": [{k: it[k] for k in ("idx", "kind", "src", "in", "out", "speed", "start", "end", "label",
                                         "trans_in", "beat_synced")}
                     | {"role": r, "ramp": bool(it["ramp"]), "voiceover": it["vo"]["src"] if it.get("vo") else None}
                     for it, r in zip(items, roles)],
        "caption_pages": len(spec["captions"]), "texts": len(spec["texts"]),
        "post_video": rel(post_out) if post_out else None,
        "in_app": in_app_card(edl, grid, info["duration"], anotes.get("voice_lufs") is not None)
        if post_out and grid else None,
    }
    write_json(wd / "render.json", result)
    if version is not None:
        write_json(out.parent / "render.json", result)
        shutil.copy2(wd / "edl.json", out.parent / "edl.json")
    mb = out.stat().st_size / 1e6
    log(f"\ndone in {time.time() - t_start:.0f}s -> {rel(out)}  ({info['duration']:.2f}s, {mb:.1f} MB)")
    if sheet_out:
        log(f"contact sheet -> {rel(sheet_out)}")
    if result["in_app"]:
        card = result["in_app"]
        log(f"to post -> {rel(post_out)} (no music): in Instagram/TikTok pick {card['song']} and start it at "
            f"{card['start_label']}" + (", turn the song down under your voice" if card["voice"] else ""))
        if card["warning"]:
            log(f"  ! {card['warning']}")
    lv = anotes.get("voice_lufs")
    vn = anotes.get("voiceover")
    log(f"audio: voice {'%.1f LUFS' % lv if lv else 'none'}"
          + (f" (incl. voiceover{', cleaned' if vn['cleaned'] else ''})" if vn else "")
          + (", ambient on" if anotes.get("ambient_lufs") else "")
          + (f", music {'ducked under voice' if anotes.get('ducked') else 'lead'}" if "music_lufs" in anotes else "")
          + f", {anotes['sfx']} sfx, normalised to {cfg['loudness_lufs']} LUFS; grade {cfg['grade']}")
    step("done", 100)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    render(a.name, draft=a.draft, sheet=not a.no_sheet)


if __name__ == "__main__":
    main()
