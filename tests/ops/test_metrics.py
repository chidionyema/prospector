"""R19 — the outcome figures are true, and they reconcile to `catalogue_stats()`.

Every test here is a MUTATION test: it names a specific wrong implementation and fails on it.
Passing on the fixture is not the point — reverting the behaviour must turn one of these red.

  * Fold defers into the kill rate  →  `test_a_defer_never_enters_a_rate_denominator` fails.
  * Draw the vetted→ruled step as drop-off  →  `test_the_vetted_to_ruled_loss_is_an_outage…` fails.
  * Print 0.0 for an unmeasured rate  →  three `…prints_an_explicit_null_with_a_reason` fail.
  * Bucket a NULL composite at 0.0  →  `test_an_unscored_row_is_never_bucketed_at_zero` fails.
  * Attribute an ungated kill to min_composite (which `run.py report` does) →
    `test_a_kill_with_no_gate_is_not_attributed_to_min_composite` fails.
  * Count rows in Python instead of SQL  →  `test_counts_come_from_sql_not_a_python_len` fails.
  * Raise on a torn jsonl line  →  `test_a_torn_line_is_skipped_never_raised` fails.
"""
from __future__ import annotations

import json
import sqlite3
import types

import pytest

from prospector.ops import metrics as M
from prospector.store import Store


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _cfg(tmp_path, *, bar: float = 3.2):
    """A cfg with a REAL store_dir. A `Path`, not a str: `Store.__init__` binds `cfg.store_dir`
    and calls `.mkdir()` on it directly, and `paths.store_dir` raises rather than defaulting to
    a cwd-relative `store/` — which under pytest IS the live store."""
    return types.SimpleNamespace(
        store_dir=tmp_path,
        thresholds=types.SimpleNamespace(min_composite_to_pass=bar),
    )


def _rows(tmp_path, rows: list[dict]) -> Store:
    """Index rows written straight into SQLite. Straight SQL rather than `store.save(Dossier())`
    because these tests are about COUNTING; building full model objects would make the fixture
    the thing under test."""
    store = Store(_cfg(tmp_path))
    with sqlite3.connect(str(store.db)) as conn:
        for r in rows:
            conn.execute(
                "INSERT INTO dossiers (candidate_id, decision, gate_fired, composite, "
                "provisional, created_at, path) VALUES (?,?,?,?,?,?,?)",
                (r["candidate_id"], r.get("decision"), r.get("gate_fired"),
                 r.get("composite"), int(r.get("provisional", 0)),
                 r.get("created_at", "2026-08-01T00:00:00+00:00"),
                 str(tmp_path / "dossiers" / f"{r['candidate_id']}.json")))
        conn.commit()
    return store


def _diag(tmp_path, *records) -> None:
    d = tmp_path / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    (d / M.DIAG_FILENAME).write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _batch(ts, *, passes=0, kills=0, defers=0, vetted=None, **extra) -> dict:
    vetted = (passes + kills + defers) if vetted is None else vetted
    rec = {"ts": ts,
           "decisions": {"pass": passes, "kill": kills, "defer": defers, "vetted": vetted}}
    rec.update(extra)
    return rec


