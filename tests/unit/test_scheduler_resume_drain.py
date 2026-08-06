"""The DEFER backlog must actually drain, and drain inside the spend rails.

THE BUG THIS ENCODES (measured 2026-08-05)

`vet --resume` has existed and worked since the moat-exhaustion handling was written. Nothing
ever called it. On 2026-08-05 `store/dossiers/` held 113 `*.defer.json` files, the oldest dated
2026-06-24, while `alerts.py` was telling the operator that provisional and deferred candidates
"auto re-vet via `vet --resume` once the moat recovers". `grep -- --resume` across the repo
returned only log strings, docstrings, the argparse flag itself, and docs — no scheduler path,
and none of the four `com.prospector.*` launchd plists. Every one of those candidates had
already been paid for through generation and prescreen and was stranded by a transient outage.

WHAT IS PINNED, AND WHY EACH ONE

1. The daemon's tick runs a resume pass. Without this the whole mechanism is a printed promise.
2. The pass is BOUNDED. `guard.evaluate()` runs once per tick, before the tick — an unbounded
   drain of a 113-item backlog would execute entirely inside one guard decision and could clear
   the daily spend cap in a single tick. That is the automated liability rail in CLAUDE.md.
3. It drains OLDEST first. At 3 per tick, newest-first ordering would starve the June backlog
   forever while churning whatever deferred most recently.
4. A failed drain must not cost the tick its generation batch.
5. The operator-facing alert copy must match the number the code actually uses.
"""
from __future__ import annotations

import argparse
import types
from pathlib import Path

import pytest

from prospector.scheduler import alerts, run_scheduled


def test_alert_copy_matches_the_number_the_daemon_uses():
    """The alert text is the only thing the operator reads; a stale copy is how this started."""
    assert alerts._RESUME_HINT == run_scheduled._RESUME_PER_TICK_DEFAULT


def test_resume_per_tick_is_bounded_and_configurable():
    cfg = types.SimpleNamespace(schedule={})
    assert run_scheduled._resume_per_tick(cfg) == run_scheduled._RESUME_PER_TICK_DEFAULT
    assert run_scheduled._resume_per_tick(types.SimpleNamespace(schedule={"resume_per_tick": 7})) == 7
    # 0 is a real value (disable the drain), not "unset".
    assert run_scheduled._resume_per_tick(types.SimpleNamespace(schedule={"resume_per_tick": 0})) == 0
    # A negative can never widen the pass into an unbounded one.
    assert run_scheduled._resume_per_tick(types.SimpleNamespace(schedule={"resume_per_tick": -5})) == 0


def test_the_tick_drains_the_backlog_before_it_generates(monkeypatch):
    """The regression is 'nothing ever calls resume'. This fails if the call is removed."""
    calls: list[tuple[str, object]] = []

    def fake_resume(cfg, *, limit=None, publish=False):
        calls.append(("resume", limit))
        return {"backlog": 113, "attempted": limit, "resumed": limit,
                "passes": 0, "kills": limit, "defers": 0}

    def fake_run_signal(_text, **kwargs):
        calls.append(("generate", kwargs.get("k")))
        return []

    monkeypatch.setattr("prospector.run.resume_deferred", fake_resume)
    monkeypatch.setattr("prospector.run.run_signal", fake_run_signal)
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)

    cfg = types.SimpleNamespace(schedule={"resume_per_tick": 3})
    out = run_scheduled._default_generate(cfg, 15)

    assert [c[0] for c in calls] == ["resume", "generate"], (
        "the backlog drain must run, and must run before generation: a backlogged candidate "
        "is already paid for through generation+prescreen, and the tick's hard deadline can "
        "force-exit mid-tick, so whatever runs second is what gets dropped"
    )
    assert calls[0][1] == 3, "the drain must be bounded — the spend guard runs once per tick"
    assert out["resumed"]["backlog"] == 113


