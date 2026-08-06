"""Stopping the treadmill must not also stop the recovery.

`PAUSE` (guard.py:203) halts the ENTIRE tick, and until 2026-08-06 the drain lived inside
`_default_generate` — so every reason to skip generation also silently switched off the only
mechanism that pays the backlog down. That made the founder's 2026-08-06 decision ("pause
generation, let drain run") impossible to express: setting PAUSE to stop the treadmill also
guaranteed the 343 backlogged rows could never clear, no matter how long it ran.

The underlying arithmetic, measured the same day: `config.yaml:966` sets `batch_size: 15` while
`resume_per_tick` is unset and falls to 3, i.e. **+12 backlog rows per tick by design**.
`guard.evaluate()` gates on PAUSE, clock-backward and the two spend caps and then returns
can_run=True — nothing anywhere read the backlog it was filling. Backlog sat flat at ~340 for
six weeks, oldest row 2026-06-14.

So: a tick that will not generate must still drain, and the daemon must come back to it on a
cadence that clears the backlog rather than one that outlives it.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

import prospector.health as H
from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, **schedule):
    sched = {"batch_size": 15}
    sched.update(schedule)
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule=sched,
        operator=["claude_cli"],
    )


@pytest.fixture
def drains(monkeypatch):
    """Capture drain calls without running a real re-vet."""
    calls = []

    def _fake(cfg, n):
        calls.append(n)
        return {"backlog": 343, "attempted": n, "resumed": n}

    monkeypatch.setattr(rs, "_drain_pass", _fake)
    return calls


@pytest.fixture
def gens():
    calls = []
    return calls


def _tick(cfg, gens):
    return rs.run_tick(cfg, generate_fn=lambda c, n: gens.append(n) or {"dossiers": n})


# --------------------------------------------------------------------------- manual half-stop

def test_pause_generation_stops_generation_but_the_drain_still_runs(tmp_path, drains, gens):
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scheduler" / "PAUSE_GENERATION").write_text("backlog too high")

    tick = _tick(_cfg(tmp_path), gens)

    assert gens == [], "generation must not run"
    assert drains, "the drain MUST still run — this is the whole point of the half-stop"
    assert "generation paused" in tick["generation_suppressed"]
    assert tick["batch_size"] == 0


def test_full_pause_still_stops_everything(tmp_path, drains, gens):
    """PAUSE is the liability rail CLAUDE.md requires, and a rail with exceptions is not a rail.
    The new half-stop must not have quietly turned it into one."""
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scheduler" / "PAUSE").write_text("stop everything")

    tick = _tick(_cfg(tmp_path), gens)

    assert gens == []
    assert drains == [], "PAUSE means PAUSE — the drain spends CLI budget too"
    assert tick["allowed"] is False


# ------------------------------------------------------------------------- the automatic brake

def _with_backlog(monkeypatch, n):
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: n)


def test_brake_engages_above_the_cap(tmp_path, drains, gens, monkeypatch):
    _with_backlog(monkeypatch, 343)
    tick = _tick(_cfg(tmp_path, backlog_cap=200), gens)

    assert gens == [], "generating 15 more into a 343-row backlog is digging"
    assert drains, "the backlog must go DOWN while the brake is engaged, or it never releases"
    assert "343" in tick["generation_suppressed"] and "200" in tick["generation_suppressed"]


def test_brake_releases_below_the_cap(tmp_path, drains, gens, monkeypatch):
    _with_backlog(monkeypatch, 199)
    tick = _tick(_cfg(tmp_path, backlog_cap=200), gens)

    assert gens == [15], "below the cap the daemon generates normally"
    assert not tick.get("generation_suppressed")


def test_brake_is_off_by_default(tmp_path, drains, gens, monkeypatch):
    """Default OFF, so an existing deployment's behaviour cannot change silently on upgrade."""
    _with_backlog(monkeypatch, 10_000)
    tick = _tick(_cfg(tmp_path), gens)

    assert gens == [15]
    assert not tick.get("generation_suppressed")


@pytest.mark.parametrize("cap", [0, -1, "not-an-int", None])
def test_a_malformed_cap_disables_the_brake_rather_than_freezing(tmp_path, drains, gens,
                                                                 monkeypatch, cap):
    _with_backlog(monkeypatch, 10_000)
    assert _tick(_cfg(tmp_path, backlog_cap=cap), gens) is not None
    assert gens == [15]


