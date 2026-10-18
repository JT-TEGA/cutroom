"""Synthetic but good-looking media for demos and screenshots: no real footage needed.

    .venv/bin/python scripts/demo_media.py [out_dir]      (default .demo/media)

Writes 9:16 clips (neon gym, golden-hour lagoon, top-down brunch...), photos, a voice memo (macOS `say`) and a
120 BPM track with a quiet intro and a drop. Everything is drawn procedurally: soft light, bokeh, grain, a slow push.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 720, 1280          # output size
SW, SH = 360, 640         # soft layers are drawn at half size, then scaled up
FPS = 30
FF = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]

yy, xx = np.mgrid[0:SH, 0:SW].astype(np.float32)
YN, XN = yy / SH, xx / SW


def hexrgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255


def gradient(stops: list[tuple[float, str]]) -> np.ndarray:
    """Vertical gradient (soft layer size) from (position 0-1, colour) stops."""
    pos = np.array([p for p, _ in stops], np.float32)
    cols = np.stack([hexrgb(c) for _, c in stops])
    out = np.empty((SH, SW, 3), np.float32)
    for ch in range(3):
        out[..., ch] = np.interp(YN[:, 0], pos, cols[:, ch])[:, None]
    return out


def glow(img: np.ndarray, x: float, y: float, r: float, color: str, a: float = 1.0, sx: float = 1.0) -> None:
    """Add a soft round light at (x, y) in 0-1 coordinates (radius r as a fraction of the width)."""
    d2 = ((XN - x) * SW / sx) ** 2 + ((YN - y) * SH) ** 2
    img += a * np.exp(-d2 / (2 * (r * SW) ** 2))[..., None] * hexrgb(color)


def disc(img: np.ndarray, x: float, y: float, r: float, color: str, a: float = 1.0, soft: float = 0.15) -> None:
    """A filled circle with a soft edge (bokeh, plates, sun)."""
    d = np.sqrt(((XN - x) * SW) ** 2 + ((YN - y) * SH) ** 2) / (r * SW)
    m = np.clip((1 - d) / soft, 0, 1)
    img[:] = img * (1 - a * m[..., None]) + a * m[..., None] * hexrgb(color)


_vig: dict[float, np.ndarray] = {}
_grain: list[np.ndarray] = []


def finish(soft: np.ndarray, t: float, seed: int, zoom: float = 0.06, vignette: float = 0.55, grain: float = 0.035,
           sharp: list | None = None) -> np.ndarray:
    """Soft layer -> full size frame: slow push-in, crisp details, vignette, film grain."""
    if vignette not in _vig:
        vy, vx = np.mgrid[0:H, 0:W].astype(np.float32)
        _vig[vignette] = np.clip(1 - vignette * (((vx / W - 0.5) * 1.3) ** 2 + ((vy / H - 0.5) * 1.05) ** 2), 0, 1)[..., None]
    if not _grain:
        rng = np.random.default_rng(0)
        _grain.extend(rng.normal(0, 1, (H, W, 1)).astype(np.float32) for _ in range(8))
    img = Image.fromarray((np.clip(soft, 0, 1) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    for fn in sharp or []:
        fn(img, t)
    z = 1 + zoom * t / 5
    cw, ch = int(W / z), int(H / z)
    img = img.crop(((W - cw) // 2, (H - ch) // 2, (W + cw) // 2, (H + ch) // 2)).resize((W, H), Image.BICUBIC)
    a = np.asarray(img).astype(np.float32) / 255 * _vig[vignette]
    a += grain * _grain[(seed + int(t * FPS)) % len(_grain)]
    return (np.clip(a, 0, 1) * 255).astype(np.uint8)


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    f = ROOT / "assets" / "fonts" / "Inter[opsz,wght].ttf"
    try:
        ft = ImageFont.truetype(str(f), size)
        try:
            ft.set_variation_by_axes([32, 700 if bold else 400])
        except Exception:
            pass
        return ft
    except OSError:
        return ImageFont.load_default()


# ---------------------------------------------------------------- scenes: frame(t) -> HxWx3 uint8

def bokeh_field(img: np.ndarray, t: float, seed: int, colors: list[str], n: int = 18, drift: float = 0.02,
                size: tuple[float, float] = (0.04, 0.12), alpha: float = 0.35) -> None:
    rng = np.random.default_rng(seed)
    for _ in range(n):
        x, y = rng.random(), rng.random()
        r = rng.uniform(*size)
        sp = rng.uniform(-1, 1)
        c = colors[rng.integers(len(colors))]
        disc(img, x + drift * sp * t, y - drift * 0.4 * t * (0.5 + abs(sp)), r, c, alpha * rng.uniform(0.4, 1), soft=0.5)


def alarm(t: float) -> np.ndarray:
    img = gradient([(0, "#060914"), (0.6, "#0b1430"), (1, "#05060c")])
    flick = 0.9 + 0.1 * math.sin(t * 9)
    glow(img, 0.5, 0.62, 0.42, "#2c5cff", 0.35 * flick)
    glow(img, 0.5, 0.62, 0.16, "#9fc0ff", 0.55 * flick, sx=0.8)
    bokeh_field(img, t, 3, ["#1d3fa8", "#3a2a7a", "#12306e"], n=10, alpha=0.25)

    def phone(im: Image.Image, _: float) -> None:
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = 248, 640, 472, 1080
        d.rounded_rectangle((x0 - 6, y0 - 6, x1 + 6, y1 + 6), 34, fill=(10, 12, 20))
        d.rounded_rectangle((x0, y0, x1, y1), 30, fill=(212, 224, 255))
        d.text(((x0 + x1) / 2, y0 + 120), "5:30", font=font(78), fill=(18, 22, 40), anchor="mm")
        d.text(((x0 + x1) / 2, y0 + 185), "Chest day", font=font(26, False), fill=(60, 70, 110), anchor="mm")
        d.rounded_rectangle((x0 + 30, y1 - 90, x1 - 30, y1 - 40), 25, fill=(124, 92, 255))
    return finish(img, t, 1, zoom=0.1, sharp=[phone])


def preworkout(t: float) -> np.ndarray:
    img = gradient([(0, "#2a0838"), (0.55, "#8a1f4d"), (1, "#f2683a")])
    glow(img, 0.5, 0.45, 0.35, "#ff9f6b", 0.35)
    rng = np.random.default_rng(7)
    for _ in range(40):
        x, y0, r, sp = rng.random(), rng.random(), rng.uniform(0.01, 0.035), rng.uniform(0.08, 0.25)
        y = (y0 - sp * t) % 1.1
        disc(img, x + 0.01 * math.sin(t * 3 + x * 9), y, r, "#ffd7c2", 0.45, soft=0.6)
    return finish(img, t, 2, zoom=0.05)


def gym(t: float, a: str = "#7c5cff", b: str = "#2ad4ff", lift: bool = True, seed: int = 3) -> np.ndarray:
    img = gradient([(0, "#07070a"), (0.7, "#121218"), (1, "#050507")])
    for x, c in ((0.12, a), (0.88, b)):
        glow(img, x, 0.42, 0.05, c, 0.9, sx=0.25)
        glow(img, x, 0.42, 0.22, c, 0.25)
        img[:, int(x * SW) - 2:int(x * SW) + 2] = img[:, int(x * SW) - 2:int(x * SW) + 2] * 0.3 + 0.7 * hexrgb("#f4f0ff")
    glow(img, 0.5, 0.95, 0.5, a, 0.12)
    bokeh_field(img, t, seed, [a, b], n=8, size=(0.02, 0.05), alpha=0.25)
    yb = 0.47 + (0.07 * math.sin(t * 2.2) if lift else 0)

    def barbell(im: Image.Image, _: float) -> None:
        if not lift and seed % 2:
            return
        d = ImageDraw.Draw(im)
        y = int(yb * H)
        d.rectangle((40, y - 7, W - 40, y + 7), fill=(28, 28, 34))
        d.line((40, y - 7, W - 40, y - 7), fill=(150, 140, 200), width=2)
        for x in (110, W - 110):
            d.ellipse((x - 62, y - 150, x + 62, y + 150), fill=(14, 14, 18), outline=(110, 96, 190), width=3)
            d.ellipse((x - 22, y - 50, x + 22, y + 50), fill=(30, 30, 36))
        d.rectangle((W // 2 - 120, int(0.8 * H), W // 2 + 120, int(0.8 * H) + 36), fill=(16, 16, 20))
    return finish(img, t, seed, zoom=0.07, sharp=[barbell])


def cable(t: float) -> np.ndarray:
    img = gradient([(0, "#03110f"), (0.5, "#08201c"), (1, "#020605")])
    for k in range(4):
        ang = -0.6 + 0.35 * k + 0.12 * math.sin(t * 0.8 + k)
        d = np.abs((XN - 0.5) * math.cos(ang) * SW - (YN - 0.05) * math.sin(ang) * SH)
        img += np.exp(-(d / 14) ** 2)[..., None] * hexrgb("#2bd4b4") * 0.18 * (1.2 - YN[..., None])
    glow(img, 0.5, 0.05, 0.25, "#9ff5e4", 0.5)
    bokeh_field(img, t, 11, ["#1fbfa0", "#7cf0d8"], n=10, size=(0.02, 0.05), alpha=0.3)

    def cables(im: Image.Image, tt: float) -> None:
        d = ImageDraw.Draw(im)
        sw = 70 * math.sin(tt * 1.8)
        for side in (-1, 1):
            d.line((W / 2 + side * 330, 80, W / 2 + side * (120 + sw), 820), fill=(190, 255, 240), width=3)
            d.ellipse((W / 2 + side * (120 + sw) - 16, 804, W / 2 + side * (120 + sw) + 16, 836), fill=(220, 255, 248))
    return finish(img, t, 4, zoom=0.05, sharp=[cables])


def lagoon(t: float) -> np.ndarray:
    img = gradient([(0, "#2b2350"), (0.32, "#d96f7a"), (0.5, "#ffb37a"), (0.56, "#ffd9a8"), (0.58, "#7a5a7a"), (1, "#1c1630")])
    glow(img, 0.62, 0.52, 0.5, "#ff9a5c", 0.35)
    disc(img, 0.62, 0.5, 0.11, "#fff1d6", 0.95, soft=0.08)
    glow(img, 0.62, 0.5, 0.16, "#ffd08a", 0.6)
    water = YN > 0.575
    for k in range(26):
        y = 0.6 + 0.4 * (k / 26) ** 1.4
        w = 0.06 + 0.25 * (k / 26)
        x = 0.62 + 0.04 * math.sin(t * 1.5 + k * 1.7)
        m = np.exp(-(((XN - x) / w) ** 2) - ((YN - y) * SH / (1.2 + k * 0.1)) ** 2)
        img += (m * water)[..., None] * hexrgb("#ffd9a8") * 0.5
    bokeh_field(img, t, 5, ["#ffcf9a", "#ff8fa0"], n=6, size=(0.03, 0.06), alpha=0.2)
    return finish(img, t, 5, zoom=0.04, grain=0.03)


def brunch(t: float) -> np.ndarray:
    img = gradient([(0, "#e9dccb"), (1, "#cdb79c")])
    ang = t * 0.12
    plates = [(0.32, 0.3, 0.2, ["#f2b33d", "#7fb069", "#e2614b"]), (0.7, 0.52, 0.17, ["#c6492f", "#f4d58d"]),
              (0.36, 0.74, 0.18, ["#5a8f4e", "#f2e6c9", "#d9822b"])]
    for (px, py, r, foods) in plates:
        cx = 0.5 + (px - 0.5) * math.cos(ang) - (py - 0.5) * math.sin(ang) * SH / SW * 0.4
        cy = py + 0.01 * math.sin(t)
        disc(img, cx + 0.015, cy + 0.012, r * 1.02, "#9c8366", 0.35, soft=0.4)
        disc(img, cx, cy, r, "#fbf8f2", 1.0, soft=0.03)
        disc(img, cx, cy, r * 0.8, "#f1ece2", 1.0, soft=0.05)
        rng = np.random.default_rng(int(px * 100))
        for c in foods:
            for _ in range(3):
                a, d = rng.random() * 6.28, rng.random() * r * 0.45
                disc(img, cx + d * math.cos(a + ang), cy + d * math.sin(a + ang) * SW / SH, r * rng.uniform(0.15, 0.28), c, 0.95, soft=0.25)
    disc(img, 0.82, 0.15, 0.07, "#f7f3ea", 1, soft=0.05)
    disc(img, 0.82, 0.15, 0.05, "#7a4a2a", 1, soft=0.1)
    glow(img, 0.2, 0.05, 0.6, "#fff4e0", 0.25)
    return finish(img, t, 6, zoom=0.05, vignette=0.4, grain=0.025)


def studio(t: float, tint: str = "#b9a68f", light: str = "#fff4e6", seed: int = 8) -> np.ndarray:
    img = gradient([(0, "#2a2420"), (0.5, "#5c4d40"), (1, "#1a1512")])
    glow(img, 0.5, 0.42, 0.45, tint, 0.45)
    arch = (np.abs(XN - 0.5) < 0.22) & ((YN > 0.22) | (((XN - 0.5) * SW) ** 2 + ((YN - 0.22) * SH) ** 2 < (0.22 * SW) ** 2)) & (YN < 0.86)
    img[arch] = img[arch] * 0.35 + 0.65 * hexrgb(light)
    img[:] = np.asarray(Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3))).astype(np.float32) / 255
    glow(img, 0.5 + 0.05 * math.sin(t), 0.9, 0.35, light, 0.18)
    # a model in the window light, out of focus: head, neck, shoulders, a dress flaring to the floor
    sway = 4 * math.sin(t * 0.9)
    fig = Image.new("L", (SW, SH), 0)
    d = ImageDraw.Draw(fig)
    cx = SW / 2 + sway
    d.ellipse((cx - 19, 0.235 * SH, cx + 19, 0.235 * SH + 46), fill=255)
    d.rectangle((cx - 8, 0.235 * SH + 40, cx + 8, 0.235 * SH + 58), fill=255)
    d.polygon([(cx - 46, 0.33 * SH), (cx + 46, 0.33 * SH), (cx + 30, 0.47 * SH), (cx + 62, 0.86 * SH),
               (cx - 62, 0.86 * SH), (cx - 30, 0.47 * SH)], fill=255)
    d.ellipse((cx - 50, 0.33 * SH - 14, cx + 50, 0.33 * SH + 22), fill=255)
    m = np.asarray(fig.filter(ImageFilter.GaussianBlur(5))).astype(np.float32)[..., None] / 255
    img[:] = img * (1 - 0.88 * m)
    glow(img, 0.5 + sway / SW + 0.06, 0.4, 0.05, light, 0.18, sx=0.4)
    return finish(img, t, seed, zoom=0.05, vignette=0.5)


def night(t: float, palette: list[str], seed: int) -> np.ndarray:
    img = gradient([(0, "#05040a"), (0.6, "#0d0a1a"), (1, "#05040a")])
    bokeh_field(img, t, seed, palette, n=34, drift=0.03, size=(0.03, 0.11), alpha=0.5)
    glow(img, 0.5, 0.6, 0.5, palette[0], 0.12)
    return finish(img, t, seed, zoom=0.04)


# ---------------------------------------------------------------- writers

def clip(path: Path, fn, seconds: float) -> None:
    n = int(seconds * FPS)
    p = subprocess.Popen(FF + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                               "-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.02:sample_rate=48000",
                               "-t", f"{seconds}", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                               "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], stdin=subprocess.PIPE)
    assert p.stdin
    for i in range(n):
        p.stdin.write(fn(i / FPS).tobytes())
    p.stdin.close()
    if p.wait():
        raise SystemExit(f"ffmpeg failed for {path}")


def photo(path: Path, fn) -> None:
    Image.fromarray(fn(1.5)).save(path, quality=92)


def voice(path: Path, text: str) -> None:
    if not shutil.which("say"):
        print("  (no `say` on this system: skipping the voice memo)")
        return
    aiff = path.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Samantha", "-r", "175", "-o", str(aiff), text], check=True)
    # a phone voice memo: a bit of room noise and level wobble, then AAC
    subprocess.run(FF + ["-i", str(aiff), "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.004:sample_rate=44100",
                         "-filter_complex", "[0:a]aresample=44100,volume=0.8[v];[v][1:a]amix=inputs=2:duration=first:normalize=0",
                         "-c:a", "aac", "-b:a", "128k", str(path)], check=True)
    aiff.unlink()


def music(path: Path, seconds: float = 48.0, bpm: float = 120.0, sr: int = 44100) -> None:
    """Kick, hats, bass and a pad: 8 quiet bars, a riser, then the drop at bar 9."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    x = np.zeros(n, np.float32)
    period = 60.0 / bpm
    drop = 32 * period
    rng = np.random.default_rng(1)
    for k in range(int(seconds / period)):
        s = int(k * period * sr)
        after = k * period >= drop
        m = min(n - s, int(0.25 * sr))
        tt = np.arange(m) / sr
        x[s:s + m] += (0.95 if after else 0.45) * np.sin(2 * np.pi * (120 * np.exp(-tt * 20) + 42) * tt) * np.exp(-tt * 16)
        for off in (0.5,) if not after else (0.25, 0.5, 0.75):
            h = int((k + off) * period * sr)
            if h < n:
                hm = min(n - h, int(0.05 * sr))
                x[h:h + hm] += (0.18 if after else 0.08) * rng.standard_normal(hm) * np.exp(-np.arange(hm) / sr * 80)
    chord = [55, 65.4, 82.4, 98]
    for i, f in enumerate(chord):
        x += (0.05 + 0.07 * (t >= drop)) * np.sin(2 * np.pi * f * t + i) * (0.6 + 0.4 * np.sin(2 * np.pi * t / (8 * period)))
    rise = (t > drop - 4 * period) & (t < drop)
    x[rise] += 0.25 * rng.standard_normal(rise.sum()).astype(np.float32) * ((t[rise] - (drop - 4 * period)) / (4 * period))
    x = (x / max(1e-6, np.abs(x).max()) * 0.85 * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(x.tobytes())


VO_TEXT = ("Five thirty A M. The alarm goes off, and I'm already up. Quick pre workout, then straight to the gym. "
           "Today is chest day. Incline bench first, four sets of ten. Cable fly to finish. "
           "Then a slow walk by the lagoon, and brunch in Lekki with the girls. Discipline over motivation, every single day.")

SETS = {
    "gym": [("alarm-5am.mp4", alarm, 4), ("pre-workout.mp4", preworkout, 3.5), ("incline-bench.mp4", gym, 5),
            ("cable-fly.mp4", cable, 4), ("lagoon-walk.mp4", lagoon, 5), ("brunch-lekki.mp4", brunch, 4)],
    "legs": [("squats.mp4", lambda t: gym(t, "#ff5c8a", "#ffb35c", True, 21), 5),
             ("leg-press.mp4", lambda t: gym(t, "#5cc8ff", "#7c5cff", True, 22), 5),
             ("walking-lunges.mp4", lambda t: gym(t, "#3ddc97", "#2ad4ff", False, 23), 5)],
    "bts": [("set-lights.mp4", lambda t: studio(t, "#c9a27a", "#fff1dc", 31), 4),
            ("makeup-chair.mp4", lambda t: studio(t, "#d7a3b6", "#ffe6f0", 32), 4),
            ("first-look.mp4", lambda t: studio(t, "#9fb3c8", "#eef6ff", 33), 4)],
}
NIGHT = [["#ff8a3d", "#ffd36b", "#ff4d6d"], ["#7c5cff", "#5cc8ff", "#ff6bd6"], ["#ffcf5c", "#ff8a3d", "#fff1c1"],
         ["#3ddc97", "#5cc8ff", "#c3ff9e"], ["#ff4d6d", "#7c5cff", "#ffd36b"], ["#5cc8ff", "#ffffff", "#7c5cff"]]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".demo" / "media"
    for sub in ("gym", "legs", "bts", "night", "glow-up"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for group, items in SETS.items():
        for name, fn, secs in items:
            p = out / group / name
            if not p.exists():
                print(f"  {group}/{name}")
                clip(p, fn, secs)
    if not (out / "gym" / "fit-check.jpg").exists():
        photo(out / "gym" / "fit-check.jpg", lambda t: studio(t, "#b9a68f", "#fff4e6", 9))
    for i, pal in enumerate(NIGHT, 1):
        p = out / "night" / f"IMG_08{i:02d}.jpg"
        if not p.exists():
            photo(p, lambda t, pal=pal, i=i: night(t, pal, 40 + i))
    for i, (tint, light) in enumerate([("#7a6a5a", "#e9dccb"), ("#8f7a66", "#f6e7d2"), ("#b39a7d", "#fff4e0")], 1):
        p = out / "glow-up" / f"week-{[1, 6, 12][i - 1]}.jpg"
        if not p.exists():
            photo(p, lambda t, tint=tint, light=light, i=i: studio(t, tint, light, 50 + i))
    if not (out / "chest-day-vo.m4a").exists():
        print("  chest-day-vo.m4a")
        voice(out / "chest-day-vo.m4a", VO_TEXT)
    if not (out / "afro-drill-120.wav").exists():
        print("  afro-drill-120.wav")
        music(out / "afro-drill-120.wav")
    print(f"demo media in {out}")


if __name__ == "__main__":
    main()
