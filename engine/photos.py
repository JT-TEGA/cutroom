"""The Mac Photos library, read with osxphotos: albums, recent items, thumbnails, and importing originals into a
project (Photos downloads them from iCloud first when they aren't on this Mac). Nothing here writes to the library.

macOS protects ~/Pictures/Photos Library.photoslibrary: the app Cutroom runs from (Terminal, iTerm, VS Code...)
needs Full Disk Access to read it. Without it the status says "no_access" with the steps to grant it; nothing crashes.

    lib = PhotosLibrary()          # osxphotos, the library Photos last opened
    lib.status()                   # starts reading the library in the background; poll until "ready"
    lib.albums(); lib.items(album=..., kind="photo", since=..., until=...); lib.thumbnail(uuid)
    import_items(store, pid, lib, [uuid, ...])     # a job: export originals -> the project's inputs/

CUTROOM_PHOTOS=demo reads a stand-in library made from a folder (CUTROOM_PHOTOS_DIR, default .demo/media) and
CUTROOM_PHOTOS=denied acts as if access was refused, so the demo and the walkthrough never touch a real library.
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from .config import EngineError, log, paths, step

if TYPE_CHECKING:
    from .project import ProjectFile, ProjectStore

State = Literal["idle", "loading", "ready", "no_access", "no_library", "unavailable", "error"]
Kind = Literal["all", "photo", "video"]
RAW_EXT = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".pef", ".srw"}
DEFAULT_LIBRARY = Path.home() / "Pictures" / "Photos Library.photoslibrary"


class PhotosStatus(BaseModel):
    state: State
    message: str = ""
    hint: str | None = None
    app: str | None = Field(None, description="the app Cutroom runs from: the one that needs Full Disk Access")
    library: str | None = None
    photos: int = 0
    videos: int = 0
    favorites: int = 0


class PhotoItem(BaseModel):
    id: str = Field(description="the Photos UUID")
    name: str
    kind: Literal["photo", "video"]
    date: datetime | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    live: bool = Field(False, description="a Live Photo: imported as the still unless the video part is asked for")
    favorite: bool = False
    local: bool = Field(True, description="the original is on this Mac; false = in iCloud, downloaded on import")


class PhotoAlbum(BaseModel):
    id: str
    title: str
    folder: str | None = Field(None, description='folders it sits in, e.g. "Shoots / 2026"')
    count: int
    photos: int
    videos: int
    cover: str | None = Field(None, description="item id to use as its cover thumbnail")
    start: datetime | None = None
    end: datetime | None = None


class ItemPage(BaseModel):
    items: list[PhotoItem]
    total: int
    offset: int
    limit: int


class PhotosError(EngineError):
    pass


# ---------------------------------------------------------------- the app that needs permission

def responsible_app(pid: int | None = None) -> str | None:
    """The .app Cutroom was started from (macOS grants Full Disk Access to that app, not to Python): walk up the
    process tree to the first process inside an .app bundle. "Terminal", "iTerm", "Visual Studio Code"..."""
    pid = pid or os.getpid()
    for _ in range(30):
        try:
            out = subprocess.run(["ps", "-o", "ppid=", "-o", "comm=", "-p", str(pid)], capture_output=True,
                                 text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        if not out:
            return None
        ppid, _, comm = out.partition(" ")
        m = re.match(r"^(.*?)/([^/]+)\.app/", comm.strip())
        if m:
            return m.group(2)
        if not ppid.strip().isdigit() or int(ppid) <= 1:
            return None
        pid = int(ppid)
    return None


def access_hint(app: str | None) -> str:
    who = app or "the app you start Cutroom from (Terminal, iTerm or VS Code)"
    return (f"System Settings → Privacy & Security → Full Disk Access: turn on {who} (add it with + if it isn't "
            f"listed). Then quit {app or 'that app'} completely (⌘Q), open it again and run ./cutroom again.")


def _denied(e: BaseException) -> bool:
    if isinstance(e, PermissionError):
        return True
    if isinstance(e, OSError) and e.errno in (errno.EPERM, errno.EACCES):
        return True
    text = str(e).lower()
    return any(k in text for k in ("operation not permitted", "permission denied", "authorization denied",
                                   "not authorized", "unable to open database"))


# ---------------------------------------------------------------- the library

class PhotosLibrary:
    """One Photos library, read once in the background and kept in memory (refresh() reads it again)."""

    def __init__(self, module: ModuleType | Any | None = None, library: str | Path | None = None,
                 cache: Path | None = None, denied: bool = False):
        self._module = module            # osxphotos, or a stand-in (tests, demo)
        self._library = Path(library) if library else None
        self._cache = cache
        self._force_denied = denied
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._status = PhotosStatus(state="idle")
        self._db: Any = None
        self._items: dict[str, PhotoItem] = {}
        self._order: list[str] = []           # newest first
        self._photo: dict[str, Any] = {}      # uuid -> PhotoInfo
        self._albums: list[PhotoAlbum] = []
        self._album_items: dict[str, list[str]] = {}

    # ------------------------------------------------------------ status / loading

    def status(self, start: bool = True) -> PhotosStatus:
        with self._lock:
            if start and self._status.state == "idle":
                self._status = PhotosStatus(state="loading", message="Reading your Photos library…")
                self._thread = threading.Thread(target=self._load, name="cutroom-photos", daemon=True)
                self._thread.start()
            return self._status.model_copy()

    def refresh(self) -> PhotosStatus:
        """Forget what was read and read the library again (after granting access, or new photos)."""
        with self._lock:
            if self._status.state == "loading":
                return self._status.model_copy()
            self._status = PhotosStatus(state="idle")
            self._db = None
        return self.status()

    def wait(self, timeout: float = 120) -> PhotosStatus:
        """Block until the library is read (tests, the command line)."""
        self.status()
        t = self._thread
        if t:
            t.join(timeout)
        return self.status(start=False)

    def _set(self, **kw: Any) -> None:
        with self._lock:
            self._status = PhotosStatus(**kw)

    def _osxphotos(self) -> Any:
        if self._module is None:
            if sys.platform != "darwin":
                raise ImportError("the Photos library is only on a Mac")
            import osxphotos
            self._module = osxphotos
        return self._module

    def library_path(self) -> Path | None:
        """The library Photos uses: the usual place first (no extra permission prompts), then where Photos says."""
        if self._library:
            return self._library
        if _exists(DEFAULT_LIBRARY):
            return DEFAULT_LIBRARY
        try:
            from osxphotos.utils import get_last_library_path, get_system_library_path
        except ImportError:
            return None
        for find in (get_last_library_path, get_system_library_path):
            try:
                p = find()
            except Exception:  # noqa: BLE001 - a lookup failing just means "try the next"
                p = None
            if p and _exists(Path(p)):
                return Path(p)
        return None

    def _load(self) -> None:
        app = None
        try:
            app = responsible_app()
            if self._force_denied:
                raise PermissionError(errno.EPERM, "Operation not permitted (CUTROOM_PHOTOS=denied)")
            try:
                osx = self._osxphotos()
            except ImportError as e:
                self._set(state="unavailable", message="Importing from Photos isn't available here.",
                          hint=("osxphotos isn't installed: run scripts/setup.sh (or .venv/bin/pip install osxphotos)."
                                if sys.platform == "darwin" else str(e)))
                return
            lib = self.library_path()
            if lib is None:
                self._set(state="no_library", app=app, message="No Photos library found on this Mac.",
                          hint="Open the Photos app once (it creates the library), then check again.")
                return
            db_file = lib / "database" / "Photos.sqlite"
            if not self._module_is_stand_in():
                with open(db_file, "rb") as f:        # PermissionError here = no Full Disk Access
                    f.read(16)
            db = osx.PhotosDB(dbfile=str(lib))
            self._index(db)
            with self._lock:
                self._db = db
                vids = sum(1 for i in self._items.values() if i.kind == "video")
                self._status = PhotosStatus(state="ready", app=app, library=str(lib),
                                            photos=len(self._items) - vids, videos=vids,
                                            favorites=sum(1 for i in self._items.values() if i.favorite))
        except BaseException as e:  # noqa: BLE001 - reading the library must never take the server down
            if _denied(e):
                self._set(state="no_access", app=app, library=str(self._library or DEFAULT_LIBRARY),
                          message="macOS hasn't given Cutroom access to your Photos library yet.",
                          hint=access_hint(app))
            elif isinstance(e, FileNotFoundError):
                self._set(state="no_library", app=app, message="No Photos library found on this Mac.",
                          hint="Open the Photos app once (it creates the library), then check again.")
            else:
                self._set(state="error", app=app, message=f"Couldn't read the Photos library: {type(e).__name__}: "
                                                          f"{str(e)[:300]}",
                          hint="Check again in a moment; if Photos is busy (upgrading or syncing), wait for it.")

    def _module_is_stand_in(self) -> bool:
        return bool(getattr(self._module, "STAND_IN", False))

    def _index(self, db: Any) -> None:
        items: dict[str, PhotoItem] = {}
        photos: dict[str, Any] = {}
        for p in db.photos(images=True, movies=True):
            if getattr(p, "hidden", False) or getattr(p, "intrash", False):
                continue
            try:
                items[p.uuid] = _item(p)
            except Exception:  # noqa: BLE001 - one odd item mustn't hide the library
                continue
            photos[p.uuid] = p
        never = datetime.min.replace(tzinfo=timezone.utc)
        order = sorted(items, key=lambda u: _aware(items[u].date) or never, reverse=True)
        albums, album_items = [], {}
        for a in db.album_info:
            ids = [p.uuid for p in a.photos if p.uuid in items]
            if not ids:
                continue
            vids = sum(1 for u in ids if items[u].kind == "video")
            folder = " / ".join(getattr(a, "folder_names", None) or []) or None
            dates = [d for d in (_aware(items[u].date) for u in ids) if d]
            albums.append(PhotoAlbum(id=a.uuid, title=a.title or "Untitled album", folder=folder, count=len(ids),
                                     photos=len(ids) - vids, videos=vids, cover=ids[0],
                                     start=min(dates) if dates else None, end=max(dates) if dates else None))
            album_items[a.uuid] = ids
        albums.sort(key=lambda a: ((a.folder or "").lower(), a.title.lower()))
        with self._lock:
            self._items, self._photo, self._order = items, photos, order
            self._albums, self._album_items = albums, album_items

    # ------------------------------------------------------------ reads

    def _ready(self) -> None:
        st = self.status()
        if st.state != "ready":
            raise PhotosError(st.message or "the Photos library isn't ready", code=f"photos_{st.state}",
                              status=503 if st.state == "loading" else 409, hint=st.hint)

    def albums(self) -> list[PhotoAlbum]:
        self._ready()
        return list(self._albums)

    def items(self, album: str | None = None, kind: Kind = "all", since: datetime | None = None,
              until: datetime | None = None, favorites: bool = False, offset: int = 0,
              limit: int = 120) -> ItemPage:
        """Newest first (Recents), or in the album's own order. until is inclusive of that day when it's a date."""
        self._ready()
        if album:
            if album not in self._album_items:
                raise PhotosError(f"no album {album!r} in your Photos library", code="photos_album_not_found",
                                  status=404)
            ids = self._album_items[album]
        else:
            ids = self._order
        since, until = _aware(since), _aware(until)
        out = []
        for u in ids:
            it = self._items[u]
            if kind != "all" and it.kind != kind:
                continue
            if favorites and not it.favorite:
                continue
            d = _aware(it.date)
            if since and (d is None or d < since):
                continue
            if until and (d is None or d > until):
                continue
            out.append(it)
        return ItemPage(items=out[offset:offset + limit], total=len(out), offset=offset, limit=limit)

    def item(self, uuid: str) -> PhotoItem:
        self._ready()
        if uuid not in self._items:
            raise PhotosError("that photo isn't in your Photos library (any more)", code="photos_item_not_found",
                              status=404)
        return self._items[uuid]

    # ------------------------------------------------------------ thumbnails

    def _cache_dir(self) -> Path:
        d = self._cache or paths().workspace / ".cache" / "photos"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def thumbnail(self, uuid: str, w: int = 320) -> Path:
        """A JPEG about w pixels wide, from Photos' own previews when it has them (so iCloud-only items have one
        too), else from the original."""
        it = self.item(uuid)
        safe = re.sub(r"[^\w-]", "_", uuid)
        out = self._cache_dir() / f"{safe}_{w}.jpg"
        if out.exists():
            return out
        p = self._photo[uuid]
        from .media import _pil
        Image, ImageOps = _pil()
        previews = [Path(d) for d in (getattr(p, "path_derivatives", None) or [])
                    if Path(d).suffix.lower() in (".jpeg", ".jpg", ".heic", ".png")]
        for d in reversed(previews):                       # smallest first; the first one big enough wins
            try:
                with Image.open(d) as im:
                    if max(im.size) >= w * 0.9 or d == previews[0]:
                        _save_thumb(ImageOps.exif_transpose(im), out, w)
                        return out
            except Exception:  # noqa: BLE001 - try the next preview
                continue
        src = getattr(p, "path", None)
        if src and Path(src).exists():
            try:
                if it.kind == "photo":
                    if Path(src).suffix.lower() in RAW_EXT:
                        raise ValueError("RAW")
                    with Image.open(src) as im:
                        _save_thumb(ImageOps.exif_transpose(im), out, w)
                else:
                    tmp = out.with_suffix(".frame.jpg")
                    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "0.5", "-i", src,
                                    "-frames:v", "1", "-vf", f"scale={w}:-2", str(tmp)], check=True,
                                   capture_output=True, timeout=30)
                    tmp.replace(out)
                return out
            except Exception:  # noqa: BLE001
                pass
        raise PhotosError("no preview for this item", code="no_thumbnail", status=404)

    # ------------------------------------------------------------ export

    def export(self, uuid: str, dest: Path, live_video: bool = False) -> Path:
        """Copy one original out of the library into dest -> the file. iCloud-only items are downloaded through
        Photos first. Live Photos give the still, or the video part with live_video=True. RAW becomes JPEG."""
        it = self.item(uuid)
        p = self._photo[uuid]
        dest.mkdir(parents=True, exist_ok=True)
        stem = Path(it.name).stem or uuid
        want_video = live_video and it.live
        src = getattr(p, "path_live_photo" if want_video else "path", None)
        if src and Path(src).exists():
            out = _free(dest / f"{stem}{Path(src).suffix}")
            shutil.copy2(src, out)
        else:
            out = self._download(p, it, dest, want_video)
        if out.suffix.lower() in RAW_EXT:
            out = _raw_to_jpeg(out)
        return out

    def _download(self, p: Any, it: PhotoItem, dest: Path, want_video: bool) -> Path:
        osx = self._osxphotos()
        tmp = dest / f".dl-{it.id[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            opts = osx.ExportOptions(download_missing=True, live_photo=want_video, timeout=300)
            res = osx.PhotoExporter(p).export(str(tmp), options=opts)
            files = [Path(f) for f in (getattr(res, "exported", None) or []) if Path(f).exists()]
            movs = [f for f in files if f.suffix.lower() in (".mov", ".mp4", ".m4v")]
            pick = (movs[:1] if want_video else [f for f in files if f not in movs or it.kind == "video"][:1])
            if not pick:
                errs = "; ".join(str(e[1]) for e in (getattr(res, "error", None) or [])[:2])
                raise PhotosError(f"{it.name} is in iCloud and Photos couldn't download it"
                                  + (f" ({errs[:200]})" if errs else ""), code="photos_download_failed", status=502,
                                  hint="Open Photos and check it's online and signed in to iCloud. The first time, "
                                       "macOS asks to let Cutroom's app control Photos: click OK (or turn it on in "
                                       "System Settings → Privacy & Security → Automation → Photos).")
            out = _free(dest / f"{Path(it.name).stem or it.id}{pick[0].suffix}")
            shutil.move(str(pick[0]), out)
            return out
        except PhotosError:
            raise
        except Exception as e:  # noqa: BLE001 - AppleScript / PhotoKit failures come in many shapes
            hint = access_hint(responsible_app()) if _denied(e) else (
                "Open Photos and check it's online and signed in to iCloud, then try again.")
            raise PhotosError(f"couldn't get {it.name} from Photos: {str(e)[:200]}", code="photos_download_failed",
                              status=502, hint=hint) from e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _item(p: Any) -> PhotoItem:
    movie = bool(getattr(p, "ismovie", False))
    duration = None
    if movie:
        ex = getattr(p, "exif_info", None)
        duration = getattr(ex, "duration", None) if ex else None
    path = getattr(p, "path", None)
    return PhotoItem(id=p.uuid, name=getattr(p, "original_filename", None) or getattr(p, "filename", None) or p.uuid,
                     kind="video" if movie else "photo", date=getattr(p, "date", None),
                     width=getattr(p, "width", None) or None, height=getattr(p, "height", None) or None,
                     duration=round(float(duration), 2) if duration else None,
                     live=bool(getattr(p, "live_photo", False)) and not movie,
                     favorite=bool(getattr(p, "favorite", False)),
                     local=bool(path) and not getattr(p, "ismissing", False))


def _exists(p: Path) -> bool:
    """exists(), but a path macOS won't let us look at counts as there (reading it then says why)."""
    try:
        return p.exists()
    except PermissionError:
        return True


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.astimezone()


