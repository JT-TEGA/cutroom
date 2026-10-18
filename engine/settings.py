"""App settings.

* Brand settings (handle, colours, fonts, caption style, music level, default end card) live where they always
  did: the ```settings block of brand.md. Saving rewrites only the changed lines, so comments and the notes around
  the block survive, and the chat-era workflow sees the same values.
* App settings (which brain backend, model, timeouts) live in workspace/settings.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import DEFAULTS, LIST_KEYS, load_settings
from .config import EngineError, paths

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandSettings(BaseModel):
    """The creator's look. Every field maps to a key in brand.md's settings block."""

    model_config = ConfigDict(extra="forbid")

    handle: str | None = Field(None, description="end card handle, e.g. @name")
    # colours
    emphasis_color: str | None = Field(None, description="the one accent colour for *key words*")
    accent_color: str | None = None
    accent_text_color: str | None = None
    caption_color: str | None = None
    caption_highlight_color: str | None = None
    title_color: str | None = None
    # fonts
    caption_font: str | None = None
    title_font: str | None = None
    label_font: str | None = None
    # caption style
    caption_size: int | None = Field(None, ge=24, le=160)
    caption_weight: int | None = Field(None, ge=100, le=900)
    caption_case: Literal["as-is", "upper", "lower", "sentence"] | None = None
    caption_position: float | None = Field(None, ge=0.08, le=0.8, description="0 = top, 1 = bottom")
    caption_max_words: int | None = Field(None, ge=1, le=12)
    caption_animation: Literal["pop", "fade", "none"] | None = None
    caption_inactive_opacity: float | None = Field(None, ge=0, le=1)
    # music level
    music_under_voice_db: float | None = Field(None, ge=-40, le=0, description="music level under talking (dB)")
    music_alone_lufs: float | None = Field(None, ge=-30, le=-8, description="music loudness on its own (LUFS)")
    # end card
    end_card: bool | None = Field(None, description="end card on by default (presets and briefs can override)")
    end_card_seconds: float | None = Field(None, ge=0.5, le=5)

    @field_validator("emphasis_color", "accent_color", "accent_text_color", "caption_color",
                     "caption_highlight_color", "title_color")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        if v is not None and not HEX.match(v):
            raise ValueError(f"{v!r} is not a #RRGGBB colour")
        return v.upper() if v else v

    @field_validator("handle")
    @classmethod
    def _handle(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not re.fullmatch(r"@?[\w.]{1,30}", v):
            raise ValueError("a handle is letters, numbers, dots and underscores (up to 30)")
        return v if v.startswith("@") else "@" + v


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brain_backend: Literal["claude-code", "anthropic-api"] = Field(
        "claude-code", description="claude-code runs your logged-in Claude Code (no API key); anthropic-api needs "
                                   "ANTHROPIC_API_KEY in .env")
    brain_model: str | None = Field(None, description="Claude Code model alias (sonnet, opus...); empty = CLI default")
    brain_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    brain_timeout_s: int = Field(300, ge=30, le=1800)
    brain_max_turns: int = Field(6, ge=1, le=30)
    anthropic_model: str = Field("claude-sonnet-5-5", description="model for the anthropic-api backend")


class Settings(BaseModel):
    brand: BrandSettings
    app: AppSettings
    fonts_available: list[str] = Field(default_factory=list)


class SettingsUpdate(BaseModel):
    """PUT /settings body: any subset; omitted fields keep their value."""

    brand: BrandSettings | None = None
    app: dict[str, Any] | None = None


def font_families() -> list[str]:
    out = []
    for f in sorted(paths().fonts.glob("*")):
        if f.suffix.lower() in (".ttf", ".otf", ".woff", ".woff2"):
            fam = re.split(r"[-\[_]", f.stem)[0]
            if fam not in out:
                out.append(fam)
    return out


# ---------------------------------------------------------------- the settings block in a markdown file

def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v)) if abs(v) >= 1 else f"{v:g}"
    return str(v)


def update_settings_block(path: Path, values: dict[str, Any]) -> None:
    """Set keys in a markdown file's ```settings block, in place. Missing keys are appended to the block;
    a file without a block gets one at the end."""
    text = path.read_text() if path.exists() else ""
    m = re.search(r"```settings\n(.*?)```", text, re.S)
    if not m:
        block = "".join(f"{k}: {_fmt(v)}\n" for k, v in values.items())
        path.write_text(text.rstrip() + ("\n\n" if text.strip() else "") + f"```settings\n{block}```\n")
        return
    lines = m.group(1).splitlines()
    todo = dict(values)
    for i, line in enumerate(lines):
        km = re.match(r"^(\s*)([A-Za-z_][\w]*)\s*:(\s*)(.*?)(\s+#\s.*)?$", line)
        if km and km.group(2) in todo:
            value = _fmt(todo.pop(km.group(2)))
            lines[i] = f"{km.group(1)}{km.group(2)}:{km.group(3) or ' '}{value}{km.group(5) or ''}"
    lines += [f"{k}: {_fmt(v)}" for k, v in todo.items()]
    new_block = "\n".join(lines) + "\n"
    path.write_text(text[:m.start(1)] + new_block + text[m.end(1):])


# ---------------------------------------------------------------- load / save

def _app_file() -> Path:
    return paths().workspace / "settings.json"


def load_app() -> AppSettings:
    p = _app_file()
    if p.exists():
        try:
            return AppSettings.model_validate(json.loads(p.read_text()))
        except (ValueError, json.JSONDecodeError):
            pass
    return AppSettings()


def load() -> Settings:
    raw = dict(DEFAULTS)
    raw.update(load_settings(paths().brand))
    brand = BrandSettings.model_construct(**{k: raw.get(k) for k in BrandSettings.model_fields})
    return Settings(brand=brand, app=load_app(), fonts_available=font_families())


def save(update: SettingsUpdate) -> Settings:
    if update.brand is not None:
        values = update.brand.model_dump(exclude_none=True)
        fonts = font_families()
        for k in ("caption_font", "title_font", "label_font"):
            if k in values and fonts and values[k] not in fonts:
                raise EngineError(f"font {values[k]!r} is not installed (assets/fonts has: {', '.join(fonts)})",
                                  code="unknown_font", status=422)
        if values:
            update_settings_block(paths().brand, values)
    if update.app is not None:
        try:
            app = AppSettings.model_validate(load_app().model_dump() | update.app)
        except ValueError as e:
            raise EngineError(f"invalid app settings: {e}", code="invalid_settings", status=422) from e
        _app_file().parent.mkdir(parents=True, exist_ok=True)
        _app_file().write_text(json.dumps(app.model_dump(), indent=2))
    return load()


# ---------------------------------------------------------------- presets

class Preset(BaseModel):
    name: str
    description: str = ""
    notes: str = Field("", description="the preset's notes for the editor (markdown, without the settings block)")
    settings: dict[str, Any] = Field(default_factory=dict)


class PresetUpdate(BaseModel):
    description: str | None = None
    notes: str | None = None
    settings: dict[str, Any] | None = None


def _split_preset(text: str) -> tuple[str, str]:
    """-> (description line, notes without the title, description and settings block)."""
    lines = text.splitlines()
    desc = lines[1].strip() if len(lines) > 1 else ""
    body = "\n".join(lines[2:])
    body = re.sub(r"```settings\n.*?```\n?", "", body, flags=re.S).strip()
    return desc, body


def list_presets() -> list[Preset]:
    out = []
    for f in sorted(paths().presets.glob("*.md")):
        if f.name.startswith("_"):
            continue
        desc, notes = _split_preset(f.read_text())
        out.append(Preset(name=f.stem, description=desc, notes=notes, settings=load_settings(f)))
    return out


def get_preset(name: str) -> Preset:
    for p in list_presets():
        if p.name == name:
            return p
    raise EngineError(f"no preset called {name!r}", code="unknown_preset", status=404)


def save_preset(name: str, upd: PresetUpdate) -> Preset:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", name):
        raise EngineError("preset names are lowercase letters, numbers and dashes", code="invalid_name", status=422)
    if upd.settings:
        unknown = sorted(set(upd.settings) - set(DEFAULTS))
        if unknown:
            raise EngineError(f"unknown setting(s): {', '.join(unknown)}", code="invalid_settings", status=422,
                              hint="see scripts/README.md for the keys a preset can set")
        for k in LIST_KEYS & set(upd.settings):
            if isinstance(upd.settings[k], str):
                upd.settings[k] = [x.strip() for x in upd.settings[k].split(",") if x.strip()]
    path = paths().presets / f"{name}.md"
    if path.exists():
        text = path.read_text()
        desc, notes = _split_preset(text)
        settings = load_settings(path)
    else:
        desc, notes, settings = "", "", {}
    desc = upd.description if upd.description is not None else desc
    notes = upd.notes if upd.notes is not None else notes
    if upd.settings:
        settings.update(upd.settings)
    if upd.notes is not None or upd.description is not None or not path.exists():
        block = "".join(f"{k}: {_fmt(v)}\n" for k, v in settings.items())
        path.write_text(f"# Preset: {name}\n{desc}\n\n{notes.strip()}\n\n```settings\n{block}```\n")
    elif upd.settings:
        update_settings_block(path, upd.settings)
    return get_preset(name)
