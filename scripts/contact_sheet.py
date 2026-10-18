#!/usr/bin/env python3
"""Contact sheet: N frames from a video in a labelled grid (the review tool, instead of
watching the whole video frame by frame).

  contact_sheet.py output/my-video.mp4                  # 6 frames -> output/my-video_contact.jpg
  contact_sheet.py output/my-video.mp4 --times 0.3 1 2.5 # specific moments
  contact_sheet.py ref.mp4 --n 12 --cols 6 --out x.jpg
"""
import argparse
import subprocess

import cv2
import numpy as np

from common import ffprobe, rel, resolve, tc
from media import is_image, photo_path

TILE_W = 360


def grab(src, t, w, h):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(resolve(src)),
           "-frames:v", "1", "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    buf = subprocess.run(cmd, capture_output=True).stdout
    if len(buf) < w * h * 3:
        return np.zeros((h, w, 3), np.uint8)
    return np.frombuffer(buf[: w * h * 3], np.uint8).reshape(h, w, 3).copy()


def default_times(dur, n, end_card=0.0):
    """First frame inside the hook, last on the end card, the rest spread evenly."""
    if n == 1:
        return [dur / 2]
    first, last = min(0.6, dur * 0.05), dur - (end_card / 2 if end_card else min(0.5, dur * 0.05))
    return [first + (last - first) * i / (n - 1) for i in range(n)]


def make(src, out=None, n=6, cols=3, times=None, labels=None, end_card=0.0):
    info = ffprobe(src)
    times = times or default_times(info["duration"], n, end_card)
    tw = TILE_W
    th = int(round(tw * info["height"] / info["width"] / 2)) * 2
    tiles = []
    for i, t in enumerate(times):
        img = grab(src, t, tw, th)
        lab = (labels[i] if labels else None) or tc(t)
        cv2.rectangle(img, (0, 0), (tw, 34), (0, 0, 0), -1)
        cv2.putText(img, lab, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.copyMakeBorder(img, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=(40, 40, 40)))
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 40))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    sheet = np.vstack(rows)
    out = resolve(out) if out else resolve(src).with_name(resolve(src).stem + "_contact.jpg")
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out, times


def board(items, out, cols=5, tw=216):
    """One frame per clip / photo with its file name, for matching B-roll to what is said: [(src, t or None)]."""
    th = int(round(tw * 16 / 9))
    tiles = []
    for src, t in items:
        tile = np.full((th, tw, 3), 24, np.uint8)
        if is_image(src):
            img = cv2.imread(str(photo_path(src)), cv2.IMREAD_COLOR)
        else:
            info = ffprobe(src)
            s = min(tw / info["width"], th / info["height"])
            img = grab(src, t or 0.0, max(2, int(info["width"] * s) // 2 * 2), max(2, int(info["height"] * s) // 2 * 2))
        if img is not None:
            s = min(tw / img.shape[1], th / img.shape[0])
            img = cv2.resize(img, (max(1, int(img.shape[1] * s)), max(1, int(img.shape[0] * s))), interpolation=cv2.INTER_AREA)
            y, x = (th - img.shape[0]) // 2, (tw - img.shape[1]) // 2
            tile[y:y + img.shape[0], x:x + img.shape[1]] = img
        name = resolve(src).name
        name = name if len(name) <= 22 else name[:10] + "…" + name[-10:]
        cv2.rectangle(tile, (0, th - 30), (tw, th), (0, 0, 0), -1)
        cv2.putText(tile, name.replace("…", ".."), (6, th - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(cv2.copyMakeBorder(tile, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=(40, 40, 40)))
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 40))
    sheet = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    out = resolve(out)
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--times", type=float, nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args()
    out, times = make(a.video, a.out, a.n, a.cols, a.times)
    print(f"contact sheet -> {rel(out)}  ({', '.join(tc(t) for t in times)})")


if __name__ == "__main__":
    main()
