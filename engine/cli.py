"""`scripts/ve <command>`: the chat-era command line, now a thin layer over the engine package.

Every command works on the repo layout (raw/, music/, voiceover/, work/<name>/, output/) exactly as before.
New: `ve import briefs/x.md` turns a brief into an app project, `ve serve` starts the API.
"""
from __future__ import annotations

import importlib
import sys

from .config import EngineError, paths

# command -> (module, takes the video name as its first argument and passes it as --name)
COMMANDS: dict[str, tuple[str, bool]] = {
    "brief": ("engine.brief", False),
    "ref": ("engine.reference", True), "reference": ("engine.reference", True),
    "transcribe": ("engine.transcribe", False),
    "vo": ("engine.voice", False), "voice": ("engine.voice", False),
    "draft": ("engine.autocut", True), "autocut": ("engine.autocut", True),
    "moments": ("engine.moments", False),
    "media": ("engine.media", False),
    "plan": ("engine.plan", False),
    "render": ("engine.render", False),
    "faces": ("engine.facetrack", False),
    "beats": ("engine.beats", False),
    "sheet": ("engine.contact_sheet", False),
    "sfx": ("engine.make_sfx", False),
}

HELP = """\
ve <command> ...   (run from anywhere; paths are relative to the repo)
  brief briefs/my-video.md          read brief + preset + brand, list gaps
  presets                           list content-type presets
  ref my-video <url> [--cookies chrome]   REFERENCE mode: download + analyse reel
  media raw/shoot-oct/              list a folder in capture order
  transcribe raw/a.mp4 [--show]     word-level transcript (cached; folders ok)
  vo voiceover/vo.m4a [--force]     clean a voiceover (noise, de-ess, compression, -16 LUFS) + transcript
  draft my-video raw/a.mp4 raw/folder/ [--preset X --music Y --talk no --vo voiceover/v.m4a]   draft plan
  moments raw/a.mp4                 best no-talk moments in a clip
  plan my-video [--cuts]            timeline preview of work/my-video/edl.json
  render my-video [--draft]         export output/my-video.mp4 + contact sheet
  faces raw/a.mp4 [--preview]       check face tracking on a clip
  beats music/track.mp3             BPM, beats, downbeats, drops
  sheet output/x.mp4 [--times ..]   contact sheet for any video
  sfx                               (re)generate the starter SFX kit
  doctor                            check every tool is installed
  import briefs/my-video.md         create a Cutroom project from a brief (copies its media in)
  serve [--host 127.0.0.1 --port 8000]   start the Cutroom API (docs at /docs)
"""


def _presets() -> None:
    for f in sorted(paths().presets.glob("*.md")):
        lines = f.read_text().splitlines()
        print(f"  {f.stem:<22} {lines[1] if len(lines) > 1 else ''}")


def _doctor() -> int:
    from .system import status
    st = status()
    for c in st.checks:
        print(f"{'ok  ' if c.ok else 'MISSING' if c.required else 'warn'} {c.label}: {c.detail}"
              + (f"\n       -> {c.hint}" if c.hint and not c.ok else ""))
    print("all good" if st.ok else "something is missing (see above)")
    return 0 if st.ok else 1


def _import(args: list[str]) -> None:
    import argparse

    from .project import ProjectStore
    ap = argparse.ArgumentParser(prog="ve import", description="create a Cutroom project from a briefs/*.md file")
    ap.add_argument("brief")
    ap.add_argument("--no-copy", action="store_true", help="don't copy the brief's clips / music / voiceover")
    a = ap.parse_args(args)
    proj = ProjectStore().import_markdown(a.brief, copy_media=not a.no_copy)
    print(f"project {proj.id}: {proj.name}  ({len(proj.files)} files)  -> {ProjectStore().dir(proj.id)}")


def _serve(args: list[str]) -> None:
    import argparse

    import uvicorn
    ap = argparse.ArgumentParser(prog="ve serve")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    a = ap.parse_args(args)
    uvicorn.run("server.app:app", host=a.host, port=a.port, reload=a.reload)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv else "help"
    try:
        if cmd == "presets":
            _presets()
        elif cmd == "doctor":
            return _doctor()
        elif cmd == "import":
            _import(argv)
        elif cmd == "serve":
            _serve(argv)
        elif cmd in COMMANDS:
            mod, named = COMMANDS[cmd]
            if named:
                if not argv:
                    print(f"usage: ve {cmd} <name> ...", file=sys.stderr)
                    return 2
                argv = argv[1:] + ["--name", argv[0]]
            sys.argv = [f"ve {cmd}", *argv]
            importlib.import_module(mod).main()
        else:
            print(HELP, end="")
            return 0 if cmd in ("help", "-h", "--help") else 2
    except EngineError as e:
        print(f"ERROR: {e.message}" + (f"\n  hint: {e.hint}" if e.hint else ""), file=sys.stderr)
        return 1
    except BrokenPipeError:            # `ve presets | head`
        sys.stderr.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
