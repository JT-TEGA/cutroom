"""Import from the Mac Photos app, with osxphotos mocked: status and access, albums, items and filters, thumbnails,
exporting originals (local, iCloud-only, Live Photos, RAW), the import job, and the demo stand-in."""
from __future__ import annotations

import errno
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from engine import photos as P
from engine.photos import PhotosLibrary
from engine.project import ProjectStore
from server.app import create_app
from server.deps import Services
from server.jobs import JobManager

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class FakePhoto:
    def __init__(self, uuid: str, name: str, path: Path | None, days: int, movie: bool = False,
                 live: Path | None = None, favorite: bool = False, hidden: bool = False,
                 derivatives: list[Path] | None = None, cloud_file: Path | None = None):
        self.uuid, self.original_filename, self.filename = uuid, name, name
        self.path = str(path) if path else None
        self.ismissing = path is None
        self.ismovie, self.isphoto = movie, not movie
        self.date = T0 + timedelta(days=days)
        self.live_photo = live is not None
        self.path_live_photo = str(live) if live else None
        self.favorite, self.hidden, self.intrash = favorite, hidden, False
        self.width, self.height = 1080, 1920
        self.exif_info = SimpleNamespace(duration=4.5 if movie else None)
        self.path_derivatives = [str(d) for d in derivatives or []]
        self.cloud_file = cloud_file            # what "downloading from iCloud" gives back


class FakeAlbum:
    def __init__(self, uuid: str, title: str, photos: list[FakePhoto], folders: list[str] | None = None):
        self.uuid, self.title, self.photos, self.folder_names = uuid, title, photos, folders or []


def fake_osxphotos(photos: list[FakePhoto], albums: list[FakeAlbum], db_error: BaseException | None = None):
    exported: list[str] = []

    class PhotosDB:
        def __init__(self, dbfile: str):
            if db_error:
                raise db_error
            self.album_info = albums

        def photos(self, images: bool = True, movies: bool = True):
            return [p for p in photos if (images and p.isphoto) or (movies and p.ismovie)]

    class PhotoExporter:
        def __init__(self, p: FakePhoto):
            self.p = p

        def export(self, dest: str, options=None):
            exported.append(self.p.uuid)
            if not self.p.cloud_file:
                return SimpleNamespace(exported=[], error=[("x", "not downloaded")])
            out = Path(dest) / self.p.original_filename
            shutil.copy(self.p.cloud_file, out)
            files = [str(out)]
            if options.live_photo:
                mov = out.with_suffix(".mov")
                shutil.copy(self.p.cloud_file, mov)
                files.append(str(mov))
            return SimpleNamespace(exported=files, error=[])

    return SimpleNamespace(PhotosDB=PhotosDB, PhotoExporter=PhotoExporter,
                           ExportOptions=lambda **kw: SimpleNamespace(**kw), exported=exported)


@pytest.fixture
def library(tmp_path: Path, media) -> dict:
    """A fake library folder (database/Photos.sqlite present) and items: 2 local photos, a local clip, a Live Photo,
    an iCloud-only photo, a hidden one, and two albums."""
    lib = tmp_path / "Photos Library.photoslibrary"
    (lib / "database").mkdir(parents=True)
    (lib / "database" / "Photos.sqlite").write_bytes(b"SQLite format 3\x00")
    orig = tmp_path / "originals"
    orig.mkdir()
    jpg = shutil.copy(media["photo"], orig / "IMG_0001.jpg")
    jpg2 = shutil.copy(media["photo"], orig / "IMG_0002.jpg")
    mov = shutil.copy(media["clip_a"], orig / "IMG_0003.MOV")
    live_mov = shutil.copy(media["clip_b"], orig / "IMG_0004.MOV")
    live_jpg = shutil.copy(media["photo"], orig / "IMG_0004.jpg")
    deriv = tmp_path / "derivatives"
    deriv.mkdir()
    big = deriv / "P5_1_105_c.jpeg"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=900x1600", "-frames:v", "1", str(big)], check=True)
    items = [
        FakePhoto("P1", "IMG_0001.JPG", Path(jpg), days=1, favorite=True),
        FakePhoto("P2", "IMG_0002.JPG", Path(jpg2), days=2),
        FakePhoto("V3", "IMG_0003.MOV", Path(mov), days=3, movie=True),
        FakePhoto("L4", "IMG_0004.HEIC", Path(live_jpg), days=4, live=Path(live_mov)),
        FakePhoto("P5", "IMG_0005.JPG", None, days=5, derivatives=[big], cloud_file=Path(jpg)),
        FakePhoto("H6", "IMG_0006.JPG", Path(jpg), days=6, hidden=True),
    ]
    by = {p.uuid: p for p in items}
    albums = [FakeAlbum("A1", "October shoot", [by["P2"], by["V3"], by["P5"]], ["Shoots"]),
              FakeAlbum("A2", "Empty", [])]
    return {"lib": lib, "items": items, "albums": albums, "tmp": tmp_path}