# --------------------------------------------------------------------------- #
# THE PROBE: reconciliation to catalogue_stats()
# --------------------------------------------------------------------------- #
def test_the_totals_reconcile_to_catalogue_stats_exactly(tmp_path, monkeypatch):
    """R19's own probe, run against the REAL `readers.catalogue_stats()`.

    Not a re-implementation of its statement: the actual function, pointed at this fixture store
    through `PROSPECTOR_STORE_ROOT` (read per call — `paths.py:69`), with its `st.cache_data`
    cleared so a previous test's store cannot answer for this one.
    """
    from prospector.control_center import readers

    store = _rows(tmp_path, [
        {"candidate_id": "p1", "decision": "pass", "composite": 3.4},
        {"candidate_id": "p2", "decision": "pass", "composite": 3.3},
        {"candidate_id": "k1", "decision": "kill", "gate_fired": "min_composite",
         "composite": 2.1},
        {"candidate_id": "k2", "decision": "kill", "gate_fired": "incumbency",
         "provisional": 1},
        {"candidate_id": "d1", "decision": "defer"},
    ])
    monkeypatch.setenv("PROSPECTOR_STORE_ROOT", str(tmp_path))
    readers.catalogue_stats.clear()

    view = M.catalogue_outcomes(_cfg(tmp_path), store=store)
    rec = view["reconciliation"]
    stats = readers.catalogue_stats()

    assert rec["reconciled"] is True, rec
    assert rec["deltas"] == {}
    # The equality, spelled out, so a change to either side has to face it.
    assert view["counts"]["pass"] == stats["n_pass"] == 2
    assert view["counts"]["kill"] == stats["n_kill"] == 2
    assert view["counts"]["defer"] == stats["n_defer"] == 1
    assert view["counts"]["total"] == stats["total"] == 5
    assert view["provisional"]["n"] == stats["n_provisional"] == 1


def test_a_divergence_from_catalogue_stats_is_reported_loudly_not_papered_over(tmp_path):
    """If the two sides ever disagree, the view must SAY SO — a figure that looks right is the
    failure this probe exists to catch, so `reconciled` goes False and carries the deltas."""
    store = _rows(tmp_path, [
        {"candidate_id": "p1", "decision": "pass"},
        {"candidate_id": "k1", "decision": "kill"},
    ])
    lying = {"n_pass": 99, "n_kill": 1, "n_defer": 0, "total": 100, "n_provisional": 0}
    rec = M.reconciliation(_cfg(tmp_path), store=store, stats=lying)

    assert rec["reconciled"] is False
    assert rec["deltas"]["pass"] == 1 - 99
    assert "FAILED" in rec["reason"]


def test_counts_come_from_sql_not_a_python_len(tmp_path, monkeypatch):
    """`counts_by_decision()` — the shipped GROUP BY — must be the source, and `store.all()`
    (which drags every row across a process boundary to be counted in Python) must not be
    touched. A second way to count is how a console and a rail come to disagree."""
    store = _rows(tmp_path, [
        {"candidate_id": "p1", "decision": "pass"},
        {"candidate_id": "k1", "decision": "kill"},
    ])
    seen = {"group_by": 0}
    real = store.counts_by_decision
    monkeypatch.setattr(store, "counts_by_decision",
                        lambda: (seen.__setitem__("group_by", seen["group_by"] + 1), real())[1])
    monkeypatch.setattr(store, "all", lambda *a, **k: pytest.fail(
        "store.all() called — R19 must count in SQLite, never by len()-ing rows in Python"))

    M.catalogue_outcomes(_cfg(tmp_path), store=store, stats={})
    assert seen["group_by"] >= 1


# --------------------------------------------------------------------------- #
# A DEFER IS AN OUTAGE, NOT AN OUTCOME
# --------------------------------------------------------------------------- #
def test_a_defer_never_enters_a_rate_denominator(tmp_path):
    """The mutation: denominator `pass + kill + defer` instead of `pass + kill`.

    5 pass, 5 kill, 32 defer — the live batch of 2026-08-15T22:12. The honest kill rate is
    50.0% of what was RULED. Folding the outage in gives 11.9% and reports a broken moat as a
    gentler filter.
    """
    store = _rows(tmp_path,
                  [{"candidate_id": f"p{i}", "decision": "pass"} for i in range(5)] +
                  [{"candidate_id": f"k{i}", "decision": "kill"} for i in range(5)] +
                  [{"candidate_id": f"d{i}", "decision": "defer"} for i in range(32)])
    v = M.catalogue_outcomes(_cfg(tmp_path), store=store, stats={})

    assert v["ruled"] == 10
    assert v["kill_rate_pct"] == 50.0
    assert v["pass_rate_pct"] == 50.0
    assert v["kill_rate_pct"] != pytest.approx(5 / 42 * 100, abs=0.1)
    assert v["defer"]["n"] == 32
    assert "outage" in v["defer"]["note"]


