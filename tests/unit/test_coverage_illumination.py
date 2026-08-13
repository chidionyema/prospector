"""G7 — illumination: a cell is covered to the degree its ideas are good.

Never touches store/: every test builds its own dossier index in tmp_path. No LLM, no
network.

The one invariant that must never break is at the top: `quality_weight: 0.0` is V2 exactly.
Every other knob in this programme is defended by a gate; this one is defended by a gate AND
by the arithmetic collapsing to the old expression, because it changes an existing code path
rather than adding a new one.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prospector.coverage import (  # noqa: E402
    SamplerConfig,
    _blended_share,
    _illumination,
    _rank_by_deficit,
    measure,
    receipt,
    select_cells,
)

_SCHEMA = """
CREATE TABLE dossiers (
    candidate_id    TEXT PRIMARY KEY,
    title           TEXT,
    decision        TEXT,
    composite       REAL,
    provisional     INTEGER DEFAULT 0,
    created_at      TEXT,
    one_liner       TEXT,
    ambition_tier   TEXT,
    structural_form TEXT,
    market          TEXT,
    audience        TEXT
);
"""

# A schema predating the composite/provisional columns — an older index is legitimate.
_SCHEMA_V1 = """
CREATE TABLE dossiers (
    candidate_id    TEXT PRIMARY KEY,
    title           TEXT,
    decision        TEXT,
    created_at      TEXT,
    ambition_tier   TEXT,
    structural_form TEXT,
    market          TEXT,
    audience        TEXT
);
"""


def _db(tmp_path: Path, rows: list[dict], schema: str = _SCHEMA) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "prospector.db"
    conn = sqlite3.connect(p)
    conn.executescript(schema)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(dossiers)").fetchall()]
    for i, row in enumerate(rows):
        d = {"candidate_id": f"c{i}", "title": f"t{i}", "decision": "kill",
             "composite": None, "provisional": 0, "created_at": f"2026-01-{(i % 28) + 1:02d}",
             "one_liner": f"one liner {i}", "ambition_tier": "smb",
             "structural_form": "vertical_tool", "market": "uk", "audience": "smb_owner"}
        d.update(row)
        use = [c for c in cols if c in d]
        conn.execute(
            f"INSERT INTO dossiers ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
            [d[c] for c in use])
    conn.commit()
    conn.close()
    return p


def _scfg(**kw):
    base = {"enabled": True, "axes": ["audience"], "min_coverage": 0.0,
            "recent_window": 0, "seed": 7}
    base.update(kw)
    return SamplerConfig.from_mapping(base)


def _two_cells(n_a: int, n_b: int, q_a: float, q_b: float) -> list[dict]:
    """n_a rows for audience `alpha` all scoring `q_a`, likewise `beta`.

    Every row carries the same composite ON PURPOSE, so mean == elite == q and the tests
    below hold under either `quality_stat`. The two statistics are separated deliberately
    in section 6, which is where the difference between them is the thing under test.
    """
    rows = []
    for name, n, q in (("alpha", n_a, q_a), ("beta", n_b, q_b)):
        for _ in range(n):
            rows.append({"audience": name, "decision": "kill", "composite": q})
    return rows


# ---------------------------------------------------------------------------
# 1. quality_weight 0.0 is V2 exactly
# ---------------------------------------------------------------------------

def test_the_default_is_zero_so_the_feature_is_inert_out_of_the_box():
    assert SamplerConfig.from_mapping({}).quality_weight == 0.0


def test_zero_weight_produces_the_identical_share_floats_as_before(tmp_path):
    """Not "similar" — identical. The old expression is `count / total` and at qw=0 the
    new one must reduce to it exactly, or a config nobody edited changes behaviour."""
    db = _db(tmp_path, _two_cells(30, 10, 3.0, 0.1))
    cov = measure(db, _scfg()).axes["audience"]
    domain = ["alpha", "beta"]
    assert _blended_share(cov, domain, 0.0) == {"alpha": 0.75, "beta": 0.25}


def test_zero_weight_produces_the_identical_PLAN_as_before(tmp_path):
    db = _db(tmp_path, _two_cells(30, 10, 3.0, 0.1))
    rep = measure(db, _scfg())
    assert select_cells(rep, _scfg(quality_weight=0.0), 6) == select_cells(rep, _scfg(), 6)


def test_the_elites_are_measured_even_at_zero_weight(tmp_path):
    """Measuring is free and always on; only STEERING is gated. A knob you must turn on to
    find out whether it would have helped is a knob nobody turns on."""
    db = _db(tmp_path, _two_cells(30, 10, 3.0, 0.1))
    cov = measure(db, _scfg()).axes["audience"]
    assert cov.elite == {"alpha": 3.0, "beta": 0.1}
    assert cov.mean_composite == pytest.approx({"alpha": 3.0, "beta": 0.1})
    assert cov.ruled == {"alpha": 30, "beta": 10}


# ---------------------------------------------------------------------------
# 2. What the weight actually does
# ---------------------------------------------------------------------------

def test_a_heavily_attempted_cell_with_a_weak_elite_stops_reading_as_covered(tmp_path):
    """30 rows in `alpha` whose best idea scored 0.1, 10 rows in `beta` whose best scored
    3.0. By row count alpha is 75% covered; by illumination it is barely covered at all."""
    db = _db(tmp_path, _two_cells(30, 10, 0.1, 3.0))
    cov = measure(db, _scfg()).axes["audience"]
    share = _blended_share(cov, ["alpha", "beta"], 1.0)
    assert share["alpha"] < share["beta"], (
        "alpha has 3x the rows and 1/30th the elite; it must not read as the covered one")


def test_the_weight_flips_which_cell_is_ranked_most_deficient(tmp_path):
    """alpha has 3x the rows of beta, so by row count beta is the deficient one. Once the
    rows are discounted by alpha's near-zero elite, alpha becomes the deficient one."""
    db = _db(tmp_path, _two_cells(30, 10, 0.1, 3.0))
    cov = measure(db, _scfg()).axes["audience"]
    off = [v for v, _ in _rank_by_deficit(cov, ["alpha", "beta"], 7, 0.0)]
    on = [v for v, _ in _rank_by_deficit(cov, ["alpha", "beta"], 7, 1.0)]
    assert off[0] == "beta", "by row count alone the under-populated beta leads"
    assert on[0] == "alpha", "with illumination on, the badly-attempted alpha leads"


