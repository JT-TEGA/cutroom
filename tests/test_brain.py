"""The brain layer without Claude: JSON extraction, validation + one retry, job log, and the Claude Code CLI
backend driven against a fake `claude` executable (success and every failure the API must explain)."""
from __future__ import annotations

import json
import stat
import textwrap
from pathlib import Path

import pytest
from conftest import MockBrain
from pydantic import BaseModel

from engine.brain import BrainError, BrainRequest, ask, extract_json
from engine.brain import claude_code as CC
from engine.config import project_layout, use_layout


class Answer(BaseModel):
    ok: bool
    n: int


def req(tmp_path: Path, **kw) -> BrainRequest:
    return BrainRequest(purpose="test.task", system="sys", prompt="do it", cwd=tmp_path, **kw)


@pytest.mark.parametrize("text", [
    '{"ok": true, "n": 1}',
    'Here you go:\n```json\n{"ok": true, "n": 1}\n```',
    'Sure! {"ok": true, "n": 1} Hope that helps.',
    '```\n{"ok": true, "n": 1}\n```',
])
def test_extract_json(text: str) -> None:
    assert extract_json(text) == {"ok": True, "n": 1}


def test_extract_json_fails_cleanly() -> None:
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_ask_retries_once_with_the_validation_error(tmp_path: Path) -> None:
    replies = iter(['{"ok": "maybe"}', '{"ok": true, "n": 2}'])
    brain = MockBrain({"test.task": lambda r: next(replies)})
    with use_layout(project_layout(tmp_path)):
        out = ask(brain, req(tmp_path), Answer)
    assert out == Answer(ok=True, n=2)
    assert len(brain.calls) == 2
    assert "rejected" in brain.calls[1].prompt and "n: Field required" in brain.calls[1].prompt
    assert "Reply with ONE JSON object" in brain.calls[0].system
    log = (tmp_path / "work" / "jobs.log").read_text()
    assert "brain test.task [mock: mock, 1 turns] attempt 1" in log and "invalid" in log
    assert "attempt 2" in log and log.strip().endswith("ok")


def test_ask_semantic_check_counts_as_invalid(tmp_path: Path) -> None:
    brain = MockBrain({"test.task": lambda r: '{"ok": true, "n": -1}'})
    with use_layout(project_layout(tmp_path)), pytest.raises(BrainError) as e:
        ask(brain, req(tmp_path), Answer, check=lambda a: ["n must be positive"] if a.n < 0 else [])
    assert e.value.code == "invalid_output" and len(brain.calls) == 2


# ---------------------------------------------------------------- the CLI backend, against a fake claude

