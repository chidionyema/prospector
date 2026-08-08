"""Tests for G5: seed provenance and the survival report.

Two layers. `summarise` is pure, so the arithmetic is exercised directly on hand-built rows —
a formatting change can never hide a counting bug. The provenance stamp is pinned end-to-end
through `Store.save`, because a tag that generation writes and the index drops is the
'write-only field' defect this repo has shipped before (memory: write-only-fields-fix-the-
reader-too).
"""
from __future__ import annotations

import sqlite3

from prospector.models import Candidate
from tools.generation_survival import _UNKNOWN, summarise


def _row(lane="smb", decision="kill", composite=0.5, seed="blue_sky",
         provisional=0, gate="incumbency"):
    return {"ambition_tier": lane, "decision": decision, "composite": composite,
            "seed_kind": seed, "provisional": provisional, "gate_fired": gate,
            "audience": "solo_agent", "structural_form": "saas", "market": "uk"}


# ----- summarise: the counting rules -----------------------------------------


def test_defers_are_excluded_from_the_denominator():
    """A DEFER is an UNFINISHED verdict, not a failure. Counting one against generation is
    how a moat outage becomes a false verdict about idea quality — the exact error class of
    the 2026-08-06 dossier that rendered seven failed verdict calls as a reasoned KILL."""
    rows = ([_row(decision="pass")] * 5 + [_row(decision="kill")] * 5
            + [_row(decision="defer")] * 90)
    rep = summarise(rows, ["seed_kind"], min_n=1)
    cell = rep["cells"][0]
    assert cell["n"] == 100          # every row is still counted
    assert cell["ruled"] == 10       # ...but only pass+kill are ruled
    assert cell["defer"] == 90
    assert cell["pass_rate"] == 0.5  # 5/10, NOT 5/100


def test_provisional_rows_are_never_counted_as_passes():
    """A provisional ruling can never publish, so crediting generation for it would report
    a result that has not survived a trusted verdict."""
    rows = [_row(decision="pass", provisional=1)] * 4 + [_row(decision="kill")] * 6
    rep = summarise(rows, ["seed_kind"], min_n=1)
    cell = rep["cells"][0]
    assert cell["pass"] == 0
    assert cell["provisional"] == 4
    assert cell["ruled"] == 6
    assert cell["pass_rate"] == 0.0


def test_blank_seed_kind_becomes_an_explicit_unknown_bucket():
    """Pre-migration rows are NOT redistributed into whichever kind is convenient."""
    rows = [_row(seed="")] * 3 + [_row(seed=None)] * 2 + [_row(seed="signal")] * 5
    rep = summarise(rows, ["seed_kind"], min_n=1)
    buckets = {tuple(c["cell"].values())[0]: c["ruled"] for c in rep["cells"]}
    assert buckets == {_UNKNOWN: 5, "signal": 5}


def test_min_n_suppression_is_reported_not_silent():
    """A truncated table that does not say it truncated reads as 'that is all there is'."""
    rows = [_row(seed="signal")] * 20 + [_row(seed="blue_sky")] * 3
    rep = summarise(rows, ["seed_kind"], min_n=10)
    assert rep["totals"]["cells"] == 2
    assert rep["totals"]["cells_shown"] == 1
    assert rep["totals"]["cells_suppressed_below_min_n"] == 1
    # The suppressed rows are still in the totals — nothing vanishes from the row count.
    assert rep["totals"]["rows"] == 23


def test_top_gate_is_the_modal_kill_gate_and_ignores_passes():
    rows = ([_row(decision="kill", gate="incumbency")] * 7
            + [_row(decision="kill", gate="payer_solvency")] * 3
            + [_row(decision="pass", gate="")] * 5)
    rep = summarise(rows, ["seed_kind"], min_n=1)
    assert rep["cells"][0]["top_gate"] == "incumbency"


