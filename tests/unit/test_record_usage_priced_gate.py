"""Audit finding (ENGINE_AUDIT_2026-08-10.md, HIGH #4): `record_usage()` never called the
config-aware `get_price()` at all — it did its own hardcoded, `cfg`-blind `PRICING.get()`
lookup, so a metered provider with no configured rate priced at $0/$0 with no warning and no
spend event, silently, and `daily_cap_usd` could never see its spend.

The provider that exposed it (standardcompute) was removed on 2026-08-15 with its adapter, and
its two tests went with it. What is left is the half that must keep holding regardless: the ~19
call sites that don't pass `cfg` at all — critically `claude_cli`, which is subscription burn,
deliberately unpriced (no PRICING or cfg.pricing entry), and must never be counted as a spend
event (test_scheduler_resume_drain.py::test_pricing_claude_cli_would_arm_the_metered_cap pins
this from the other side).
"""
from __future__ import annotations

from prospector import telemetry


def _spend_events(records):
    return [r for r in records if (r[1] or {}).get("event") == "spend"]


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
