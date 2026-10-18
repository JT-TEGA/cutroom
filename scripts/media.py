"""Media helpers: folder input, capture-time ordering, photos (HEIC -> JPEG). No OpenCV / Whisper here.

  media.py raw/shoot-oct/        # list a folder in capture order
"""
import datetime as dt
import re
import sys
from pathlib import Path

from common import cache_dir, describe, ffprobe, file_key, parse_clip_spec, rel, resolve, run

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".3gp"}
AUDIO_EXT = {".m4a", ".wav", ".mp3", ".aac", ".aif", ".aiff", ".caf", ".flac", ".ogg", ".opus"}
NEEDS_CONVERT = {".heic", ".heif", ".webp", ".tif", ".tiff"}


def is_image(p):
    return Path(p).suffix.lower() in IMAGE_EXT


def is_video(p):
    return Path(p).suffix.lower() in VIDEO_EXT


def is_audio(p):
    """Voiceover / voice memo files (voiceover/)."""
    return Path(p).suffix.lower() in AUDIO_EXT


def _pil():
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    return Image, ImageOps


def _parse_exif_time(s, offset=None):
    try:
        t = dt.datetime.strptime(str(s).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if offset and re.match(r"^[+-]\d\d:\d\d$", str(offset)):
        sign = 1 if offset[0] == "+" else -1
        tz = dt.timezone(sign * dt.timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6])))
        return t.replace(tzinfo=tz).timestamp()
    return t.timestamp()


def capture_time(path):
    """When the photo/clip was taken (EXIF / QuickTime metadata), falling back to file dates."""
    p = resolve(path)
    t = None
    if is_image(p):
        try:
            Image, _ = _pil()
            with Image.open(p) as im:
                ex = im.getexif()
                sub = ex.get_ifd(0x8769)
                t = _parse_exif_time(sub.get(36867) or ex.get(306), sub.get(36881))
        except Exception:
            t = None
    elif is_video(p):
        try:
            import json
            r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_entries", "format_tags", p])
            tags = {k.lower(): v for k, v in json.loads(r.stdout).get("format", {}).get("tags", {}).items()}
            s = tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")
            if s:
                s = s.replace("Z", "+00:00")
                s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s)
                t = dt.datetime.fromisoformat(s).timestamp()
        except Exception:
            t = None
    if t is None:
        st = p.stat()
        t = getattr(st, "st_birthtime", st.st_mtime)
    return t


def expand(specs):
    """Clip specs -> [(path, in, out)]. A folder expands to every photo/clip inside, in capture order."""
    out = []
    for spec in specs:
        path, a, b = parse_clip_spec(spec)
        p = resolve(path)
        if p.is_dir():
            files = [f for f in p.rglob("*") if f.is_file() and not f.name.startswith(".")
                     and (is_image(f) or is_video(f))]
            files.sort(key=lambda f: (capture_time(f), f.name))
            out += [(rel(f), None, None) for f in files]
        else:
            out.append((path, a, b))
    return out


def photo_path(src):
    """A path OpenCV can read with the right orientation (HEIC/WebP/TIFF converted to a cached JPEG)."""
    p = resolve(src)
    if p.suffix.lower() not in NEEDS_CONVERT:
        return p
    out = cache_dir("photos") / f"{file_key(p)}.jpg"
    if not out.exists():
        Image, ImageOps = _pil()
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.save(out, "JPEG", quality=95)
    return out


def photo_size(src):
    Image, ImageOps = _pil()
    with Image.open(resolve(src)) as im:
        im = ImageOps.exif_transpose(im)
        return im.size


def describe_media(src):
    if is_image(src):
        w, h = photo_size(src)
        shape = "vertical" if h > w else ("square" if h == w else "horizontal")
        return f"photo {w}x{h} ({shape})"
    return describe(ffprobe(src))


if __name__ == "__main__":
    for path, a, b in expand(sys.argv[1:]):
        t = dt.datetime.fromtimestamp(capture_time(path)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{t}  {path}  [{describe_media(path)}]")