def test_the_weight_moves_the_actual_plan_under_entropy_sampling(tmp_path):
    """`quota` deals round-robin, so over a 2-value domain it always splits 50/50 whatever
    the ranking says — the ranking only sets where the rotation starts. `entropy` samples
    ON the deficit weights, which is where a share change becomes a plan change."""
    db = _db(tmp_path, _two_cells(30, 10, 0.1, 3.0))
    rep = measure(db, _scfg(method="entropy"))
    off = [c["audience"] for c in select_cells(rep, _scfg(method="entropy"), 40)]
    on = [c["audience"] for c in
          select_cells(rep, _scfg(method="entropy", quality_weight=1.0), 40)]
    assert off.count("alpha") < on.count("alpha"), (
        f"illumination must buy the badly-attempted cell more of the batch: "
        f"{off.count('alpha')} -> {on.count('alpha')} of 40")


def test_the_weight_interpolates_rather_than_switching(tmp_path):
    db = _db(tmp_path, _two_cells(30, 10, 0.1, 3.0))
    cov = measure(db, _scfg()).axes["audience"]
    shares = [_blended_share(cov, ["alpha", "beta"], w)["alpha"]
              for w in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert shares == sorted(shares, reverse=True), f"must be monotone in the weight: {shares}"
    assert shares[0] > shares[-1]


def test_equal_elites_leave_the_ranking_untouched_at_any_weight(tmp_path):
    """The weight must be a no-op when there is no quality DIFFERENCE to act on."""
    db = _db(tmp_path, _two_cells(30, 10, 2.0, 2.0))
    cov = measure(db, _scfg()).axes["audience"]
    assert _blended_share(cov, ["alpha", "beta"], 1.0) == \
        _blended_share(cov, ["alpha", "beta"], 0.0)


# ---------------------------------------------------------------------------
# 3. What counts as an elite
# ---------------------------------------------------------------------------

def test_a_provisional_row_never_sets_the_elite(tmp_path):
    """A provisional composite comes from a brain that may not rule (`is_provisional_provider`).
    Letting it set the elite would let a non-ruling model steer generation."""
    db = _db(tmp_path, [
        {"audience": "alpha", "decision": "pass", "composite": 9.0, "provisional": 1},
        {"audience": "alpha", "decision": "kill", "composite": 1.0, "provisional": 0},
    ])
    cov = measure(db, _scfg()).axes["audience"]
    assert cov.elite == {"alpha": 1.0}
    assert cov.ruled == {"alpha": 1}


def test_a_deferred_row_never_sets_the_elite(tmp_path):
    """A DEFER is an unfinished verdict. Its composite does not speak for the cell."""
    db = _db(tmp_path, [
        {"audience": "alpha", "decision": "defer", "composite": 9.0},
        {"audience": "alpha", "decision": "kill", "composite": 1.0},
    ])
    assert measure(db, _scfg()).axes["audience"].elite == {"alpha": 1.0}


def test_a_kill_still_sets_the_elite(tmp_path):
    """A KILL is a completed, grounded ruling and its composite is real. Counting only
    passes would make every elite a pass-rate proxy, which is the lever we may not pull."""
    db = _db(tmp_path, [{"audience": "alpha", "decision": "kill", "composite": 2.4}])
    assert measure(db, _scfg()).axes["audience"].elite == {"alpha": 2.4}


def test_a_null_composite_is_absent_rather_than_zero(tmp_path):
    """Treating "not scored" as 0.0 would invent the worst possible evidence from silence."""
    db = _db(tmp_path, [{"audience": "alpha", "decision": "kill", "composite": None}])
    cov = measure(db, _scfg()).axes["audience"]
    assert cov.elite == {} and cov.ruled == {} and cov.mean_composite == {}


# ---------------------------------------------------------------------------
# 4. Silence is not evidence
# ---------------------------------------------------------------------------

def test_a_never_ruled_value_takes_no_quality_discount():
    """One lucky ruled value must not stampede a domain of values nobody has data on."""
    from prospector.coverage import AxisCoverage
    cov = AxisCoverage(axis="audience", rows=10, counts={"alpha": 5, "beta": 5},
                       elite={"alpha": 3.0}, mean_composite={"alpha": 3.0})
    for stat in ("mean", "elite"):
        assert _illumination(cov, ["alpha", "beta"], stat) == {"alpha": 1.0, "beta": 1.0}


def test_no_elites_at_all_makes_the_quality_term_inert():
    from prospector.coverage import AxisCoverage
    cov = AxisCoverage(axis="audience", rows=10, counts={"alpha": 8, "beta": 2})
    assert _blended_share(cov, ["alpha", "beta"], 1.0) == \
        _blended_share(cov, ["alpha", "beta"], 0.0)


def test_all_zero_elites_make_the_quality_term_inert():
    """There is no scale to normalise against, so 0/0 must not become a divide or a NaN."""
    from prospector.coverage import AxisCoverage
    cov = AxisCoverage(axis="audience", rows=10, counts={"alpha": 8, "beta": 2},
                       elite={"alpha": 0.0, "beta": 0.0},
                       mean_composite={"alpha": 0.0, "beta": 0.0})
    share = _blended_share(cov, ["alpha", "beta"], 1.0)
    assert share == {"alpha": 0.8, "beta": 0.2}


def test_a_negative_elite_clamps_to_zero_illumination_not_a_negative_share():
    from prospector.coverage import AxisCoverage
    cov = AxisCoverage(axis="audience", rows=10, counts={"alpha": 8, "beta": 2},
                       elite={"alpha": -5.0, "beta": 2.0},
                       mean_composite={"alpha": -5.0, "beta": 2.0})
    illum = _illumination(cov, ["alpha", "beta"])
    assert illum["alpha"] == 0.0 and illum["beta"] == 1.0
    assert all(v >= 0.0 for v in _blended_share(cov, ["alpha", "beta"], 1.0).values())


# ---------------------------------------------------------------------------
# 5. It must never be able to break a measurement
# ---------------------------------------------------------------------------

def test_an_index_predating_the_composite_column_still_measures_coverage(tmp_path):
    """The columns arrived by migration at different times; an older index is legitimate.
    Coverage is the load-bearing measurement, elites are the enrichment."""
    db = _db(tmp_path, [{"audience": "alpha"}, {"audience": "beta"}], schema=_SCHEMA_V1)
    cov = measure(db, _scfg()).axes["audience"]
    assert cov.rows == 2
    assert sorted(cov.observed) == ["alpha", "beta"]
    assert cov.elite == {} and cov.ruled == {} and cov.mean_composite == {}


def test_an_out_of_range_weight_is_clamped_rather_than_raising():
    """A typo in a steering knob must not stop the daemon generating."""
    assert SamplerConfig.from_mapping({"quality_weight": 5}).quality_weight == 1.0
    assert SamplerConfig.from_mapping({"quality_weight": -2}).quality_weight == 0.0
    assert SamplerConfig.from_mapping({"quality_weight": None}).quality_weight == 0.0


def test_the_weight_appears_in_the_receipt_with_the_elites(tmp_path):
    db = _db(tmp_path, _two_cells(3, 3, 2.0, 0.5))
    cfg = SimpleNamespace(
        store_dir=tmp_path,
        coverage_sampler={"enabled": True, "axes": ["audience"], "min_coverage": 0.0,
                          "recent_window": 0, "seed": 7, "quality_weight": 0.6})
    r = receipt(cfg, 2, db_path=db)
    assert r["quality_weight"] == pytest.approx(0.6)
    assert r["quality_stat"] == "mean"
    assert r["coverage"]["axes"]["audience"]["elite"] == {"alpha": 2.0, "beta": 0.5}
    assert r["coverage"]["axes"]["audience"]["mean_composite"] == {"alpha": 2.0, "beta": 0.5}
    assert r["coverage"]["axes"]["audience"]["ruled"] == {"alpha": 3, "beta": 3}


def test_the_elites_are_not_hashed_into_the_seed(tmp_path):
    """The seed drives tie-breaks and rotation offsets. Folding elites in would change the
    plan on a DB whose distribution did not move, and qw=0 would stop being V2."""
    a = _db(tmp_path / "a", _two_cells(5, 5, 3.0, 0.1))
    b = _db(tmp_path / "b", _two_cells(5, 5, 0.1, 3.0))
    assert measure(a, _scfg()).fingerprint() == measure(b, _scfg()).fingerprint()


# ---------------------------------------------------------------------------
# 6. mean vs elite — the statistic the weight acts on
# ---------------------------------------------------------------------------

def test_the_default_statistic_is_the_mean_not_the_qd_canonical_elite():
    """Measured on the live index (1,789 rows, 2026-08-08, cells with n>=30): the max
    spreads 1.16x-1.20x across cells while the mean spreads 1.71x-2.56x. The maximum is an
    extreme order statistic and over 40-110 samples it has converged everywhere, so steering
    on it would be a lever with no authority."""
    assert SamplerConfig.from_mapping({}).quality_stat == "mean"


def test_the_two_statistics_disagree_and_the_choice_decides_the_ranking(tmp_path):
    """`alpha` produced one brilliant idea and 19 worthless ones; `beta` produced 20
    mediocre ones. By elite alpha is the best cell on the axis; by mean it is the worst.
    That is the entire disagreement, and it is why the statistic is a config choice with a
    measurement behind it rather than an implementation detail."""
    rows = [{"audience": "alpha", "decision": "kill", "composite": 3.5 if i == 0 else 0.0}
            for i in range(20)]
    rows += [{"audience": "beta", "decision": "kill", "composite": 1.5} for _ in range(20)]
    db = _db(tmp_path, rows)
    cov = measure(db, _scfg()).axes["audience"]
    assert cov.elite["alpha"] > cov.elite["beta"]
    assert cov.mean_composite["alpha"] < cov.mean_composite["beta"]

    by_elite = _rank_by_deficit(cov, ["alpha", "beta"], 7, 1.0, "elite")[0][0]
    by_mean = _rank_by_deficit(cov, ["alpha", "beta"], 7, 1.0, "mean")[0][0]
    assert by_elite == "beta", "on elites, beta is the under-illuminated cell"
    assert by_mean == "alpha", "on means, alpha is the under-illuminated cell"


def test_an_unknown_statistic_raises_rather_than_silently_picking_one():
    """Unlike `quality_weight`, a misspelt statistic has no safe interpretation: silently
    falling back would steer on a number the operator did not choose."""
    with pytest.raises(ValueError, match="quality_stat"):
        SamplerConfig.from_mapping({"quality_stat": "median"})


def test_the_statistic_is_irrelevant_while_the_weight_is_zero(tmp_path):
    rows = [{"audience": "alpha", "decision": "kill", "composite": 3.5 if i == 0 else 0.0}
            for i in range(20)]
    rows += [{"audience": "beta", "decision": "kill", "composite": 1.5} for _ in range(20)]
    db = _db(tmp_path, rows)
    rep = measure(db, _scfg())
    assert select_cells(rep, _scfg(quality_stat="elite"), 6) == \
        select_cells(rep, _scfg(quality_stat="mean"), 6)


def test_unknown_policy_exclude_drops_the_blank_cells_elite_too(tmp_path):
    db = _db(tmp_path, [
        {"audience": "", "decision": "kill", "composite": 9.0},
        {"audience": "alpha", "decision": "kill", "composite": 1.0},
    ])
    cov = measure(db, _scfg(unknown_policy="exclude")).axes["audience"]
    assert cov.elite == {"alpha": 1.0}, "a blank cell is never a generation target"
    assert cov.unknown == 1, "but it is still visible to the min_coverage guard"


def test_the_shipped_config_yaml_actually_accepts_the_two_new_keys():
    """Pin the allow-list, not just the parser.

    Every other test in this file builds its own `SamplerConfig` dict and so never touches
    `prospector/config.py`'s per-block key allow-list. That is exactly how `quality_weight`
    and `quality_stat` reached a full-suite run as a COLLECTION error: `config.py:349` did
    not list them, and the only thing that noticed was an integration test that loads the
    real file. A new config key is not shipped until something loads the real config.
    """
    from prospector.config import load_config

    root = Path(__file__).resolve().parents[2]
    cfg = load_config(str(root / "config.yaml"))
    block = cfg.coverage_sampler
    assert "quality_weight" in block, "the shipped config must carry the key it documents"
    assert "quality_stat" in block
    scfg = SamplerConfig.from_config(cfg)
    assert scfg.quality_weight == 0.0, "G7 ships inert; steering is opt-in"
    assert scfg.quality_stat == "mean", "elite has no measured authority on this index"
