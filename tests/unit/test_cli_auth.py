"""The subscription must win over an ambient API key, for every spawn of the `claude` CLI.

The CLI's credential precedence is not ours to set: an `ANTHROPIC_API_KEY` in the process
environment OUTRANKS the claude.ai login and gets billed. Ours has a zero balance, so a spawn
that inherits it exits 1 with "Credit balance is too low" and the head of MOAT_PRIMARY dies
without ever having been asked a question.

Measured 2026-08-07, same binary, same second: `claude -p` -> "Credit balance is too low";
`env -u ANTHROPIC_API_KEY claude -p` -> "OK".

Three layers are tested here, because the first two do not stop the failure coming BACK:
  1. the helper strips what it promises to strip (unit),
  2. the real spawn path actually uses it (behavioural — this is the regression),
  3. no NEW spawn site can quietly inherit the environment (structural guard).
"""
from __future__ import annotations

import ast
import pathlib

from prospector import claude_cli
from prospector.cli_auth import (
    SUBSCRIPTION_HIJACK_VARS,
    ambient_hijackers,
    describe_ambient_auth,
    subscription_env,
)

_PKG = pathlib.Path(claude_cli.__file__).parent


# --------------------------------------------------------------------------- 1. the helper

def test_subscription_env_strips_every_hijack_var():
    base = {k: "hijack" for k in SUBSCRIPTION_HIJACK_VARS}
    base["PATH"] = "/usr/bin"
    out = subscription_env(base)
    assert not (set(out) & set(SUBSCRIPTION_HIJACK_VARS))


def test_subscription_env_is_a_denylist_and_keeps_everything_else():
    """An allowlist here breaks the CLI the day it needs a var nobody enumerated."""
    base = {"ANTHROPIC_API_KEY": "dead", "PATH": "/usr/bin", "HOME": "/home/x",
            "EXA_API_KEY": "keep-me", "SOME_FUTURE_VAR": "keep-me-too"}
    out = subscription_env(base)
    assert out == {"PATH": "/usr/bin", "HOME": "/home/x",
                   "EXA_API_KEY": "keep-me", "SOME_FUTURE_VAR": "keep-me-too"}


def test_base_url_is_stripped_because_it_hijacks_the_BRAIN_not_the_bill():
    """A repointed endpoint means an untrusted brain answers a call that MOAT_PRIMARY
    still counts as trusted. This assertion is the fence, not a style preference."""
    assert "ANTHROPIC_BASE_URL" in SUBSCRIPTION_HIJACK_VARS
    assert "ANTHROPIC_BASE_URL" not in subscription_env({"ANTHROPIC_BASE_URL": "http://evil"})


def test_ambient_hijackers_reports_only_vars_that_are_actually_set():
    assert ambient_hijackers({}) == []
    assert ambient_hijackers({"ANTHROPIC_API_KEY": ""}) == []          # empty is not set
    assert ambient_hijackers({"ANTHROPIC_API_KEY": "x"}) == ["ANTHROPIC_API_KEY"]


def test_describe_ambient_auth_never_prints_the_secret():
    secret = "sk-ant-api03-SUPERSECRET"
    line = describe_ambient_auth({"ANTHROPIC_API_KEY": secret})
    assert secret not in line and "HIJACKED" in line
    assert "OK" in describe_ambient_auth({})


# ------------------------------------------------------------------- 2. the real spawn path

def test_the_real_cli_spawn_passes_a_stripped_env(monkeypatch):
    """THE regression test. Everything above can pass while the spawn still inherits os.environ.

    Non-vacuity: this test FAILS if `env=child_env` is dropped from the subprocess.run call in
    `_attempt_claude_cli` (verified by reverting that line).
    """
    for var in SUBSCRIPTION_HIJACK_VARS:
        monkeypatch.setenv(var, "would-hijack-the-subscription")
    monkeypatch.setenv("PATH", "/usr/bin")

    seen: dict = {}

    class _Proc:
        returncode = 0
        stdout = '{"result": "ok"}'
        stderr = ""

    def _fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return _Proc()

    class _FreeSlot:
        def acquire(self, timeout=None): return True
        def release(self): pass
        def current_slot(self): return 0

    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run)
    monkeypatch.setattr(claude_cli, "_CLI_SEM", _FreeSlot())

    claude_cli._attempt_claude_cli(["claude", "-p", "hi"], timeout=5, web=False)

    env = seen.get("env")
    assert env is not None, "spawn inherited os.environ — the dead key wins over the subscription"
    for var in SUBSCRIPTION_HIJACK_VARS:
        assert var not in env, f"{var} reached the CLI child environment"
    assert env["PATH"] == "/usr/bin", "the strip must not damage the rest of the environment"


# --------------------------------------------------------------------- 3. structural guard

def _subprocess_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name in ("run", "Popen", "check_output", "call", "check_call"):
            yield node


def test_no_spawn_of_the_claude_binary_may_inherit_the_environment():
    """A NEW `subprocess.run([CLAUDE_BIN, ...])` added without `env=` is the way this bug
    returns. Catch it in the tree, not in production three weeks later."""
    offenders = []
    for path in _PKG.rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        if "CLAUDE_BIN" not in src and '"claude"' not in src:
            continue
        tree = ast.parse(src)
        for call in _subprocess_calls(tree):
            seg = ast.get_source_segment(src, call) or ""
            names_the_binary = "CLAUDE_BIN" in seg or '"claude"' in seg
            passes_env = any(kw.arg == "env" for kw in call.keywords)
            if names_the_binary and not passes_env:
                offenders.append(f"{path.name}:{call.lineno}")
    assert not offenders, (
        "these spawn the claude binary with an inherited environment, so an ambient "
        f"ANTHROPIC_API_KEY outranks the subscription: {offenders}")


def test_the_hijack_list_has_exactly_one_definition():
    """Two copies is how one of them drifts. cli_auth.py owns it; nobody else re-inlines it."""
    dupes = []
    for path in _PKG.rglob("*.py"):
        if path.name == "cli_auth.py":
            continue
        src = path.read_text(encoding="utf-8")
        if "ANTHROPIC_API_KEY" in src and "ANTHROPIC_AUTH_TOKEN" in src:
            # A comment may name them; a tuple/list literal pairing them is a second definition.
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                    consts = {e.value for e in node.elts if isinstance(e, ast.Constant)}
                    if {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"} <= consts:
                        dupes.append(f"{path.name}:{node.lineno}")
    assert not dupes, f"second definition of the hijack list (use cli_auth): {dupes}"
