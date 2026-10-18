"""Presets, settings (brand + app) and system status."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from engine import settings as S
from engine.config import EngineError, paths
from engine.system import SystemStatus, status

router = APIRouter(tags=["config"])


@router.get("/presets", response_model=list[S.Preset])
def list_presets() -> list[S.Preset]:
    return S.list_presets()


@router.get("/presets/{name}", response_model=S.Preset)
def get_preset(name: str) -> S.Preset:
    return S.get_preset(name)


@router.put("/presets/{name}", response_model=S.Preset)
def put_preset(name: str, body: S.PresetUpdate) -> S.Preset:
    """Create or update a content-type preset. `settings` keys are merged into its settings block."""
    return S.save_preset(name, body)


@router.get("/settings", response_model=S.Settings)
def get_settings() -> S.Settings:
    """Brand settings (from brand.md) + app settings (brain backend etc.) + the fonts you can pick."""
    return S.load()


@router.put("/settings", response_model=S.Settings)
def put_settings(body: S.SettingsUpdate) -> S.Settings:
    """Change any subset. Brand values are written into brand.md's settings block (comments kept)."""
    return S.save(body)


@router.get("/system/status", response_model=SystemStatus)
def system_status(claude: bool = Query(True, description="also check Claude Code (takes ~1-2 s)")) -> SystemStatus:
    """ffmpeg, node/puppeteer, Python packages, Whisper model, face model, fonts, Claude Code install + login."""
    return status(include_claude=claude)


@router.get("/fonts/{name}", response_class=FileResponse)
def font(name: str) -> FileResponse:
    """A font from assets/fonts (the app previews captions and titles with the real fonts)."""
    root = paths().fonts.resolve()
    p = (root / name).resolve()
    if p.parent != root or p.suffix.lower() not in S.FONT_EXT or not p.is_file():
        raise EngineError(f"no font {name!r}", code="font_not_found", status=404)
    return FileResponse(p, headers={"Cache-Control": "max-age=86400"})
