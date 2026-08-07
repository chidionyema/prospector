"""A moat-blind tick must page the founder, not just write a log line.

PROBED LIVE 2026-08-06 (commercial-readiness audit, doc §2.6 R1): `run_scheduled`'s moat
preflight skips the whole tick — no generation, no drain — and already calls
`_emit_tick_alerts`, but `alerts_for_tick` had no `moat_blind` branch. A blind tick carries no
`result` dict, so every branch fell through and the function returned `[]`: the engine's most
severe live state (every trusted brain dead at once, dominated by PERMANENT 402/allowance
exhaustion that only a human can clear) was log-only, and `moat_blind` was not in
`TELEGRAM_KEYS`, so even a hand-emitted alert would never have left the machine.

These tests drive the REAL tick shape `run_scheduled.run_tick` writes on the blind path
(`moat_blind=True, reason=<str>, batch_size=None`, and crucially NO `result` key) — not an
idealised dict — because the defect was precisely a mismatch between the real shape and the
shapes `alerts_for_tick` understood.
"""
from __future__ import annotations

import types

import pytest

from prospector.scheduler import run_scheduled as rs
from prospector.scheduler.alerts import (
    CRITICAL,
    TELEGRAM_KEYS,
    TICK_ALERT_KEYS,
    active_alerts,
    alerts_for_tick,
)


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    # No desktop popups and no webhook POSTs from a test run.
    monkeypatch.setattr("prospector.scheduler.alerts._desktop_notify", lambda *a, **k: None)
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    return types.SimpleNamespace(store_dir=str(tmp_path))


def _blind_tick(**over) -> dict:
    """The dict `run_tick` appends on the moat-blind path — with NO `result` key."""
    t = {"ts": "2026-08-06T02:00:00+00:00", "allowed": True, "dry_run": False,
         "moat_blind": True, "reason": "moat blind: claude_cli dead until 03:00 (permanent)",
         "batch_size": None, "error": None}
    t.update(over)
    return t


def test_blind_tick_fires_exactly_one_critical_moat_blind_alert():
    specs = alerts_for_tick(_blind_tick())
    assert [(s["key"], s["severity"]) for s in specs] == [("moat_blind", CRITICAL)]
    # The operator's first question is "why"; the dead-mark reason must survive into the page.
    assert "claude_cli dead until 03:00" in specs[0]["message"]


def test_moat_blind_reaches_telegram_and_is_declared_resolvable():
    # Off-machine page: permanent exhaustion will not clear without a human funding an account.
    assert "moat_blind" in TELEGRAM_KEYS
    # Clearable: a later healthy tick resolves every TICK_ALERT_KEYS entry it did not raise.
    assert "moat_blind" in TICK_ALERT_KEYS


def test_tick_error_still_outranks_moat_blind():
    # Worst-first contract: an errored tick is its own page even if it also flagged blindness.
    specs = alerts_for_tick(_blind_tick(error="boom"))
    assert [s["key"] for s in specs] == ["tick_error"]


def test_guard_skipped_or_dry_blind_tick_stays_silent():
    # PAUSE/spend-cap idle is intended; a dry run proves nothing. Same fence as every other key.
    assert alerts_for_tick(_blind_tick(allowed=False)) == []
    assert alerts_for_tick(_blind_tick(dry_run=True)) == []


def test_seam_emit_tick_alerts_lands_moat_blind_in_the_active_set(cfg):
    # The join, not the halves: the real emission path must leave an ACTIVE alert on disk.
    rs._emit_tick_alerts(cfg, _blind_tick())
    assert "moat_blind" in active_alerts(cfg)
