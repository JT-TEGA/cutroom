#!/usr/bin/env python3
"""NO-TALK mode: find the best moments in footage by look, not words.

  moments.py raw/a.mp4 [--len 1.0] [--n 5] [--shake-ok]

Scores every 0.1 s on sharpness (Laplacian variance), camera shake (jitter of the global motion
from phase correlation), exposure, how much is happening (frame difference) and faces, then picks
the best non-overlapping windows that contain no blurry / shaky / badly exposed frames.
Analysis is cached at work/_cache/moments/<key>.json.
"""
import argparse
import subprocess

import cv2
import numpy as np

from .common import cache_dir, ffprobe, file_key, read_json, resolve, tc, write_json
from .config import log, paths

FPS = 10
SHORT = 288          # analysis size: short side in px
SHAKE_PX = 4.5       # frame-to-frame camera jitter (at SHORT px) that counts as shaky
CACHE_VERSION = 3


def _frames(src, info):
    s = SHORT / min(info["width"], info["height"])
    w, h = int(info["width"] * s) // 2 * 2, int(info["height"] * s) // 2 * 2
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(resolve(src)), "-an",
                          "-vf", f"fps={FPS},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE)
    size = w * h
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(h, w)
    p.wait()


def _audio_rms(src, n):
    """Loudness per 0.1 s sample (for picking ambient-sound moments)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(resolve(src)), "-vn", "-ac", "1",
                        "-ar", "8000", "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, np.float32)
    hop = 8000 // FPS
    m = len(x) // hop
    rms = np.sqrt((x[: m * hop].reshape(m, hop) ** 2).mean(1) + 1e-10) if m else np.zeros(0)
    out = np.full(n, 1e-5, np.float32)
    out[: min(n, m)] = rms[:n]
    return 20 * np.log10(out)


_HANN = {}


def _camera_motion(prev, cur):
    """Dominant (camera) translation between frames, so people or objects moving inside the shot
    don't count as shake: tracked corners + RANSAC when the agreeing points cover the frame,
    else whole-frame phase correlation if its peak is clear, else (0, 0)."""
    h, w = prev.shape
    pts = cv2.goodFeaturesToTrack(prev, 200, 0.01, 7)
    if pts is not None and len(pts) >= 12:
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, winSize=(21, 21), maxLevel=3)
        ok = st.ravel() == 1
        if ok.sum() >= 10:
            M, inl = cv2.estimateAffinePartial2D(pts[ok], nxt[ok], method=cv2.RANSAC, ransacReprojThreshold=1.5)
            if M is not None and inl is not None and inl.sum() >= 8:
                p = pts[ok].reshape(-1, 2)[inl.ravel() == 1]
                if p[:, 0].std() >= 0.18 * w and p[:, 1].std() >= 0.18 * h and inl.sum() >= 0.4 * ok.sum():
                    return (float(M[0, 2]), float(M[1, 2]))
    win = _HANN.setdefault((w, h), cv2.createHanningWindow((w, h), cv2.CV_32F))
    (dx, dy), resp = cv2.phaseCorrelate(prev.astype(np.float32), cur.astype(np.float32), win)
    return (float(dx), float(dy)) if resp > 0.3 else (0.0, 0.0)


def analyse(src, force=False):
    out = cache_dir("moments") / f"{file_key(src)}.json"
    if out.exists() and not force:
        d = read_json(out)
        if d.get("v") == CACHE_VERSION:
            return d
    info = ffprobe(src)
    det = None
    sharp, bright, act, mot, face = [], [], [], [], []
    prev = None
    for i, g in enumerate(_frames(src, info)):
        sharp.append(float(cv2.Laplacian(g, cv2.CV_32F).var()))
        bright.append(float(g.mean()))
        if prev is None:
            act.append(0.0)
            mot.append((0.0, 0.0))
        else:
            mot.append(_camera_motion(prev, g))
            act.append(float(np.abs(g.astype(np.float32) - prev.astype(np.float32)).mean()))
        prev = g
        if i % 5 == 0:   # faces at 2 fps
            if det is None:
                det = cv2.FaceDetectorYN.create(str(paths().face_model), "", (g.shape[1], g.shape[0]), 0.6, 0.3, 20)
            _, faces = det.detect(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))
            face.append(1.0 if faces is not None and len(faces) else 0.0)
        else:
            face.append(face[-1] if face else 0.0)
    n = len(sharp)
    mot = np.array(mot) if n else np.zeros((0, 2))
    # shake = high-frequency part of the camera motion (smooth pans are fine, jitter is not)
    k = 5
    if n > k:
        sm = np.stack([np.convolve(mot[:, j], np.ones(k) / k, mode="same") for j in range(2)], 1)
        jitter = np.linalg.norm(mot - sm, axis=1)
    else:
        jitter = np.zeros(n)
    d = {"v": CACHE_VERSION, "fps": FPS, "duration": info["duration"], "n": n,
         "sharp": np.round(sharp, 1).tolist(), "bright": np.round(bright, 1).tolist(),
         "activity": np.round(act, 2).tolist(), "jitter": np.round(jitter, 2).tolist(),
         "face": face, "audio_db": np.round(_audio_rms(src, n), 1).tolist() if info["has_audio"] else [-100.0] * n}
    write_json(out, d)
    return d


def frame_scores(d, shake_ok=False):
    sharp = np.array(d["sharp"])
    if not len(sharp):
        return np.zeros(0), np.zeros(0, bool)
    med = np.median(sharp) + 1e-6
    rel = sharp / med
    jitter = np.array(d["jitter"])
    bright = np.array(d["bright"])
    act = np.array(d["activity"])
    act_n = np.clip(act / (np.percentile(act, 90) + 1e-6), 0, 1.2)
    blurry = (rel < 0.45) | (sharp < 12)
    shaky = (jitter > SHAKE_PX) & (not shake_ok)
    exposure = (bright < 22) | (bright > 238)
    good = ~(blurry | shaky | exposure)
    score = np.log(np.clip(rel, 0.05, 4)) + 0.6 * act_n + 0.5 * np.array(d["face"])
    if not shake_ok:
        score -= 0.25 * np.clip(jitter, 0, 6)
    return score, good


def windows(d, length, n=3, shake_ok=False, a=0.0, b=None, min_gap=0.3):
    """Best non-overlapping windows of `length` seconds -> [{"in", "out", "score", "loud_db"}]."""
    score, good = frame_scores(d, shake_ok)
    fps = d["fps"]
    L = max(1, int(round(length * fps)))
    lo = int(a * fps)
    hi = min(len(score), int((b if b is not None else d["duration"]) * fps))
    audio = np.array(d["audio_db"])
    cands = []
    for strict in (True, False):
        for s in range(lo, max(lo, hi - L) + 1):
            seg = slice(s, s + L)
            if s + L > len(score):
                break
            if strict and not good[seg].all():
                continue
            cands.append((float(score[seg].mean()) - (0 if strict else 2.0), s))
        if cands:
            break
    cands.sort(reverse=True)
    picked = []
    gap = int(min_gap * fps)
    for sc, s in cands:
        if all(s + L + gap <= p or s >= p + L + gap for _, p in picked):
            picked.append((sc, s))
        if len(picked) >= n:
            break
    out = []
    for sc, s in sorted(picked, key=lambda x: x[1]):
        out.append({"in": round(s / fps, 2), "out": round((s + L) / fps, 2), "score": round(sc, 2),
                    "loud_db": round(float(audio[s:s + L].mean()), 1) if len(audio) else -100.0})
    return out


def usable_seconds(d, shake_ok=False):
    _, good = frame_scores(d, shake_ok)
    return float(good.sum()) / d["fps"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--len", type=float, default=1.0)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--shake-ok", action="store_true")
    a = ap.parse_args()
    for c in a.clips:
        d = analyse(c)
        log(f"== {c}: {d['duration']:.1f}s, usable {usable_seconds(d, a.shake_ok):.1f}s")
        for w in windows(d, a.len, a.n, a.shake_ok):
            log(f"  {tc(w['in'], 2)}-{tc(w['out'], 2)}  score {w['score']:+.2f}  audio {w['loud_db']} dB")


if __name__ == "__main__":
    main()
