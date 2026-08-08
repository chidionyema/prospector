"""V2 coverage sampler — unit tests.

Never touches store/: every test builds its own dossier index in tmp_path. No LLM, no
network. The config blocks are built inline as plain dicts (config.py is owned elsewhere).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prospector.coverage import (  # noqa: E402
    AXES,
    UNKNOWN,
    SamplerConfig,
    cell_directive,
    measure,
    off_domain_values,
    plan_cells,
    receipt,
    sampling_domains,
    select_cells,
)

_SCHEMA = """
CREATE TABLE dossiers (
    candidate_id    TEXT PRIMARY KEY,
    title           TEXT,
    decision        TEXT,
    created_at      TEXT,
    one_liner       TEXT,
    ambition_tier   TEXT,
    structural_form TEXT,
    market          TEXT,
    audience        TEXT
);
"""


def _db(tmp_path: Path, rows: list[tuple], name: str = "prospector.db") -> Path:
    """rows = (id, tier, form, audience, market[, created_at])."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / name
    conn = sqlite3.connect(p)
    conn.executescript(_SCHEMA)
    for i, row in enumerate(rows):
        cid, tier, form, aud, market = row[:5]
        created = row[5] if len(row) > 5 else f"2026-01-{(i % 28) + 1:02d}"
        conn.execute(
            "INSERT INTO dossiers (candidate_id, title, decision, created_at, one_liner,"
            " ambition_tier, structural_form, market, audience)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, f"title {cid}", "kill", created, f"one liner {cid}", tier, form, market, aud))
    conn.commit()
    conn.close()
    return p


def _cfg(store_dir: Path, **sampler) -> SimpleNamespace:
    return SimpleNamespace(store_dir=store_dir, coverage_sampler=dict(sampler))


def _rows(n_a: int, n_b: int, blanks: int = 0) -> list[tuple]:
    rows: list[tuple] = []
    for i in range(n_a):
        rows.append((f"a{i}", "smb", "vertical_tool", "smb_owner", "uk"))
    for i in range(n_b):
        rows.append((f"b{i}", "growth", "local_service", "retiree_cohort", "uk"))
    for i in range(blanks):
        rows.append((f"z{i}", "", "", "", "uk"))
    return rows


# ----------------------------------------------------------------------------- config


def test_defaults_land_inert():
    s = SamplerConfig.from_config(SimpleNamespace())
    assert s.enabled is False
    assert s.axes == AXES
    assert (s.method, s.unknown_policy, s.recent_window, s.min_coverage, s.seed) == (
        "quota", "include", 200, 0.25, None)


def test_unknown_axis_is_refused_not_interpolated_into_sql():
    # The axis name reaches a `SELECT <col>` — a whitelist, not quoting, is the defence.
    with pytest.raises(ValueError, match="unknown axis"):
        SamplerConfig.from_mapping({"axes": ["sector"]})
    with pytest.raises(ValueError, match="unknown axis"):
        SamplerConfig.from_mapping({"axes": ["1=1; DROP TABLE dossiers"]})


def test_bad_method_and_policy_are_refused():
    with pytest.raises(ValueError, match="method"):
        SamplerConfig.from_mapping({"method": "vibes"})
    with pytest.raises(ValueError, match="unknown_policy"):
        SamplerConfig.from_mapping({"unknown_policy": "backfill"})


# ------------------------------------------------------------------------ measurement


def test_measure_counts_blanks_as_an_explicit_unknown_cell(tmp_path):
    db = _db(tmp_path, _rows(6, 2, blanks=2))
    rep = measure(db, SamplerConfig.from_mapping({"enabled": True}))
    assert rep.rows == 10
    form = rep.axes["structural_form"]
    assert form.counts == {"vertical_tool": 6, "local_service": 2, UNKNOWN: 2}
    assert form.unknown == 2 and form.known == 8
    assert form.coverage == pytest.approx(0.8)
    assert form.distinct == 2  # UNKNOWN is not a "known value"


def test_unknown_policy_exclude_hides_blanks_from_counts_but_not_from_the_guard(tmp_path):
    """`exclude` must not launder a mostly-blank axis into "100% covered"."""
    db = _db(tmp_path, _rows(6, 2, blanks=2))
    rep = measure(db, SamplerConfig.from_mapping(
        {"enabled": True, "unknown_policy": "exclude"}))
    form = rep.axes["structural_form"]
    assert UNKNOWN not in form.counts
    assert form.rows == 10 and form.unknown == 2
    assert form.coverage == pytest.approx(0.8)

    # 1 labelled + 9 blank under `exclude`: the guard must still suppress the axis.
    db2 = _db(tmp_path / "sub", _rows(1, 0, blanks=9), name="prospector.db")
    rep2 = measure(db2, SamplerConfig.from_mapping(
        {"enabled": True, "unknown_policy": "exclude", "min_coverage": 0.25}))
    assert "structural_form" in rep2.suppressed
    assert "coverage 10.00%" in rep2.suppressed["structural_form"]


def test_min_coverage_suppresses_a_mostly_blank_axis(tmp_path):
    # 2 labelled, 8 blank => coverage 20% < 25%: the axis must not steer.
    db = _db(tmp_path, _rows(1, 1, blanks=8))
    scfg = SamplerConfig.from_mapping({"enabled": True, "min_coverage": 0.25})
    rep = measure(db, scfg)
    assert "structural_form" in rep.suppressed
    assert "coverage 20.00%" in rep.suppressed["structural_form"]
    assert "structural_form" not in sampling_domains(rep, scfg)
    # market is fully populated with one value => suppressed for lack of variety, not blanks
    assert "only 1 distinct" in rep.suppressed["market"]


def test_recent_window_is_the_freshest_rows_only(tmp_path):
    rows = [("old%d" % i, "smb", "vertical_tool", "smb_owner", "uk", "2026-01-01")
            for i in range(10)]
    rows += [("new%d" % i, "growth", "local_service", "retiree_cohort", "uk", "2026-06-01")
             for i in range(3)]
    db = _db(tmp_path, rows)
    rep = measure(db, SamplerConfig.from_mapping({"enabled": True, "recent_window": 3}))
    assert rep.axes["structural_form"].recent_counts == {"local_service": 3}
    assert rep.axes["structural_form"].counts["vertical_tool"] == 10


def test_context_filters_the_measurement(tmp_path):
    rows = _rows(4, 0) + [("us1", "smb", "local_service", "smb_owner", "us")]
    db = _db(tmp_path, rows)
    scfg = SamplerConfig.from_mapping({"enabled": True})
    assert measure(db, scfg, context={"market": "uk"}).rows == 4
    assert measure(db, scfg, context={"market": "us"}).rows == 1
    # An axis outside the whitelist is ignored rather than concatenated into the WHERE.
    assert measure(db, scfg, context={"sector": "'; DROP TABLE dossiers--"}).rows == 5


def test_measure_opens_the_index_read_only(tmp_path):
    db = _db(tmp_path, _rows(4, 4))
    measure(db, SamplerConfig.from_mapping({"enabled": True}))
    from prospector.coverage import _connect_ro
    conn = _connect_ro(db)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM dossiers")
    finally:
        conn.close()


# -------------------------------------------------------------------------- selection


def test_quota_targets_the_least_covered_value_first(tmp_path):
    db = _db(tmp_path, _rows(20, 1))
    scfg = SamplerConfig.from_mapping({"enabled": True, "axes": ["structural_form"]})
    rep = measure(db, scfg)
    cells = select_cells(rep, scfg, 4, domains={"structural_form": [
        "vertical_tool", "local_service", "picks_and_shovels"]})
    picked = [c["structural_form"] for c in cells]
    # picks_and_shovels has zero rows, local_service one, vertical_tool twenty:
    # the over-covered value must come last in the deal order.
    assert picked[0] == "picks_and_shovels"
    assert picked.index("vertical_tool") == 2
    assert set(picked[:3]) == {"picks_and_shovels", "local_service", "vertical_tool"}


def test_selection_is_deterministic_given_a_seed(tmp_path):
    db = _db(tmp_path, _rows(9, 4, blanks=1))
    for method in ("quota", "entropy"):
        scfg = SamplerConfig.from_mapping(
            {"enabled": True, "method": method, "seed": 1234, "min_coverage": 0.0})
        rep = measure(db, scfg)
        a = select_cells(rep, scfg, 12)
        b = select_cells(rep, scfg, 12)
        assert a == b, f"{method} sampling is not replayable"
        assert len(a) == 12


def test_a_different_seed_moves_entropy_sampling(tmp_path):
    db = _db(tmp_path, _rows(9, 4))
    base = {"enabled": True, "method": "entropy", "min_coverage": 0.0}
    rep = measure(db, SamplerConfig.from_mapping(base))
    dom = {"structural_form": ["a", "b", "c", "d", "e", "f", "g", "h"]}
    one = select_cells(rep, SamplerConfig.from_mapping({**base, "seed": 1}), 20, domains=dom)
    two = select_cells(rep, SamplerConfig.from_mapping({**base, "seed": 2}), 20, domains=dom)
    assert one != two


def test_seed_unset_is_still_replayable_from_the_distribution(tmp_path):
    db = _db(tmp_path, _rows(9, 4))
    scfg = SamplerConfig.from_mapping({"enabled": True, "min_coverage": 0.0})
    rep = measure(db, scfg)
    assert select_cells(rep, scfg, 8) == select_cells(rep, scfg, 8)


def test_unknown_is_never_a_generation_target(tmp_path):
    db = _db(tmp_path, _rows(3, 3, blanks=20))
    scfg = SamplerConfig.from_mapping({"enabled": True, "min_coverage": 0.0})
    rep = measure(db, scfg)
    assert rep.axes["audience"].counts[UNKNOWN] == 20
    cells = select_cells(rep, scfg, 10)
    assert cells, "expected cells once min_coverage lets the axis through"
    assert all(UNKNOWN not in c.values() for c in cells)


def test_configured_domain_widens_beyond_what_was_observed(tmp_path):
    db = _db(tmp_path, _rows(5, 5))
    scfg = SamplerConfig.from_mapping({"enabled": True, "axes": ["audience"]})
    rep = measure(db, scfg)
    dom = ["smb_owner", "retiree_cohort", "software_developer", "agency_owner"]
    picked = {c["audience"] for c in select_cells(rep, scfg, 8, domains={"audience": dom})}
    assert {"software_developer", "agency_owner"} <= picked


def test_cells_do_not_lock_to_the_diagonal(tmp_path):
    db = _db(tmp_path, _rows(5, 5))
    scfg = SamplerConfig.from_mapping({"enabled": True, "min_coverage": 0.0})
    rep = measure(db, scfg)
    cells = select_cells(rep, scfg, 12, domains={
        "structural_form": [f"f{i}" for i in range(4)],
        "audience": [f"a{i}" for i in range(3)],
    })
    pairs = {(c["structural_form"], c["audience"]) for c in cells}
    assert len(pairs) >= 8, f"only {len(pairs)} distinct cells: {sorted(pairs)}"


def test_context_is_stamped_onto_every_cell(tmp_path):
    db = _db(tmp_path, _rows(5, 5))
    scfg = SamplerConfig.from_mapping({"enabled": True, "min_coverage": 0.0})
    rep = measure(db, scfg, context={"market": "uk"})
    assert all(c["market"] == "uk" for c in select_cells(rep, scfg, 5))


def test_cell_directive_reads_as_a_constraint():
    assert cell_directive({"structural_form": "local_service", "audience": "smb_owner"}) == (
        "structural_form=local_service; audience=smb_owner")


# ---------------------------------------------------------------------------- wire-in


def test_plan_cells_is_inert_when_disabled(tmp_path):
    _db(tmp_path, _rows(9, 4))
    assert plan_cells(_cfg(tmp_path), 8) == []
    assert plan_cells(_cfg(tmp_path, enabled=False), 8) == []


def test_plan_cells_returns_cells_when_enabled(tmp_path):
    _db(tmp_path, _rows(9, 4))
    cells = plan_cells(_cfg(tmp_path, enabled=True, min_coverage=0.0), 6,
                       domains={"structural_form": ["x", "y"], "audience": ["p", "q"]})
    assert len(cells) == 6
    assert all(c["structural_form"] in {"x", "y"} for c in cells)


def test_plan_cells_never_raises(tmp_path):
    # missing index, invalid config, unreadable file: all must degrade to the rotation.
    assert plan_cells(_cfg(tmp_path / "nope", enabled=True), 4) == []
    _db(tmp_path, _rows(9, 4))
    assert plan_cells(_cfg(tmp_path, enabled=True, axes=["sector"]), 4) == []
    assert plan_cells(SimpleNamespace(coverage_sampler={"enabled": True}), 4) == []
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "prospector.db").write_text("not a database", encoding="utf-8")
    assert plan_cells(_cfg(broken, enabled=True), 4) == []


