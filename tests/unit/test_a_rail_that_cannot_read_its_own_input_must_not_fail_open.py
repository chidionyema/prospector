"""The scheduler's rails must be able to say "I could not read", not just "zero".

The daemon is unattended, so every one of its safety rails is a function that returns a
number or a string and a caller that acts on it. Each rail below used to answer a FAILED
read with the same value it uses for a healthy, boring answer:

  * `_subscription_soft_cap_reason` — a `daily_subscription_soft_cap_usd` that is not a
    number returned `""`, which is the word for "the burn is under the ceiling". A config
    typo therefore removed the ceiling, silently, on the meter that recorded $438.68 of
    ungoverned subscription burn in a day.
  * `_generation_suppressed` — THE ONE RAIL ON THIS LIST THAT DELIBERATELY FAILS OPEN, and
    the exception is what makes the rule legible. This file originally braked on an
    unreadable `backlog_cap` too, for symmetry with the branch below it (an uncountable
    backlog DOES brake). On merging to main 2026-08-15 that met main's
    `test_a_malformed_cap_disables_the_brake_rather_than_freezing`, and main was right —
    not by seniority, by cost:

      unreadable SPEND ceiling, failed open  -> burn is unbounded and unrecoverable
                                                (measured: $438.68 in one day)
      unreadable SPEND ceiling, failed closed-> generation stops; cost is one config edit

      unreadable BACKLOG cap, failed open    -> generation runs unbraked into a queue the
                                                drain works off. This is ALSO the normal
                                                state of every deployment that never set
                                                the cap, since it is default-0 = OFF.
      unreadable BACKLOG cap, failed closed  -> generation stops INDEFINITELY. Nothing
                                                self-clears a typo, and "one stale
                                                condition suppresses generation forever"
                                                is the exact failure that "gate on the
                                                RATE, not the stock" was written to kill
                                                (CLAUDE.md, founder decision 2026-08-06).

    The symmetry argument was also weaker than it looked: `cap <= 0` already treats 0 AND
    -1 as brake-off, so braking on a bad STRING while waving through a bad INT was never a
    consistent policy. The real distinction is not "which half could I not read" but
    "does this rail govern MONEY or THROUGHPUT". Money fails closed. A default-off
    throughput floor fails open and SHOUTS — the grievance that a typo used to be an
    invisible log line is answered by a CRITICAL `backlog_cap_unreadable` operator alert,
    which is pinned below.
  * `_unlist_pass` — an unreadable `pending_unlist.jsonl` returned `None`, which is this
    function's word for "the queue is empty, no pack needs pulling off sale". Every other
    failure path in it returns `{"error": ...}` at CRITICAL, because the cost of not
    running it is a KILLed pack still taking money (6 of them, 2026-08-09).
  * `_tail_errors` — an unreadable `launchd.err.log` returned `[]`, i.e. "the daemon logged
    no errors": the single most reassuring line `--status` can print, produced by a file
    nobody could open. That readout exists because a dead daemon looked alive for 15h.
  * `_backlog_size` / `alerts._load_state` — already returned an honest value, but reported
    the failure at `logger.warning`, which does not reach `launchd.err.log` (measured
    2026-08-05). A rail that fails correctly and invisibly is only half a rail.

Every test pins the DISTINCTION — broken must not equal empty — and carries a falsifier so
"suppress everything, always" cannot pass.
"""
from __future__ import annotations

import json
import logging
import types
from pathlib import Path

from prospector.scheduler import alerts
from prospector.scheduler import run_scheduled as rs

_QUEUE = "pending_unlist.jsonl"
_ERRLOG = "launchd.err.log"


def _cfg(tmp_path, *, schedule=None, spend=None):
    """A daemon config with the LIVE grounding probe off — it makes a real search call."""
    sched = {"batch_size": 15, "gate_generation_on_grounding": False}
    sched.update(schedule or {})
    return types.SimpleNamespace(
        store_dir=str(tmp_path),
        schedule=sched,
        spend=types.SimpleNamespace(**(spend or {})),
        operator=["claude_cli"],
    )