def test_the_vetted_to_ruled_loss_is_an_outage_and_is_excluded_from_dropped_total(tmp_path):
    """The mutation: counting the defer step as funnel attrition.

    50 generated → 42 vetted → 10 ruled → 5 pass. The 32 that never got a verdict are NOT
    drop-off; `dropped_total` must count only the 8 prescreened out and the 5 killed.
    """
    _diag(tmp_path, _batch("2026-08-15T22:12:07+00:00", passes=5, kills=5, defers=32, vetted=42,
                           funnel={"generated": 50, "dedup_dropped": 0, "rejection_fastpath": 0,
                                   "prescreen_in": 50, "prescreened_out": 8,
                                   "novelty_selected": 42, "vetted": 42},
                           kill_gates={"moat_ungrounded": 3, "min_composite": 2}))
    f = M.funnel_view(_cfg(tmp_path))

    ruled_step = next(s for s in f["steps"] if s["stage"] == "ruled")
    assert ruled_step["kind"] == "outage"
    assert ruled_step["lost"] == 32
    assert "NOT drop-off" in ruled_step["note"]
    assert f["outage_total"] == 32
    assert f["dropped_total"] == 8 + 5, "the 32 defers leaked into the drop-off total"
    assert f["steps"][-1]["attributed_to"] == {"moat_ungrounded": 3, "min_composite": 2}


def test_the_outage_rate_is_named_and_measured_over_vetted_not_ruled(tmp_path):
    """`defer_rate` alongside `kill_rate` invites a reader to add them up. The share of work the
    engine could not FINISH is a different question from how strict the filter is, so it gets a
    different name and a different denominator (vetted, not ruled)."""
    _diag(tmp_path, _batch("2026-08-15T22:12:07+00:00", passes=5, kills=5, defers=32, vetted=42))
    p = M.rates_over_time(_cfg(tmp_path))["points"][0]

    assert "defer_rate_pct" not in p
    assert p["outage_rate_pct"] == pytest.approx(32 / 42 * 100, abs=0.05)
    assert p["kill_rate_pct"] == 50.0


# --------------------------------------------------------------------------- #
# HONEST NULLS — an unmeasured figure is never 0.0
# --------------------------------------------------------------------------- #
def test_an_all_defer_batch_prints_an_explicit_null_with_a_reason(tmp_path):
    """The mutation: `pass_rate_pct: 0.0` on a batch where the moat was down.

    Nothing was ruled, so there is no rate. `0.0` reads as "we passed nothing", which is a
    judgement the engine never made (`a-saturated-metric-prints-as-a-confident-null`).
    """
    _diag(tmp_path, _batch("2026-08-14T10:00:00+00:00", defers=20, vetted=20))
    p = M.rates_over_time(_cfg(tmp_path))["points"][0]

    assert p["pass_rate_pct"] is None
    assert p["kill_rate_pct"] is None
    assert "outage" in p["reason"] and "20" in p["reason"]


def test_an_empty_catalogue_rate_is_null_not_zero(tmp_path):
    store = _rows(tmp_path, [{"candidate_id": "d1", "decision": "defer"}])
    v = M.catalogue_outcomes(_cfg(tmp_path), store=store, stats={})

    assert v["pass_rate_pct"] is None and v["kill_rate_pct"] is None
    assert "outage population" in v["rate_reason"]


