"""Is everything installed? Used by `ve doctor` and GET /system/status.

Nothing heavy is imported here: Python packages are found with importlib.util.find_spec (importing faster-whisper
next to OpenCV in one process is exactly what the pipeline avoids), the Whisper model is looked up in the
Hugging Face cache, and Claude Code is asked for its version and login state.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .common import load_brand
from .config import paths, which

PY_MODULES = ["numpy", "cv2", "faster_whisper", "librosa", "PIL", "pillow_heif", "yt_dlp", "fastapi", "pydantic"]


class Check(BaseModel):
    id: str
    label: str
    ok: bool
    detail: str = ""
    hint: str | None = None
    required: bool = True


class SystemStatus(BaseModel):
    ok: bool = Field(description="everything required is there")
    can_render: bool
    can_plan: bool
    checks: list[Check]
    claude_code: dict[str, Any]
    brain: dict[str, Any]
    platform: str
    demo: bool = Field(False, description="brain calls are answered by the scripted demo brain (CUTROOM_BRAIN=demo)")


def _version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (r.stdout or r.stderr).strip().splitlines()[0][:80]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return ""


def whisper_model_cached(name: str) -> tuple[bool, str]:
    if Path(name).expanduser().is_dir():
        return True, str(Path(name).expanduser())
    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface"))
               / "hub")
    hits = sorted(hub.glob(f"models--*--faster-whisper-{name}")) if hub.exists() else []
    return (bool(hits), str(hits[0]) if hits else str(hub))


def status(include_claude: bool = True) -> SystemStatus:
    from .brain import get_brain
    from .brain.claude_code import auth_status
    from .settings import font_families, load_app

    checks: list[Check] = []
    for b, hint in (("ffmpeg", "brew install ffmpeg"), ("ffprobe", "brew install ffmpeg"),
                    ("node", "brew install node, then npm install")):
        path = which(b)
        checks.append(Check(id=b, label=b, ok=bool(path), detail=_version([b, "-version" if b != "node" else
                                                                           "--version"]) if path else "not found",
                            hint=None if path else hint))
    pup = (paths().root / "node_modules" / "puppeteer").exists()
    checks.append(Check(id="puppeteer", label="puppeteer (overlay renderer)", ok=pup,
                        detail="installed" if pup else "missing", hint=None if pup else "npm install"))
    missing = [m for m in PY_MODULES if importlib.util.find_spec(m) is None]
    checks.append(Check(id="python", label="Python environment", ok=not missing,
                        detail=f"Python {platform.python_version()} ({sys.executable})"
                               + (f"; missing: {', '.join(missing)}" if missing else ""),
                        hint="pip install -e '.[dev]'" if missing else None))
    model = str(load_brand().get("whisper_model", "large-v3-turbo"))
    cached, where = whisper_model_cached(model)
    checks.append(Check(id="whisper_model", label=f"Whisper model ({model})", ok=cached, required=False,
                        detail=f"cached at {where}" if cached else "not downloaded yet",
                        hint=None if cached else "it downloads automatically on the first transcription (~1.6 GB)"))
    face = paths().face_model.exists()
    checks.append(Check(id="face_model", label="face detection model", ok=face, detail=str(paths().face_model),
                        hint=None if face else "scripts/setup.sh downloads it"))
    fonts = font_families()
    checks.append(Check(id="fonts", label="fonts", ok=bool(fonts), detail=", ".join(fonts) or "none",
                        hint=None if fonts else "scripts/setup.sh downloads them"))

    app = load_app()
    claude = auth_status() if include_claude else {"skipped": True}
    if include_claude:
        checks.append(Check(id="claude_code", label="Claude Code (brain)", ok=bool(claude.get("ready")),
                            required=app.brain_backend == "claude-code",
                            detail=("not installed" if not claude.get("installed") else
                                    f"{claude.get('version') or ''} "
                                    + ("logged in" + (f" ({claude.get('subscription')})"
                                                      if claude.get("subscription") else "")
                                       if claude.get("logged_in") else "not logged in")).strip(),
                            hint=claude.get("hint")))
    brain = get_brain(app)
    demo = brain.name == "demo"
    brain_info = {"backend": app.brain_backend, "model": app.anthropic_model
                  if app.brain_backend == "anthropic-api" else (app.brain_model or "CLI default")}
    if demo:
        brain_info.update(brain.status())
    elif app.brain_backend == "anthropic-api":
        brain_info.update(brain.status())
    else:
        brain_info["ready"] = bool(claude.get("ready")) if include_claude else None

    ok_ = {c.id: c.ok for c in checks}
    required_ok = all(c.ok for c in checks if c.required)
    can_render = all(ok_.get(k, False) for k in ("ffmpeg", "ffprobe", "node", "puppeteer", "python", "fonts"))
    return SystemStatus(ok=required_ok, can_render=can_render,
                        can_plan=can_render and bool(brain_info.get("ready")), checks=checks,
                        claude_code=claude, brain=brain_info, platform=f"{platform.system()} {platform.release()}",
                        demo=demo)


def reveal(path: Path) -> None:
    """Show a file (selected) or folder in the file manager: Finder on macOS."""
    from .config import EngineError
    path = Path(path)
    if not path.exists():
        raise EngineError(f"not found: {path.name}", code="file_not_found", status=404)
    system = platform.system()
    if system == "Darwin":
        cmd = ["open", "-R", str(path)] if path.is_file() else ["open", str(path)]
    elif system == "Windows":
        cmd = ["explorer", f"/select,{path}"] if path.is_file() else ["explorer", str(path)]
    else:
        cmd = ["xdg-open", str(path.parent if path.is_file() else path)]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise EngineError(f"couldn't open the file manager: {e}", code="reveal_failed", status=500) from e
