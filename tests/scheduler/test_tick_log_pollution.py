"""ticks.jsonl is written by more than one program, and the alerts on top of it must survive that.

MEASURED 2026-08-06, by watching the live file and dumping `ps` on every append::

    32982  hermes_cli.main gateway run --replace
     └ 37045  ~/.hermes/scripts/otto-dispatch.py
       └ 37094  bash ~/.hermes/scripts/prospector-run.sh
         └ 37096  timeout 110 uv run --directory ~/Documents/code/prospector \
                      python -m prospector.scheduler.run_scheduled --once --dry-run

A driver in the ADJACENT estate fires one-shot dry runs into this checkout's production tick log.
Measured rate: 25 rows in 0.42 h = **59.6 rows/hour**. The daemon's own real ticks, over the same
log, are ~2.5 h apart (2026-08-05 14:58 → 17:31 → 20:04 → 23:06).

What that did to the alert built on it::

    $ last 50 rows of store/scheduler/ticks.jsonl
      49 skipped (dry-run / not-allowed), 1 REAL

`_trailing_barren_count` took `readlines()[-50:]` and then SKIPPED dry rows, so its 50-line window
held one real tick. Two consecutive real ticks are ~150 junk rows apart, so they could never both
be inside it, the streak could never reach 2, and `barren_streak` could never fire. That is worse
than a missing alert — a barren factory reads as an all-clear.

These tests pin the three seams that pollution touches: the streak must count real TICKS not
lines, the aggregate must not report another program's probes as our ticks, and every row must
name the process that wrote it so the next person does not have to catch it with `ps`.
"""
from __future__ import annotations

import json
import types

import pytest

from prospector.audit import run_id as audit_run_id
from prospector.scheduler import run_scheduled as rs


@pytest.fixture()
def cfg(tmp_path):
    return types.SimpleNamespace(store_dir=str(tmp_path))


def _real(dossiers: int = 0, *, error=None) -> dict:
    return {"ts": "2026-08-06T00:00:00+00:00", "allowed": True, "dry_run": False,
            "error": error, "result": {"dossiers": dossiers, "passes": 0}}


def _dry() -> dict:
    """Exactly the shape the external driver appends: allowed, dry, no result."""
    return {"ts": "2026-08-06T00:00:00+00:00", "allowed": True, "dry_run": True,
            "reason": "ok: $0.5719 of $20.00 spent today", "batch_size": 15, "result": None}


def _write(cfg, rows):
    for r in rows:
        rs._append_tick(cfg, r)


# ── the streak must count ticks, not lines ──────────────────────────────────

def test_a_flood_of_dry_runs_cannot_hide_a_barren_streak(cfg):
    """The live shape: barren real ticks separated by ~150 external dry rows each.

    Under the old 50-LINE window this returns 0 and the factory looks fine while producing
    nothing.
    """
    rows = []
    for _ in range(4):
        rows.append(_real(dossiers=0))
        rows.extend(_dry() for _ in range(150))
    _write(cfg, rows)

    # 4 barren real ticks written; the last one is "the current tick" and is excluded.
    assert rs._trailing_barren_count(cfg) == 3, (
        "the barren streak was diluted to nothing by another program's dry runs"
    )


def test_the_streak_still_breaks_on_a_productive_tick_across_the_flood(cfg):
    rows = [_real(dossiers=7)]
    rows += [x for _ in range(2) for x in ([_real(dossiers=0)] + [_dry()] * 150)]
    rows.append(_real(dossiers=0))
    _write(cfg, rows)
    assert rs._trailing_barren_count(cfg) == 2, (
        "widening the window must not make the streak run past a tick that produced dossiers"
    )


def test_an_errored_tick_still_breaks_the_streak(cfg):
    """Errors alert on their own key; the streak must not double-count them."""
    _write(cfg, [_real(error="boom")] + [_dry()] * 60 + [_real(dossiers=0), _real(dossiers=0)])
    assert rs._trailing_barren_count(cfg) == 1


def test_a_dry_only_log_yields_no_streak(cfg):
    """No real tick has happened, so there is no evidence either way — not a barren streak."""
    _write(cfg, [_dry() for _ in range(200)])
    assert rs._trailing_barren_count(cfg) == 0


def test_window_still_bounds_the_streak(cfg):
    """`window` is a real-tick count now; it must still bound the answer."""
    _write(cfg, [_real(dossiers=0) for _ in range(40)])
    assert rs._trailing_barren_count(cfg, window=10) == 9


def test_a_missing_tick_log_is_zero_not_a_crash(cfg):
    assert rs._trailing_barren_count(cfg) == 0


# ── the aggregate must not report someone else's probes as our ticks ─────────

def test_dry_runs_are_reported_separately_from_ticks(cfg):
    _write(cfg, [_real(dossiers=3), _real(dossiers=0)] + [_dry()] * 133)
    agg = rs._aggregate_ticks(cfg)
    assert agg["ticks"] == 2, "an external dry-run probe is not this factory producing"
    assert agg["dry_runs"] == 133, "and it must stay visible, not be silently dropped"
    assert agg["candidates"] == 3


# ── every row names its writer ──────────────────────────────────────────────

def test_every_tick_row_names_the_process_that_wrote_it(cfg):
    _write(cfg, [_real(dossiers=1)])
    row = json.loads(rs._ticks_path(cfg).read_text().splitlines()[0])
    assert row["pid"] > 0
    assert row["run_id"] == audit_run_id(), (
        "tick and audit rows share one run identity so a tick can be joined to the searches it ran"
    )


def test_an_upstream_tick_cannot_misattribute_itself(cfg):
    """Identity is applied after the caller's dict, not before."""
    _write(cfg, [{**_real(), "pid": 1, "run_id": "somebody-else"}])
    row = json.loads(rs._ticks_path(cfg).read_text().splitlines()[0])
    assert row["run_id"] == audit_run_id()
    assert row["pid"] != 1


def test_attribution_does_not_disturb_the_fields_the_alerts_read(cfg):
    _write(cfg, [_real(dossiers=5)])
    row = json.loads(rs._ticks_path(cfg).read_text().splitlines()[0])
    assert row["allowed"] is True and row["dry_run"] is False
    assert row["result"] == {"dossiers": 5, "passes": 0}
