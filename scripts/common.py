"""Shared helpers for the short-form creator pipeline.

Settings resolve in layers: DEFAULTS < brand.md < presets/<content type>.md < edl.json "style".

Rule: never import cv2 and faster_whisper in the same process (both bundle
their own libav and macOS complains). Transcription lives in transcribe.py
and is always run as a subprocess.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
WORK = ROOT / "work"
CACHE = WORK / "_cache"
OUTPUT = ROOT / "output"
PRESETS = ROOT / "presets"
PY = sys.executable

# Fallbacks if brand.md is missing a key.
DEFAULTS = {
    "handle": "@YOURHANDLE", "captions": "talking",
    "caption_font": "Inter", "caption_weight": 700, "caption_size": 64, "caption_case": "as-is",
    "caption_color": "#FFFFFF", "caption_highlight_color": "#FFFFFF", "caption_inactive_opacity": 0.6,
    "caption_outline_color": "#000000", "caption_outline_px": 0, "caption_max_words": 4,
    "caption_max_chars": 24, "caption_position": 0.70, "caption_animation": "pop",
    "title_font": "Inter", "title_weight": 800, "title_color": "#FFFFFF", "title_outline_color": "#000000",
    "title_outline_px": 0, "title_case": "as-is", "label_font": "Inter", "accent_color": "#FFFFFF",
    "emphasis_color": "#FFD54A",
    "accent_text_color": "#111111",
    "text_style": "sticker",
    "grade": "none", "grain": 0.0, "vignette": False, "handheld": 0.0, "kenburns": 0.06,
    "kb_moves": ["in", "out", "left", "right"], "photo_fit": "auto", "transition": "cut",
    "transition_location": "cut", "transition_downbeat": "cut", "transition_drop": "cut",
    "ramp_on_drop": "none", "compare_mode": "swipe", "card_min_seconds": 2.5, "text_min_seconds": 1.2,
    "hold_last_beats": 0,
    "max_pause": 0.30, "cut_pad_in": 0.07, "cut_pad_out": 0.12,
    "voice_clean": "voiceover", "voice_denoise_db": 15.0, "voice_deess": 0.4, "voice_comp_ratio": 2.5,
    "voice_highpass": 80, "vo_shot_min": 1.0, "vo_shot_max": 2.5,
    "fillers": ["um", "umm", "uh", "uhh", "erm", "er", "ah", "hmm", "mm", "mhm"],
    "shot_min": 0.6, "shot_max": 1.8, "beat_every": 0, "beat_every_after_drop": 0, "shake_ok": False,
    "one_per_clip": False,
    "talk_default": "some", "target_length": 30,
    "language": "en", "whisper_model": "large-v3-turbo", "vocab": [],
    "end_card": True, "end_card_seconds": 1.5, "end_card_text": "",
    "end_card_logo": "", "end_card_background": "blur",
    "music_mode": "bed", "music_start": "auto", "music_under_voice_db": -14.0, "music_alone_lufs": -14.0,
    "music_under_ambient_db": -6.0, "duck": True, "duck_db": 8.0,
    "ambient_share": 0.0, "ambient_lufs": -20.0, "ambient_duck_db": 7.0,
    "loudness_lufs": -14.0, "true_peak_db": -1.5,
    "width": 1080, "height": 1920, "fps": 30, "video_crf": 18, "audio_bitrate": "192k",
}
LIST_KEYS = {"fillers", "vocab", "kb_moves"}


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def resolve(p):
    p = Path(p).expanduser()
    return p if p.is_absolute() else ROOT / p


def rel(p):
    try:
        return os.path.relpath(Path(p).resolve(), ROOT)
    except ValueError:
        return str(p)


def work_dir(name, *sub):
    d = WORK.joinpath(name, *sub)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(*sub):
    d = CACHE.joinpath(*sub)
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_key(path):
    """Cheap content signature: path + size + mtime."""
    p = resolve(path)
    st = p.stat()
    h = hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()
    return f"{p.stem[:40]}-{h[:10]}"


def read_json(path, default=None):
    p = resolve(path)
    if not p.exists():
        return default
    return json.loads(p.read_text())


def write_json(path, data):
    p = resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return p


# ---------------------------------------------------------------- time codes

def tc(sec, decimals=1):
    """3.25 -> '0:03.2'"""
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = sec - m * 60
    w = 3 + decimals if decimals else 2
    return f"{m}:{s:0{w}.{decimals}f}"


def parse_tc(s):
    """'0:05' | '1:02.5' | '12.3' | '1:02:03' -> seconds."""
    s = str(s).strip()
    if not s:
        raise ValueError("empty timecode")
    parts = [float(x) for x in s.split(":")]
    out = 0.0
    for x in parts:
        out = out * 60 + x
    return out


def parse_clip_spec(spec):
    """'raw/a.mp4' or 'raw/a.mp4@0:05-0:12' -> (path, start|None, end|None)."""
    m = re.match(r"^(.*?)(?:@([\d:.]+)?-([\d:.]+)?)?$", spec)
    path, a, b = m.group(1), m.group(2), m.group(3)
    return path, (parse_tc(a) if a else None), (parse_tc(b) if b else None)


# ---------------------------------------------------------------- brand

def _coerce(key, val):
    v = val.strip()
    if key in LIST_KEYS:
        return [x.strip() for x in v.split(",") if x.strip()]
    if v.lower() in ("true", "yes", "on"):
        return True
    if v.lower() in ("false", "no", "off"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def load_settings(path):
    """The ```settings block of a markdown file (brand.md or a preset) as a dict."""
    p = resolve(path)
    out = {}
    if not p.exists():
        return out
    m = re.search(r"```settings\n(.*?)```", p.read_text(), re.S)
    if not m:
        return out
    for line in m.group(1).splitlines():
        line = re.sub(r"\s+#\s.*$", "", line).strip()   # inline comments; keeps #hex colours
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = _coerce(k.strip(), v)
    return out


def load_brand(path="brand.md"):
    cfg = dict(DEFAULTS)
    cfg.update(load_settings(path))
    return cfg


def list_presets():
    return sorted(p.stem for p in PRESETS.glob("*.md"))


def load_preset(name):
    if not name:
        return {}
    p = PRESETS / f"{name}.md"
    if not p.exists():
        die(f"unknown content type {name!r}. Presets: {', '.join(list_presets())}")
    return load_settings(p)


def style_for(edl):
    """DEFAULTS < brand.md < preset < the edit plan's "style" block (brief overrides live there)."""
    cfg = load_brand()
    cfg.update(load_preset(edl.get("preset")))
    cfg.update(edl.get("style") or {})
    for k in LIST_KEYS:
        if isinstance(cfg.get(k), str):
            cfg[k] = [x.strip() for x in cfg[k].split(",") if x.strip()]
    return cfg


# ---------------------------------------------------------------- processes

def run(cmd, quiet=True, check=True, capture=True):
    cmd = [str(c) for c in cmd]
    if not quiet:
        print("  $", " ".join(cmd[:12]) + (" ..." if len(cmd) > 12 else ""), flush=True)
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        tail = (r.stderr or "")[-2500:]
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(cmd[:8])} ...\n{tail}")
    return r


def need(binary):
    if not shutil.which(binary):
        die(f"{binary} not found. Run scripts/setup.sh")


FF = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]


def ffprobe(path):
    """Normalised media info. Width/height are display size (rotation applied)."""
    p = resolve(path)
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", p])
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    info = {
        "path": str(p),
        "duration": float(d["format"].get("duration") or 0),
        "has_audio": a is not None,
        "has_video": v is not None,
    }
    if a:
        info.update({"sample_rate": int(a.get("sample_rate") or 0), "channels": int(a.get("channels") or 0)})
    if v:
        w, h = int(v["width"]), int(v["height"])
        # rotation = degrees clockwise needed for display (displaymatrix stores the inverse)
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = (-int(float(sd["rotation"]))) % 360
        if "rotate" in v.get("tags", {}):
            rot = int(v["tags"]["rotate"]) % 360
        if rot in (90, 270):
            w, h = h, w
        num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
        fps = float(num) / float(den) if float(den) else 30.0
        trc = v.get("color_transfer", "")
        info.update({
            "width": w, "height": h, "fps": round(fps, 3), "rotation": rot,
            "codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
            "color_transfer": trc, "hdr": trc in ("arib-std-b67", "smpte2084"),
            "still": fmt_is_image(d["format"].get("format_name", "")),
        })
    return info


def fmt_is_image(format_name):
    return "image2" in format_name or format_name.endswith("_pipe")


def describe(info):
    if not info.get("has_video"):
        bits = [f"audio {tc(info['duration'])}"]
        if info.get("sample_rate"):
            bits.append(f"{info['sample_rate'] / 1000:g} kHz {'mono' if info.get('channels') == 1 else 'stereo'}")
        return ", ".join(bits)
    w, h = info["width"], info["height"]
    shape = "vertical" if h > w else ("square" if h == w else "horizontal")
    if info.get("still"):
        return f"image {w}x{h} ({shape})"
    bits = [f"{tc(info['duration'])}", f"{w}x{h} {shape}", f"{info['fps']:g}fps"]
    if info.get("hdr"):
        bits.append("HDR")
    if not info.get("has_audio"):
        bits.append("no audio")
    return ", ".join(bits)


def transcript_path(src):
    return cache_dir("transcripts") / f"{file_key(src)}.json"


def load_transcript(src, auto=True, model=None):
    """Return cached transcript, running transcribe.py in a subprocess if needed."""
    p = transcript_path(src)
    if not p.exists() and auto:
        cmd = [PY, SCRIPTS / "transcribe.py", src]
        if model:
            cmd += ["--model", model]
        subprocess.run([str(c) for c in cmd], check=True)
    return read_json(p)
