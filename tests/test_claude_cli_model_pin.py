"""The claude fallback must always name the cheapest Claude, at every construction site.

Founder directive 2026-08-19: "i need to ensure they fall back to the cheapest possible
version of claude ... enforced and documented".

The defect this guards is not a wrong model name, it is an ABSENT one. `run_claude_cli` only
adds `--model` when a model is given, so any `ClaudeCliOperator()` or
`ClaudeCliGroundingProvider()` built without one silently inherits the machine's Claude Code
default. Measured 2026-08-19 that default was `opus[1m]` (~/.claude/settings.json:81) — the
most expensive Claude, ruling verdicts on the £49 deliverable and burning the subscription
allowance several times faster than Haiku, which drags `usage_wall` forward for every caller.

So the assertions here are deliberately two-layer: the built objects carry a pin (behaviour),
AND no source line constructs either class without one (the class of mistake).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from prospector.claude_cli import CHEAPEST_CLAUDE_MODEL
from prospector.config import load_config

REPO = pathlib.Path(__file__).resolve().parent.parent
PKG = REPO / "prospector"
CLAUDE_CLI_CLASSES = {"ClaudeCliOperator", "ClaudeCliGroundingProvider"}


def test_the_default_is_the_cheapest_tier_not_merely_a_named_one():
    # A pin that drifts to sonnet or opus is the same failure wearing a model name. Haiku is
    # the cheapest Claude tier; if a cheaper one ships, change this line deliberately.
    assert "haiku" in CHEAPEST_CLAUDE_MODEL, CHEAPEST_CLAUDE_MODEL


def test_the_verdict_tier_is_pinned_when_config_says_nothing():
    from prospector.operator import _build_operator

    cfg = load_config()
    cfg.claude_cli_model = ""
    op = _build_operator("claude_cli", cfg, fast=False)
    assert op.model == CHEAPEST_CLAUDE_MODEL
    # The name is what lands in the audit trail; "default" there means nothing was pinned.
    assert "default" not in op.name


def test_config_can_override_the_pin():
    from prospector.operator import _build_operator

    cfg = load_config()
    cfg.claude_cli_model = "claude-sonnet-5"
    assert _build_operator("claude_cli", cfg, fast=False).model == "claude-sonnet-5"


def test_a_whitespace_only_pin_falls_back_to_cheapest_not_to_none():
    from prospector.operator import _build_operator

    cfg = load_config()
    cfg.claude_cli_model = "   "
    assert _build_operator("claude_cli", cfg, fast=False).model == CHEAPEST_CLAUDE_MODEL


def test_the_grounding_provider_is_pinned_too():
    # Grounding is the highest-volume claude_cli caller, so an unpinned default costs most here.
    from prospector.retrieval import make_provider

    cfg = load_config()
    cfg.claude_cli_model = ""
    cfg.retrieval.provider = ["claude_cli"]
    prov = make_provider(cfg)

    # make_provider wraps the real provider several layers deep (cache, enricher, ranker,
    # stamper), and the wrappers do not agree on an attribute name for their inner provider.
    # Walk every attribute rather than guessing names — a guess here would make this test pass
    # by finding nothing.
    def unwrap(node, depth=0, seen=None):
        seen = seen if seen is not None else set()
        if depth > 10 or id(node) in seen:
            return None
        seen.add(id(node))
        if type(node).__name__ == "ClaudeCliGroundingProvider":
            return node
        for value in list(getattr(node, "__dict__", {}).values()):
            children = value if isinstance(value, (list, tuple)) else [value]
            for child in children:
                if hasattr(child, "__dict__"):
                    found = unwrap(child, depth + 1, seen)
                    if found is not None:
                        return found
        return None

    target = unwrap(prov)
    assert target is not None, "no ClaudeCliGroundingProvider under %s" % type(prov).__name__
    assert target.model == CHEAPEST_CLAUDE_MODEL, target.model


def _construction_sites():
    """Every call to a claude CLI class in the package, as (file, line, has_model_kwarg)."""
    for path in sorted(PKG.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name in CLAUDE_CLI_CLASSES:
                kw = next((k for k in node.keywords if k.arg == "model"), None)
                # `model=None` is the defect itself, not a pin — the constructor's own default
                # is None and that is what inherits the machine's Claude Code setting. A
                # literal None here must fail exactly like a missing kwarg.
                pinned = kw is not None and not (
                    isinstance(kw.value, ast.Constant) and kw.value.value is None)
                yield path.relative_to(REPO), node.lineno, pinned


def test_every_construction_site_names_a_model():
    sites = list(_construction_sites())
    # An empty scan passes vacuously — pin the count so a rename or a moved file fails loudly
    # rather than quietly grading nothing (memory: a-guard-that-iterates-an-empty-list-passes).
    assert len(sites) >= 2, "expected to find the operator and the grounding provider, got %r" % (sites,)
    unpinned = ["%s:%d" % (f, ln) for f, ln, ok in sites if not ok]
    assert not unpinned, (
        "these claude CLI construction sites pass no model=, so they inherit the machine's "
        "Claude Code default (measured `opus[1m]` on 2026-08-19): " + ", ".join(unpinned))


def test_the_pin_reaches_the_command_line():
    # The whole point is the `--model` flag. Prove the pin survives into argv rather than
    # trusting that a stored attribute is used.
    import prospector.claude_cli as cc

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        raise RuntimeError("stop here — argv is all this test needs")

    orig = cc.subprocess.run
    cc.subprocess.run = fake_run
    try:
        with pytest.raises(Exception):
            cc.run_claude_cli("hello", web=False, model=CHEAPEST_CLAUDE_MODEL, retries=0)
    finally:
        cc.subprocess.run = orig

    cmd = seen.get("cmd")
    if cmd is None:
        pytest.skip("run_claude_cli did not reach subprocess.run (usage wall or missing binary)")
    assert "--model" in cmd and CHEAPEST_CLAUDE_MODEL in cmd, cmd