def test_a_drain_failure_does_not_cost_the_tick_its_generation(monkeypatch):
    def boom(cfg, *, limit=None, publish=False):
        raise RuntimeError("moat still down")

    generated: list[int] = []

    def fake_run_signal(_text, **kwargs):
        generated.append(kwargs.get("k"))
        return []

    monkeypatch.setattr("prospector.run.resume_deferred", boom)
    monkeypatch.setattr("prospector.run.run_signal", fake_run_signal)
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)

    out = run_scheduled._default_generate(types.SimpleNamespace(schedule={}), 15)

    assert generated == [15], "a failed drain must not swallow the generation batch"
    assert "moat still down" in out["resumed"]["error"]


def test_disabling_the_drain_skips_it_entirely(monkeypatch):
    def must_not_run(cfg, *, limit=None, publish=False):
        raise AssertionError("resume ran despite resume_per_tick: 0")

    monkeypatch.setattr("prospector.run.resume_deferred", must_not_run)
    monkeypatch.setattr("prospector.run.run_signal", lambda _t, **k: [])
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)

    out = run_scheduled._default_generate(types.SimpleNamespace(schedule={"resume_per_tick": 0}), 5)
    assert "resumed" not in out


class _FakeStore:
    """Minimal stand-in for Store — only the two readers `_cmd_resume` uses."""

    def __init__(self, rows, on_disk=None, root=None):
        self._rows = rows
        # None => nothing is on disk (every row orphaned), which is the historical default
        # here and the path that prints "dossier JSON missing, skipping".
        self._on_disk = on_disk
        # Where a real Store would keep the drain's attempt ledger. Unused while the attempt cap
        # is off (these call sites pass cfg=None, so `drain_state.max_attempts` returns 0), but
        # `drain_survey` binds to it, so the double has to carry it.
        self._root = Path(root) if root is not None else Path("/nonexistent-fake-store")

    @property
    def root(self):
        return self._root

    def all(self, decision=None):
        return [r for r in self._rows if r["decision"] == decision]

    def provisional(self):
        return [r for r in self._rows if r.get("provisional")]

    def get(self, cid):
        if self._on_disk is None:
            return None
        return ({"candidate": {"title": cid}, "decision": "defer"}
                if cid in self._on_disk else None)

    def has_dossier(self, cid):
        """Same criterion as `get()` without the read — see `Store.has_dossier`."""
        return self.get(cid) is not None


def _stub_vetting(monkeypatch, seen):
    """Replace the real vet with a recorder, so a test asserts on WHAT WAS RE-VETTED.

    The old version of the ordering test asserted on printed output from a store where every
    row was orphaned — so it passed while proving only that the banner mentioned the oldest id,
    never that the candidate was actually put through the moat.
    """
    from prospector.models import Decision

    def fake_vet(cand, *_a, **_k):
        seen.append(cand.title)
        return types.SimpleNamespace(decision=Decision.KILL)

    monkeypatch.setattr("prospector.run.vet_candidate", fake_vet)


def test_the_bounded_pass_takes_the_oldest_first(monkeypatch):
    """At 3 per tick, newest-first would starve the June backlog forever."""
    rows = [
        {"candidate_id": "new", "decision": "defer", "created_at": "2026-08-05T09:54:00+00:00"},
        {"candidate_id": "old", "decision": "defer", "created_at": "2026-06-24T20:10:00+00:00"},
        {"candidate_id": "mid", "decision": "defer", "created_at": "2026-07-28T00:00:00+00:00"},
    ]
    from prospector import run as run_mod

    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)
    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=1, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(rows, on_disk={"new", "old", "mid"}),
    )

    assert seen == ["old"], (
        "the bounded pass must start at the oldest deferral; this backlog reaches back weeks"
    )
    assert summary["backlog"] == 3
    assert summary["attempted"] == 1
    assert summary["resumed"] == 1


