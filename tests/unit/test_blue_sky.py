"""Blue-sky generation must be reachable per RUN.md (the `generate` command).

The engine always supported `signal_text=""` programmatically, but the CLI rejected
it. These tests pin the fixed behaviour: an empty signal flows through run_signal to
generate() as blue-sky, and the --exploration override is honoured.

Each case pins `noncritical_operator` to mock alongside `operator`, and that is a
precondition rather than tidying. `run_signal` builds the ancillary chain EAGERLY
(run.py:955) before it knows whether anything will use it, and since standardcompute's
removal on 2026-08-15 that chain is minimax alone — key-metered, so
`_build_operator_chain` raises ProviderExhaustedError at construction wherever the key
is absent. CI has no keys, so these three died there while passing on every developer
machine (run 31793597064). Every consumer of that chain is stubbed out below, so the
tests were never about ancillary providers; the mock states that.
"""
from __future__ import annotations

from prospector import run as runmod
from prospector.adaptive import blue_sky_failure_steer
from prospector.config import load_config
from prospector.store import Store


def test_blue_sky_steer_inverts_kill_log_into_no_go_zone():
    raw = "Recent kill-gates: value_durability (15). Incumbents: hmrc.gov.uk, mtd.digital."
    out = blue_sky_failure_steer(raw)
    assert "BLUE-SKY MANDATE" in out
    assert "NO-GO zone" in out
    assert raw in out                       # the saturated area is named, as exclusion
    assert "AVOID" in out


def test_blue_sky_steer_handles_empty_history():
    out = blue_sky_failure_steer("")
    assert "BLUE-SKY MANDATE" in out
    assert "AVOID" not in out               # nothing to exclude yet


from unittest.mock import MagicMock


def test_blue_sky_run_reframes_failure_modes_but_signal_run_keeps_raw(monkeypatch):
    cfg = load_config()
    cfg.operator = "mock"
    cfg.noncritical_operator = ["mock"]  # see the module docstring: keyless CI cannot build it
    captured = {}
    monkeypatch.setattr(runmod, "generate",
                        lambda *a, **k: captured.update(fails=k.get("recent_failure_modes")) or [])
    monkeypatch.setattr("prospector.adaptive.get_recent_failure_modes",
                        lambda store, cfg=None, window=20: "MTD/HMRC saturated area")

    # blue-sky → reframed
    runmod.run_signal("", cfg=cfg, op=MagicMock(), search=object(), store=Store(cfg))
    assert "BLUE-SKY MANDATE" in captured["fails"]

    # signal-driven → raw failure modes preserved (no reframe)
    runmod.run_signal("a real signal", cfg=cfg, op=MagicMock(), search=object(), store=Store(cfg))
    assert captured["fails"].startswith("MTD/HMRC saturated area")


def test_run_signal_blue_sky_forwards_empty_signal_and_exploration(monkeypatch):
    cfg = load_config()
    cfg.operator = "mock"
    cfg.noncritical_operator = ["mock"]  # see the module docstring: keyless CI cannot build it
    captured: dict = {}

    def fake_generate(op, cfg, signal_text="", k=None, strategy_lens="",
                      exploration_level=0.5, recent_failure_modes=None, **kw):
        captured["signal_text"] = signal_text
        captured["exploration_level"] = exploration_level
        return []  # 0 candidates → run_signal returns early, no vetting needed

    monkeypatch.setattr(runmod, "generate", fake_generate)

    out = runmod.run_signal("", cfg=cfg, op=MagicMock(), search=object(),
                            store=Store(cfg), exploration=0.9)

    assert out == []
    assert captured["signal_text"] == ""          # blue-sky reached generate()
    assert captured["exploration_level"] == 0.9   # --exploration override honoured


def test_run_signal_uses_adaptive_exploration_when_not_overridden(monkeypatch):
    cfg = load_config()
    cfg.operator = "mock"
    cfg.noncritical_operator = ["mock"]  # see the module docstring: keyless CI cannot build it
    captured: dict = {}

    monkeypatch.setattr(runmod, "generate",
                        lambda *a, **k: captured.update(exploration_level=k.get("exploration_level")) or [])
    # Force the adaptive calc to a known value so we can assert it is used.
    monkeypatch.setattr("prospector.adaptive.calculate_exploration_level", lambda store, cfg=None, window=50: 0.42)

    runmod.run_signal("some signal", cfg=cfg, op=MagicMock(), search=object(), store=Store(cfg))

    assert captured["exploration_level"] == 0.42  # adaptive value, no override
