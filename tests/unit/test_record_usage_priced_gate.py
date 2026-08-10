"""Audit finding (ENGINE_AUDIT_2026-08-10.md, HIGH #4): `record_usage()` never called the
config-aware `get_price()` at all — it did its own hardcoded, `cfg`-blind `PRICING.get()`
lookup, so `StandardComputeOperator` (no public rate exists; `Pricing.standardcompute`
deliberately defaults to `None` — see the class comment) always priced at $0/$0 with no
warning and no spend event, silently. `daily_cap_usd` could never see standardcompute spend
no matter how many calls it made.

The fix threads `cfg` from `_build_operator` -> `StandardComputeOperator.__init__` ->
every `record_usage()` call in `StandardComputeOperator._raw`, and makes `record_usage`
warn AND log a $0 "UNPRICED" spend event when a caller supplies `cfg` and that config has
no rate for the provider (today: only standardcompute).

This must NOT change behavior for the ~19 call sites that don't pass `cfg` at all —
critically `claude_cli`, which is subscription burn, deliberately unpriced (no PRICING or
cfg.pricing entry), and must never be counted as a spend event
(test_scheduler_resume_drain.py::test_pricing_claude_cli_would_arm_the_metered_cap pins
this from the other side). These two tests pin both halves of the fix.
"""
from __future__ import annotations

from prospector import telemetry
from prospector.config import Config


def _spend_events(records):
    return [r for r in records if (r[1] or {}).get("event") == "spend"]


def test_standardcompute_with_cfg_and_no_rate_warns_and_logs_loud_zero(monkeypatch):
    records: list = []
    monkeypatch.setattr(
        telemetry.logger, "info",
        lambda msg, *a, **k: records.append((msg, k.get("extra") or {})),
    )
    warnings: list = []
    monkeypatch.setattr(telemetry.logger, "warning", lambda msg, *a, **k: warnings.append(msg))

    cfg = Config()
    assert cfg.pricing.standardcompute is None  # the deliberate default this test relies on

    telemetry.reset_usage()
    telemetry.record_usage(input_tokens=1000, output_tokens=500, provider="standardcompute", cfg=cfg)

    events = _spend_events(records)
    assert events, "standardcompute with cfg supplied and no configured rate must log a spend event even at cost=0"
    msg, extra = events[0]
    assert extra["amount_usd"] == 0.0
    assert extra["priced"] is False
    assert "UNPRICED" in msg
    assert any("standardcompute" in w and "no price configured" in w for w in warnings)


def test_standardcompute_with_a_configured_rate_prices_normally_and_stays_quiet_at_zero_cost(monkeypatch):
    records: list = []
    monkeypatch.setattr(
        telemetry.logger, "info",
        lambda msg, *a, **k: records.append((msg, k.get("extra") or {})),
    )
    warnings: list = []
    monkeypatch.setattr(telemetry.logger, "warning", lambda msg, *a, **k: warnings.append(msg))

    from prospector.config import PriceTier
    cfg = Config()
    cfg.pricing.standardcompute = PriceTier(1.0, 2.0)

    telemetry.reset_usage()
    telemetry.record_usage(input_tokens=0, output_tokens=0, provider="standardcompute", cfg=cfg)

    # Zero tokens -> zero cost, and the provider IS configured -> no loud UNPRICED event.
    assert not _spend_events(records)
    assert not warnings


def test_claude_cli_without_cfg_is_unaffected_by_the_fix(monkeypatch):
    """Pins the same invariant as test_scheduler_resume_drain.py's
    test_pricing_claude_cli_would_arm_the_metered_cap, at the telemetry layer directly."""
    records: list = []
    monkeypatch.setattr(
        telemetry.logger, "info",
        lambda msg, *a, **k: records.append((msg, k.get("extra") or {})),
    )
    warnings: list = []
    monkeypatch.setattr(telemetry.logger, "warning", lambda msg, *a, **k: warnings.append(msg))

    telemetry.reset_usage()
    telemetry.record_usage(input_tokens=900_000, output_tokens=400_000, web=True, provider="claude_cli")

    assert not _spend_events(records), "claude_cli (subscription, no cfg passed) must never emit a spend event"
    assert not warnings
