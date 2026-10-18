"""The editor's judgement as functions.

Each task returns validated JSON:

    brief.analyse(...)          -> clarifying questions (or none)
    plan.build(...)             -> the edit plan (timeline)
    match.clips(...)            -> which clip shows which voiceover phrase, with reasons
    reference.style_spec(...)   -> what a reference reel does, in editing terms
    revise.revise(...)          -> the plan with the creator's notes applied

Backends: ClaudeCodeBrain (default; your logged-in Claude Code, no API key) and AnthropicAPIBrain (API key);
DemoBrain (scripted answers) for demos and screenshots.
"""
from __future__ import annotations

import os

from .base import Brain, BrainError, BrainRequest, BrainResponse, ask, extract_json


def get_brain(app_settings=None) -> Brain:
    """The backend picked in settings (workspace/settings.json); CUTROOM_BRAIN=demo forces the scripted demo brain."""
    if os.environ.get("CUTROOM_BRAIN") == "demo":
        from .demo import DemoBrain
        return DemoBrain()
    from ..settings import load_app
    s = app_settings or load_app()
    if s.brain_backend == "anthropic-api":
        from .anthropic_api import AnthropicAPIBrain
        return AnthropicAPIBrain(model=s.anthropic_model, effort=s.brain_effort or "high")
    from .claude_code import ClaudeCodeBrain
    return ClaudeCodeBrain(model=s.brain_model, effort=s.brain_effort)


__all__ = ["Brain", "BrainError", "BrainRequest", "BrainResponse", "ask", "extract_json", "get_brain"]
