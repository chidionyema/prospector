"""The console must not show a control the engine ignores.

Founder directive 2026-08-21, repeated: "i dont want consurreny onclaude code", "its too
expencice". The number is clamped in code at `claude_cli.MAX_CLAUDE_CLI`, so a console knob
offering 16 would move config.yaml, print a receipt, and change nothing the engine does. That is
worse than having no knob at all: the operator believes they turned it down.

These tests pin the two halves of the fix — the ceiling is READ from the clamp rather than
restated, and the write is refused with the reason rather than accepted and ignored.
"""
from __future__ import annotations

import pytest

from prospector.claude_cli import MAX_CLAUDE_CLI
from prospector.ops import console_api as api

KEY = "retrieval.claude_concurrency"


def _knob(key: str) -> dict:
    spec = api.KNOBS_BY_KEY.get(key)
    assert spec is not None, f"{key} is not a console knob at all"
    return spec


def test_the_console_ceiling_is_the_code_ceiling():
    """Not "is 1" — is THE SAME NUMBER. A test asserting 1 twice would pass while the two
    drifted apart in opposite directions."""
    assert _knob(KEY)["max"] == MAX_CLAUDE_CLI


def test_the_knob_says_why_it_will_not_move():
    reason = _knob(KEY).get("pinned_reason") or ""
    assert reason, "a pinned knob with no reason is a broken control, not a pinned one"
    assert "MAX_CLAUDE_CLI" in reason, "the reason must name where the ceiling actually lives"
    assert "expensive" in reason.lower(), "the reason must carry the founder's reason, not just a rule"


def test_a_write_is_refused_and_the_refusal_carries_the_reason():
    with pytest.raises(ValueError) as exc:
        api._act_config_set(None, {"key": KEY, "value": 4, "reason": "faster"}, preview=True)
    assert "MAX_CLAUDE_CLI" in str(exc.value)


def test_the_refusal_fires_before_the_value_is_even_read():
    """Refused with no `value` at all, so nothing about the payload can route around the pin."""
    with pytest.raises(ValueError) as exc:
        api._act_config_set(None, {"key": KEY, "reason": "faster"}, preview=True)
    assert "cannot be changed from the console" in str(exc.value)


def test_the_pin_is_one_knob_and_not_a_blanket():
    """MiniMax leads the chain and its concurrency is the real throughput knob. Pinning Claude
    must not quietly freeze the control the operator actually needs."""
    minimax = _knob("retrieval.minimax_concurrency")
    assert not minimax.get("pinned_reason")
    assert minimax["max"] > 1


def test_the_config_file_is_inside_the_console_ceiling():
    """A config.yaml above the console max would render a knob whose current value is out of
    its own range — the exact display an operator reads as "someone raised it"."""
    from prospector.config import load_config

    cfg = load_config()
    live = int(getattr(cfg.retrieval, "claude_concurrency", 1) or 1)
    assert live <= _knob(KEY)["max"]


def test_the_page_renders_it_read_only_with_the_reason():
    """The dashboard's own read, not the spec. The UI already draws a "read only" pill and a
    banner from `writable: false`, so the pin has to reach the operator through THAT field —
    yaml_surgery can edit this line perfectly well, and would say so if left to answer."""
    from prospector.config import load_config

    view = api._read_config(load_config(), {})
    knobs = [k for g in view["groups"] for k in g["knobs"] if k["key"] == KEY]
    assert len(knobs) == 1, "the knob must still be listed — a hidden control cannot be explained"
    knob = knobs[0]
    assert knob["writable"] is False
    assert "MAX_CLAUDE_CLI" in (knob["reason"] or "")
    assert knob["current"] == MAX_CLAUDE_CLI, "the page must show the value the engine uses"