def ready(lib: PhotosLibrary) -> PhotosLibrary:
    st = lib.wait(30)
    assert st.state == "ready", st
    return lib


def make(library: dict, **kw) -> PhotosLibrary:
    mod = fake_osxphotos(library["items"], library["albums"], **kw)
    return PhotosLibrary(module=mod, library=library["lib"], cache=library["tmp"] / "thumbs")


# ---------------------------------------------------------------- status, albums, items

def test_status_loads_in_the_background_then_lists_albums(library) -> None:
    lib = make(library)
    first = lib.status()
    assert first.state in ("loading", "ready")
    st = ready(lib).status()
    assert (st.photos, st.videos, st.favorites) == (4, 1, 1)          # the hidden one isn't there
    albums = lib.albums()
    assert [a.title for a in albums] == ["October shoot"]             # empty albums are left out
    a = albums[0]
    assert (a.count, a.photos, a.videos, a.folder, a.cover) == (3, 2, 1, "Shoots", "P2")
    assert a.start.date().isoformat() == "2026-10-03" and a.end.date().isoformat() == "2026-10-06"


def test_items_recent_first_filters_and_pages(library) -> None:
    lib = ready(make(library))
    page = lib.items()
    assert [i.id for i in page.items] == ["P5", "L4", "V3", "P2", "P1"] and page.total == 5
    assert [i.id for i in lib.items(kind="video").items] == ["V3"]
    assert [i.id for i in lib.items(kind="photo", favorites=True).items] == ["P1"]
    since = T0 + timedelta(days=2)
    until = T0 + timedelta(days=4, hours=1)
    assert [i.id for i in lib.items(since=since, until=until).items] == ["L4", "V3", "P2"]
    assert [i.id for i in lib.items(album="A1").items] == ["P2", "V3", "P5"]          # the album's own order
    p2 = lib.items(offset=1, limit=2)
    assert [i.id for i in p2.items] == ["L4", "V3"] and p2.total == 5
    v, live, cloud = lib.item("V3"), lib.item("L4"), lib.item("P5")
    assert v.kind == "video" and v.duration == 4.5
    assert live.live and live.kind == "photo"
    assert cloud.local is False and lib.item("P1").local is True
    with pytest.raises(P.PhotosError) as e:
        lib.items(album="nope")
    assert e.value.status == 404


def test_no_full_disk_access(library, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(P, "responsible_app", lambda pid=None: "Terminal")
    lib = make(library, db_error=PermissionError(errno.EPERM, "Operation not permitted"))
    st = lib.wait(10)
    assert st.state == "no_access" and st.app == "Terminal"
    assert "Full Disk Access" in st.hint and "turn on Terminal" in st.hint and "⌘Q" in st.hint
    with pytest.raises(P.PhotosError) as e:
        lib.albums()
    assert e.value.code == "photos_no_access" and e.value.status == 409


def test_unreadable_database_file_is_no_access(library) -> None:
    db = library["lib"] / "database" / "Photos.sqlite"
    db.chmod(0)
    try:
        assert make(library).wait(10).state == "no_access"
    finally:
        db.chmod(0o644)


def test_other_failures_never_crash(library, tmp_path: Path) -> None:
    st = make(library, db_error=RuntimeError("database disk image is malformed")).wait(10)
    assert st.state == "error" and "malformed" in st.message
    missing = PhotosLibrary(module=fake_osxphotos([], []), library=tmp_path / "nowhere.photoslibrary")
    assert missing.wait(10).state == "no_library"


def test_check_again_reads_the_library_again(library) -> None:
    mod = fake_osxphotos(library["items"], library["albums"], db_error=PermissionError(1, "no"))
    lib = PhotosLibrary(module=mod, library=library["lib"], cache=library["tmp"] / "thumbs")
    assert lib.wait(10).state == "no_access"
    lib._module = fake_osxphotos(library["items"], library["albums"])         # access granted meanwhile
    lib.refresh()
    assert lib.wait(10).state == "ready"


def test_without_osxphotos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import builtins
    real = builtins.__import__

    def no_osxphotos(name, *a, **kw):
        if name == "osxphotos":
            raise ImportError("No module named 'osxphotos'")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_osxphotos)
    monkeypatch.setattr(P.sys, "platform", "darwin")
    st = PhotosLibrary(library=tmp_path).wait(10)
    assert st.state == "unavailable" and "osxphotos" in st.hint