def test_receipt_is_json_able(tmp_path):
    import json
    _db(tmp_path, _rows(9, 4, blanks=2))
    r = receipt(_cfg(tmp_path, enabled=True, min_coverage=0.0), 4)
    json.dumps(r)
    assert r["coverage"]["rows"] == 15
    assert r["coverage"]["axes"]["structural_form"]["unknown"] == 2
    assert len(r["cells"]) == 4


# ------------------------------------------------------- generate.py integration seam


class _NullOp:
    """An operator that returns no candidates — this test measures the CELL, not the LLM."""

    def complete_json(self, system, user, temperature=0.9):
        return []


def _gen_cfg_double(tmp_path):
    # generate() only needs these attributes; market_kwargs() raises AttributeError on a
    # namespace, which generate() already handles as "no markets configured".
    return SimpleNamespace(
        generation={
            "candidates_per_signal": 2, "max_per_call": 1, "max_rounds": 1,
            "structural_forms": ["form_a", "form_b"],
            "audience_forms": ["aud_a", "aud_b"],
            "refinement_enabled": False,
        },
        personas={}, active_persona="", store_dir=tmp_path, coverage_sampler={},
    )


def test_generation_wire_in_is_inert_by_default_and_owns_the_cell_when_on(tmp_path, monkeypatch):
    import prospector.generate as gen

    seen: dict[str, object] = {}

    def fake_plan(cfg, k, **kw):
        seen["k"] = k
        seen["domains"] = kw.get("domains")
        return list(seen.get("cells") or [])

    assigned: list[tuple[str, str]] = []

    def spy_render(name, **kw):
        assigned.append((kw.get("structural_form", ""), kw.get("audience_persona", "")))
        return ("system", "user")

    monkeypatch.setattr(gen, "plan_cells", fake_plan)
    monkeypatch.setattr(gen, "render", spy_render)

    cfg = _gen_cfg_double(tmp_path)

    # (a) sampler silent (the default: plan_cells returns []) => the rotation still decides.
    gen.generate(_NullOp(), cfg, k=2)
    assert seen["k"] == 2
    assert seen["domains"] == {"structural_form": ["form_a", "form_b"],
                               "audience": ["aud_a", "aud_b"]}
    assert {f for f, _a in assigned} <= {"form_a", "form_b"}
    assert {a for _f, a in assigned} <= {"aud_a", "aud_b"}

    # (b) sampler speaking => its cell overrides the rotation on both axes.
    assigned.clear()
    seen["cells"] = [{"structural_form": "form_z", "audience": "aud_z"}]
    gen.generate(_NullOp(), cfg, k=2)
    assert assigned, "generation made no calls"
    assert {f for f, _a in assigned} == {"form_z"}
    assert {a for _f, a in assigned} == {"aud_z"}


