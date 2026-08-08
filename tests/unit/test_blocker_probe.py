"""`scripts/blocker_probe.py` must not misreport its own inputs.

The probe exists because the programme register twice carried an item as "blocked"
when it was not, and once quoted a figure ("172 price views / 90 days") whose only
origin is a source comment — a note, not a receipt, and not re-derivable. A tracking
probe that reads the wrong key, or the wrong FILE, or quotes a retracted number, is
that same failure wearing the fix's clothes — so every defect the probe had on its
first runs is pinned here.

Five real defects, all caught by running it:

1. `probe_e6` read a verdict straight out of the receipts file without checking
   `_meta.argv`. The only receipts on disk were from `--limit 200`, so it would have
   reported a bar verdict computed on a truncated corpus.
2. `probe_e5` looked for the per-axis batch requirement in `axes`. It lives in
   `batch_noise`; `axes` carries entropy/coverage only, so the probe printed
   "per-axis need=run E5" while the receipt held the numbers.
3. `probe_e2` derived "which personas are missing" by filtering its own GROUP BY for
   `count == 0`. A GROUP BY can only return values that OCCUR, so that filter is
   unsatisfiable and the absent arms — the entire point — could never be reported.
4. `probe_numeric_citation` dumped the whole summary dict, whose `untraceable_rate`
   deliberately keeps its old LUMPED meaning for back-compat
   (COMMERCIAL_READINESS_PROGRAM.md:2931). Printing it unlabelled re-publishes the
   38.0% that §31.1 retracted.
5. `probe_matched_pair` read `<stem>_receipts.json` while telling you to run the
   experiment with `--all`, which `runner.py:223` writes to `<stem>_full_receipts.json`.
   The probe measured a file its own reproduce command never writes, so it would have
   reported the pair BLOCKED forever — including after the pair actually landed. This
   is the worst failure mode available to a tracking probe: a permanent red that no
   amount of correct work can clear.

Everything is driven against a fixture ROOT in tmp_path. Nothing reads the real
store, and nothing writes anywhere.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO / "scripts" / "blocker_probe.py"

CONFIG = """\
active_persona: ""
personas:
  academic:
    generation_bias: "a"
  minimalist:
    generation_bias: "b"
  shark:
    generation_bias: "c"
coverage_sampler:
  enabled: false
