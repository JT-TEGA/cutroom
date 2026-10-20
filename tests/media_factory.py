"""Tiny generated media for tests: clips, a photo, a 120 BPM music loop, a voice-like tone. No real footage."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

FF = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]


def clip(path: Path, seconds: float = 3.0, pattern: str = "testsrc2", size: str = "360x640", fps: int = 30,
         tone: float | None = 440.0) -> Path:
    """A vertical test-pattern clip, optionally with a sine tone as its sound."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = FF + ["-f", "lavfi", "-i", f"{pattern}=size={size}:rate={fps}"]
    if tone:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000"]
    cmd += ["-t", f"{seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac"] if tone else []
    subprocess.run(cmd + [str(path)], check=True)
    return path


def photo(path: Path, size: str = "480x640", pattern: str = "smptebars") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(FF + ["-f", "lavfi", "-i", f"{pattern}=size={size}", "-frames:v", "1", str(path)], check=True)
    return path


def music(path: Path, seconds: float = 12.0, bpm: float = 120.0, sr: int = 44100) -> Path:
    """A kick on every beat, hi-hat on the off-beats, a bass note per bar: enough for beat detection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    x = np.zeros(n, np.float32)
    period = 60.0 / bpm
    for k in range(int(seconds / period)):
        s = int(k * period * sr)
        m = min(n - s, int(0.18 * sr))
        tt = np.arange(m) / sr
        x[s:s + m] += 0.9 * np.sin(2 * np.pi * (110 * np.exp(-tt * 18) + 45) * tt) * np.exp(-tt * 22)
        h = int((k + 0.5) * period * sr)
        if h < n:
            hm = min(n - h, int(0.04 * sr))
            x[h:h + hm] += 0.15 * np.random.default_rng(k).standard_normal(hm) * np.exp(-np.arange(hm) / sr * 90)
    x += 0.12 * np.sin(2 * np.pi * 55 * t) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * t / (4 * period))))
    x = (x / max(1e-6, np.abs(x).max()) * 0.8 * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(x.tobytes())
    return path


# MediaRecorder's output in each browser: Chrome/Edge WebM Opus (no duration, no cues: written live), Firefox Ogg
# Opus, Safari fragmented MP4 AAC
RECORDER = {
    "webm": ["-c:a", "libopus", "-b:a", "96k", "-f", "webm", "-live", "1"],
    "ogg": ["-c:a", "libopus", "-b:a", "96k", "-f", "ogg"],
    "mp4": ["-c:a", "aac", "-b:a", "128k", "-f", "mp4", "-movflags", "frag_keyframe+empty_moov"],
}


def recording(path: Path, seconds: float = 2.5, fmt: str = "webm", sr: int = 48000) -> Path:
    """A voice-like take as a browser's MediaRecorder would save it: a 160 Hz buzz in four "syllables" with pauses."""
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * sr)) / sr
    voice = sum(np.sin(2 * np.pi * 160 * k * t) / k for k in range(1, 6))
    envelope = np.clip(np.sin(2 * np.pi * t * 1.6), 0, None) ** 0.5
    x = (0.3 * voice * envelope + 0.002 * np.random.default_rng(1).standard_normal(len(t))).astype(np.float32)
    subprocess.run(FF + ["-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", *RECORDER[fmt], str(path)],
                   input=x.tobytes(), check=True)
    return path


def make_set(root: Path) -> dict[str, Path]:
    """Two clips, a photo and a music track under root."""
    return {
        "clip_a": clip(root / "gym-squats.mp4", 3.0, "testsrc2", tone=440),
        "clip_b": clip(root / "street-walk.mp4", 3.0, "mandelbrot", tone=None),
        "photo": photo(root / "fit-check.jpg"),
        "music": music(root / "beat.wav"),
    }