def test_generation_default_config_never_reaches_the_db(tmp_path, monkeypatch):
    """With no `coverage_sampler` block at all, the sampler must not even open an index."""
    import prospector.coverage as cov
    import prospector.generate as gen

    monkeypatch.setattr(gen, "render", lambda name, **kw: ("system", "user"))
    monkeypatch.setattr(cov, "measure", lambda *a, **kw: pytest.fail("sampler measured"))
    cfg = _gen_cfg_double(tmp_path)
    del cfg.coverage_sampler  # a Config predating V2
    gen.generate(_NullOp(), cfg, k=2)


# ----------------------------------------------------------------- vocabulary drift
#
# `sampling_domains` falls back to `cov.observed` when no configured domain is supplied,
# and the catalogue is NOT the same set as what generation can produce. Measured
# 2026-08-08 on store/prospector.db: `structural_form` holds 29 distinct values against
# the 8 in `config.yaml generation.structural_forms` — 21 of them (421 rows) are
# vocabularies from earlier configs, still arriving because the drain keeps vetting
# candidates minted under them. `generate.py:273` does supply the configured domain, so
# the shipped path is correct; these tests pin that, and make the drift measurable
# instead of leaving it to be re-discovered by hand.

def _drifted(tmp_path):
    rows = _rows(6, 4)                      # 6 vertical_tool (configured) + 4 local_service
    return _db(tmp_path, rows, name="drift.db")