def test_the_drain_outcome_lands_on_the_stream_that_is_the_daemon_log(monkeypatch, capsys):
    """The drain's trace must go to STDERR, because that is the file operators read.

    Under launchd the two streams are two different files: `com.prospector.scheduler.plist`
    sets StandardOutPath=store/scheduler/launchd.out.log and StandardErrorPath=
    store/scheduler/launchd.err.log. Measured 2026-08-05, with the live daemon (pid 8308)
    holding fd 1 open on it: launchd.out.log was 1 byte, mtime Jun 24, while launchd.err.log
    held 10,472 lines including the entire progress stream (progress.py:43 prints to stderr).
    This print exists because `logger.info` never reaches the daemon log; printing to stdout
    instead relocates the invisibility rather than fixing it.
    """
    monkeypatch.setattr("prospector.run.resume_deferred",
                        lambda cfg, *, limit=None, publish=False: {"backlog": 411, "resumed": 3})
    monkeypatch.setattr("prospector.run.run_signal", lambda _t, **k: [])
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)

    run_scheduled._default_generate(types.SimpleNamespace(schedule={"resume_per_tick": 3}), 5)
    cap = capsys.readouterr()
    assert "tick resume pass" in cap.err
    assert "tick resume pass" not in cap.out, (
        "stdout is launchd.out.log, a file no probe and no operator reads"
    )

    def boom(cfg, *, limit=None, publish=False):
        raise RuntimeError("moat still down")

    monkeypatch.setattr("prospector.run.resume_deferred", boom)
    run_scheduled._default_generate(types.SimpleNamespace(schedule={"resume_per_tick": 3}), 5)
    cap = capsys.readouterr()
    assert "tick resume pass FAILED" in cap.err
    assert "tick resume pass FAILED" not in cap.out


def test_a_zero_limit_drains_nothing_rather_than_everything(monkeypatch):
    """`limit=0` must disable the pass, not run it unbounded.

    `if limit is not None and limit > 0` let a 0 fall through unsliced, so a single call
    would have re-vetted the whole backlog (411 items on 2026-08-05) inside one spend-guard
    decision — the rail evaluates once per tick, before the tick.
    """
    from prospector import run as run_mod

    rows = [{"candidate_id": f"c{i}", "decision": "defer",
             "created_at": f"2026-07-{i + 1:02d}T00:00:00+00:00"} for i in range(5)]
    # ON DISK, all five. Orphaned rows are excluded from the backlog before the `limit` branch is
    # reached (`run.drain_survey`), so a store where nothing is on disk would take the "nothing
    # workable" early return and pass this test without ever evaluating limit=0 — the vacuous form
    # of exactly the assertion being made here.
    ids = {r["candidate_id"] for r in rows}
    # And with the rows now readable, the unbounded leg below would put all five through the real
    # moat. It used to be the orphaning that stopped it, which is a test passing for the wrong
    # reason twice over.
    _stub_vetting(monkeypatch, [])

    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=0, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None, store=_FakeStore(rows, on_disk=ids),
    )
    assert summary == {"backlog": 5, "attempted": 0, "resumed": 0,
                       "passes": 0, "kills": 0, "defers": 0}

    # None still means unbounded — that is what `vet --resume` has always done on the CLI.
    unbounded = run_mod._cmd_resume(
        argparse.Namespace(limit=None, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None, store=_FakeStore(rows, on_disk=ids),
    )
    assert unbounded["attempted"] == 5


def test_an_empty_backlog_is_reported_not_crashed():
    from prospector import run as run_mod

    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=3, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None, store=_FakeStore([]),
    )
    assert summary == {"backlog": 0, "attempted": 0, "resumed": 0,
                       "passes": 0, "kills": 0, "defers": 0}