def _break_reads(monkeypatch, name: str, exc: OSError) -> None:
    """Make `name` look PRESENT but unreadable — the state both rails conflated with empty.

    `Path.exists()` swallows OSError itself and answers False, so simply revoking permissions
    would take the "file is not there" branch and prove nothing about the branch under test.
    """
    real_exists, real_stat, real_read = Path.exists, Path.stat, Path.read_text

    def exists(self, *a, **k):
        return True if self.name == name else real_exists(self, *a, **k)

    def stat(self, *a, **k):
        if self.name == name:
            raise exc
        return real_stat(self, *a, **k)

    def read_text(self, *a, **k):
        if self.name == name:
            raise exc
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(Path, "read_text", read_text)


# ---------------------------------------------------- the money rail: subscription burn

def test_an_unparseable_subscription_cap_brakes_instead_of_removing_the_ceiling(tmp_path):
    decision = types.SimpleNamespace(today_subscription_usd=1.0,
                                     daily_subscription_cap_usd=0.0)
    cfg = _cfg(tmp_path, spend={"daily_subscription_soft_cap_usd": "twenty dollars"})

    reason = rs._subscription_soft_cap_reason(cfg, decision)
    assert reason, "an unreadable spend ceiling must not read as 'under the ceiling'"
    assert "UNREADABLE" in reason

    # FALSIFIERS — the brake must still be a brake, not a permanent stop:
    under = _cfg(tmp_path, spend={"daily_subscription_soft_cap_usd": 100.0})
    assert rs._subscription_soft_cap_reason(under, decision) == "", "burn under a real cap generates"
    off = _cfg(tmp_path, spend={"daily_subscription_soft_cap_usd": 0.0})
    assert rs._subscription_soft_cap_reason(off, decision) == "", "0.0 is the documented OFF value"
    assert rs._subscription_soft_cap_reason(cfg, None) == "", "no guard decision, nothing to judge"


# ---------------------------------------------------- the backlog rail: cap vs count

def test_an_unparseable_backlog_cap_fails_open_but_pages_instead_of_going_quiet(tmp_path,
                                                                                monkeypatch,
                                                                                caplog):
    """The deliberate exception: THROUGHPUT rail, default-off, so it fails OPEN — loudly.

    This is the one place in this file where "could not read" is allowed to keep working,
    and it is allowed only because it does not go quiet. The thing that made the original
    fail-open a defect was silence, not the direction: it disabled a rail with a
    `logger.warning` nobody reads. So the assertion here is not "generation continues" on
    its own — it is "generation continues AND the operator is paged". Either half alone is
    the bug: continuing quietly hides a broken rail, and braking freezes the storefront's
    supply on a typo that nothing self-clears.

    Contrast `test_an_unparseable_subscription_cap_brakes_instead_of_removing_the_ceiling`
    directly above, which fails CLOSED on the same class of input. The two are not
    inconsistent; see the module docstring for the cost asymmetry that separates them.
    """
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 0)
    caplog.set_level(logging.CRITICAL, logger="prospector.scheduler.run_scheduled")

    bad = rs._generation_suppressed(_cfg(tmp_path, schedule={"backlog_cap": "fifteen"}))
    assert bad == "", "a cap that never expressed a threshold must not freeze generation"
    assert [r for r in caplog.records if r.levelno >= logging.CRITICAL], (
        "the brake is OFF and nobody was told — logger.warning does not reach "
        "launchd.err.log, which is how a disabled rail stays disabled for weeks")

    # The neighbouring half, which DOES brake, because a valid cap whose COUNT failed is a
    # different animal: the threshold is known, only the reading failed, and it self-clears
    # on the very next tick. That distinction is the point of keeping both in one test.
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: None)
    uncountable = rs._generation_suppressed(_cfg(tmp_path, schedule={"backlog_cap": 5}))
    assert "could not be counted" in uncountable

    # FALSIFIERS — a readable config still generates, so this is not "never suppress".
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 1)
    assert rs._generation_suppressed(_cfg(tmp_path, schedule={"backlog_cap": None})) == ""
    assert rs._generation_suppressed(_cfg(tmp_path, schedule={"backlog_cap": 0})) == ""
    assert rs._generation_suppressed(_cfg(tmp_path, schedule={"backlog_cap": 5})) == ""
    # ...and the brake still engages when it CAN read both halves, or the test above would
    # pass just as well against a rail that was deleted outright.
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 999)
    assert rs._generation_suppressed(_cfg(tmp_path, schedule={"backlog_cap": 5})) != ""