def test_a_check_with_no_observation_prints_an_explicit_null_with_a_reason(tmp_path):
    """The live shape: `value_durability: {}` and `incumbency: {}` because kill-fast
    short-circuited before them. `unverifiable_pct: 0.0` there would read as perfect
    grounding on a check that never ran."""
    _diag(tmp_path, _batch("2026-08-15T22:12:07+00:00", passes=5, kills=5, defers=32, vetted=42,
                           verdict_matrix={
                               "pain_reality": {"unverifiable": 2, "supported": 6},
                               "value_durability": {},
                               "incumbency": {},
                               "legality": {"supported": 5, "unverifiable": 6}},
                           retrieval_failed_checks=8))
    v = M.verdict_matrix(_cfg(tmp_path))
    by_check = {r["check"]: r for r in v["rows"]}

    assert by_check["value_durability"]["n"] == 0
    assert by_check["value_durability"]["unverifiable_pct"] is None
    assert "kill-fast" in by_check["value_durability"]["reason"]
    assert by_check["pain_reality"]["unverifiable_pct"] == 25.0
    # The outage counter is beside the matrix, never inside it as `unverifiable`.
    assert v["retrieval_failed_checks"] == 8
    assert sum(r["unverifiable"] for r in v["rows"]) == 8  # 2 + 6, NOT 8 + 8


def test_an_unscored_row_is_never_bucketed_at_zero(tmp_path):
    """The mutation: `coalesce(composite, 0)`.

    On the live store 1,348 kills have `composite IS NULL` — killed before scoring ran. Reading
    NULL as 0.0 piles them into the leftmost bucket and manufactures a distribution of
    worst-possible ideas out of rows that were never scored.
    """
    store = _rows(tmp_path, [
        {"candidate_id": "p1", "decision": "pass", "composite": 3.4},
        {"candidate_id": "k1", "decision": "kill", "composite": 2.1},
        {"candidate_id": "k2", "decision": "kill", "gate_fired": "incumbency"},   # NULL
        {"candidate_id": "k3", "decision": "kill", "gate_fired": "legality"},     # NULL
        {"candidate_id": "d1", "decision": "defer"},                              # NULL
    ])
    v = M.composite_view(_cfg(tmp_path), store=store, records=[])

    assert v["scored"] == 2
    assert v["unscored"]["total"] == 3
    assert v["unscored"]["by_decision"] == {"kill": 2, "defer": 1}
    assert all(b["low"] > 0 for b in v["distribution"]), \
        "a NULL composite was bucketed at 0.0"
    # And a defer never appears in the distribution at all — it was never judged.
    assert all("defer" not in b for b in v["distribution"])


def test_a_zero_composite_is_still_charted_because_it_was_actually_measured(tmp_path):
    """The inverse guard: excluding NULLs must not also exclude a genuine 0.0. The live store
    has kills at composite 0.0 — a real score, not a missing one."""
    store = _rows(tmp_path, [{"candidate_id": "k0", "decision": "kill", "composite": 0.0}])
    v = M.composite_view(_cfg(tmp_path), store=store, records=[])

    assert v["scored"] == 1
    assert v["distribution"][0]["low"] == 0.0
    assert v["unscored"]["total"] == 0


def test_several_bars_in_the_window_forbid_a_single_line(tmp_path):
    """Personas override `min_composite_to_pass`; the live diagnostics show 2.5 while the config
    default is 3.2. One line drawn through a distribution judged against several bars is wrong
    for most of its rows, so the view carries every bar it saw and says so."""
    store = _rows(tmp_path, [{"candidate_id": "p1", "decision": "pass", "composite": 3.4}])
    recs = [{"ts": "2026-08-15T22:12:07+00:00", "thresholds": {"min_composite_to_pass": 2.5}},
            {"ts": "2026-08-14T22:12:07+00:00", "thresholds": {"min_composite_to_pass": 3.2}}]
    v = M.composite_view(_cfg(tmp_path), store=store,
                         records=[dict(r, _ts=0.0, _day="x") for r in recs])

    assert v["bars_observed"] == [2.5, 3.2]
    assert "persona overrides" in v["bar_caveat"]


def test_zero_metered_spend_is_explained_not_reported_as_free(tmp_path):
    """`claude_cli` bills the subscription and reports `cost_usd: 0.0` on every call. A window it
    served entirely must not render as $0 of work."""
    _diag(tmp_path, _batch("2026-08-15T22:12:07+00:00", passes=1, kills=1, vetted=2,
                           usage={"total": {"calls": 77}, "total_cost_usd": 0.0,
                                  "by_provider": {"claude_cli": {"calls": 77, "cost_usd": 0.0}}}))
    v = M.cost_view(_cfg(tmp_path))

    assert v["cost_per_ruled_usd"] is None
    assert v["unmetered_providers"] == ["claude_cli"]
    assert "Not $0 of work" in v["reason"]