def test_orphaned_rows_do_not_consume_the_bounded_pass(monkeypatch):
    """Rows in the index with no dossier JSON must not eat the drain's budget every tick.

    MEASURED on the live store 2026-08-06, on the first tick that ever ran the drain:

        ticks.jsonl -> 'resumed': {'backlog': 406, 'attempted': 3, 'resumed': 0, ...}
        backlog 406, orphaned 46, leading unbroken run of orphans 45 (2026-06-14..2026-06-21)

    The pass always takes the OLDEST rows, so it re-selected the same three unreadable
    2026-06-14 rows every tick: `attempted: 3, resumed: 0`, indefinitely. At 3 per tick and a
    2h cadence the leading run alone is 15 ticks (~1.2 days) of no-op drains before the pass
    reaches its first re-vettable candidate.
    """
    from prospector import run as run_mod

    # 4 orphans (oldest), then 3 real rows — exactly the live shape, scaled down.
    rows = [{"candidate_id": f"orphan{i}", "decision": "defer",
             "created_at": f"2026-06-1{i}T00:00:00+00:00"} for i in range(4)]
    rows += [{"candidate_id": f"real{i}", "decision": "defer",
              "created_at": f"2026-07-0{i}T00:00:00+00:00"} for i in range(3)]
    store = _FakeStore(rows, on_disk={"real0", "real1", "real2"})

    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)
    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=3, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None, store=store,
    )

    assert summary["attempted"] == 3, (
        "the bound must be spent on rows that can actually be re-vetted; before this fix the "
        "three oldest orphans consumed the entire pass and resumed nothing"
    )
    assert summary["backlog"] == 3, (
        "`backlog` is the count the scheduler's brake compares against `schedule.backlog_cap` and "
        "then waits to see fall, so it must be the WORKABLE population (3), not the raw index "
        "population (7). Reporting 7 here is what let the brake engage on a number that included "
        "4 rows no drain pass could ever subtract — a generation freeze with no exit."
    )
    assert summary["orphaned"] == 4, (
        "an index row with nothing on disk is a store inconsistency the operator must see, "
        "not a slot the drain silently wastes"
    )
    assert seen == ["real0", "real1", "real2"], "and the pass must reach the real backlog"


def test_the_drain_reports_its_cost_against_the_real_ledger(tmp_path, monkeypatch):
    """The one caller that spends money unwatched was the one with no audit log path.

    `resume_deferred` called `_cmd_resume` without `log_path`, so its last line resolved to
    `costs_report('')` and printed "No audit log at ." on every daemon tick. The pass re-vets
    real candidates against real providers; the operator must get the cost line for it.
    """
    from prospector import run as run_mod

    seen: dict = {}

    def fake_cmd_resume(args, cfg, op, fast_op, search, store, log_path=None):
        seen["log_path"] = log_path
        return {"backlog": 0, "attempted": 0, "resumed": 0,
                "passes": 0, "kills": 0, "defers": 0}

    monkeypatch.setattr(run_mod, "_cmd_resume", fake_cmd_resume)
    monkeypatch.setattr(run_mod, "_make_search", lambda *a, **k: None)
    monkeypatch.setattr(run_mod, "Store", lambda cfg: None)
    monkeypatch.setattr("prospector.operator.make_operator", lambda *a, **k: None)

    cfg = types.SimpleNamespace(store_dir=tmp_path)
    run_mod.resume_deferred(cfg, limit=3)

    assert seen["log_path"] == tmp_path / "prospector.jsonl", (
        "the drain must read the same ledger every other command reports from"
    )


def test_the_drain_returns_its_cost_because_its_stdout_is_unread(monkeypatch):
    """A printed cost report is not a reported cost report.

    Passing the real ledger fixed WHAT gets rendered; it did not fix WHERE. Under launchd the
    daemon's fd 1 is store/scheduler/launchd.out.log (measured on pid 48771 with lsof) — a file
    nothing reads, and one Python block-buffers, so the 00:58 tick's report was still unflushed
    in the process. The return value is the stream that survives: run_scheduled.py:190 logs it
    to stderr and it lands in the tick row, which the state probe reads.
    """
    from prospector import run as run_mod
    from prospector import telemetry
    from prospector.models import Decision

    telemetry.reset_usage()
    rows = [{"candidate_id": "live", "decision": "defer",
             "created_at": "2026-07-01T00:00:00+00:00"}]

    def vet_that_spends(cand, *_a, **_k):
        telemetry.record_usage(provider="deepseek", input_tokens=1_000_000,
                                 output_tokens=1_000_000)
        return types.SimpleNamespace(decision=Decision.KILL)

    monkeypatch.setattr("prospector.run.vet_candidate", vet_that_spends)

    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=1, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(rows, on_disk={"live"}),
    )

    assert "metered_usd" in summary, "the tick row is the only channel the operator actually reads"
    # 1M in @ $0.27 + 1M out @ $1.10 (telemetry.PRICING['deepseek']).
    assert summary["metered_usd"] == pytest.approx(1.37), (
        "and it must be the spend this pass actually made, not a placeholder"
    )


