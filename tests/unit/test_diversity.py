"""Tests for the per-batch diversity meter (G1) — prospector.diversity.

Distinct-k / per-axis entropy are pure-stdlib signals used to monitor batch
quality over time. These tests pin the clustering behaviour so the meter
cannot drift into collapsing distinct ideas OR into over-splitting reworded
clusters.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from prospector.diversity import (
    _entropy,
    batch_report,
    distinct_k,
    write_receipt,
)


class _Cand(SimpleNamespace):
    """SimpleNamespace pretending to be a Candidate — the meter only reads
    attributes by name, so this is enough. Using SimpleNamespace (not a dataclass)
    so the test file matches the lightweight fake-store style elsewhere in the
    suite (test_adaptive_persona.MockStore)."""

    def __init__(self, title: str, one_liner: str = "", *,
                 structural_form: str = "", audience: str = "",
                 market: str = "", ambition_tier: str = "",
                 tags: dict[str, Any] | None = None):
        # Pass everything through kwargs so SimpleNamespace accepts arbitrary
        # attributes (its __init__ does not allow positional args beyond the
        # first namespace source).
        super().__init__(
            title=title, one_liner=one_liner,
            structural_form=structural_form, audience=audience,
            market=market, ambition_tier=ambition_tier,
            tags=(tags if tags is not None else ({"audience": audience} if audience else {})),
        )


def test_distinct_k_clusters_near_duplicates():
    """Three rewordings of the same idea collapse to a single cluster; two
    genuinely different ideas form their own clusters -> distinct_k == 3."""
    one_liner = "Local produce broker for older growers"
    cands = [
        _Cand(title="Retiree garden harvest share", one_liner=one_liner),
        _Cand(title="Retiree's garden legacy harvest", one_liner=one_liner),
        _Cand(title="Garden harvest share for retirees", one_liner=one_liner),
        _Cand(title="The Vet's Fee Extractor",
              one_liner="Surgical invoicing auditor for vet practices"),
        _Cand(title="The Solo Builder's Warranty Audit",
              one_liner="Claims review service for self-builders"),
    ]
    assert distinct_k(cands) == 3


def test_distinct_k_all_distinct():
    """Four unrelated ideas stay four clusters."""
    cands = [
        _Cand(title="The Vet's Fee Extractor",
              one_liner="Surgical invoicing auditor for vet practices"),
        _Cand(title="The Solo Builder's Warranty Audit",
              one_liner="Claims review service for self-builders"),
        _Cand(title="The Tradie's Time-Capture Agent",
              one_liner="Job-hour reconciliation for sole traders"),
        _Cand(title="The Garden Office Power Broker",
              one_liner="Negotiation desk for garden-office landlords"),
    ]
    assert distinct_k(cands) == 4


def test_batch_report_axes_and_entropy():
    """Two-value uniform axis -> entropy 1.0; single value -> entropy 0.0;
    empty batch -> n 0 and distinct_ratio 0.0 (no division by zero)."""
    # Uniform two-value structural_form axis.
    cands_uniform = [
        _Cand(title=f"Idea {i}", one_liner="x", structural_form="a" if i < 2 else "b")
        for i in range(4)
    ]
    rep = batch_report(cands_uniform)
    assert rep["n"] == 4
    assert rep["axes"]["structural_form"]["entropy"] == pytest.approx(1.0)
    assert rep["axes"]["structural_form"]["histogram"] == {"a": 2, "b": 2}

    # Single-value axis -> entropy 0.0 (one bucket = no information).
    cands_same = [
        _Cand(title=f"Idea {i}", one_liner="x", structural_form="a")
        for i in range(3)
    ]
    rep_same = batch_report(cands_same)
    assert rep_same["axes"]["structural_form"]["entropy"] == 0.0
    assert rep_same["axes"]["structural_form"]["histogram"] == {"a": 3}

    # Empty batch — no division by zero, all overlap stats are 0.0.
    rep_empty = batch_report([])
    assert rep_empty["n"] == 0
    assert rep_empty["distinct_ratio"] == 0.0
    assert rep_empty["distinct_k"] == 0
    assert rep_empty["mean_pairwise_overlap"] == 0.0
    assert rep_empty["max_pairwise_overlap"] == 0.0
    for axis in ("structural_form", "audience", "market", "ambition_tier"):
        assert rep_empty["axes"][axis]["histogram"] == {}
        assert rep_empty["axes"][axis]["entropy"] == 0.0


def test_entropy_empty_and_single_bucket():
    """Direct unit-test of _entropy's guard rails."""
    assert _entropy({}) == 0.0
    assert _entropy({"only": 5}) == 0.0
    # Three-way uniform -> log2(3)/log2(3) == 1.0.
    assert _entropy({"a": 1, "b": 1, "c": 1}) == pytest.approx(1.0)
    # Skewed distribution -> entropy strictly between 0 and 1.
    h = _entropy({"a": 9, "b": 1})
    assert 0.0 < h < 1.0


