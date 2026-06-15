"""Blue-sky generation must be reachable per RUN.md (the `generate` command).

The engine always supported `signal_text=""` programmatically, but the CLI rejected
it. These tests pin the fixed behaviour: an empty signal flows through run_signal to
generate() as blue-sky, and the --exploration override is honoured.
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
    captured = {}
    monkeypatch.setattr(runmod, "generate",
                        lambda *a, **k: captured.update(fails=k.get("recent_failure_modes")) or [])
    monkeypatch.setattr("prospector.adaptive.get_recent_failure_modes",
                        lambda store, window=20: "MTD/HMRC saturated area")

    # blue-sky → reframed
    runmod.run_signal("", cfg=cfg, op=MagicMock(), search=object(), store=Store(cfg))
    assert "BLUE-SKY MANDATE" in captured["fails"]

    # signal-driven → raw failure modes preserved (no reframe)
    runmod.run_signal("a real signal", cfg=cfg, op=MagicMock(), search=object(), store=Store(cfg))
    assert captured["fails"].startswith("MTD/HMRC saturated area")


def test_run_signal_blue_sky_forwards_empty_signal_and_exploration(monkeypatch):
    cfg = load_config()
    cfg.operator = "mock"
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
    captured: dict = {}

    monkeypatch.setattr(runmod, "generate",
                        lambda *a, **k: captured.update(exploration_level=k.get("exploration_level")) or [])
    # Force the adaptive calc to a known value so we can assert it is used.
    monkeypatch.setattr("prospector.adaptive.calculate_exploration_level", lambda store: 0.42)

    runmod.run_signal("some signal", cfg=cfg, op=MagicMock(), search=object(), store=Store(cfg))

    assert captured["exploration_level"] == 0.42  # adaptive value, no override