def test_the_outage_tax_separates_what_an_answer_costs_from_what_downtime_costs(tmp_path):
    """One cost-per-outcome number hides the defers. $10 over 42 vetted of which 10 were ruled
    is $0.238/vetted and $1.00/ruled; the $0.762 difference is money spent on rows the moat could
    not rule, and `vet --resume` will spend it again."""
    _diag(tmp_path, _batch("2026-08-15T22:12:07+00:00", passes=5, kills=5, defers=32, vetted=42,
                           usage={"total": {"calls": 100}, "total_cost_usd": 10.0,
                                  "by_provider": {"minimax": {"calls": 100, "cost_usd": 10.0}}}))
    v = M.cost_view(_cfg(tmp_path))

    assert v["cost_per_vetted_usd"] == pytest.approx(10.0 / 42, abs=1e-4)
    assert v["cost_per_ruled_usd"] == pytest.approx(1.0, abs=1e-4)
    assert v["cost_per_pass_usd"] == pytest.approx(2.0, abs=1e-4)
    assert v["outage_tax_usd"] == pytest.approx(1.0 - 10.0 / 42, abs=1e-3)
    assert v["unmetered_providers"] == []


# --------------------------------------------------------------------------- #
# Kill reason by gate
# --------------------------------------------------------------------------- #
def test_a_kill_with_no_gate_is_not_attributed_to_min_composite(tmp_path):
    """The mutation is a line that already exists elsewhere: `report.py:117` writes
    `r.get("gate_fired") or "min_composite"`, which on the live store invents 9 min_composite
    kills out of rows whose gate was never recorded. "We do not know why this died" is a
    finding, and it gets its own bucket."""
    store = _rows(tmp_path, [
        {"candidate_id": "k1", "decision": "kill", "gate_fired": "min_composite"},
        {"candidate_id": "k2", "decision": "kill", "gate_fired": ""},
        {"candidate_id": "k3", "decision": "kill"},
    ])
    v = M.gate_view(_cfg(tmp_path), store=store)
    gates = {g["gate"]: g["n"] for g in v["gates"]}

    assert gates["min_composite"] == 1, "an ungated kill was folded into min_composite"
    assert gates[M.UNRECORDED_GATE] == 2
    assert v["unrecorded"] == 2
    assert v["kills"] == 3


def test_a_defer_is_never_listed_as_a_kill_gate(tmp_path):
    """Defer rows carry an empty `gate_fired` and would otherwise land in the `(unrecorded)`
    bucket, inflating a kill reason with an outage."""
    store = _rows(tmp_path, [
        {"candidate_id": "k1", "decision": "kill", "gate_fired": "legality"},
        {"candidate_id": "d1", "decision": "defer"},
        {"candidate_id": "d2", "decision": "defer"},
    ])
    v = M.gate_view(_cfg(tmp_path), store=store)

    assert v["kills"] == 1
    assert v["unrecorded"] == 0
    assert sum(g["n"] for g in v["gates"]) == 1
    assert v["gates"][0]["pct_of_kills"] == 100.0


# --------------------------------------------------------------------------- #
# Reading a file the daemon is appending to
# --------------------------------------------------------------------------- #
def test_a_torn_line_is_skipped_never_raised(tmp_path):
    """`batch_diagnostics.jsonl` is appended by a live producer, so a half-written last line is
    the NORMAL case, not corruption. A monitor that raises here is down exactly when the thing
    it watches is busy."""
    d = tmp_path / "scheduler"
    d.mkdir(parents=True)
    (d / M.DIAG_FILENAME).write_text(
        json.dumps(_batch("2026-08-14T10:00:00+00:00", passes=1, kills=1, vetted=2)) + "\n"
        + "\n"
        + '{"ts": "2026-08-15T10:00:00+00:00", "decisions": {"pass": 1, "ki\n')

    recs = M.diagnostics_records(_cfg(tmp_path))
    assert len(recs) == 1
    assert M.rates_over_time(_cfg(tmp_path))["points"][0]["ruled"] == 2