def test_responsible_app_walks_up_to_the_app_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    tree = {100: "99 /Users/me/cutroom/.venv/bin/python3.10", 99: "98 -zsh",
            98: "1 /Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper (Plugin).app/Contents/MacOS/x"}

    def ps(cmd, **kw):
        return SimpleNamespace(stdout=tree.get(int(cmd[-1]), ""))

    monkeypatch.setattr(P.subprocess, "run", ps)
    assert P.responsible_app(100) == "Visual Studio Code"
    tree[98] = "1 /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"
    assert P.responsible_app(100) == "Terminal"
    tree[98] = "1 /usr/sbin/sshd"
    assert P.responsible_app(100) is None
    # the framework Python is inside a Python.app: skipped, the terminal above it counts
    tree[100] = "99 /Library/Frameworks/Python.framework/Versions/3.10/Resources/Python.app/Contents/MacOS/Python"
    tree[98] = "1 /Applications/iTerm.app/Contents/MacOS/iTerm2"
    assert P.responsible_app(100) == "iTerm"


# ---------------------------------------------------------------- thumbnails and export

def test_thumbnails_from_previews_or_originals(library) -> None:
    from PIL import Image
    lib = ready(make(library))
    t = lib.thumbnail("P5", 320)                               # iCloud-only: from Photos' preview
    with Image.open(t) as im:
        assert im.width == 320 and im.format == "JPEG"
    assert lib.thumbnail("P5", 320) == t                       # cached
    with Image.open(lib.thumbnail("P1", 200)) as im:           # no previews: from the original
        assert im.width == 200
    with Image.open(lib.thumbnail("V3", 240)) as im:           # a clip: a frame
        assert im.width == 240


def test_export_local_icloud_and_live(library, tmp_path: Path) -> None:
    lib = ready(make(library))
    out = tmp_path / "out"
    a = lib.export("P1", out)
    assert a.name == "IMG_0001.jpg" and a.exists()             # the original's own extension
    assert lib.export("P1", out).name == "IMG_0001-2.jpg"       # never overwrites
    still = lib.export("L4", out)
    assert still.name == "IMG_0004.jpg"
    video = lib.export("L4", out, live_video=True)
    assert video.name == "IMG_0004.MOV"
    cloud = lib.export("P5", out)                              # downloaded through Photos
    assert cloud.name == "IMG_0005.JPG" and cloud.exists()
    assert lib._module.exported == ["P5"]
    assert not any(p.name.startswith(".dl-") for p in out.iterdir())


def test_export_icloud_failure_explains(library, tmp_path: Path) -> None:
    lib = ready(make(library))
    lib._photo["P5"].cloud_file = None
    with pytest.raises(P.PhotosError) as e:
        lib.export("P5", tmp_path / "out")
    assert e.value.code == "photos_download_failed" and "iCloud" in e.value.message and "Automation" in e.value.hint


def test_raw_becomes_jpeg(library, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def sips(cmd, **kw):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"jpeg")
        return SimpleNamespace(returncode=0)

    lib = ready(make(library))
    raw = library["tmp"] / "originals" / "IMG_0007.DNG"
    raw.write_bytes(b"raw")
    lib._photo["P1"].path = str(raw)
    lib._items["P1"] = lib._items["P1"].model_copy(update={"name": "IMG_0007.DNG"})
    monkeypatch.setattr(P.subprocess, "run", sips)
    out = lib.export("P1", tmp_path / "out")
    assert out.suffix == ".jpg" and calls and calls[0][0] == "sips"
    assert not (tmp_path / "out" / "IMG_0007.DNG").exists()


# ---------------------------------------------------------------- the API and the import job

@pytest.fixture
def client(library, cutroom_paths, mock_brain):
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: mock_brain,
                   photos=make(library))
    with TestClient(create_app(svc)) as c:
        yield c, svc


def wait_ready(c: TestClient) -> dict:
    for _ in range(100):
        st = c.get("/photos/status").json()
        if st["state"] != "loading":
            return st
        time.sleep(0.05)
    raise AssertionError("library never finished loading")


