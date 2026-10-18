"""Settings live in brand.md's settings block (edited in place) and workspace/settings.json; presets too."""
from __future__ import annotations

import pytest

from engine import settings as S
from engine.common import load_settings
from engine.config import EngineError, paths


def test_settings_block_update_keeps_comments_and_appends(tmp_path) -> None:
    f = tmp_path / "x.md"
    f.write_text("# Notes\nkeep me\n\n```settings\n# who I am\nhandle: @old   # inline note\n"
                 "caption_color: #FFFFFF\n```\nafter\n")
    S.update_settings_block(f, {"handle": "@new", "caption_color": "#FFD54A", "duck": False})
    text = f.read_text()
    assert "# who I am" in text and "keep me" in text and text.endswith("after\n")
    assert "handle: @new   # inline note" in text
    assert load_settings(f) == {"handle": "@new", "caption_color": "#FFD54A", "duck": False}


def test_brand_settings_round_trip_through_brand_md() -> None:
    s = S.save(S.SettingsUpdate(brand=S.BrandSettings(handle="newname", emphasis_color="#ff0000",
                                                      caption_size=72, end_card=False)))
    assert s.brand.handle == "@newname" and s.brand.emphasis_color == "#FF0000"
    assert s.brand.caption_size == 72 and s.brand.end_card is False
    raw = load_settings(paths().brand)
    assert raw["handle"] == "@newname" and raw["end_card"] is False
    assert "## End card" in paths().brand.read_text()          # the notes around the block survive


def test_app_settings_saved_to_workspace() -> None:
    s = S.save(S.SettingsUpdate(app={"brain_backend": "anthropic-api", "brain_timeout_s": 120}))
    assert s.app.brain_backend == "anthropic-api" and s.app.brain_timeout_s == 120
    assert (paths().workspace / "settings.json").exists()
    with pytest.raises(EngineError):
        S.save(S.SettingsUpdate(app={"brain_backend": "gpt"}))


def test_brand_validation() -> None:
    with pytest.raises(ValueError):
        S.BrandSettings(emphasis_color="yellow")
    with pytest.raises(ValueError):
        S.BrandSettings(caption_position=0.95)          # outside the safe zone
    with pytest.raises(EngineError, match="not installed"):
        S.save(S.SettingsUpdate(brand=S.BrandSettings(caption_font="Comic Sans")))


def test_presets_read_and_write() -> None:
    names = [p.name for p in S.list_presets()]
    assert "photo-dump" in names and "gym-vlog" in names
    p = S.save_preset("photo-dump", S.PresetUpdate(settings={"shot_max": 0.9}))
    assert p.settings["shot_max"] == 0.9 and "Structure" in p.notes
    new = S.save_preset("night-out", S.PresetUpdate(description="Night out reel", notes="## Structure\n1. Hook",
                                                     settings={"beat_every": 1, "grade": "warm"}))
    assert new.description == "Night out reel" and new.settings == {"beat_every": 1, "grade": "warm"}
    with pytest.raises(EngineError, match="unknown setting"):
        S.save_preset("night-out", S.PresetUpdate(settings={"sparkle": True}))
    with pytest.raises(EngineError):
        S.save_preset("Bad Name!", S.PresetUpdate())