def test_off_domain_values_names_the_drift_with_counts(tmp_path):
    rep = measure(_drifted(tmp_path), SamplerConfig.from_mapping(
        {"enabled": True, "axes": ["structural_form"]}))
    drift = off_domain_values(rep, {"structural_form": ["vertical_tool", "marketplace"]})

    assert drift == {"structural_form": {"local_service": 4}}, (
        "the meter must name the off-domain value AND how many rows carry it")


def test_off_domain_is_silent_when_corpus_and_config_agree(tmp_path):
    rep = measure(_drifted(tmp_path), SamplerConfig.from_mapping(
        {"enabled": True, "axes": ["structural_form"]}))
    assert off_domain_values(rep, {"structural_form": ["vertical_tool", "local_service"]}) == {}


def test_off_domain_says_nothing_rather_than_flagging_everything(tmp_path):
    """No configured domain for an axis is not evidence that all its values are wrong.

    Two of the four axes (`ambition_tier`, `market`) have no vocabulary under
    `generation` at all. Reporting drift there would make the meter fire forever on a
    condition that is correct, and a meter that always fires is not read.
    """
    rep = measure(_drifted(tmp_path), SamplerConfig.from_mapping(
        {"enabled": True, "axes": ["structural_form"]}))
    assert off_domain_values(rep, None) == {}
    assert off_domain_values(rep, {"structural_form": []}) == {}


