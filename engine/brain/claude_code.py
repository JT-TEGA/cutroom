"""ClaudeCodeBrain: runs the logged-in `claude` CLI headless (print mode). No API key needed.

Each call is one isolated, non-persistent session:
  claude -p --output-format json --max-turns N --append-system-prompt <task> --tools Read|"" ...
with the project folder as cwd, user/project settings, hooks, plugins and MCP servers switched off, and the only
tool (Read, when a task needs to look at contact sheets) allowed for work/ and denied for inputs/ and output/.
The prompt goes in on stdin, so long transcripts never hit argument limits.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import Brain, BrainError, BrainRequest, BrainResponse

INSTALL_HINT = ("Install Claude Code (https://claude.com/claude-code), then run `claude` once in a terminal "
                "and log in with your Claude account.")
LOGIN_HINT = "Run `claude` in a terminal and log in (or `claude auth login`), then try again."
LIMIT_HINT = ("Wait for your Claude usage limit to reset, then try again. Settings > brain backend can switch to "
              "the Anthropic API if you have a key.")
# Never let these reach the CLI: an API key in the environment would bill the API instead of the subscription.
STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")

LIMIT_RX = re.compile(r"usage limit|limit reached|hit your (usage )?limit|rate.?limit|out of (extra )?usage|"
                      r"quota|too many requests", re.I)
AUTH_RX = re.compile(r"not logged in|please (run )?/?login|log ?in again|invalid api key|authenticat|oauth|"
                     r"unauthori[sz]ed|credentials|token (has )?expired", re.I)


def find_claude(explicit: str | None = None) -> str | None:
    """The claude executable: settings / env first, then PATH, then the usual install locations
    (a server started from an IDE or launchd often has a short PATH)."""
    home = Path.home()
    cands = [explicit, os.environ.get("CUTROOM_CLAUDE_BIN"), shutil.which("claude"),
             str(home / ".local/bin/claude"), str(home / ".claude/local/claude"),
             "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    for c in cands:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env.setdefault("PATH", "/usr/bin:/bin")
    return env


def _reset_time(text: str) -> str:
    """'Claude AI usage limit reached|1760000000' -> ' (resets 14:00)'."""
    m = re.search(r"\|(\d{10})\b", text)
    if m:
        return f" (resets {datetime.fromtimestamp(int(m.group(1))).strftime('%a %H:%M')})"
    m = re.search(r"resets?\s+(?:at\s+)?([^\n.|]{2,40})", text, re.I)
    return f" (resets {m.group(1).strip()})" if m else ""


def classify(text: str, status: int | None = None, subtype: str | None = None,
             max_turns: int | None = None) -> BrainError:
    """Turn a failed CLI run into a BrainError the API can show."""
    t = (text or "").strip()
    short = t.splitlines()[-1][:300] if t else "no output"
    if subtype == "error_max_turns":
        return BrainError(f"Claude Code used all {max_turns} turns without finishing the answer.", code="max_turns",
                          status=502, hint="Try again, or raise brain_max_turns in settings.")
    if status == 429 or LIMIT_RX.search(t):
        return BrainError("Claude usage limit reached" + _reset_time(t) + ".", code="usage_limit", status=429,
                          hint=LIMIT_HINT)
    if status in (401, 403) or AUTH_RX.search(t):
        return BrainError("Claude Code is not logged in.", code="claude_not_logged_in", status=503, hint=LOGIN_HINT)
    if re.search(r"overloaded|529|503", t):
        return BrainError("Claude is overloaded right now.", code="brain_busy", status=503,
                          hint="Try again in a minute.")
    return BrainError(f"Claude Code failed: {short}", code="brain_error", status=502)


def _parse(stdout: str) -> dict[str, Any] | None:
    s = (stdout or "").strip()
    if not s:
        return None
    for chunk in (s, s.splitlines()[-1]):
        try:
            d = json.loads(chunk)
            if isinstance(d, dict) and d.get("type") == "result":
                return d
        except json.JSONDecodeError:
            continue
    return None


def _main_model(d: dict[str, Any]) -> str | None:
    mu = d.get("modelUsage") or {}
    if not mu:
        return None
    return max(mu.items(), key=lambda kv: kv[1].get("outputTokens", 0))[0]


class ClaudeCodeBrain(Brain):
    name = "claude-code"

    def __init__(self, model: str | None = "sonnet", effort: str | None = None, binary: str | None = None):
        self.model = model or None          # None / "": no --model, the CLI picks
        self.effort = effort or None
        self.binary = binary

    def command(self, req: BrainRequest, exe: str) -> list[str]:
        cmd = [exe, "-p", "--output-format", "json",
               "--max-turns", str(req.max_turns),
               "--append-system-prompt", req.system,
               "--no-session-persistence",          # nothing saved, nothing to resume
               "--setting-sources", "",             # no user / project settings, hooks, plugins or CLAUDE.md
               "--strict-mcp-config",               # no MCP servers
               "--permission-mode", "dontAsk",      # anything not allowed below is denied, never prompted
               "--tools", "Read" if req.readable else ""]
        if req.readable:
            cmd += ["--allowedTools", ",".join(f"Read(./{g})" for g in req.readable),
                    "--disallowedTools", "Read(./inputs/**),Read(./output/**)"]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        return cmd

    def complete(self, req: BrainRequest) -> BrainResponse:
        exe = find_claude(self.binary)
        if not exe:
            raise BrainError("Claude Code is not installed (no `claude` command found).", code="claude_not_installed",
                             status=503, hint=INSTALL_HINT)
        t0 = time.time()
        try:
            p = subprocess.Popen(self.command(req, exe), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, cwd=str(req.cwd), env=clean_env(),
                                 start_new_session=True)
        except FileNotFoundError as e:
            raise BrainError("Claude Code is not installed (no `claude` command found).", code="claude_not_installed",
                             status=503, hint=INSTALL_HINT) from e
        try:
            out, err = p.communicate(req.prompt, timeout=req.timeout)
        except subprocess.TimeoutExpired as e:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.communicate()
            raise BrainError(f"Claude Code didn't answer within {req.timeout:.0f}s and was stopped.", code="timeout",
                             status=504, hint="Try again, or raise brain_timeout_s in settings.") from e
        dt = time.time() - t0
        d = _parse(out)
        if d is None:
            raise classify(f"{out}\n{err}", None)
        if d.get("is_error") or d.get("subtype") != "success":
            raise classify(f"{d.get('result') or ''}\n{err}", d.get("api_error_status"), d.get("subtype"),
                           req.max_turns)
        return BrainResponse(text=d.get("result") or "", duration_s=dt, model=_main_model(d), turns=d.get("num_turns"))

    def status(self) -> dict[str, Any]:
        return {"backend": self.name, "model": self.model or "CLI default", **auth_status(self.binary)}


def auth_status(binary: str | None = None, timeout: float = 20) -> dict[str, Any]:
    """Is Claude Code installed and logged in? (claude --version, claude auth status --json)."""
    exe = find_claude(binary)
    if not exe:
        return {"installed": False, "logged_in": False, "ready": False, "hint": INSTALL_HINT}
    out: dict[str, Any] = {"installed": True, "path": exe}
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=timeout, env=clean_env())
        out["version"] = v.stdout.strip().split(" ")[0] or None
        a = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=timeout,
                           env=clean_env())
        info = json.loads(a.stdout) if a.stdout.strip().startswith("{") else {}
        out.update({"logged_in": bool(info.get("loggedIn")), "auth_method": info.get("authMethod"),
                    "subscription": info.get("subscriptionType")})
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
        out.update({"logged_in": None, "error": str(e)[:200]})
    out["ready"] = bool(out.get("logged_in"))
    if not out["ready"]:
        out["hint"] = LOGIN_HINT
    return out
