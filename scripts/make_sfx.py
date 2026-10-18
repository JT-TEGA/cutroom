#!/usr/bin/env python3
"""Generate a starter SFX kit into assets/sfx/ (synthesised, royalty-free).

  make_sfx.py           # whoosh, bass_hit, pop, riser, click (skips existing files)
  make_sfx.py --force

Drop your own .wav/.mp3 files in assets/sfx/ any time; briefs can name them.
"""
import argparse
import wave

import numpy as np

from common import ROOT, rel

SR = 48000
rng = np.random.default_rng(7)


def env(n, attack, release_pow=2.0):
    a = int(attack * SR)
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a) if a else 1
    e[a:] = np.linspace(1, 0, n - a) ** release_pow
    return e


def lowpass(x, cutoff):
    """One-pole low-pass with a time-varying cutoff (Hz array or scalar)."""
    c = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    a = 1 - np.exp(-2 * np.pi * c / SR)
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def whoosh(d=0.55):
    n = int(d * SR)
    t = np.linspace(0, 1, n)
    sweep = 300 + 5000 * np.sin(np.pi * t) ** 2
    noise = rng.standard_normal(n)
    x = lowpass(noise, sweep) - lowpass(noise, sweep * 0.25)
    x *= np.sin(np.pi * t) ** 1.5
    pan = 0.5 + 0.45 * np.sin(np.pi * (t - 0.5))
    return np.stack([x * (1 - pan), x * pan], 1)


def bass_hit(d=0.9):
    n = int(d * SR)
    t = np.arange(n) / SR
    f = 42 + 80 * np.exp(-t * 18)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.2)
    x += 0.35 * np.tanh(3 * x)
    click = rng.standard_normal(n) * np.exp(-t * 400) * 0.4
    return np.stack([x + click] * 2, 1)


def pop(d=0.12):
    n = int(d * SR)
    t = np.arange(n) / SR
    f = 900 * np.exp(-t * 25) + 300
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.002, 3)
    return np.stack([x] * 2, 1)


def riser(d=1.6):
    n = int(d * SR)
    t = np.linspace(0, 1, n)
    noise = lowpass(rng.standard_normal(n), 200 + 7000 * t ** 2)
    tone = np.sin(2 * np.pi * np.cumsum(200 + 900 * t ** 2) / SR) * 0.3
    x = (noise + tone) * t ** 2
    x[-int(0.02 * SR):] *= np.linspace(1, 0, int(0.02 * SR))
    return np.stack([x] * 2, 1)


def click(d=0.05):
    n = int(d * SR)
    t = np.arange(n) / SR
    x = rng.standard_normal(n) * np.exp(-t * 180) + np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 120)
    return np.stack([x] * 2, 1)


def write(path, x, peak_db=-3.0):
    x = x / (np.abs(x).max() + 1e-9) * 10 ** (peak_db / 20)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((x * 32767).astype(np.int16).tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    d = ROOT / "assets/sfx"
    d.mkdir(parents=True, exist_ok=True)
    for name, fn in [("whoosh", whoosh), ("bass_hit", bass_hit), ("pop", pop), ("riser", riser), ("click", click)]:
        p = d / f"{name}.wav"
        if p.exists() and not a.force:
            continue
        write(p, fn())
        print(f"  {rel(p)}")


if __name__ == "__main__":
    main()