def test_the_receipt_carries_the_drift_meter(tmp_path):
    cfg = _cfg(tmp_path, enabled=True, axes=["structural_form"])
    r = receipt(cfg, 4, domains={"structural_form": ["vertical_tool"]},
                db_path=_drifted(tmp_path))
    assert r["off_domain"] == {"structural_form": {"local_service": 4}}
    json.dumps(r)       # a receipt that cannot be written is not a receipt


def test_an_unsupplied_domain_targets_the_catalogue_not_the_config(tmp_path):
    """Pins the trap itself: forgetting `domains=` aims the quota at unreachable values.

    `local_service` is in the index but not in the configured vocabulary here, so the
    fallback selects a form `prompts/generate.md` can no longer be asked for — and the
    deficit never closes, because the target is unreachable.
    """
    rep = measure(_drifted(tmp_path), SamplerConfig.from_mapping(
        {"enabled": True, "axes": ["structural_form"]}))
    scfg = SamplerConfig.from_mapping({"enabled": True, "axes": ["structural_form"]})

    forgot = sampling_domains(rep, scfg)["structural_form"]
    supplied = sampling_domains(rep, scfg, {"structural_form": ["vertical_tool"]})[
        "structural_form"]

    assert "local_service" in forgot, "the fallback really does target the catalogue"
    assert supplied == ["vertical_tool"], "a supplied domain must be the whole answer"
