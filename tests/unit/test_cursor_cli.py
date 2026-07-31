"""Cursor Agent CLI operator — subscription-backed Claude-independent brain."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from prospector import cursor_cli
from prospector.config import load_config
from prospector.errors import ProviderExhaustedError
from prospector.operator import MOAT_PRIMARY, _build_operator, is_provisional_provider


def test_cursor_cli_is_a_trusted_moat_brain():
    """Without this, every Cursor ruling would be marked provisional and never publish."""
    assert "cursor_cli" in MOAT_PRIMARY
    assert not is_provisional_provider("cursor_cli")
    assert is_provisional_provider("deepseek")
    assert is_provisional_provider("minimax")


def test_build_operator_constructs_cursor_cli():
    cfg = load_config()
    op = _build_operator("cursor_cli", cfg, fast=False)
    assert op.name.startswith("cursor-cli/")


def test_run_cursor_cli_uses_ask_mode_and_neutral_workspace(monkeypatch):
    """`-p` alone grants write/shell; ask mode is what keeps this a completion brain."""
    captured = {}

    class _Proc:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return _Proc()

    monkeypatch.setattr(cursor_cli.shutil, "which", lambda _: "/fake/agent")
    monkeypatch.setattr(cursor_cli.subprocess, "run", fake_run)

    out = cursor_cli.run_cursor_cli("say hi", model="gpt-5", retries=0)
    assert json.loads(out)["ok"] is True
    cmd = captured["cmd"]
    assert cmd[0] == "/fake/agent"
    assert "-p" in cmd
    assert "--mode" in cmd and cmd[cmd.index("--mode") + 1] == "ask"
    assert "--trust" in cmd
    assert "--workspace" in cmd
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "gpt-5"
    # Must not run inside the repo tree (project instruction files hijack prompts).
    assert not (captured["cwd"] or "").startswith(str(cursor_cli.REPO_ROOT))
    assert "prospector_cursor_cli_cwd" in (captured["cwd"] or "")


def test_auth_failure_is_provider_exhausted(monkeypatch):
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "Error: Authentication required. Please run 'agent login' first"

    monkeypatch.setattr(cursor_cli.shutil, "which", lambda _: "/fake/agent")
    monkeypatch.setattr(cursor_cli.subprocess, "run", lambda *a, **k: _Proc())

    with pytest.raises(ProviderExhaustedError):
        cursor_cli.run_cursor_cli("hi", retries=0)


def test_operator_complete_json_extracts_payload(monkeypatch):
    op = cursor_cli.CursorCliOperator()

    def fake_raw(system, user, temperature):
        return 'Here you go:\n{"verdict":"supported","confidence":0.8}'

    monkeypatch.setattr(op, "_raw", fake_raw)
    data = op.complete_json("sys", "user", temperature=0.0, retries=0)
    assert data["verdict"] == "supported"
