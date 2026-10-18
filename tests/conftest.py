"""Test fixtures. Tests never call Claude (the Brain is mocked) and never touch the real workspace, brand.md or
Photos library."""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import media_factory  # noqa: E402

from engine import config  # noqa: E402
from engine.brain.base import Brain, BrainError, BrainRequest, BrainResponse  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Generated once per run: two clips, a photo and a 120 BPM track."""
    return media_factory.make_set(tmp_path_factory.mktemp("media"))


@pytest.fixture(autouse=True)
def cutroom_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> config.Paths:
    """Fresh workspace, presets and brand.md per test; fonts / SFX / models / overlay from the repo."""
    for var in [v for v in list(__import__("os").environ) if v.startswith("CUTROOM_")]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CUTROOM_PHOTOS", "denied")      # tests never read the real Photos library
    root = tmp_path / "root"
    for sub in ("raw", "music", "voiceover", "briefs"):
        (root / sub).mkdir(parents=True)
    shutil.copytree(REPO / "presets", tmp_path / "presets")
    shutil.copy(REPO / "brand.md", tmp_path / "brand.md")
    config.reset_paths()
    p = config.configure(root=root, presets=tmp_path / "presets", brand=tmp_path / "brand.md",
                         workspace=tmp_path / "workspace", fonts=REPO / "assets" / "fonts",
                         sfx=REPO / "assets" / "sfx", models=REPO / "scripts" / "models",
                         overlay=REPO / "engine" / "overlay", env_file=tmp_path / ".env")
    p.workspace.mkdir()
    yield p
    config.reset_paths()


class MockBrain(Brain):
    """Answers each purpose with a handler(request) -> reply text (or raises). Records every request."""

    name = "mock"

    def __init__(self, handlers: dict[str, Callable[[BrainRequest], str]] | None = None):
        self.handlers = handlers or {}
        self.calls: list[BrainRequest] = []

    def complete(self, req: BrainRequest) -> BrainResponse:
        self.calls.append(req)
        h = self.handlers.get(req.purpose)
        if h is None:
            raise BrainError(f"mock has no answer for {req.purpose}", code="brain_error")
        return BrainResponse(text=h(req), duration_s=0.01, model="mock", turns=1)


def draft_from_prompt(req: BrainRequest) -> dict:
    """The DRAFT plan JSON the pipeline put in a plan.build prompt (or the current plan in a revise prompt)."""
    m = re.search(r"## (?:DRAFT plan|Current edit plan) \(JSON\)\n(\{.*\})\s*$", req.prompt, re.S)
    assert m, "no plan JSON in the prompt"
    return json.loads(m.group(1))


def plan_reply(req: BrainRequest) -> str:
    """A believable plan.build answer: the draft, with a sticker on the first shot and reasons."""
    tl = draft_from_prompt(req)
    tl["segments"][0]["reason"] = "strongest moment first"
    tl["text"] = [{"text": "Lekki, 7PM", "style": "sticker", "on": "#1"}]
    tl.setdefault("notes", []).append("Kept the draft order: it already follows the preset")
    return json.dumps({"timeline": tl, "summary": "A quick beat-cut dump.", "changes": ["added a location sticker"]})


def revise_reply(req: BrainRequest) -> str:
    tl = draft_from_prompt(req)
    tl["text"] = [{"text": "Lekki, 8PM", "style": "sticker", "on": "#1"}]
    return json.dumps({"timeline": tl, "summary": "Changed the time.", "changes": ["sticker now says 8PM"]})


def analyse_reply(_: BrainRequest) -> str:
    return json.dumps({"questions": [{"id": "music-track", "question": "Which song should it be cut to?",
                                      "why": "photo dumps are cut to the beat", "field": "track",
                                      "options": ["beat.wav"], "blocking": True}],
                       "assumptions": ["no hook given: opening on the strongest moment"], "ready": False})


@pytest.fixture
def mock_brain() -> MockBrain:
    return MockBrain({"brief.analyse": analyse_reply, "plan.build": plan_reply, "revise": revise_reply})
