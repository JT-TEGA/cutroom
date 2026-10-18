"""AnthropicAPIBrain: the same interface over the Claude API (needs ANTHROPIC_API_KEY in .env).

A stub-level backend for people without Claude Code: one streamed Messages API call per task, with contact sheets
attached as images (there is no Read tool here). Off by default; pick it in settings. Requires `pip install anthropic`.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any

from ..config import paths
from .base import Brain, BrainError, BrainRequest, BrainResponse

KEY_HINT = "Add ANTHROPIC_API_KEY=... to the .env file in the repo root, or switch the brain back to claude-code."


def api_key() -> str | None:
    """ANTHROPIC_API_KEY from .env (read here, never exported to the environment, so Claude Code calls stay on the
    subscription), falling back to the process environment."""
    env_file = paths().env_file
    if env_file.exists():
        try:
            from dotenv import dotenv_values
            v = dotenv_values(env_file).get("ANTHROPIC_API_KEY")
            if v:
                return v
        except ImportError:
            for line in env_file.read_text().splitlines():
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'") or None
    return os.environ.get("ANTHROPIC_API_KEY") or None


class AnthropicAPIBrain(Brain):
    name = "anthropic-api"

    def __init__(self, model: str = "claude-sonnet-5-5", effort: str | None = "high"):
        self.model = model
        self.effort = effort

    def status(self) -> dict[str, Any]:
        try:
            import anthropic  # noqa: F401
            sdk = True
        except ImportError:
            sdk = False
        key = bool(api_key())
        return {"backend": self.name, "model": self.model, "sdk_installed": sdk, "api_key": key,
                "ready": sdk and key, "hint": None if key and sdk else
                ("pip install anthropic" if not sdk else KEY_HINT)}

    def complete(self, req: BrainRequest) -> BrainResponse:
        key = api_key()
        if not key:
            raise BrainError("No ANTHROPIC_API_KEY found for the anthropic-api brain.", code="api_key_missing",
                             status=503, hint=KEY_HINT)
        try:
            import anthropic
        except ImportError as e:
            raise BrainError("The anthropic package is not installed.", code="sdk_missing", status=503,
                             hint="pip install anthropic") from e

        content: list[dict[str, Any]] = []
        for img in req.images[:6]:
            if img.exists():
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(img.read_bytes()).decode()}})
        content.append({"type": "text", "text": req.prompt})
        system = ("You are the planning brain of Cutroom, a short-form video editor. Contact sheet images, when "
                  "relevant, are attached to the message.\n\n" + req.system)

        client = anthropic.Anthropic(api_key=key, timeout=req.timeout, max_retries=1)
        t0 = time.time()
        try:
            with client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": self.effort} if self.effort else anthropic.NOT_GIVEN,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",               # a declined request is re-run on Anthropic's recommended fallback
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise BrainError("The Anthropic API key was rejected.", code="api_key_invalid", status=503,
                             hint=KEY_HINT) from e
        except anthropic.RateLimitError as e:
            raise BrainError("Anthropic API rate limit reached.", code="usage_limit", status=429,
                             hint="Wait a minute and try again.") from e
        except anthropic.APITimeoutError as e:
            raise BrainError(f"The Anthropic API didn't answer within {req.timeout:.0f}s.", code="timeout",
                             status=504) from e
        except anthropic.APIStatusError as e:
            raise BrainError(f"Anthropic API error {e.status_code}: {e.message}", code="brain_error",
                             status=502) from e
        except anthropic.APIConnectionError as e:
            raise BrainError("Couldn't reach the Anthropic API.", code="brain_error", status=502,
                             hint="Check your internet connection.") from e
        if msg.stop_reason == "refusal":
            raise BrainError("Claude declined this request.", code="brain_refused", status=502)
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return BrainResponse(text=text, duration_s=time.time() - t0, model=msg.model, turns=1)