def test_a_failed_backlog_count_is_reported_at_error_not_warning(tmp_path, caplog, monkeypatch):
    """The count is broken AT ITS SOURCE, not by handing the rail a junk cfg.

    A junk cfg is not a proof: `Store(None)` falls back to a cwd-relative "store" directory,
    so `_backlog_size(None)` reads the PRODUCTION store and returns a real 0 outside pytest
    (verified 2026-08-15). This patches `run.drain_survey` so the failure is the one the
    branch is written for and cannot be a fence firing somewhere else.
    """
    import prospector.run as run_mod

    def boom(*_a, **_k):
        raise RuntimeError("sqlite index unreadable")

    # `Store` mkdirs `store_dir`, so this one wants a real Path rather than the daemon's str.
    cfg = _cfg(tmp_path)
    cfg.store_dir = tmp_path

    monkeypatch.setattr(run_mod, "drain_survey", boom)
    caplog.set_level(logging.ERROR, logger="prospector.scheduler.run_scheduled")

    assert rs._backlog_size(cfg) is None, "None, never 0 — 0 would release the brake"
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "logger.warning never reaches launchd.err.log, so the operator could not find out "
        "why the daemon stopped generating")

    # FALSIFIER: an intact count is still a count, and does NOT log at ERROR.
    caplog.clear()
    monkeypatch.setattr(run_mod, "drain_survey",
                        lambda *a, **k: types.SimpleNamespace(workable=[], orphaned=[],
                                                              stalled=[], unpublishable=[]))
    assert rs._backlog_size(cfg) == 0
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---------------------------------------------------- the shelf rail: unlist queue

def test_an_unreadable_unlist_queue_is_not_reported_as_an_empty_queue(tmp_path, monkeypatch):
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    cfg = types.SimpleNamespace(store_dir=str(tmp_path))

    # The real empty answer, which must keep being None (a normal tick pays nothing for it).
    assert rs._unlist_pass(cfg) is None

    _break_reads(monkeypatch, _QUEUE, OSError(5, "Input/output error"))
    broken = rs._unlist_pass(cfg)
    assert isinstance(broken, dict) and "error" in broken, (
        "'the queue is empty' and 'a KILLed pack may still be selling' must not be the same "
        "return value")
    assert broken is not None


# ---------------------------------------------------- the liveness readout

def test_an_unreadable_stderr_log_does_not_print_as_no_errors(tmp_path, monkeypatch):
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    cfg = types.SimpleNamespace(store_dir=str(tmp_path))
    log = tmp_path / "scheduler" / _ERRLOG

    assert rs._tail_errors(cfg) == [], "no log file yet is a real answer"
    log.write_text("boom one\n\nboom two\n", encoding="utf-8")
    assert rs._tail_errors(cfg) == ["boom one", "boom two"]

    _break_reads(monkeypatch, _ERRLOG, OSError(13, "Permission denied"))
    out = rs._tail_errors(cfg)
    assert out != [], "an unopenable log must not render as a clean daemon"
    assert "UNREADABLE" in out[0]


# ---------------------------------------------------- the alert state

def test_a_corrupt_alert_state_is_logged_but_an_absent_one_is_not(tmp_path, caplog):
    cfg = types.SimpleNamespace(store_dir=str(tmp_path))
    sdir = tmp_path / "scheduler"
    sdir.mkdir(parents=True, exist_ok=True)

    caplog.set_level(logging.ERROR, logger="prospector.scheduler.alerts")
    assert alerts._load_state(cfg) == {}, "no state file yet is a real answer"
    assert not caplog.records, "an absent state file is not a failure and must not page anyone"

    (sdir / "alert_state.json").write_text('{"_active": {"liveness"', encoding="utf-8")
    assert alerts._load_state(cfg) == {}
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "losing the ACTIVE alert set silently is how ALERT.txt goes green while the daemon "
        "is down")

    # FALSIFIER: a readable state is still read, not blanket-reset.
    (sdir / "alert_state.json").write_text(json.dumps({"liveness": "2026-08-15T00:00:00+00:00"}),
                                           encoding="utf-8")
    assert alerts._load_state(cfg) == {"liveness": "2026-08-15T00:00:00+00:00"}
