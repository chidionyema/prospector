"""The always-on daemon must generate when permitted, skip when guarded, and never die on a
single batch failure."""
from __future__ import annotations

import json
import types
from pathlib import Path

from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, cap=20.0, batch=3):
    return types.SimpleNamespace(
        store_dir=str(tmp_path),
        spend=types.SimpleNamespace(daily_cap_usd=cap, warn_at_usd=cap * 0.75),
        schedule={"batch_size": batch},
    )


def _ticks(tmp_path):
    p = Path(tmp_path) / "scheduler" / "ticks.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_tick_runs_when_permitted(tmp_path):
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: calls.append(n) or {"dossiers": n})
    assert tick["allowed"]
    assert calls == [3]  # config batch_size
    assert tick["result"] == {"dossiers": 3}
    assert len(_ticks(tmp_path)) == 1


def test_candidates_override_batch_size(tmp_path):
    calls = []
    rs.run_tick(_cfg(tmp_path), candidates=7, generate_fn=lambda c, n: calls.append(n))
    assert calls == [7]


def test_tick_skips_when_paused(tmp_path):
    sd = Path(tmp_path) / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "PAUSE").write_text("")
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: calls.append(n))
    assert not tick["allowed"]
    assert calls == []
    assert "paused" in tick["reason"]


def test_dry_run_never_generates(tmp_path):
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), dry_run=True, generate_fn=lambda c, n: calls.append(n))
    assert tick["allowed"]
    assert calls == []


def test_tick_survives_generation_error(tmp_path):
    def boom(c, n):
        raise RuntimeError("moat exhausted")

    tick = rs.run_tick(_cfg(tmp_path), generate_fn=boom)
    assert tick["error"] and "moat exhausted" in tick["error"]
    # Still logged, so the audit trail records the failure.
    assert len(_ticks(tmp_path)) == 1


def test_daemon_runs_max_cycles(tmp_path):
    calls = []
    n = rs.run_daemon(
        _cfg(tmp_path), interval=0,
        generate_fn=lambda c, k: calls.append(k),
        max_cycles=2, sleep_fn=lambda s: None,
    )
    assert n == 2
    assert calls == [3, 3]


def test_daemon_idles_when_paused(tmp_path):
    sd = Path(tmp_path) / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "PAUSE").write_text("")
    calls = []
    n = rs.run_daemon(
        _cfg(tmp_path), interval=0,
        generate_fn=lambda c, k: calls.append(k),
        max_cycles=3, sleep_fn=lambda s: None,
    )
    assert n == 3
    assert calls == []  # paused every cycle, never generated


# ---------------------------------------------------------------------------
# Retry escalation. The retry used to be FLAT: every unproductive tick slept
# _RETRY_BACKOFF_S (300s), forever. Right for the blip it was written for, wrong for an
# outage — measured on 2026-08-01/02, when 131 of 144 real ticks failed
# `moat_preflight: no trusted moat brain answered: cursor_cli: ProviderExhaustedError`
# and the daemon re-probed every 5 minutes for two days at 24x its normal cadence.
# ---------------------------------------------------------------------------

def test_first_retry_is_still_fast():
    """The blip case must not regress — a single bad tick still retries in 5 minutes."""
    assert rs._retry_sleep_s(1, interval=7200) == rs._RETRY_BACKOFF_S


def test_retry_doubles_and_caps_at_the_normal_cadence():
    assert [rs._retry_sleep_s(n, interval=7200) for n in range(1, 7)] == \
        [300, 600, 1200, 2400, 4800, 7200]
    # Capped: a sustained outage settles to the ordinary heartbeat, never slower. A
    # recovered moat must not wait longer than a healthy daemon would to notice.
    assert rs._retry_sleep_s(50, interval=7200) == 7200
    # A short interval clamps immediately rather than exceeding it.
    assert rs._retry_sleep_s(3, interval=120) == 120


def test_two_day_outage_costs_probes_not_hundreds():
    """The quantified claim behind the change, as an assertion rather than a comment."""
    interval, day = 7200, 86400
    flat = day // rs._RETRY_BACKOFF_S              # what the old code did: 288 probes/day
    slept, escalated, n = 0, 0, 0
    while slept < day:
        n += 1
        slept += rs._retry_sleep_s(n, interval)
        escalated += 1
    assert flat == 288
    # Measured, not guessed: 300+600+1200+2400+4800 covers the first 9300s in 5 probes,
    # then it settles to the 2h cadence for the remaining 77100s — 11 more, 16 in all.
    assert escalated == 16
    assert escalated < flat / 15


def test_daemon_escalates_across_consecutive_unproductive_ticks(tmp_path):
    """Drives the REAL loop: the escalation must be wired in, not just computable."""
    def boom(c, k):
        raise RuntimeError("moat exhausted")

    slept = []
    rs.run_daemon(_cfg(tmp_path), interval=7200, generate_fn=boom,
                  max_cycles=4, sleep_fn=slept.append)
    # Sleeps happen after cycles 1..3 (the 4th breaks on max_cycles before sleeping), and
    # run_daemon sleeps in <=5s slices, so the sum is what the cycle actually waited.
    assert sum(slept) == 300 + 600 + 1200


def test_a_productive_tick_resets_the_escalation(tmp_path):
    """Recovery is immediate. Otherwise a healthy daemon inherits the outage's backoff.

    Must run a FIFTH cycle to mean anything. A shorter version of this test passed even with
    the reset deleted: the recovery cycle sleeps the full interval either way, so the reset
    is only observable on the NEXT failure. Caught by mutation, not by reading it.
    """
    seq = iter([False, False, True, False, False])   # fail, fail, succeed, fail, fail

    def flaky(c, k):
        if next(seq):
            return {"dossiers": 3, "passes": 1, "defers": 0, "provisional": 0}
        raise RuntimeError("moat exhausted")

    slept = []
    rs.run_daemon(_cfg(tmp_path), interval=7200, generate_fn=flaky,
                  max_cycles=5, sleep_fn=slept.append)
    # 300 (1st fail), 600 (2nd), 7200 (success -> full cadence), then 300 again because the
    # counter reset — NOT 1200, which is what a persisted count would give. The 5th cycle
    # breaks on max_cycles before sleeping.
    assert sum(slept) == 300 + 600 + 7200 + 300