def test_an_absent_diagnostics_file_is_a_reason_not_a_crash_and_not_a_zero(tmp_path):
    cfg = _cfg(tmp_path)
    assert M.diagnostics_records(cfg) == []
    assert "no parsable record" in M.rates_over_time(cfg)["reason"]
    assert M.verdict_matrix(cfg)["reason"] == "no check observation in the window"
    assert M.cost_view(cfg)["cost_per_ruled_usd"] is None


def test_a_record_with_an_unparsable_ts_is_dropped_not_dated_today(tmp_path):
    """Dating an undated record to read-time invents a spike on today — the chart equivalent of
    a confident null."""
    _diag(tmp_path,
          {"ts": "not-a-timestamp", "decisions": {"pass": 99, "kill": 0, "vetted": 99}},
          _batch("2026-08-14T10:00:00+00:00", passes=1, kills=1, vetted=2))
    r = M.rates_over_time(_cfg(tmp_path))

    assert [p["day"] for p in r["points"]] == ["2026-08-14"]
    assert r["totals"]["pass"] == 1


def test_the_funnel_prints_its_residual_instead_of_absorbing_it(tmp_path):
    """If the emitter and this view disagree about the top of the funnel, a chart that silently
    rescales looks healthy while a field is being dropped."""
    _diag(tmp_path, _batch("2026-08-15T22:12:07+00:00", passes=1, kills=1, vetted=2,
                           funnel={"generated": 50, "dedup_dropped": 0, "rejection_fastpath": 0,
                                   "prescreen_in": 40, "prescreened_out": 0,
                                   "novelty_selected": 40, "vetted": 2}))
    f = M.funnel_view(_cfg(tmp_path))

    assert f["residual_generated_vs_prescreen_in"] == 10
    assert "unaccounted" in f["residual_note"]
    assert f["unfinished_total"] == 38
    assert next(s for s in f["steps"] if s["stage"] == "vetted")["kind"] == "unfinished"


# --------------------------------------------------------------------------- #
# The two populations
# --------------------------------------------------------------------------- #
def test_coverage_names_the_gap_between_the_jsonl_and_the_catalogue(tmp_path):
    """The jsonl covers scheduled batches since 2026-06-22; the catalogue covers every entry
    point and all history. Measured live the gap is over a thousand rows. A view that did not
    name it would let a time series be read as a catalogue total."""
    store = _rows(tmp_path, [{"candidate_id": f"k{i}", "decision": "kill"} for i in range(10)])
    _diag(tmp_path, _batch("2026-08-15T22:12:07+00:00", passes=1, kills=1, vetted=2))
    c = M.coverage(_cfg(tmp_path), store=store)

    assert c["catalogue_rows"] == 10
    assert c["diagnostics_vetted"] == 2
    assert c["covered_pct"] == 20.0
    assert "different populations" in c["note"]


def test_snapshot_returns_every_view_and_reads_each_source_once(tmp_path):
    store = _rows(tmp_path, [
        {"candidate_id": "p1", "decision": "pass", "composite": 3.4},
        {"candidate_id": "k1", "decision": "kill", "gate_fired": "legality", "composite": 1.0},
        {"candidate_id": "d1", "decision": "defer"},
    ])
    _diag(tmp_path, _batch("2026-08-15T22:12:07+00:00", passes=1, kills=1, defers=1, vetted=3))
    snap = M.snapshot(_cfg(tmp_path), store=store)

    assert set(snap) >= {"outcomes", "gates", "rates", "verdicts", "funnel", "composite",
                         "cost", "coverage"}
    assert snap["outcomes"]["ruled"] == 2
    assert snap["gates"]["kills"] == 1
    assert snap["composite"]["scored"] == 2
