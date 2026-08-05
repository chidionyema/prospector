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

    def __init__(self, rows):
        self._rows = rows

    def all(self, decision=None):
        return [r for r in self._rows if r["decision"] == decision]

    def provisional(self):
        return [r for r in self._rows if r.get("provisional")]

    def get(self, cid):
        return None  # forces the "dossier JSON missing, skipping" path — no vetting happens


def test_the_bounded_pass_takes_the_oldest_first(capsys):
    """At 3 per tick, newest-first would starve the June backlog forever."""
    rows = [
        {"candidate_id": "new", "decision": "defer", "created_at": "2026-08-05T09:54:00+00:00"},
        {"candidate_id": "old", "decision": "defer", "created_at": "2026-06-24T20:10:00+00:00"},
        {"candidate_id": "mid", "decision": "defer", "created_at": "2026-07-28T00:00:00+00:00"},
    ]
    from prospector import run as run_mod

    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=1, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None, store=_FakeStore(rows),
    )

    out = capsys.readouterr().out
    assert "old" in out and "new" not in out, (
        "the bounded pass must start at the oldest deferral; this backlog reaches back weeks"
    )
    assert summary["backlog"] == 3
    assert summary["attempted"] == 1


def test_an_empty_backlog_is_reported_not_crashed():
    from prospector import run as run_mod

    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=3, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None, store=_FakeStore([]),
    )
    assert summary == {"backlog": 0, "attempted": 0, "resumed": 0,
                       "passes": 0, "kills": 0, "defers": 0}
