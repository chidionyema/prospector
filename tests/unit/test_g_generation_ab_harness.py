"""The A/B harness must refuse to turn an outage into a finding.

Both defects pinned here shipped and produced a wrong result on 2026-08-08: a live run
hit the Claude usage wall, recorded five `0/0` cells as real observations, reported
`shipped -6.00` and `g8_critique_revise -1.50` as if they were effects of the levers,
and stamped the whole thing `complete: true`. The numbers were an outage.

These are tests of the RULER, not of the levers. They run entirely offline.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _harness():
    """Import the harness by path; `tools/` is not a package."""
    path = ROOT / "tools" / "experiments" / "g_generation_ab.py"
    spec = importlib.util.spec_from_file_location("g_generation_ab_under_test", path)
    assert spec and spec.loader, path
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


#: Deliberately unrelated vocabulary. `distinct_k` collapses near-duplicates on shared
#: title+one_liner tokens, so a lazy fixture ("Idea 0/1/2 ... a thing for buyer N")
#: scores distinct_k=1 and makes a healthy harness look broken.
_IDEAS = [
    ("Kerbside battery swaps", "Scooter fleets rent charged packs from corner shops"),
    ("Abattoir cold-chain audit", "Meat wholesalers prove temperature compliance hourly"),
    ("Dialect voice fonts", "Regional broadcasters licence synthetic presenters"),
    ("Marina berth arbitrage", "Yacht owners sublet unused moorings by the night"),
    ("Foundry scrap assay", "Metal recyclers price loads from a phone photo"),
    ("Parish burial records", "Genealogists search digitised churchyard ledgers"),
]


def _c(i):
    """One Candidate-shaped stub; `batch_report` reads attributes defensively."""
    title, one_liner = _IDEAS[i % len(_IDEAS)]

    class _C:
        pass

    c = _C()
    c.title = title
    c.one_liner = one_liner
    c.structural_form = ["saas", "marketplace", "service"][i % 3]
    c.market = ["uk", "us", "eu"][i % 3]
    c.ambition_tier = ["incremental", "ambitious", "moonshot"][i % 3]
    c.tags = {"audience": ["smb", "enterprise", "prosumer"][i % 3]}
    return c


# ---------------------------------------------------------------------------
# Defect 1: an empty batch is an abort, not a zero.
# ---------------------------------------------------------------------------

def test_empty_batch_raises_instead_of_scoring_zero(monkeypatch):
    """`generate()` returning [] must raise, never reach `batch_report`.

    This is the whole defect. `batch_report([])` is perfectly well-formed and returns
    `distinct_k=0, n=0`, which is indistinguishable downstream from a real batch of
    identical ideas.
    """
    mod = _harness()

    import prospector.generate as gen_mod
    monkeypatch.setattr(gen_mod, "generate", lambda *a, **kw: [])

    with pytest.raises(mod.EmptyBatch) as ei:
        mod._run_cell(op=object(), cfg=object(), signal_text="anything", k=6)

    # The message must name the outage, so a receipt reader is not left guessing.
    assert "0 of 6" in str(ei.value)
    assert ei.value.calls == 0


def test_a_non_empty_batch_still_reports_normally(monkeypatch):
    """The converse. A guard that rejects everything would pass the test above."""
    mod = _harness()

    import prospector.generate as gen_mod

    monkeypatch.setattr(gen_mod, "generate",
                        lambda *a, **kw: [_c(i) for i in range(6)])

    rep, made = mod._run_cell(op=object(), cfg=object(), signal_text="x", k=6)
    assert rep["n"] == 6
    # Six lexically unrelated ideas, so the ruler should see six of them. If this ever
    # collapses, the fixture has drifted into near-duplicates, not the code.
    assert rep["distinct_k"] == 6
    assert made == 0


def test_empty_batch_carries_its_spend():
    """An aborted cell still cost money; the receipt must not lose it."""
    mod = _harness()
    e = mod.EmptyBatch("boom", calls=3)
    assert e.calls == 3


# ---------------------------------------------------------------------------
# Defect 2: distinct_k saturation is announced, not printed as +0.00.
# ---------------------------------------------------------------------------

def test_saturation_detected_when_every_cell_is_a_full_house():
    """All 19 non-empty cells of the 2026-08-08 live run scored exactly 6/6."""
    mod = _harness()
    cells = {
        f"sig#{r}": {arm: {"distinct_k": 6, "n": 6} for arm in ("baseline", "g3_denylist")}
        for r in range(4)
    }
    assert mod._distinct_k_saturated(cells) is True


def test_saturation_not_claimed_when_a_single_cell_has_headroom():
    """One cell below the ceiling proves the ruler still discriminates."""
    mod = _harness()
    cells = {
        "sig#0": {"baseline": {"distinct_k": 6, "n": 6}, "g3_denylist": {"distinct_k": 6, "n": 6}},
        "sig#1": {"baseline": {"distinct_k": 4, "n": 6}, "g3_denylist": {"distinct_k": 6, "n": 6}},
    }
    assert mod._distinct_k_saturated(cells) is False


def test_no_cells_is_not_saturated():
    """An aborted run must not claim a property of data it never collected."""
    mod = _harness()
    assert mod._distinct_k_saturated({}) is False


def test_a_saturated_run_says_so_on_stdout_and_in_the_receipt(monkeypatch, tmp_path,
                                                              capsys):
    """The detector is useless if the report still reads as a confident null.

    `_c` always yields six fully distinct ideas, so every cell scores 6/6 — exactly the
    shape of the 2026-08-08 live run. The operator must be told the ruler hit its
    ceiling, not shown `+0.00` deltas.
    """
    mod = _harness()

    import prospector.generate as gen_mod
    monkeypatch.setattr(gen_mod, "generate", lambda *a, **kw: [_c(i) for i in range(6)])

    out = tmp_path / "receipts.json"
    rc = mod.main([
        "--fixture", "--signals", "1", "--repeats", "1", "--k", "6", "--out", str(out),
    ])

    import json
    receipts = json.loads(out.read_text())
    printed = capsys.readouterr().out

    assert rc == 0, "saturation is a limit of the ruler, not a failed run"
    assert receipts["distinct_k_saturated"] is True
    assert receipts["primary_metric"] == "mean_pairwise_overlap"
    assert "SATURATED" in printed
    assert "not evidence" in printed


# ---------------------------------------------------------------------------
# Fallback tier: the chain may serve a cell from minimax, and a delta that
# crosses brains measures the brain rather than the lever.
# ---------------------------------------------------------------------------

def _cell(dk, n, overlap, provider):
    return {"distinct_k": dk, "n": n, "mean_pairwise_overlap": overlap,
            "_provider": provider}


def test_a_pair_that_crosses_brains_is_dropped_not_averaged():
    """Arms run in the OUTER loop, so a tier flip lands between whole arms.

    baseline on claude_cli vs g3 on minimax is a comparison of two generators. Averaging
    it would report the fallback's personality as an effect of the denylist.
    """
    mod = _harness()
    cells = {
        "sig#0": {"baseline": _cell(6, 12, 0.20, "claude_cli"),
                  "g3_denylist": _cell(9, 12, 0.10, "minimax")},
    }
    got = mod._paired_deltas(cells, "g3_denylist", "distinct_k")
    assert got["n_pairs"] == 0
    assert got["mixed_provider_pairs"] == 1
    assert got["mean_delta"] is None, "a cross-brain delta must never render as a number"


def test_same_brain_pairs_still_compare_normally():
    """The converse: a guard that drops everything would pass the test above."""
    mod = _harness()
    cells = {
        "sig#0": {"baseline": _cell(6, 12, 0.20, "minimax"),
                  "g3_denylist": _cell(9, 12, 0.10, "minimax")},
    }
    got = mod._paired_deltas(cells, "g3_denylist", "distinct_k")
    assert got["n_pairs"] == 1
    assert got["mixed_provider_pairs"] == 0
    assert got["mean_delta"] == 3.0


def test_mixed_pairs_are_dropped_while_clean_pairs_survive():
    """A partial flip must shrink n, not silently poison the surviving pairs."""
    mod = _harness()
    cells = {
        "sig#0": {"baseline": _cell(6, 12, 0.20, "minimax"),
                  "g3_denylist": _cell(8, 12, 0.10, "minimax")},
        "sig#1": {"baseline": _cell(6, 12, 0.20, "claude_cli"),
                  "g3_denylist": _cell(99, 12, 0.01, "minimax")},
    }
    got = mod._paired_deltas(cells, "g3_denylist", "distinct_k")
    assert got["n_pairs"] == 1
    assert got["mixed_provider_pairs"] == 1
    assert got["mean_delta"] == 2.0, "the 99 came from the dropped cross-brain pair"


def test_serving_provider_prefers_the_tier_that_actually_served():
    """`FallbackOperator.name` is the whole chain; only `last_served()` names the tier."""
    mod = _harness()

    class _Chain:
        name = "fallback(claude_cli+minimax)"

        def last_served(self):
            return "minimax"

    class _Plain:
        name = "minimax/MiniMax-M3"

    assert mod._serving_provider(_Chain()) == "minimax"
    assert mod._serving_provider(_Plain()) == "minimax/MiniMax-M3"


def test_serving_provider_falls_back_when_the_chain_has_served_nothing():
    """`last_served()` returns '' before the first successful call."""
    mod = _harness()

    class _Fresh:
        name = "fallback(claude_cli+minimax)"

        def last_served(self):
            return ""

    assert mod._serving_provider(_Fresh()) == "fallback(claude_cli+minimax)"


# ---------------------------------------------------------------------------
# The regression that started all this, replayed end to end.
# ---------------------------------------------------------------------------

def test_the_2026_08_08_outage_shape_would_now_abort(monkeypatch, tmp_path):
    """Replay the exact failure: batches succeed, then the wall opens and they empty.

    Before the fix this run reported `complete: true` with five 0/0 cells folded into
    the deltas. It must now stop at the first empty batch and stamp `complete: false`.
    """
    mod = _harness()

    import prospector.generate as gen_mod

    state = {"n": 0}

    def _wall_after_a_while(*a, **kw):
        state["n"] += 1
        if state["n"] > 3:          # the usage wall opens
            return []
        return [_c(i) for i in range(6)]

    monkeypatch.setattr(gen_mod, "generate", _wall_after_a_while)

    out = tmp_path / "receipts.json"
    rc = mod.main([
        "--fixture", "--signals", "1", "--repeats", "2", "--k", "6",
        "--out", str(out),
    ])

    import json
    receipts = json.loads(out.read_text())

    # The three load-bearing assertions.
    assert rc != 0, "an aborted measurement must not exit 0"
    assert receipts["complete"] is False
    assert "0 of 6" in receipts["stopped_because"]

    # And no 0/0 cell may have been recorded as an observation.
    for cell, by_arm in receipts["raw"].items():
        for arm, rep in by_arm.items():
            assert rep["n"] > 0, f"{arm} {cell} recorded an empty batch as data"