def test_the_drains_number_is_billed_money_only_and_says_so(monkeypatch):
    """A drain on the subscription CLI is not free, so the key must not be called `cost_usd`.

    The moat's primary brain is claude_cli, whose burn is subscription-equivalent and is
    deliberately NOT priced (see the metered/subscription split at scheduler/guard.py:21-45).
    So a real drain reports 0.00 here — true for billed money, and actively misleading under a
    name like `cost_usd`. The second leg rides in the same tick row as `today_subscription_usd`.
    """
    from prospector import run as run_mod
    from prospector import telemetry
    from prospector.models import Decision

    telemetry.reset_usage()
    rows = [{"candidate_id": "live", "decision": "defer",
             "created_at": "2026-07-01T00:00:00+00:00"}]

    def vet_on_the_subscription(cand, *_a, **_k):
        # Exactly claude_cli._record_claude_usage's call shape.
        telemetry.record_usage(input_tokens=900_000, output_tokens=400_000,
                               web=True, provider="claude_cli")
        return types.SimpleNamespace(decision=Decision.KILL)

    monkeypatch.setattr("prospector.run.vet_candidate", vet_on_the_subscription)

    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=1, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(rows, on_disk={"live"}),
    )

    assert "cost_usd" not in summary, (
        "0.00 under the name `cost_usd` reads as 'the drain was free'; it spent subscription"
    )
    assert summary["metered_usd"] == 0.0, "no billed money was spent — that part is true"
    assert "claude_cli" in telemetry.get_usage_summary()["by_provider"], (
        "and the moat's primary brain must be attributable, not filed under 'unknown'"
    )


def test_pricing_claude_cli_would_arm_the_metered_cap(monkeypatch):
    """Guard on the fix above: naming the provider must never make it billable.

    record_usage emits an `event: "spend"` row only when `cost > 0` (telemetry.py:227), and
    those rows are what scheduler/guard.py counts against `daily_cap_usd`. guard.py:36-39
    measured that folding subscription burn into that cap "would halt the daemon within about
    two hours of every day for spend that is never invoiced". So claude_cli must stay unpriced.
    """
    from prospector import telemetry

    assert "claude_cli" not in telemetry.PRICING, (
        "pricing claude_cli turns subscription burn into billed spend and stops the daemon"
    )

    records: list = []
    monkeypatch.setattr(telemetry.logger, "info",
                        lambda msg, *a, **k: records.append((msg, k.get("extra") or {})))
    telemetry.reset_usage()
    telemetry.record_usage(input_tokens=900_000, output_tokens=400_000,
                           web=True, provider="claude_cli")

    assert not [r for r in records if (r[1] or {}).get("event") == "spend"], (
        "a spend event here would be counted as billed money by the daily cap"
    )


def test_reset_usage_clears_the_cost_a_long_lived_daemon_reports(monkeypatch):
    """`reset_usage` cleared `_USAGE` only, and cost is computed from `_USAGE_BY_PROVIDER`.

    A CLI process dies after one run so nothing showed. The daemon does not: it calls
    reset_usage() per tick (run.py:1235) and would have reported cost cumulative since process
    start, which grows forever. Without the fix the second assert reads ~$1.37, not 0.
    """
    from prospector import telemetry

    telemetry.reset_usage()
    telemetry.record_usage(provider="deepseek", input_tokens=1_000_000,
                                 output_tokens=1_000_000)
    assert telemetry.get_usage_summary()["total_cost_usd"] > 0, "precondition: spend recorded"

    telemetry.reset_usage()

    after = telemetry.get_usage_summary()
    assert after["total_cost_usd"] == 0.0, "a reset ledger must report a reset cost"
    assert after["by_provider"] == {}, "and must not still name the provider it forgot"


