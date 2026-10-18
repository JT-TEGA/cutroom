"""A stand-in for osxphotos over a plain folder, for ./cutroom --demo and the walkthrough: each subfolder is an
album, every photo and clip is an item, and a couple of items act as if they were only in iCloud (export "downloads"
them by copying). Same attributes as osxphotos' PhotosDB / PhotoInfo / AlbumInfo / PhotoExporter, as far as
engine.photos uses them.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from .media import IMAGE_EXT, VIDEO_EXT
from .photos import stable_id


class _Photo:
    def __init__(self, path: Path, date: datetime, cloud: bool, favorite: bool):
        from .common import ffprobe
        self.uuid = stable_id(str(path))
        self.original_filename = self.filename = path.name
        self._file = path
        self.ismovie = path.suffix.lower() in VIDEO_EXT
        self.isphoto = not self.ismovie
        self.date = date
        self.favorite = favorite
        self.hidden = self.intrash = False
        self.live_photo = False
        self.path_live_photo = None
        self.path_derivatives: list[str] = []
        self.ismissing = cloud
        self.path = None if cloud else str(path)
        if self.ismovie:
            info = ffprobe(path)
            self.width, self.height = info.get("width"), info.get("height")
            self.exif_info = SimpleNamespace(duration=info.get("duration"))
        else:
            from .media import photo_size
            self.width, self.height = photo_size(path)
            self.exif_info = None


class _Album:
    def __init__(self, title: str, photos: list[_Photo]):
        self.uuid = stable_id("album:" + title)
        self.title = title
        self.photos = photos
        self.folder_names = ["Shoots"] if title.lower() in ("bts", "night out", "night") else []


class _DB:
    def __init__(self, dbfile: str):
        root = Path(dbfile)
        files = sorted(f for f in root.rglob("*") if f.is_file() and not f.name.startswith(".")
                       and f.suffix.lower() in IMAGE_EXT | VIDEO_EXT)
        base = datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc)
        self._photos = [_Photo(f, base - timedelta(hours=3 * k), cloud=k in (2, 9), favorite=k % 4 == 0)
                        for k, f in enumerate(files)]
        by_dir: dict[str, list[_Photo]] = {}
        for p in self._photos:
            if p._file.parent != root:
                by_dir.setdefault(p._file.parent.name, []).append(p)
        title = lambda n: n.upper() if n.lower() == "bts" else n.replace("-", " ").capitalize()  # noqa: E731
        self.album_info = [_Album(title(name), ps) for name, ps in sorted(by_dir.items())]

    def photos(self, images: bool = True, movies: bool = True) -> list[_Photo]:
        return [p for p in self._photos if (images and p.isphoto) or (movies and p.ismovie)]


class _Exporter:
    def __init__(self, photo: _Photo):
        self.photo = photo

    def export(self, dest: str, options: object = None) -> SimpleNamespace:
        out = Path(dest) / self.photo._file.name
        shutil.copy2(self.photo._file, out)
        return SimpleNamespace(exported=[str(out)], error=[])


def stand_in(folder: Path) -> SimpleNamespace:
    """The module-like object engine.photos.PhotosLibrary takes in place of osxphotos."""
    return SimpleNamespace(STAND_IN=True, PhotosDB=_DB, PhotoExporter=_Exporter,
                           ExportOptions=lambda **kw: SimpleNamespace(**kw), folder=folder)