"""


@pytest.fixture
def probe(tmp_path, monkeypatch):
    """Load the probe with ROOT pointed at a fixture tree."""
    spec = importlib.util.spec_from_file_location("blocker_probe_uut", PROBE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "config.yaml").write_text(CONFIG)
    return mod


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


# --------------------------------------------------------------------------- #
# 1. a smoke run is not an answer
# --------------------------------------------------------------------------- #

E6B_RECEIPTS = "tools/experiments/e6b_prefilter_pass_safety_receipts.json"


def test_e6_refuses_to_quote_a_limited_run(probe, tmp_path):
    """A `--limit` receipt is shaped exactly like a real one. Reading a verdict off
    it is 'truncate the evidence, then classify the truncation'."""
    _write(tmp_path / E6B_RECEIPTS, {
        "verdict": "MEETS_BAR",
        "safe_no_pass_no_defer": {"drop_rate": 0.91},
        "_meta": {"argv": ["--limit", "200"]},
    })
    row = probe.probe_e6()
    assert row["state"] == probe.BLOCKED
    # the verdict and its headline rate must not leak into the output at all
    assert "MEETS_BAR" not in row["measured"]
    assert "91" not in row["measured"]
    assert "SMOKE" in row["measured"]


def test_e6_reports_a_full_run(probe, tmp_path):
    """The refusal must be specific to truncation, not a blanket refusal — otherwise
    the item can never be closed."""
    _write(tmp_path / E6B_RECEIPTS, {
        "verdict": "FAILS_BAR",
        "safe_no_pass_no_defer": {"drop_rate": 0.0123},
        "_meta": {"argv": []},
    })
    row = probe.probe_e6()
    assert row["state"] == probe.DEAD
    assert "FAILS_BAR" in row["measured"]
    assert "1.23%" in row["measured"]


def test_e6_tolerates_a_missing_safe_row(probe, tmp_path):
    """`safe_no_pass_no_defer` is None when nothing is safe at any threshold. The
    probe must render that, not raise on `None * 100`."""
    _write(tmp_path / E6B_RECEIPTS, {
        "verdict": "FAILS_BAR", "safe_no_pass_no_defer": None, "_meta": {"argv": []},
    })
    row = probe.probe_e6()
    assert row["state"] == probe.DEAD
    assert "FAILS_BAR" in row["measured"]


# --------------------------------------------------------------------------- #
# 2. the per-axis requirement lives in batch_noise
# --------------------------------------------------------------------------- #

E5_RECEIPTS = "tools/experiments/e5_coverage_sampler_entropy_receipts.json"
E5_SHAPE = {
    "axes": {"ambition_tier": {"h_norm": 0.68}, "structural_form": {"h_norm": 0.83}},
    "batch_noise": {
        "ambition_tier": {"sd": 0.1613, "batches_for_target_mde": 41},
        "structural_form": {"sd": 0.0525, "batches_for_target_mde": 5},
        "audience": {"sd": 0.0595, "batches_for_target_mde": 6},
        "market": {"sd": 0.1589, "batches_for_target_mde": 40},
    },
    "headline": {"batches_per_arm_for_target": 41},
}


def test_e5_reads_the_per_axis_need_not_the_headline_max(probe, tmp_path):
    """The headline 41 is a max() across axes and hides that two axes are 7x cheaper.
    Reading `axes` instead of `batch_noise` yields an empty need — the original bug."""
    _write(tmp_path / E5_RECEIPTS, E5_SHAPE)
    row = probe.probe_e5()
    assert "batches/arm at mde=0.10 per axis={" in row["measured"]
    assert "'structural_form': 5" in row["measured"]
    assert "'audience': 6" in row["measured"]
    # the BAR must be scoped to the axes that can actually move
    assert row["bar"].startswith("6 batches/arm on")
    assert "audience" in row["bar"] and "structural_form" in row["bar"]
    assert "ambition_tier" not in row["bar"] and "market" not in row["bar"]


def test_e5_falls_back_when_the_receipt_is_absent(probe):
    """No receipt must produce an honest 'run E5', never a fabricated number."""
    row = probe.probe_e5()
    assert row["bar"] == "run E5 to derive the per-axis requirement"


def test_e5_state_follows_the_config_flag(probe, tmp_path):
    _write(tmp_path / E5_RECEIPTS, E5_SHAPE)
    assert probe.probe_e5()["state"] == probe.BLOCKED
    (tmp_path / "config.yaml").write_text(CONFIG.replace(
        "coverage_sampler:\n  enabled: false", "coverage_sampler:\n  enabled: true"))
    assert probe.probe_e5()["state"] == probe.OK


# --------------------------------------------------------------------------- #
# 3. the absent arms are the ones a GROUP BY cannot show
# --------------------------------------------------------------------------- #

def _make_db(path: Path, personas: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("create table dossiers (candidate_id text, persona text)")
        conn.executemany("insert into dossiers values (?, ?)",
                         [(str(i), p) for i, p in enumerate(personas)])
        conn.commit()
    finally:
        conn.close()


def test_e2_reports_personas_with_no_rows_at_all(probe, tmp_path):
    """`count == 0` over a GROUP BY is unsatisfiable: the missing set must be derived
    by subtracting observed values from the CONFIGURED ones."""
    _make_db(tmp_path / "store/prospector.db", ["", "", "", "shark"])
    row = probe.probe_e2()
    assert "missing=['academic', 'minimalist']" in row["measured"]
    assert "{'shark': 1}" in row["measured"]
    assert "unlabelled=3/4" in row["measured"]


def test_e2_missing_is_empty_when_every_persona_has_rows(probe, tmp_path):
    """Guards the subtraction against always reporting everything as missing."""
    _make_db(tmp_path / "store/prospector.db", ["academic", "minimalist", "shark"])
    assert "missing=[]" in probe.probe_e2()["measured"]


def test_e2_survives_an_unreadable_index(probe):
    """No db at all is an unknown, not a crash."""
    row = probe.probe_e2()
    assert row["state"] == probe.BLOCKED
    assert "missing=['academic', 'minimalist', 'shark']" in row["measured"]


# --------------------------------------------------------------------------- #
# configured-persona parsing, both routes
# --------------------------------------------------------------------------- #

def test_configured_personas_yaml_route(probe):
    assert probe._configured_personas() == ["academic", "minimalist", "shark"]


def test_configured_personas_text_fallback(probe, monkeypatch):
    """The probe is documented as runnable under a bare `python3`, so the fallback
    parser must return the same answer PyYAML does."""
    monkeypatch.setitem(sys.modules, "yaml", None)   # makes `import yaml` raise
    assert probe._configured_personas() == ["academic", "minimalist", "shark"]


def test_configured_personas_is_empty_without_a_config(probe, tmp_path):
    """[] makes `missing` empty rather than inventing persona names."""
    (tmp_path / "config.yaml").unlink()
    assert probe._configured_personas() == []


# --------------------------------------------------------------------------- #
# 5. read the file the reproduce command actually writes
# --------------------------------------------------------------------------- #

def _pair(tmp_path, suffix, sha15, sha17, frozen=True):
    for stem, sha in (("e15_hhem_groundedness", sha15),
                      ("e17_hhem_moat_agreement", sha17)):
        _write(tmp_path / "tools/experiments" / f"{stem}{suffix}_receipts.json",
               {"corpus_fingerprint": {"sha256": sha, "frozen": frozen}})


def test_matched_pair_prefers_the_full_run_receipt(probe, tmp_path):
    """The reproduce command runs `--all`, which writes `_full_receipts.json`. Reading
    only the unsuffixed file makes the probe a permanent red that correct work cannot
    clear."""
    _pair(tmp_path, "", "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", frozen=False)
    _pair(tmp_path, "_full", "cccccccccccccccc", "cccccccccccccccc")
    row = probe.probe_matched_pair()
    assert row["state"] == probe.OK
    assert "cccccccccccccccc" in row["measured"]
    assert "aaaaaaaaaaaaaaaa" not in row["measured"]


def test_matched_pair_names_the_files_it_compared(probe, tmp_path):
    """A fingerprint with no filename beside it cannot be traced back to a run."""
    _pair(tmp_path, "_full", "dddddddddddddddd", "dddddddddddddddd")
    measured = probe.probe_matched_pair()["measured"]
    assert "e15_hhem_groundedness_full_receipts.json" in measured
    assert "e17_hhem_moat_agreement_full_receipts.json" in measured


def test_matched_pair_falls_back_to_the_unsuffixed_receipt(probe, tmp_path):
    """Before any `--all` run exists, the plain receipts are still the best evidence."""
    _pair(tmp_path, "", "eeeeeeeeeeeeeeee", "ffffffffffffffff", frozen=False)
    row = probe.probe_matched_pair()
    assert row["state"] == probe.BLOCKED
    assert "e15_hhem_groundedness_receipts.json" in row["measured"]


def test_matched_pair_is_blocked_when_a_receipt_is_missing(probe):
    """Absent evidence is not a match. Two Nones are equal in Python; they are not a
    matched pair."""
    row = probe.probe_matched_pair()
    assert row["state"] == probe.BLOCKED
    assert "(no receipt)" in row["measured"]


# --------------------------------------------------------------------------- #
# 4. never re-publish the retracted rate unlabelled
# --------------------------------------------------------------------------- #

def test_numeric_citation_labels_the_lumped_rate(probe, monkeypatch):
    """`untraceable_rate` keeps its pre-correction meaning on purpose. The probe must
    name it as lumped and carry §31.1's decision figure beside it."""
    monkeypatch.setattr(
        probe, "_json", lambda p: {})
    import types
    fake = types.ModuleType("prospector.numeric_citation")
    fake.summarise_shadow_log = lambda p: {
        "rows": 132, "figures": 92, "untraceable_rate": 0.3804, "split_figures": 0}
    monkeypatch.setitem(sys.modules, "prospector.numeric_citation", fake)
    # a log must exist for the summariser to be reached
    logs = probe.ROOT / "store/numeric_citation_shadow"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "shadow-2026-08-08.jsonl").write_text("{}\n")

    row = probe.probe_numeric_citation()
    assert "lumped_untraceable_rate=38.0%" in row["measured"]
    assert "NOT the decision figure" in row["measured"]
    assert "9.7%" in row["measured"]


# --------------------------------------------------------------------------- #
# the runner's own contract
# --------------------------------------------------------------------------- #

def test_a_raising_probe_is_unmeasurable_and_exits_nonzero(probe, monkeypatch, capsys):
    """'An unmeasurable blocker is an unknown, not a blocker' — and it must be loud."""
    def boom():
        raise RuntimeError("input gone")
    monkeypatch.setattr(probe, "PROBES", (boom,))
    assert probe.main([]) == 1
    out = capsys.readouterr().out
    assert probe.UNKNOWN in out
    assert "input gone" in out


def test_json_mode_emits_every_row(probe, monkeypatch, capsys):
    monkeypatch.setattr(probe, "PROBES", (probe.probe_e5, probe.probe_e2))
    assert probe.main(["--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 2
    assert {"item", "bar", "measured", "state", "note", "cmd"} <= set(rows[0])