def test_write_receipt_gated_and_appends(tmp_path, monkeypatch):
    """Gated ON: appends one JSONL row, returns the record. Gated OFF: None
    and no file is created.

    The env override is cleared so this pins the PRODUCTION resolution path
    (cfg.store_dir); the autouse conftest fence would otherwise redirect it."""
    monkeypatch.delenv("PROSPECTOR_GENERATION_ARTIFACT_DIR", raising=False)
    cands = [_Cand(title="Idea one", one_liner="x"),
             _Cand(title="Idea two", one_liner="y")]

    cfg_on = SimpleNamespace(
        generation={"diversity_meter": True},
        store_dir=str(tmp_path),
    )
    record = write_receipt(cfg_on, "generated", cands)
    assert record is not None
    assert record["stage"] == "generated"
    assert record["n"] == 2

    out_file = tmp_path / "generation_metrics.jsonl"
    assert out_file.exists()
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["stage"] == "generated"
    assert parsed["n"] == 2

    # Gate OFF -> no-op, no file.
    other = tmp_path / "other"
    cfg_off = SimpleNamespace(
        generation={},   # diversity_meter absent
        store_dir=str(other),
    )
    assert write_receipt(cfg_off, "generated", cands) is None
    assert not (other / "generation_metrics.jsonl").exists()


def test_write_receipt_never_raises(tmp_path, monkeypatch):
    """A store_dir under an existing FILE (mkdir(parents=True) fails) must be
    swallowed, not raised into the generation path. Returns None on failure."""
    monkeypatch.delenv("PROSPECTOR_GENERATION_ARTIFACT_DIR", raising=False)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")   # any file at this path blocks mkdir
    bad_dir = blocker / "nested"            # parent is a file, mkdir will fail
    cfg = SimpleNamespace(
        generation={"diversity_meter": True},
        store_dir=str(bad_dir),
    )
    cands = [_Cand(title="Idea one", one_liner="x")]
    # Should NOT raise — broad except inside write_receipt absorbs the OSError.
    result = write_receipt(cfg, "generated", cands)
    assert result is None


# ---- G4 typicality observability --------------------------------------------


def test_typicality_stats_reported():
    """Three candidates with valid typicality tags => n_reported 3, mean ~0.4,
    atypical_fraction ~2/3 under atypical_threshold=0.3."""
    cands = [
        _Cand(title="Idea A", one_liner="x", tags={"typicality": 0.1}),
        _Cand(title="Idea B", one_liner="x", tags={"typicality": 0.9}),
        _Cand(title="Idea C", one_liner="x", tags={"typicality": 0.2}),
    ]
    rep = batch_report(cands, atypical_threshold=0.3)
    t = rep["typicality"]
    assert t["n_reported"] == 3
    assert t["mean"] == pytest.approx(0.4)
    assert t["atypical_fraction"] == pytest.approx(2 / 3)


def test_typicality_absent_is_zeroed():
    """No typicality tag => n_reported 0, mean 0.0, atypical_fraction 0.0.

    A bool tag is NOT a typicality — it must be ignored (not coerced to 1.0/0.0)
    because True/False carries no meaning for typicality, unlike automatability."""
    cands = [
        _Cand(title="Idea A", one_liner="x"),                                # no tag
        _Cand(title="Idea B", one_liner="x", tags={"typicality": True}),    # bool -> ignored
        _Cand(title="Idea C", one_liner="x", tags={"typicality": False}),   # bool -> ignored
        _Cand(title="Idea D", one_liner="x", tags={"typicality": "x"}),     # bad type -> ignored
    ]
    rep = batch_report(cands, atypical_threshold=0.3)
    t = rep["typicality"]
    assert t["n_reported"] == 0
    assert t["mean"] == 0.0
    assert t["atypical_fraction"] == 0.0