def test_a_tombstoned_row_is_not_backlog(monkeypatch):
    """Reporting orphans made the waste visible; tombstoning takes it out of the count.

    `orphaned: 45` stopped the drain wasting its budget, but the operator was still told the
    backlog was 406 when 45 of those rows could never be re-vetted — so the "~11d to drain"
    estimate was a fiction, and every tick re-scanned rows already known to be dead. Once
    reconciled (scripts/reconcile_orphan_index.py) they are neither backlog nor orphans:
    they are history.
    """
    from prospector import run as run_mod

    rows = [{"candidate_id": "dead", "decision": "defer", "tombstone": "dossier_missing",
             "created_at": "2026-06-14T00:00:00+00:00"},
            {"candidate_id": "live", "decision": "defer",
             "created_at": "2026-07-01T00:00:00+00:00"},
            {"candidate_id": "deadprov", "decision": "kill", "provisional": 1,
             "tombstone": "quarantined_ungrounded", "created_at": "2026-06-21T00:00:00+00:00"}]

    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)
    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=3, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(rows, on_disk={"live"}),
    )

    assert summary["backlog"] == 1, "a tombstoned row is history, not work awaiting the moat"
    assert seen == ["live"]
    assert "orphaned" not in summary, (
        "a reconciled row must not be re-counted as an orphan every tick either"
    )


def test_orphans_are_still_reported_when_everything_is_orphaned():
    from prospector import run as run_mod

    rows = [{"candidate_id": f"o{i}", "decision": "defer",
             "created_at": f"2026-06-1{i}T00:00:00+00:00"} for i in range(3)]
    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=2, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None, store=_FakeStore(rows),
    )
    assert summary["attempted"] == 0
    assert summary["orphaned"] == 3


# ---------------------------------------------------------------------------
# `--only`: targeting a backlog population
#
# THE MEASUREMENT THAT FORCED THIS. On the live index 2026-08-06 the drainable backlog was
# 351 rows: 166 provisional KILL, 108 DEFER, 72 provisional PASS, 5 provisional DEFER. Of the
# OLDEST 100 — the rows a bounded `--limit` pass actually takes — 51 were provisional KILLs,
# 47 DEFERs, 1 provisional DEFER, and exactly ONE was a provisional PASS. Only a provisional
# PASS can become sellable inventory, because publishing is gated on `not dossier.provisional`
# (run.py:422). So the population worth draining first was structurally unreachable through
# `--limit` alone.
# ---------------------------------------------------------------------------

def _live_shaped_rows():
    """A miniature of the measured backlog: old provisional KILLs and DEFERs, recent passes."""
    return [
        {"candidate_id": "k1", "decision": "kill", "provisional": 1,
         "created_at": "2026-06-16T09:00:00+00:00"},
        {"candidate_id": "d1", "decision": "defer", "provisional": 0,
         "created_at": "2026-06-24T20:10:00+00:00"},
        {"candidate_id": "k2", "decision": "kill", "provisional": 1,
         "created_at": "2026-06-25T09:00:00+00:00"},
        {"candidate_id": "p1", "decision": "pass", "provisional": 1,
         "created_at": "2026-07-10T12:00:00+00:00"},
        {"candidate_id": "p2", "decision": "pass", "provisional": 1,
         "created_at": "2026-08-06T03:31:00+00:00"},
    ]


def _resume(monkeypatch, seen, **ns):
    from prospector import run as run_mod
    rows = _live_shaped_rows()
    _stub_vetting(monkeypatch, seen)
    kwargs = {"limit": None, "publish": False, "board": None}
    kwargs.update(ns)
    return run_mod._cmd_resume(
        argparse.Namespace(**kwargs), cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(rows, on_disk={r["candidate_id"] for r in rows}),
    )


def test_a_bounded_pass_without_only_never_reaches_a_provisional_pass(monkeypatch):
    """The bug, stated as a test: oldest-first spends the whole bound on kills and defers."""
    seen: list[str] = []
    _resume(monkeypatch, seen, limit=3)
    assert seen == ["k1", "d1", "k2"]
    assert not any(t.startswith("p") for t in seen), (
        "a bounded drain must be shown NOT to reach the only sellable population — this is "
        "the measured 1-in-100 problem in miniature"
    )


