"""The Brain interface: the decisions an editor makes, as calls that return validated JSON.

A backend only has to turn (system prompt, prompt) into text. ``ask()`` does the rest for every task: asks for
JSON only, pulls the JSON out of the reply, validates it with Pydantic (plus an optional semantic check), retries
once with the validation errors, and writes each call's purpose and duration to the project's job log.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import EngineError, job_log, log

T = TypeVar("T", bound=BaseModel)


class BrainError(EngineError):
    """A brain call failed. ``code`` tells the API / UI what to show:

    claude_not_installed, claude_not_logged_in, usage_limit, timeout, max_turns, invalid_output,
    api_key_missing, sdk_missing, brain_error."""

    code = "brain_error"
    status = 502


@dataclass
class BrainRequest:
    purpose: str                                        # "plan.build", "brief.analyse", ...
    system: str                                         # task instructions (added to the backend's own prompt)
    prompt: str                                         # the task input: brief, transcripts, clip info...
    cwd: Path                                           # the project folder
    readable: list[str] = field(default_factory=list)   # folders the brain may Read, relative to cwd ("work/**")
    images: list[Path] = field(default_factory=list)    # contact sheets worth looking at
    timeout: float = 300.0
    max_turns: int = 6


@dataclass
class BrainResponse:
    text: str
    duration_s: float
    model: str | None = None
    turns: int | None = None


class Brain(ABC):
    name = "brain"

    @abstractmethod
    def complete(self, req: BrainRequest) -> BrainResponse:
        """Send one request, return the model's final text. Raise BrainError on failure."""

    def status(self) -> dict[str, Any]:
        return {"backend": self.name, "ready": True}


# ---------------------------------------------------------------- JSON in, JSON out

JSON_RULES = """
## Output format
Reply with ONE JSON object and nothing else: no prose before or after, no markdown fences, no comments.
It must validate against this JSON Schema:
{schema}
"""

RETRY = """
## Your previous answer was rejected
It failed validation with:
{errors}

Previous answer (for reference):
{previous}

Return the corrected, complete JSON object only.
"""


def extract_json(text: str) -> Any:
    """The JSON object in a model reply: the whole reply, a ```json fence, or the first {...} that parses."""
    t = text.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", t, re.S):
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(t[i:])
                return obj
            except json.JSONDecodeError:
                continue
    raise ValueError("the reply contained no JSON object")


def schema_text(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(by_alias=True), separators=(",", ":"))


def _problems(e: Exception) -> list[str]:
    if isinstance(e, ValidationError):
        return [f"{'.'.join(str(x) for x in err['loc']) or '(root)'}: {err['msg']}" for err in e.errors()[:20]]
    return [str(e)]


def ask(brain: Brain, req: BrainRequest, schema: type[T],
        check: Callable[[T], list[str]] | None = None, schema_hint: str | None = None) -> T:
    """One structured brain call -> a validated ``schema`` instance (one retry with the errors if it fails).

    check: extra validation after the schema (files exist, cues are said...); returns problems, [] if fine.
    schema_hint: text to show instead of the generated JSON Schema (for very large schemas)."""
    system = req.system.rstrip() + "\n" + JSON_RULES.format(schema=schema_hint or schema_text(schema))
    prompt = req.prompt
    problems: list[str] = []
    for attempt in (1, 2):
        t0 = time.time()
        log(f"  brain: {req.purpose} ({brain.name}{', retry' if attempt > 1 else ''})...")
        try:
            resp = brain.complete(replace(req, system=system, prompt=prompt))
        except BrainError as e:
            job_log(f"brain {req.purpose} [{brain.name}] attempt {attempt}: FAILED after {time.time() - t0:.1f}s "
                    f"({e.code}: {e.message})")
            raise
        try:
            result = schema.model_validate(extract_json(resp.text))
            problems = check(result) if check else []
        except (ValueError, ValidationError) as e:
            problems = _problems(e)
        meta = ", ".join(filter(None, [resp.model, f"{resp.turns} turns" if resp.turns else None]))
        job_log(f"brain {req.purpose} [{brain.name}{': ' + meta if meta else ''}] attempt {attempt}: "
                f"{resp.duration_s:.1f}s, " + ("ok" if not problems else f"invalid ({problems[0][:160]})"))
        log(f"  brain: {req.purpose} answered in {resp.duration_s:.1f}s" + ("" if not problems else " (invalid)"))
        if not problems:
            return result
        prompt = req.prompt + "\n" + RETRY.format(errors="\n".join(f"- {p}" for p in problems),
                                                  previous=resp.text[:12000])
    raise BrainError(f"the brain's answer for {req.purpose} was invalid twice: " + "; ".join(problems[:3]),
                     code="invalid_output", status=502,
                     hint="Try again. If it keeps failing, simplify the brief or pick another brain model in settings.")
