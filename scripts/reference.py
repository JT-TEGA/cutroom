#!/usr/bin/env python3
"""REFERENCE mode: download a reel and measure its style.

  reference.py --name my-video "https://www.instagram.com/reel/..."
  reference.py --name my-video URL --cookies chrome     # Instagram often needs your browser login

Writes to work/<name>/reference/:
  ref.mp4, stats.json, hook.jpg (first 2.5 s, 6 frames), shots.jpg (one frame per shot),
  transcript (cached like any clip). Look at the two sheets + stats, then write style_spec.md.
"""
import argparse

import subprocess
import sys
from pathlib import Path

import numpy as np

import contact_sheet
from beats import beats_for
from common import ROOT, describe, ffprobe, load_transcript, rel, tc, work_dir, write_json


def download(url, rd, cookies=None):
    rd.mkdir(parents=True, exist_ok=True)
    ytdlp = Path(sys.executable).with_name("yt-dlp")
    cmd = [str(ytdlp), "-f", "bv*+ba/b", "--merge-output-format", "mp4", "--no-playlist",
           "--write-info-json", "-o", str(rd / "ref.%(ext)s"), url]
    if cookies:
        cmd[1:1] = ["--cookies-from-browser", cookies]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        msg = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "unknown error"
        hint = "" if cookies else "\n  try again with --cookies chrome (uses your logged-in browser session)"
        raise SystemExit(f"yt-dlp failed: {msg}{hint}")
    mp4 = rd / "ref.mp4"
    if not mp4.exists():
        cands = [p for p in rd.glob("ref.*") if p.suffix in (".mp4", ".mkv", ".webm", ".mov")]
        if not cands:
            raise SystemExit("download produced no video file")
        mp4 = cands[0]
    return mp4


def scene_cuts(src, fps, ratio=4.0, floor=8.0, nms=0.2):
    """Cut times from frame-difference spikes. Unlike ffmpeg's scene score this also catches
    jump cuts and punch-ins inside the same shot, which is most of the pace in talking reels."""
    w, hh = 144, 256
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(src), "-an", "-vf",
                          f"scale={w}:{hh},format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, hh, w).astype(np.float32)
    if len(f) < 3:
        return []
    d = np.abs(np.diff(f, axis=0)).mean((1, 2))
    k, rad = 15, max(1, int(nms * fps))
    cuts = []
    for i in range(len(d)):
        local = np.median(d[max(0, i - k):i + k])
        if d[i] > max(floor, ratio * local) and d[i] == d[max(0, i - rad):i + rad + 1].max():
            cuts.append(round((i + 1) / fps, 3))
    return cuts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--name", required=True)
    ap.add_argument("--cookies", help="browser to borrow login cookies from (chrome, safari, firefox...)")
    ap.add_argument("--file", help="use an already-downloaded video instead of the URL")
    a = ap.parse_args()
    rd = work_dir(a.name, "reference")
    src = Path(a.file).resolve() if a.file else download(a.url, rd, a.cookies)
    info = ffprobe(src)
    dur = info["duration"]
    print(f"reference: {rel(src)}  [{describe(info)}]")

    cuts = [c for c in scene_cuts(src, info.get("fps") or 30) if 0.15 < c < dur - 0.1]
    bounds = [0.0] + cuts + [dur]
    shots = [b - a for a, b in zip(bounds, bounds[1:])]
    sh = np.array(shots)

    tr = load_transcript(str(src)) if info["has_audio"] else {"words": []}
    words = tr["words"] if tr else []
    speech = sum(w["e"] - w["s"] for w in words)
    first_word = words[0]["s"] if words else None

    music = None
    if info["has_audio"]:
        try:
            bt = beats_for(str(src))
            beats = np.array(bt["beats"])
            on_beat = sum(1 for c in cuts if len(beats) and np.min(np.abs(beats - c)) < 0.09)
            music = {"bpm": bt["bpm"], "cuts_on_beat": f"{on_beat}/{len(cuts)}"}
        except Exception as e:  # silent track etc.
            music = {"error": str(e)[:120]}

    meta = {}
    ij = rd / "ref.info.json"
    if ij.exists():
        import json
        d = json.loads(ij.read_text())
        meta = {k: d.get(k) for k in ("title", "description", "uploader", "track", "artist", "duration", "like_count")}

    stats = {
        "url": a.url, "file": rel(src), "duration": round(dur, 2),
        "size": f"{info.get('width')}x{info.get('height')}", "fps": info.get("fps"),
        "shots": len(shots), "cuts": [round(c, 2) for c in cuts],
        "avg_shot": round(float(sh.mean()), 2), "median_shot": round(float(np.median(sh)), 2),
        "shortest_shot": round(float(sh.min()), 2), "longest_shot": round(float(sh.max()), 2),
        "cuts_per_10s": round(len(cuts) / dur * 10, 1),
        "first_cut": round(cuts[0], 2) if cuts else None,
        "speech_seconds": round(speech, 1), "speech_ratio": round(speech / dur, 2) if dur else 0,
        "words_per_sec": round(len(words) / speech, 2) if speech else 0,
        "first_word_at": first_word, "transcript": " ".join(w["w"] for w in words),
        "music": music, "meta": meta,
    }
    write_json(rd / "stats.json", stats)

    hook_t = [min(dur - 0.05, x) for x in (0.05, 0.5, 1.0, 1.5, 2.0, 2.5)]
    contact_sheet.make(src, rd / "hook.jpg", times=hook_t, cols=6)
    mids = [(a_ + b_) / 2 for a_, b_ in zip(bounds, bounds[1:])]
    if len(mids) > 24:
        mids = [mids[int(i * len(mids) / 24)] for i in range(24)]
    labels = [f"{tc(t)} shot{i + 1}" for i, t in enumerate(mids)]
    contact_sheet.make(src, rd / "shots.jpg", times=mids, cols=6, labels=labels)

    print(f"  {len(shots)} shots, avg {stats['avg_shot']}s (median {stats['median_shot']}s), "
          f"{stats['cuts_per_10s']} cuts / 10s, first cut at {stats['first_cut']}s")
    print(f"  speech {stats['speech_ratio'] * 100:.0f}% of runtime, {stats['words_per_sec']} words/s, "
          f"first word at {first_word}s")
    if music:
        print(f"  music: {music}")
    if meta.get("title") or meta.get("track"):
        print(f"  meta: {meta.get('title')!r} track={meta.get('track')!r} artist={meta.get('artist')!r}")
    print(f"  transcript: {stats['transcript'][:300]}")
    print(f"\nlook at: {rel(rd / 'hook.jpg')}, {rel(rd / 'shots.jpg')}\nthen write: {rel(rd.parent / 'style_spec.md')}")


if __name__ == "__main__":
    main()
