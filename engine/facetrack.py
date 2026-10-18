#!/usr/bin/env python3
"""Face tracking for vertical reframing (OpenCV YuNet detector, cached per clip).

  facetrack.py raw/a.mp4            # analyse + print summary
  facetrack.py raw/a.mp4 --preview  # also write a debug jpg with the track

The track is a smoothed "virtual camera operator": it ignores small head
movement (dead zone), eases into bigger moves and never jitters.
Output: work/_cache/tracks/<clip-key>.json  {"t": [...], "x": [...], "y": [...], "size": [...]}
(x, y = face centre as 0-1 of the frame; size = face height as 0-1 of frame height)
"""
import argparse
import subprocess

import cv2
import numpy as np

from .common import cache_dir, ffprobe, file_key, read_json, rel, resolve, write_json
from .config import log, paths

SAMPLE_FPS = 8
DET_W = 640


def _frames(src, info, fps):
    """Yield (t, bgr) downscaled frames via ffmpeg (handles rotation, HEVC, VFR)."""
    w = DET_W if info["width"] >= info["height"] else int(DET_W * info["width"] / info["height"]) // 2 * 2
    h = int(round(w * info["height"] / info["width"] / 2)) * 2
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(resolve(src)), "-an",
           "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n, size = 0, w * h * 3
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield n / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        n += 1
    p.wait()


def still_face(img):
    """Biggest confident face in a photo -> (x, y, size) as 0-1 of the image, or None."""
    h, w = img.shape[:2]
    s = DET_W / max(h, w)
    small = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
    sh, sw = small.shape[:2]
    det = cv2.FaceDetectorYN.create(str(paths().face_model), "", (sw, sh), 0.6, 0.3, 50)
    _, faces = det.detect(small)
    if faces is None or not len(faces):
        return None
    f = max(faces, key=lambda f: f[3] * f[14])
    return ((f[0] + f[2] / 2) / sw, (f[1] + f[3] / 2) / sh, f[3] / sh)


def detect(src, info):
    det = None
    samples = []  # (t, cx, cy, size) normalised, or None
    prev = None
    for t, img in _frames(src, info, SAMPLE_FPS):
        h, w = img.shape[:2]
        if det is None:
            det = cv2.FaceDetectorYN.create(str(paths().face_model), "", (w, h), 0.6, 0.3, 50)
        _, faces = det.detect(img)
        best = None
        if faces is not None and len(faces):
            cands = []
            for f in faces:
                x, y, fw, fh, score = f[0], f[1], f[2], f[3], f[14]
                cx, cy, sz = (x + fw / 2) / w, (y + fh / 2) / h, fh / h
                # prefer big, confident faces near where the face was last time
                cont = 1.0 if prev is None else max(0.2, 1 - 2.5 * abs(cx - prev[0]))
                cands.append((sz * score * cont, cx, cy, sz))
            _, cx, cy, sz = max(cands)
            best = (cx, cy, sz)
            prev = best
        samples.append((t, best))
    return samples


def smooth_track(samples, dead_zone=0.05, follow=0.35):
    """Fill gaps, kill outliers, then a dead-zone camera with zero-lag smoothing."""
    t = np.array([s[0] for s in samples])
    hit = np.array([s[1] is not None for s in samples])
    if not hit.any():
        return None
    def series(i):
        v = np.array([s[1][i] if s[1] else np.nan for s in samples])
        good = ~np.isnan(v)
        return np.interp(t, t[good], v[good])
    x, y, size = series(0), series(1), series(2)

    def median(v, k=5):
        pad = np.pad(v, k // 2, mode="edge")
        return np.array([np.median(pad[i:i + k]) for i in range(len(v))])
    x, y, size = median(x), median(y), median(size, 9)

    # dead zone: camera only moves once the face drifts out of a small window
    cam = np.empty_like(x)
    cam[0] = x[0]
    for i in range(1, len(x)):
        d = x[i] - cam[i - 1]
        cam[i] = cam[i - 1] + (np.sign(d) * (abs(d) - dead_zone) if abs(d) > dead_zone else 0.0)

    def filtfilt(v, tau):
        a = 1 - np.exp(-1 / (SAMPLE_FPS * tau))
        f = v.copy()
        for i in range(1, len(f)):
            f[i] = f[i - 1] + a * (f[i] - f[i - 1])
        for i in range(len(f) - 2, -1, -1):
            f[i] = f[i + 1] + a * (f[i] - f[i + 1])
        return f
    return {"t": t.round(3).tolist(), "x": filtfilt(cam, follow).round(4).tolist(),
            "y": filtfilt(y, 0.6).round(4).tolist(), "size": filtfilt(size, 1.0).round(4).tolist(),
            "coverage": round(float(hit.mean()), 3)}


def track_for(src, force=False):
    """Cached track for a clip, or None if no face found."""
    out = cache_dir("tracks") / f"{file_key(src)}.json"
    if out.exists() and not force:
        d = read_json(out)
        return d.get("track")
    info = ffprobe(src)
    tr = smooth_track(detect(src, info)) if info.get("has_video") and not info.get("still") else None
    write_json(out, {"src": rel(resolve(src)), "track": tr})
    return tr


def at(track, t):
    """Face (x, y, size) at source time t, or None."""
    if not track:
        return None
    ts = track["t"]
    return (float(np.interp(t, ts, track["x"])), float(np.interp(t, ts, track["y"])),
            float(np.interp(t, ts, track["size"])))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    for c in a.clips:
        tr = track_for(c, a.force)
        if not tr:
            log(f"{c}: no face found -> centre crop")
            continue
        xs = np.array(tr["x"])
        log(f"{c}: face in {tr['coverage'] * 100:.0f}% of samples, x range {xs.min():.2f}-{xs.max():.2f}")
        if a.preview:
            info = ffprobe(c)
            mid = tr["t"][len(tr["t"]) // 2]
            img = next(img for t, img in _frames(c, info, SAMPLE_FPS) if t >= mid)
            h, w = img.shape[:2]
            for i in range(len(tr["t"]) - 1):
                p0 = (int(tr["x"][i] * w), int(i / len(tr["t"]) * h))
                p1 = (int(tr["x"][i + 1] * w), int((i + 1) / len(tr["t"]) * h))
                cv2.line(img, p0, p1, (0, 255, 255), 2)
            out = cache_dir("tracks") / f"{file_key(c)}_preview.jpg"
            cv2.imwrite(str(out), img)
            log(f"  preview -> {rel(out)}")


if __name__ == "__main__":
    main()