# canned `claude -p --output-format json` results, one per scenario
FAKE = textwrap.dedent("""\
    #!/bin/bash
    printf '%s\\n' "$@" > "$FAKE_DIR/args.txt"
    cat > "$FAKE_DIR/stdin.txt"
    echo "${ANTHROPIC_API_KEY:-unset}" > "$FAKE_DIR/apikey.txt"
    case "$FAKE_MODE" in
      ok)       echo '{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"{\\"ok\\": true, \\"n\\": 3}","modelUsage":{"claude-sonnet-5":{"outputTokens":9}}}' ;;
      login)    echo '{"type":"result","subtype":"success","is_error":true,"result":"Invalid API key · Please run /login","api_error_status":401}' ;;
      limit)    echo '{"type":"result","subtype":"success","is_error":true,"result":"Claude AI usage limit reached|1760000000"}' ;;
      turns)    echo '{"type":"result","subtype":"error_max_turns","is_error":true,"num_turns":6}' ;;
      garbage)  echo 'segfault or something'; exit 3 ;;
      slow)     sleep 5 ;;
    esac
""")


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(FAKE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAKE_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    return exe


def run_fake(tmp_path: Path, exe: Path, mode: str, monkeypatch: pytest.MonkeyPatch, **kw):
    monkeypatch.setenv("FAKE_MODE", mode)
    return CC.ClaudeCodeBrain(binary=str(exe)).complete(req(tmp_path, **kw))


def test_cli_success_and_isolation_flags(tmp_path, fake_claude, monkeypatch) -> None:
    r = run_fake(tmp_path, fake_claude, "ok", monkeypatch, readable=["work/**"])
    assert json.loads(r.text) == {"ok": True, "n": 3} and r.model == "claude-sonnet-5" and r.turns == 1
    args = (tmp_path / "args.txt").read_text().splitlines()
    for flag in ("-p", "--no-session-persistence", "--strict-mcp-config"):
        assert flag in args
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--tools") + 1] == "Read"
    assert args[args.index("--allowedTools") + 1] == "Read(./work/**)"
    assert "Read(./inputs/**)" in args[args.index("--disallowedTools") + 1]
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert args[args.index("--setting-sources") + 1] == ""
    assert args[args.index("--model") + 1] == "sonnet"
    assert (tmp_path / "stdin.txt").read_text() == "do it"            # prompt via stdin
    assert (tmp_path / "apikey.txt").read_text().strip() == "unset"   # stays on the subscription


def test_cli_model_defaults_to_sonnet_and_follows_settings(tmp_path) -> None:
    from engine import settings as S
    from engine.brain import get_brain
    assert get_brain().model == "sonnet"
    S.save(S.SettingsUpdate(app={"brain_model": "opus"}))
    assert get_brain().command(req(tmp_path), "claude")[-2:] == ["--model", "opus"]
    S.save(S.SettingsUpdate(app={"brain_model": None}))          # empty: leave the model to the CLI
    assert "--model" not in get_brain().command(req(tmp_path), "claude")


def test_cli_without_images_has_no_tools(tmp_path, fake_claude, monkeypatch) -> None:
    run_fake(tmp_path, fake_claude, "ok", monkeypatch)
    args = (tmp_path / "args.txt").read_text().splitlines()
    assert args[args.index("--tools") + 1] == "" and "--allowedTools" not in args


@pytest.mark.parametrize("mode, code, status", [
    ("login", "claude_not_logged_in", 503),
    ("limit", "usage_limit", 429),
    ("turns", "max_turns", 502),
    ("garbage", "brain_error", 502),
])
def test_cli_errors_are_classified(tmp_path, fake_claude, monkeypatch, mode, code, status) -> None:
    with pytest.raises(BrainError) as e:
        run_fake(tmp_path, fake_claude, mode, monkeypatch)
    assert e.value.code == code and e.value.status == status
    if mode == "limit":
        assert "resets" in e.value.message and e.value.hint


def test_cli_timeout(tmp_path, fake_claude, monkeypatch) -> None:
    with pytest.raises(BrainError) as e:
        run_fake(tmp_path, fake_claude, "slow", monkeypatch, timeout=0.5)
    assert e.value.code == "timeout" and e.value.status == 504


def test_cli_not_installed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(CC, "find_claude", lambda explicit=None: None)
    with pytest.raises(BrainError) as e:
        CC.ClaudeCodeBrain().complete(req(tmp_path))
    assert e.value.code == "claude_not_installed" and "Install Claude Code" in e.value.hint


def test_api_backend_without_key_explains(tmp_path) -> None:
    from engine.brain.anthropic_api import AnthropicAPIBrain
    with pytest.raises(BrainError) as e:
        AnthropicAPIBrain().complete(req(tmp_path))
    assert e.value.code == "api_key_missing" and ".env" in e.value.hint
    assert AnthropicAPIBrain().status()["ready"] is False


def test_api_backend_model_defaults_to_sonnet_and_follows_settings() -> None:
    from engine import settings as S
    from engine.brain import get_brain
    assert get_brain(S.AppSettings(brain_backend="anthropic-api")).model == "claude-sonnet-5-5"
    S.save(S.SettingsUpdate(app={"brain_backend": "anthropic-api", "anthropic_model": "claude-opus-5-5"}))
    assert get_brain().model == "claude-opus-5-5"