def _save_thumb(im: Any, out: Path, w: int) -> None:
    im = im.convert("RGB")
    im.thumbnail((w, w * 3))
    tmp = out.with_suffix(".part.jpg")
    im.save(tmp, "JPEG", quality=80)
    tmp.replace(out)


def _free(p: Path) -> Path:
    n, cand = 2, p
    while cand.exists():
        cand, n = p.with_name(f"{p.stem}-{n}{p.suffix}"), n + 1
    return cand


def _raw_to_jpeg(src: Path) -> Path:
    """RAW (ProRAW DNG, CR3...) -> a full-size JPEG with macOS's own converter; the RAW is removed."""
    out = _free(src.with_suffix(".jpg"))
    try:
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", str(src), "--out", str(out)],
                       check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise PhotosError(f"{src.name}: couldn't convert this RAW photo", code="unsupported_media", status=422,
                          hint="Export it from Photos as a JPEG, then drop that in.") from e
    src.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------- importing into a project

def import_items(store: ProjectStore, pid: str, lib: PhotosLibrary, ids: list[str],
                 live_video: bool = False) -> dict[str, Any]:
    """Export each item's original into the project (edit order: after what's there). One that fails is skipped
    with its reason; nothing imported at all is an error. -> {"added": [ProjectFile], "skipped": [...]}"""
    store.get(pid)
    tmp = store.dir(pid) / "work" / "_photos_import"
    added: list[ProjectFile] = []
    skipped: list[dict[str, str]] = []
    n = len(ids)
    try:
        for k, uid in enumerate(ids):
            try:
                name = lib.item(uid).name
            except EngineError as e:
                skipped.append({"id": uid, "name": uid, "reason": e.message})
                continue
            step(f"import {k + 1}/{n}: {name}", 100 * k / max(1, n))
            try:
                path = lib.export(uid, tmp, live_video=live_video)
                try:
                    f = store.add_file(pid, path.name, path)
                finally:
                    path.unlink(missing_ok=True)
                added.append(f)
                log(f"  + {f.name}  [{f.info}]")
            except EngineError as e:
                skipped.append({"id": uid, "name": name, "reason": e.message})
                log(f"  ! {name}: {e.message}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not added and skipped:
        first = skipped[0]
        raise PhotosError(f"nothing was imported: {first['name']}: {first['reason']}", code="photos_import_failed",
                          status=502, hint="Check the Photos app is open, online and signed in to iCloud.")
    step("done", 100)
    return {"added": added, "skipped": skipped}


# ---------------------------------------------------------------- which library (env)

def from_env() -> PhotosLibrary:
    mode = os.environ.get("CUTROOM_PHOTOS", "").strip().lower()
    if mode == "denied":
        return PhotosLibrary(denied=True, library=DEFAULT_LIBRARY)
    if mode == "demo":
        from .photos_demo import stand_in
        folder = Path(os.environ.get("CUTROOM_PHOTOS_DIR") or paths().root / ".demo" / "media")
        return PhotosLibrary(module=stand_in(folder), library=folder)
    return PhotosLibrary()


def stable_id(text: str) -> str:
    """A Photos-style UUID from any text (the demo stand-in)."""
    h = hashlib.sha1(text.encode()).hexdigest().upper()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
