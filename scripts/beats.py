#!/usr/bin/env python3
"""Beat grid, downbeats and drops for a music track (librosa; numpy fallback).

  beats.py music/track.mp3            # BPM, first beats, downbeats, drops
  beats.py music/track.mp3 --all      # every beat time

Cached at work/_cache/beats/<key>.json
  {"bpm": 104.2, "beats": [...], "downbeats": [...], "drops": [...]}
"drops" = moments where the track's energy jumps (the drop after a build-up), snapped to a downbeat.
"""
import argparse
import subprocess

import numpy as np

from common import cache_dir, file_key, read_json, resolve, tc, write_json

SR, HOP, NFFT = 22050, 512, 2048
CACHE_VERSION = 4


def _load(src):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(resolve(src)), "-vn", "-ac", "1",
           "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32).copy()


# ---------------------------------------------------------------- numpy fallback (no librosa)

def _stft_mag(x):
    n = 1 + (len(x) - NFFT) // HOP
    win = np.hanning(NFFT).astype(np.float32)
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(max(n, 1))[:, None]
    return np.abs(np.fft.rfft(x[np.minimum(idx, len(x) - 1)] * win, axis=1)).T  # (freq, frames)


def _flux(S):
    logm = np.log1p(100 * S)
    f = np.concatenate([[0], np.maximum(0, np.diff(logm, axis=1)).sum(0)])
    f -= np.convolve(f, np.ones(16) / 16, mode="same")
    f = np.maximum(f, 0)
    return f / (f.std() + 1e-9)


def _tempo(env, fr, lo=70, hi=180, prior=110):
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lags = np.arange(int(fr * 60 / hi), int(fr * 60 / lo) + 1)
    bpms = 60 * fr / lags
    w = np.exp(-0.5 * (np.log2(bpms / prior) / 0.9) ** 2)
    return float(bpms[np.argmax(ac[lags] * w)])


def _dp_track(env, fr, bpm, tight=100):
    period = fr * 60 / bpm
    n = len(env)
    score, back = env.copy(), -np.ones(n, int)
    lo, hi = int(round(period / 2)), int(round(period * 2))
    for t in range(hi, n):
        prev = np.arange(t - hi, t - lo + 1)
        pen = -tight * np.log((t - prev) / period) ** 2
        j = int(np.argmax(score[prev] + pen))
        score[t] = env[t] + score[prev[j]] + pen[j]
        back[t] = prev[j]
    t = int(np.argmax(score[-hi:])) + n - hi
    out = []
    while t >= 0:
        out.append(t)
        t = back[t]
    return np.array(out[::-1])


# ---------------------------------------------------------------- analysis

def _fill_gaps(beats, period, dur):
    """Quiet intros/breaks can lose beats; keep a regular grid through them."""
    if len(beats) < 2:
        return np.arange(0, dur, period)
    out = list(np.arange(beats[0], -1e-9, -period)[::-1][:-1])
    for a, b in zip(beats, beats[1:]):
        out.append(a)
        n = int(round((b - a) / period))
        if n > 1:
            out += [a + (b - a) * k / n for k in range(1, n)]
    out.append(beats[-1])
    out += list(np.arange(beats[-1] + period, dur, period))
    return np.array([b for b in out if 0 <= b < dur])


def _attack_offset(x, beats):
    """Median distance from grid beats to the sharpest transient nearby (the hit's attack click;
    the low end of a kick peaks 30-40 ms later, which is what onset envelopes lock onto)."""
    k = max(1, int(0.003 * SR))
    env = np.convolve(np.abs(x), np.ones(k) / k, mode="same")
    d = np.diff(env, prepend=env[0])
    offs = []
    for b in beats:
        i0, i1 = int((b - 0.08) * SR), int((b + 0.03) * SR)
        if i0 < 0 or i1 > len(d) or d[i0:i1].max() <= 0:
            continue
        offs.append((i0 + int(np.argmax(d[i0:i1]))) / SR - b)
    if len(offs) < 4:
        return 0.0
    return float(np.clip(np.median(offs), -0.06, 0.06))