def test_only_provisional_pass_drains_exactly_that_population_oldest_first(monkeypatch):
    seen: list[str] = []
    summary = _resume(monkeypatch, seen, only="provisional-pass")
    assert seen == ["p1", "p2"], "must take both provisional PASSes, oldest first"
    assert summary["backlog"] == 5, (
        "backlog keeps reporting the WHOLE drainable population, so the operator still sees "
        "the true size next to the filtered count"
    )
    assert summary["attempted"] == 2


def test_only_composes_with_limit(monkeypatch):
    seen: list[str] = []
    _resume(monkeypatch, seen, only="provisional-pass", limit=1)
    assert seen == ["p1"]


def test_the_other_selectors_pick_their_own_population(monkeypatch):
    for only, expected in (
        ("defer", ["d1"]),
        ("provisional", ["k1", "k2", "p1", "p2"]),
        ("all", ["k1", "d1", "k2", "p1", "p2"]),
    ):
        seen: list[str] = []
        _resume(monkeypatch, seen, only=only)
        assert seen == expected, f"--only {only}"


def test_the_daemon_namespace_has_no_only_attribute_and_keeps_draining_everything(monkeypatch):
    """`resume_deferred` builds its Namespace by hand (run.py) — it must not need updating.

    A `getattr(args, "only")` without a default would raise AttributeError on every tick;
    a wrong default would silently narrow the daemon's drain.
    """
    from prospector import run as run_mod
    rows = _live_shaped_rows()
    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)
    run_mod._cmd_resume(
        argparse.Namespace(limit=None, publish=False, board=None, fixtures=None, search=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(rows, on_disk={r["candidate_id"] for r in rows}),
    )
    assert seen == ["k1", "d1", "k2", "p1", "p2"]


def test_an_unknown_selector_exits_rather_than_draining_everything(monkeypatch):
    """Failing open here would re-vet the whole backlog under a typo."""
    seen: list[str] = []
    with pytest.raises(SystemExit) as exc:
        _resume(monkeypatch, seen, only="provisional_pass")   # underscore, not hyphen
    assert exc.value.code == 2
    assert seen == []


def test_a_selector_matching_nothing_reports_instead_of_draining_everything(monkeypatch):
    from prospector import run as run_mod
    rows = [{"candidate_id": "d1", "decision": "defer", "provisional": 0,
             "created_at": "2026-06-24T20:10:00+00:00"}]
    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)
    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=None, publish=False, board=None, only="provisional-pass"),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(rows, on_disk={"d1"}),
    )
    assert seen == []
    assert summary["attempted"] == 0
    assert summary["backlog"] == 1


def test_the_documented_resume_command_can_actually_be_invoked(monkeypatch, capsys):
    """RUN.md:97 documents `vet --resume`, and `--title required=True` made it exit 2.

    The daemon calls `resume_deferred()` in-process, so the parser was never on its path and
    the documented operator command was dead without anything noticing. Asserted at the
    argparse layer, because that is where it died.
    """
    from prospector import run as run_mod
    parser = run_mod._build_parser() if hasattr(run_mod, "_build_parser") else None
    if parser is None:                       # parser is built inline in main()
        import sys as _sys
        monkeypatch.setattr(_sys, "argv", ["prospector", "vet", "--resume"])
        called = {}
        monkeypatch.setattr(run_mod, "_cmd_vet", lambda *a, **k: called.setdefault("ok", True))
        run_mod.main()
        assert called.get("ok"), "`vet --resume` must reach _cmd_vet, not die in argparse"
        return
    args = parser.parse_args(["vet", "--resume"])
    assert args.resume is True and args.title is None


def test_a_single_candidate_vet_without_a_title_is_still_a_usage_error(monkeypatch):
    """Relaxing argparse must not let a real vet run with no title."""
    import sys as _sys
    from prospector import run as run_mod
    monkeypatch.setattr(_sys, "argv", ["prospector", "vet"])
    monkeypatch.setattr(run_mod, "_cmd_vet", lambda *a, **k: pytest.fail("must not dispatch"))
    with pytest.raises(SystemExit) as exc:
        run_mod.main()
    assert exc.value.code == 2
