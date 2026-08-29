"""The meta-diagnostic: is the prose repair turn moving the number it is spent on.

`human_register` says which packs sit outside the human band. It cannot say whether the
repair that exists to fix that is doing anything, because a pack outside the band looks
identical whether the repair ran and failed or never ran at all. Measured 2026-08-21 over
181 model-written artifacts, five days after `listing.human_register_repair` went on:
five of six armed measures were responding, three of them fully, and `hedges_per_1k` had
moved 1%.
"""
import json

import pytest

from ops.automations import prose_repair_effect as pre_mod

# --- the defect this module's own output caught -----------------------------------------

def test_a_value_inside_the_band_is_zero_distance():
    assert pre_mod._outside_distance(2.26, 0.0, 3.72) == 0.0
    assert pre_mod._outside_distance(0.5, 0.0, 3.72) == 0.0


def test_crossing_into_the_band_and_overshooting_scores_as_closed():
    """The first version measured distance to the EDGE and scored this a regression.

    punct_semicolon_per_1k moved 4.58 -> 2.26 against a band of 0.00 - 3.72. That is a
    complete success. Because 2.26 is further from the 3.72 edge than 4.58 was, the edge
    version returned -0.72 and printed "NOT RESPONDING".
    """
    assert pre_mod._closed_fraction(4.58, 2.26, 0.0, 3.72, "above") == pytest.approx(1.0)


def test_a_measure_that_does_not_move_scores_about_zero():
    """hedges_per_1k: 3.51 -> 3.49 against a floor of 5.67."""
    got = pre_mod._closed_fraction(3.51, 3.49, 5.6711, 23.0516, "below")
    assert -0.05 < got < 0.05


def test_moving_further_out_scores_negative():
    assert pre_mod._closed_fraction(10.0, 12.0, 0.0, 5.0, "above") < 0


def test_partial_progress_scores_between():
    """punct_hyphen_per_1k: 31.84 -> 15.61 against a p95 of 7.05."""
    got = pre_mod._closed_fraction(31.84, 15.61, 0.694, 7.0547, "above")
    assert 0.6 < got < 0.7


def test_a_measure_that_started_inside_the_band_is_already_closed():
    assert pre_mod._closed_fraction(2.0, 2.0, 0.0, 5.0, "above") == 1.0


# --- the automation contract -------------------------------------------------------------

def _target(tmp_path, ours_mean, post_hint=None):
    t = tmp_path / "prose_target.json"
    t.write_text(json.dumps({"measured_on": "2026-08-16", "measures": {
        "punct_hyphen_per_1k": {"armed": True, "side": "above", "ours_mean": ours_mean,
                                "p5": 0.694, "p95": 7.0547},
        "sent_len_mean": {"armed": False, "side": "above", "ours_mean": 28.0,
                          "p5": 17.1, "p95": 28.8},
    }}))
    return t


def _decl(tmp_path, target, store, min_docs=30, min_closed=0.10):
    d = tmp_path / "decl.yaml"
    d.write_text(
        f"store_dir: {store}\n"
        f"dossier_glob: '*.pass.json'\n"
        f"prose_keys:\n  - build_spec\n"
        f"target_path: {target.name}\n"
        f"min_closed_fraction: {min_closed}\n"
        f"min_documents: {min_docs}\n")
    return d


def test_a_missing_declaration_cannot_establish_rather_than_passing(tmp_path):
    report = pre_mod.run(tmp_path / "nope.yaml", tmp_path)
    assert report.exit_code == pre_mod.EXIT_UNKNOWN
    assert not report.ok
    assert "not found" in report.reason


def test_an_empty_store_cannot_establish_rather_than_reporting_clean(tmp_path):
    """A near-empty store must never print a perfect score.

    register_baseline.py hardcoded a path holding 0 pass dossiers and printed
    "0 documents, 0.0% outside" and exited clean for weeks.
    """
    store = tmp_path / "store" / "dossiers"
    store.mkdir(parents=True)
    target = _target(tmp_path, 31.84)
    decl = _decl(tmp_path, target, "store/dossiers")
    report = pre_mod.run(decl, tmp_path)
    assert report.exit_code == pre_mod.EXIT_UNKNOWN
    assert "below the declared floor" in report.reason


def test_an_unarmed_measure_is_not_graded(tmp_path):
    """The target declares which measures count. An unarmed one carries no verdict."""
    target = _target(tmp_path, 31.84)
    spec = json.loads(target.read_text())
    assert spec["measures"]["sent_len_mean"]["armed"] is False
    store = tmp_path / "store" / "dossiers"
    store.mkdir(parents=True)
    report = pre_mod.run(_decl(tmp_path, target, "store/dossiers"), tmp_path)
    assert all(r.measure != "sent_len_mean" for r in report.results)


def test_the_json_carries_its_provenance(tmp_path):
    """No black boxes: every figure names where it came from."""
    report = pre_mod.run(tmp_path / "nope.yaml", tmp_path)
    d = report.as_dict()
    for key in ("store", "target", "instrument", "pre_source",
                "documents_graded_after", "documents_graded_before"):
        assert key in d["provenance"], key
    assert d["caveats"], "the caveats must ship with the numbers, not be buried"


def test_there_is_deliberately_no_fix_flag():
    """When a measure stalls the change is English in a diff a person reads."""
    with pytest.raises(SystemExit):
        pre_mod.main(["--fix"])