def test_mean_composite_ignores_bools_and_missing():
    """`isinstance(True, int)` is True in Python — a bool must never enter a mean."""
    rows = [_row(composite=0.4), _row(composite=0.6),
            _row(composite=True), _row(composite=None)]
    rep = summarise(rows, ["seed_kind"], min_n=1)
    assert abs(rep["cells"][0]["mean_composite"] - 0.5) < 1e-9


def test_multi_axis_grouping_splits_cells():
    rows = ([_row(seed="signal", lane="smb")] * 10
            + [_row(seed="signal", lane="venture")] * 10)
    rep = summarise(rows, ["seed_kind", "ambition_tier"], min_n=1)
    assert len(rep["cells"]) == 2
    assert {c["cell"]["ambition_tier"] for c in rep["cells"]} == {"smb", "venture"}


def test_empty_rows_produce_an_empty_report_not_a_crash():
    rep = summarise([], ["seed_kind"], min_n=1)
    assert rep["cells"] == []
    assert rep["totals"]["rows"] == 0


# ----- the provenance stamp reaches the index --------------------------------


def test_seed_kind_property_reads_the_tag():
    assert Candidate(title="t", one_liner="o", tags={"seed_kind": " Blue_Sky "}
                     ).seed_kind == "blue_sky"
    assert Candidate(title="t", one_liner="o", tags={}).seed_kind == ""
    assert Candidate(title="t", one_liner="o", tags=None).seed_kind == ""


def test_generate_stamps_seed_kind_by_whether_a_signal_was_given():
    """The whole point of the field: `run_signal("")` from the daemon and an operator's
    `vet "<signal>"` are different generation problems and must be distinguishable."""
    from prospector.config import load_config
    from prospector.generate import generate

    class _Op:
        model_version = "stub"

        def complete_json(self, system, user, temperature=0.0):
            return [{"title": f"Idea {i}", "one_liner": "x", "why_now": "y",
                     "tags": {"sector": "s"}} for i in range(6)]

    cfg = load_config()
    cfg.generation["refinement_enabled"] = False

    blue = generate(_Op(), cfg, signal_text="", sector="", k=6)
    seeded = generate(_Op(), cfg, signal_text="vet invoicing pain", sector="veterinary", k=6)

    assert blue and all(c.tags["seed_kind"] == "blue_sky" for c in blue)
    assert seeded and all(c.tags["seed_kind"] == "signal" for c in seeded)


def test_seed_kind_is_indexed_by_store_save(tmp_path):
    """End-to-end: the tag survives into a queryable SQLite column. Without this the
    survival report would read every row as `unknown` while the tag sat in the JSON."""
    from types import SimpleNamespace

    from prospector.models import Decision, Dossier
    from prospector.store import Store

    cfg = SimpleNamespace(store_dir=tmp_path)
    store = Store(cfg)
    cand = Candidate(title="Indexed", one_liner="o",
                     tags={"seed_kind": "blue_sky", "audience": "solo_agent"})
    store.save(Dossier(candidate=cand, decision=Decision.KILL, gate_fired="incumbency"))

    conn = sqlite3.connect(str(store.db))
    try:
        got = conn.execute("SELECT seed_kind, audience FROM dossiers").fetchall()
    finally:
        conn.close()
    assert got == [("blue_sky", "solo_agent")]


def test_missing_seed_kind_is_empty_string_never_null(tmp_path):
    """'' and NULL in one column silently split every GROUP BY into two buckets that mean
    the same thing — the rule `audience` and `market` already follow."""
    from types import SimpleNamespace

    from prospector.models import Decision, Dossier
    from prospector.store import Store

    store = Store(SimpleNamespace(store_dir=tmp_path))
    store.save(Dossier(candidate=Candidate(title="Bare", one_liner="o"),
                       decision=Decision.KILL, gate_fired="incumbency"))
    conn = sqlite3.connect(str(store.db))
    try:
        (val,) = conn.execute("SELECT seed_kind FROM dossiers").fetchone()
    finally:
        conn.close()
    assert val == ""