def test_api_albums_items_thumbnails(client) -> None:
    c, _ = client
    assert wait_ready(c)["state"] == "ready"
    albums = c.get("/photos/albums").json()
    assert albums[0]["title"] == "October shoot" and albums[0]["count"] == 3
    page = c.get("/photos/items", params={"album": albums[0]["id"], "kind": "photo"}).json()
    assert [i["id"] for i in page["items"]] == ["P2", "P5"] and page["total"] == 2
    page = c.get("/photos/items", params={"since": "2026-10-03", "until": "2026-10-04"}).json()
    assert [i["id"] for i in page["items"]] == ["V3", "P2"]          # until is the whole day
    r = c.get("/photos/thumbnail/P5", params={"w": 160})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert c.get("/photos/thumbnail/NOPE").status_code == 404


def test_api_import_job_adds_files_and_reports_skips(client) -> None:
    c, svc = client
    wait_ready(c)
    pid = c.post("/projects", json={"name": "From Photos"}).json()["id"]
    svc.photos._photo["P2"].path = None                      # in iCloud and won't download
    r = c.post(f"/projects/{pid}/photos/import", params={"wait": "true"},
               json={"ids": ["V3", "L4", "P5", "P2"], "live_video": False})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done" and job["kind"] == "photos-import"
    added = job["result"]["added"]
    assert [f["name"] for f in added] == ["IMG_0003.MOV", "IMG_0004.jpg", "IMG_0005.JPG"]
    assert [f["kind"] for f in added] == ["clip", "photo", "photo"]
    assert job["result"]["skipped"][0]["name"] == "IMG_0002.JPG"
    files = c.get(f"/projects/{pid}/files").json()
    assert [f["name"] for f in files] == ["IMG_0003.MOV", "IMG_0004.jpg", "IMG_0005.JPG"]
    assert not (svc.store.dir(pid) / "work" / "_photos_import").exists()

    r = c.post(f"/projects/{pid}/photos/import", params={"wait": "true"}, json={"ids": ["L4"], "live_video": True})
    assert r.json()["result"]["added"][0]["name"] == "IMG_0004.MOV"
    assert r.json()["result"]["added"][0]["kind"] == "clip"

    r = c.post(f"/projects/{pid}/photos/import", params={"wait": "true"}, json={"ids": ["P2"]})
    assert r.status_code == 502 and r.json()["error"]["code"] == "photos_import_failed"
    r = c.post(f"/projects/{pid}/photos/import", json={"ids": ["NOT-THERE"]})
    assert r.status_code == 404


def test_api_no_access_screen_data(library, cutroom_paths, mock_brain, monkeypatch) -> None:
    monkeypatch.setattr(P, "responsible_app", lambda pid=None: "iTerm")
    svc = Services(store=ProjectStore(cutroom_paths.workspace), jobs=JobManager(), brain_factory=lambda: mock_brain,
                   photos=make(library, db_error=PermissionError(1, "Operation not permitted")))
    with TestClient(create_app(svc)) as c:
        st = wait_ready(c)
        assert st["state"] == "no_access" and st["app"] == "iTerm" and "Full Disk Access" in st["hint"]
        r = c.get("/photos/albums")
        assert r.status_code == 409 and r.json()["error"]["code"] == "photos_no_access"
        assert c.post("/photos/refresh").json()["state"] in ("loading", "no_access")


def test_demo_stand_in(media, tmp_path: Path) -> None:
    from engine.photos_demo import stand_in
    folder = tmp_path / "media"
    (folder / "gym").mkdir(parents=True)
    (folder / "night").mkdir()
    shutil.copy(media["clip_a"], folder / "gym" / "squats.mp4")
    shutil.copy(media["photo"], folder / "night" / "IMG_0801.jpg")
    shutil.copy(media["photo"], folder / "night" / "IMG_0802.jpg")
    lib = ready(PhotosLibrary(module=stand_in(folder), library=folder, cache=tmp_path / "thumbs"))
    assert sorted(a.title for a in lib.albums()) == ["Gym", "Night"]
    items = lib.items().items
    assert len(items) == 3 and any(not i.local for i in items)
    out = lib.export(next(i.id for i in items if not i.local), tmp_path / "out")
    assert out.exists()


def test_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CUTROOM_PHOTOS", "denied")
    assert P.from_env().wait(10).state == "no_access"
    monkeypatch.setenv("CUTROOM_PHOTOS", "demo")
    monkeypatch.setenv("CUTROOM_PHOTOS_DIR", str(tmp_path))
    assert P.from_env().wait(10).state == "ready"