def analyse(src):
    x = _load(src)
    dur = len(x) / SR
    fr = SR / HOP
    try:
        import librosa
        S = np.abs(librosa.stft(x, n_fft=NFFT, hop_length=HOP))
        onset = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S, ref=np.max), sr=SR, hop_length=HOP)
        tempo, frames = librosa.beat.beat_track(onset_envelope=onset, sr=SR, hop_length=HOP, start_bpm=110,
                                                units="frames", trim=False)
        bpm = float(np.atleast_1d(tempo)[0])
        beats = librosa.frames_to_time(frames, sr=SR, hop_length=HOP)
        engine = f"librosa {librosa.__version__}"
    except ImportError:
        S = _stft_mag(x)
        env = _flux(S)
        bpm = _tempo(env, fr)
        beats = _dp_track(env, fr, bpm) / fr
        engine = "numpy"
    period = 60 / bpm
    beats = _fill_gaps(np.asarray(beats, float), period, dur)

    freqs = np.linspace(0, SR / 2, S.shape[0])
    low = S[freqs < 150].sum(0)
    low_on = np.concatenate([[0], np.maximum(0, np.diff(low))])
    kick = lambda ts: float(low_on[np.clip((np.asarray(ts) * fr).round().astype(int), 0, len(low_on) - 1)].mean())
    # trackers sometimes lock onto off-beat hi-hats; the beat is where the kick is
    if kick(beats + period / 2) > 1.3 * kick(beats):
        beats = _fill_gaps(beats + period / 2, period, dur)
    # onset envelopes lag the real hit by a frame or two: line the grid up with the kick attacks
    lag = _attack_offset(x, beats)
    beats = beats + lag
    beats = beats[beats >= 0]

    # downbeats: the 1-in-4 phase with the most kick (low-band onset) energy
    bf = np.clip((beats * fr).round().astype(int), 0, len(low_on) - 1)
    phase = int(np.argmax([low_on[bf[p::4]].mean() if len(bf[p::4]) else 0 for p in range(4)]))
    downbeats = beats[phase::4]

    # drops: energy after a downbeat >> energy before it
    rms = np.sqrt((S ** 2).mean(0))
    k = max(1, int(0.5 * fr))
    rms = np.convolve(rms, np.ones(k) / k, mode="same")
    loud = 0.6 * np.percentile(rms, 95)
    cands = []
    for t in downbeats:
        i = int(t * fr)
        before = rms[max(0, i - int(4 * fr)):i]
        after = rms[i:i + int(2 * fr)]
        if len(before) < fr or len(after) < fr / 2:
            continue
        ratio = after.mean() / (before.mean() + 1e-9)
        if ratio > 1.5 and after.mean() >= loud:
            cands.append((ratio, t))
    drops = []
    for ratio, t in sorted(cands, reverse=True):
        if all(abs(t - d) > 6 for d in drops):
            drops.append(t)
    r3 = lambda a: [round(float(v), 3) for v in a]
    return {"v": CACHE_VERSION, "engine": engine, "bpm": round(bpm, 1), "duration": round(dur, 2),
            "beats": r3(beats), "downbeats": r3(downbeats), "drops": r3(sorted(drops))}


def beats_for(src, force=False):
    out = cache_dir("beats") / f"{file_key(src)}.json"
    d = read_json(out) if out.exists() and not force else None
    if not d or d.get("v") != CACHE_VERSION:
        d = analyse(src)
        write_json(out, d)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    d = beats_for(a.audio, a.force)
    bs = d["beats"]
    print(f"{a.audio}: ~{d['bpm']} BPM ({d['engine']}), {len(bs)} beats, one every {60 / d['bpm']:.2f}s")
    show = bs if a.all else bs[:16]
    print("  beats:     " + "  ".join(tc(x, 2) for x in show) + ("" if a.all else "  ..."))
    print("  downbeats: " + "  ".join(tc(x, 2) for x in d["downbeats"][:10]) + "  ...")
    print("  drops:     " + ("  ".join(tc(x, 2) for x in d["drops"]) or "none found"))


if __name__ == "__main__":
    main()