def test_an_uncountable_backlog_stops_generation(tmp_path, drains, gens, monkeypatch):
    """The rail cannot function, so it stops — it does not wave the tick through. Same call
    guard.py makes when the clock goes backwards and the daily cap cannot be summed. The
    operator opted into this brake explicitly; an unreadable store is not consent to generate.
    It is a pause, not a deadlock: the drain runs and the next tick re-counts."""
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: None)
    tick = _tick(_cfg(tmp_path, backlog_cap=200), gens)

    assert gens == [], "an unknown backlog must not authorise a generation batch"
    assert drains
    assert "could not be counted" in tick["generation_suppressed"]


def test_backlog_size_returns_none_not_zero_when_it_cannot_count(tmp_path, monkeypatch):
    """0 would read as 'backlog clear' and release the brake — the one direction a counting bug
    must never fail in. This is why `_backlog_size` is `int | None` and not `int`."""
    import prospector.store as S
    monkeypatch.setattr(S, "Store", lambda cfg: (_ for _ in ()).throw(OSError("disk gone")))
    assert rs._backlog_size(_cfg(tmp_path)) is None


# ---------------------------------------------------------------- ordering against the moat

def test_a_blind_moat_beats_the_brake_and_the_drain_does_not_run(tmp_path, drains, gens):
    """A drain-only tick needs a trusted brain just as much as a generating one. Draining into
    a blind moat only relabels rows provisional->defer (measured -14/+13 in 30 min) and its own
    CLI load helps keep the brain benched — so the moat preflight must win."""
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scheduler" / "PAUSE_GENERATION").write_text("x")
    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")

    tick = _tick(_cfg(tmp_path), gens)

    assert tick["moat_blind"] is True
    assert gens == []
    assert drains == [], "the brake must not smuggle a drain past the moat preflight"


# ------------------------------------------------------------------------------- the cadence

def test_a_drain_only_tick_gets_the_bigger_bound(tmp_path):
    """`resume_per_tick` is 3 because a normal tick spends its budget generating. A tick that is
    not generating has that budget free, so the honest default is the batch it is not running:
    15, not 3 — ~23 ticks to clear 343 rows instead of ~114."""
    assert rs._drain_only_resume_per_tick(_cfg(tmp_path)) == 15
    assert rs._drain_only_resume_per_tick(_cfg(tmp_path, drain_only_resume_per_tick=4)) == 4


def test_drain_only_cadence_is_shorter_than_the_generation_interval(tmp_path):
    assert rs._drain_only_interval_s(_cfg(tmp_path), 7200) == 900


def test_the_brake_can_never_make_the_daemon_slower(tmp_path):
    """Clamped to the interval. Otherwise a large `drain_only_interval_s` would mean engaging
    the brake DELAYS the recovery it exists to accelerate."""
    assert rs._drain_only_interval_s(_cfg(tmp_path, drain_only_interval_s=99_999), 7200) == 7200
    assert rs._drain_only_interval_s(_cfg(tmp_path, drain_only_interval_s="junk"), 300) == 300


def test_a_drain_only_tick_is_not_treated_as_an_outage(tmp_path):
    """`_tick_unproductive` sees `dossiers == 0` and would escalate 5m/10m/20m/40m/80m to the 2h
    cap — slowing a working drain down exactly as it made progress. The daemon loop must branch
    on `generation_suppressed` BEFORE it consults the outage backoff."""
    suppressed = {"allowed": True, "generation_suppressed": "backlog brake: ...",
                  "result": {"dossiers": 0, "resumed": {"resumed": 15}}}
    assert rs._tick_unproductive(suppressed) is True, (
        "unchanged by design — the loop must not reach this call for a suppressed tick")


def test_the_tick_row_records_why_generation_was_skipped(tmp_path, drains, gens):
    """A daemon that has quietly stopped generating is the invisible degradation this whole
    change is about. `logger.info` never reaches launchd.err.log (verified 2026-08-05), so the
    audited tick row is the only durable trace."""
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scheduler" / "PAUSE_GENERATION").write_text("x")
    _tick(_cfg(tmp_path), gens)

    rows = [json.loads(x) for x
            in (Path(tmp_path) / "scheduler" / "ticks.jsonl").read_text().splitlines() if x.strip()]
    assert len(rows) == 1
    assert "generation paused" in rows[0]["generation_suppressed"]
    assert rows[0]["result"]["resumed"]["resumed"] == 15
