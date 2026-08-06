"""A self-releasing brake must count only rows a drain can actually move.

`schedule.backlog_cap` freezes generation while the drainable backlog is at or above the cap, and
releases itself the moment the count falls back under — no human, no PAUSE file
(`scheduler/run_scheduled._generation_suppressed`). That self-release is only real if every
counted row is a row a drain pass can move. Two populations cannot be moved:

  * ORPHANED — an index row with no dossier JSON behind it. Measured on the live store
    2026-08-06: 46 of 406, with a leading unbroken run of 45 dated 2026-06-14..06-21. The drain
    can only print "dossier JSON missing, skipping".
  * STALLED — a row that has been fully re-vetted `schedule.max_resume_attempts` times and comes
    back drainable every time.

Counting either one holds the brake engaged on a number nothing can reduce: a generation freeze
that outlives its own reason, waiting on a count that cannot fall, with nothing anywhere naming
the rows responsible. Every test below states the deadlock as well as the fix.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import types

import pytest

from prospector import drain_state
from prospector import run as run_mod
from prospector.models import Decision
from prospector.scheduler import run_scheduled as rs
from prospector.store import Store


def _cfg(tmp_path, **schedule):
    sched = {"batch_size": 15}
    sched.update(schedule)
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule=sched,
        operator=["claude_cli"],
    )


def _store_with(tmp_path, rows):
    """A REAL Store (not a double) whose index holds `rows` = (cid, decision, provisional, on_disk).

    Real, because the orphan predicate is "the index row's path does not exist on disk" and that is
    the disagreement between SQLite and the filesystem the fix turns on. A double cannot fail the
    way the live store did.
    """
    store = Store(types.SimpleNamespace(store_dir=tmp_path))
    with sqlite3.connect(store.db) as conn:
        for i, (cid, decision, prov, on_disk) in enumerate(rows):
            p = tmp_path / "dossiers" / f"{cid}.json"
            if on_disk:
                p.write_text(json.dumps({"candidate": {"title": cid}, "decision": decision}),
                             encoding="utf-8")
            conn.execute(
                "INSERT INTO dossiers (candidate_id, title, decision, provisional, created_at,"
                " path) VALUES (?,?,?,?,?,?)",
                (cid, cid, decision, 1 if prov else 0, f"2026-06-{i + 10:02d}T00:00:00+00:00",
                 str(p)))
    return store


def _raw_population(store):
    """The pre-fix definition of "backlog": every untombstoned defer + provisional row.

    This is what `drainable()` returned before 2026-08-06 and what the brake therefore counted.
    Kept here so each test can assert the counterfactual — that the brake WOULD have deadlocked —
    rather than only asserting the new number.
    """
    deferred = [r for r in store.all(decision="defer") if not r.get("tombstone")]
    prov = [r for r in store.provisional() if not r.get("tombstone")]
    seen = {r.get("candidate_id") for r in deferred}
    return deferred + [r for r in prov if r.get("candidate_id") not in seen]


# ---------------------------------------------------------------------------
# Orphans: counted by the brake, unmovable by the drain
# ---------------------------------------------------------------------------

def test_orphaned_rows_are_excluded_from_the_count_the_brake_reads(tmp_path):
    store = _store_with(tmp_path, [
        ("live1", "defer", False, True),
        ("gone1", "defer", False, False),
        ("gone2", "kill", True, False),
    ])
    survey = run_mod.drain_survey(store)
    assert [r["candidate_id"] for r in survey.workable] == ["live1"]
    assert sorted(survey.orphaned) == ["gone1", "gone2"]
    assert len(_raw_population(store)) == 3, (
        "the pre-fix definition counted all three — 2 of them rows no drain pass can move"
    )


def test_the_brake_would_deadlock_forever_if_orphans_were_counted(tmp_path):
    """The deadlock in miniature: cap 3, three rows, none of them workable.

    Pre-fix the brake counted 3 >= 3 and suppressed generation on every tick, while the drain
    could resolve none of them — so the count could never fall and the freeze could never lift.
    """
    store = _store_with(tmp_path, [(f"gone{i}", "defer", False, False) for i in range(3)])
    cfg = _cfg(tmp_path, backlog_cap=3)

    assert len(_raw_population(store)) >= 3, "counterfactual: the old count sat at/above the cap"
    assert rs._backlog_size(cfg) == 0
    assert rs._generation_suppressed(cfg) == "", (
        "with the unmovable rows excluded the brake must release itself and let the tick generate"
    )


def test_a_real_backlog_still_engages_the_brake(tmp_path):
    """The exclusions must not defang the brake — a workable backlog still stops generation."""
    store = _store_with(tmp_path, [(f"live{i}", "defer", False, True) for i in range(4)])
    cfg = _cfg(tmp_path, backlog_cap=3)
    assert len(store.all(decision="defer")) == 4
    reason = rs._generation_suppressed(cfg)
    assert "backlog brake" in reason and "4 drainable rows" in reason


def test_the_brake_names_the_rows_it_set_aside(tmp_path, capsys):
    """`logger.warning` never reaches launchd.err.log (measured 2026-08-05), so this must print.

    A brake that waits on a count has to be able to tell an operator which rows are holding it,
    or the freeze is unexplainable from the daemon log.
    """
    store = _store_with(tmp_path, [("live", "defer", False, True), ("gone", "defer", False, False)])
    assert rs._backlog_size(_cfg(tmp_path, backlog_cap=99)) == 1
    err = capsys.readouterr().err
    assert "1 orphaned" in err and "0 stalled" in err
    assert str(drain_state.ledger_path(tmp_path)) in err, "the reversal switch must be named"


# ---------------------------------------------------------------------------
# The per-row attempt cap
# ---------------------------------------------------------------------------

def test_a_row_stops_being_counted_once_it_exhausts_its_attempts(tmp_path):
    store = _store_with(tmp_path, [("stuck", "defer", False, True), ("fresh", "defer", False, True)])
    assert len(run_mod.drainable(store, max_attempts=2)) == 2

    drain_state.record_unresolved(tmp_path, "stuck")
    assert len(run_mod.drainable(store, max_attempts=2)) == 2, "one attempt is not the budget"

    drain_state.record_unresolved(tmp_path, "stuck")
    survey = run_mod.drain_survey(store, max_attempts=2)
    assert [r["candidate_id"] for r in survey.workable] == ["fresh"]
    assert survey.stalled == ["stuck"]


def test_the_cap_is_off_at_zero_so_nothing_changes_by_default(tmp_path):
    store = _store_with(tmp_path, [("stuck", "defer", False, True)])
    for _ in range(50):
        drain_state.record_unresolved(tmp_path, "stuck")
    assert len(run_mod.drainable(store, max_attempts=0)) == 1
    assert drain_state.max_attempts(_cfg(tmp_path, max_resume_attempts=0)) == 0
    assert drain_state.max_attempts(None) == 0, "no config must mean uncapped, not crash"


def test_the_cap_comes_from_config_and_survives_a_bad_value(tmp_path):
    assert drain_state.max_attempts(_cfg(tmp_path, max_resume_attempts=7)) == 7
    assert drain_state.max_attempts(_cfg(tmp_path)) == drain_state.DEFAULT_MAX_ATTEMPTS
    assert drain_state.max_attempts(_cfg(tmp_path, max_resume_attempts="banana")) == 0, (
        "an unparseable cap must disable the cap, never abandon every row"
    )


def test_a_resolved_row_gets_its_whole_budget_back(tmp_path):
    """Otherwise a row that defers 4 times in June, resolves, then defers again in August starts
    one attempt from being abandoned on a history that no longer describes it."""
    drain_state.record_unresolved(tmp_path, "cid")
    drain_state.record_unresolved(tmp_path, "cid")
    assert drain_state.attempts_for(tmp_path, "cid") == 2
    drain_state.forget(tmp_path, "cid")
    assert drain_state.attempts_for(tmp_path, "cid") == 0


def test_a_corrupt_ledger_gives_every_row_its_budget_back(tmp_path):
    """Bookkeeping must not be able to stop a drain, and must fail toward WORKING rows."""
    p = drain_state.ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    store = _store_with(tmp_path, [("live", "defer", False, True)])
    assert drain_state.load(tmp_path) == {}
    assert len(run_mod.drainable(store, max_attempts=1)) == 1


def test_the_ledger_write_is_atomic_and_leaves_no_temp_behind(tmp_path):
    drain_state.record_unresolved(tmp_path, "cid")
    scheduler_dir = drain_state.ledger_path(tmp_path).parent
    assert not list(scheduler_dir.glob("*.tmp")), "a torn ledger reads as 'nothing tried'"
    assert json.loads(drain_state.ledger_path(tmp_path).read_text()) == {"cid": 1}


# ---------------------------------------------------------------------------
# What the drain records — and what it must NOT
# ---------------------------------------------------------------------------

def _run_drain(tmp_path, monkeypatch, store, verdicts, *, blind="", **ns):
    """Drive `_cmd_resume` with a stubbed moat that returns `verdicts[title]`."""
    monkeypatch.setattr("prospector.health.moat_blind_reason", lambda cfg: blind)

    def fake_vet(cand, *_a, **_k):
        return types.SimpleNamespace(**verdicts[cand.title])

    monkeypatch.setattr("prospector.run.vet_candidate", fake_vet)
    kwargs = {"limit": None, "publish": False, "board": None}
    kwargs.update(ns)
    return run_mod._cmd_resume(argparse.Namespace(**kwargs), cfg=_cfg(tmp_path, **{}),
                              op=None, fast_op=None, search=None, store=store)


def test_an_unresolved_revet_is_counted_and_a_resolved_one_is_not(tmp_path, monkeypatch):
    store = _store_with(tmp_path, [("d", "defer", False, True), ("k", "defer", False, True)])
    summary = _run_drain(tmp_path, monkeypatch, store, {
        "d": {"decision": Decision.DEFER, "provisional": False},
        "k": {"decision": Decision.KILL, "provisional": False},
    })
    assert summary["attempted"] == 2
    assert drain_state.attempts_for(tmp_path, "d") == 1, "still drainable — it must count"
    assert drain_state.attempts_for(tmp_path, "k") == 0, "resolved — it must not"


def test_a_provisional_reruling_still_counts_because_the_row_stays_drainable(tmp_path, monkeypatch):
    """A provisional PASS can never publish, so it is still backlog. If it did not count, a row
    that keeps coming back provisional would hold the brake engaged forever."""
    store = _store_with(tmp_path, [("p", "defer", False, True)])
    _run_drain(tmp_path, monkeypatch, store,
               {"p": {"decision": Decision.PASS, "provisional": True}})
    assert drain_state.attempts_for(tmp_path, "p") == 1


def test_a_blind_moat_never_spends_a_rows_budget(tmp_path, monkeypatch):
    """The backlog exists BECAUSE of outages. If an outage burned attempts, a long enough moat
    outage would abandon the entire backlog without one real verdict being reached."""
    store = _store_with(tmp_path, [("d", "defer", False, True)])
    summary = _run_drain(tmp_path, monkeypatch, store, {}, blind="claude_cli is dead for 3033s")
    assert summary["attempted"] == 0 and "skipped" in summary
    assert drain_state.attempts_for(tmp_path, "d") == 0


def test_a_provider_exhaustion_mid_pass_never_spends_a_budget(tmp_path, monkeypatch):
    """Same rule for the moat dying DURING the pass: the loop breaks, and the row it broke on
    keeps its full budget because no verdict was ever reached for it."""
    from prospector.errors import ProviderExhaustedError

    store = _store_with(tmp_path, [("a", "defer", False, True), ("b", "defer", False, True)])
    monkeypatch.setattr("prospector.health.moat_blind_reason", lambda cfg: "")

    def fake_vet(cand, *_a, **_k):
        raise ProviderExhaustedError("moat gone mid-pass")

    monkeypatch.setattr("prospector.run.vet_candidate", fake_vet)
    run_mod._cmd_resume(argparse.Namespace(limit=None, publish=False, board=None),
                        cfg=_cfg(tmp_path), op=None, fast_op=None, search=None, store=store)
    assert drain_state.load(tmp_path) == {}


# ---------------------------------------------------------------------------
# Visibility: an exclusion nobody can see is a silent cap
# ---------------------------------------------------------------------------

def test_the_exclusion_counts_reach_the_tick_row_on_every_return_path(tmp_path, monkeypatch):
    """Pre-fix `orphaned` was attached on ONE return path — the one that ran a pass. A tick that
    excluded every row returned a clean `attempted: 0` and named no reason for it."""
    store = _store_with(tmp_path, [("gone", "defer", False, False), ("stuck", "defer", False, True)])
    for _ in range(drain_state.DEFAULT_MAX_ATTEMPTS):
        drain_state.record_unresolved(tmp_path, "stuck")

    # Nothing workable is left, so this takes the earliest return path of all.
    summary = _run_drain(tmp_path, monkeypatch, store, {})
    assert summary["attempted"] == 0
    assert summary["orphaned"] == 1
    assert summary["stalled"] == 1

    # ...and so does the blind-moat path, which returns before any row is looked at.
    blind = _run_drain(tmp_path, monkeypatch, store, {}, blind="moat blind")
    assert blind["orphaned"] == 1 and blind["stalled"] == 1


def test_the_drain_prints_how_to_undo_the_give_up(tmp_path, monkeypatch, capsys):
    store = _store_with(tmp_path, [("stuck", "defer", False, True), ("live", "defer", False, True)])
    for _ in range(drain_state.DEFAULT_MAX_ATTEMPTS):
        drain_state.record_unresolved(tmp_path, "stuck")
    _run_drain(tmp_path, monkeypatch, store,
               {"live": {"decision": Decision.KILL, "provisional": False}})
    out = capsys.readouterr().out
    assert "1 stalled" in out
    assert f"rm {drain_state.ledger_path(tmp_path)}" in out, (
        "a cap the operator cannot reverse is the silent truncation the rules forbid"
    )


def test_has_dossier_matches_get_without_reading_the_file(tmp_path):
    """One predicate, two implementations would drift. `has_dossier` is the cheap half of `get`:
    the brake surveys ~340 rows per tick and must not read and parse every dossier to do it."""
    store = _store_with(tmp_path, [("live", "defer", False, True), ("gone", "defer", False, False)])
    for cid in ("live", "gone", "never-indexed", ""):
        assert store.has_dossier(cid) == (store.get(cid) is not None), cid
