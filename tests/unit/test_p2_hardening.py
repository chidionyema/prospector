"""P2 launch-hardening regressions (2026-06-18).

Covers the five non-blocking robustness fixes cleared before launch:
  1. DiskCache TTL — stale cached grounding is re-fetched, not served.
  2. dedup threshold is read from config (tunable without a code change).
  3. _save_pending_signal returns None (not a Path) when the write fails.
  4. Store persists retrieval_degraded and migrates an old DB without that column.
  5. report cost uses telemetry.get_price (no removed PRICING import).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from prospector.config import load_config
from prospector.models import Source
from prospector.retrieval import DiskCache, SearchProvider


# --- 1. DiskCache TTL -------------------------------------------------------
class _CountingProvider(SearchProvider):
    """Inner provider that records how many live searches it served."""
    def __init__(self):
        self.calls = 0

    def search(self, query, k=4, max_chars=1500):
        self.calls += 1
        return [Source(source_id="s1", url="http://example.test", text="evidence")]


def test_diskcache_serves_fresh_hit_without_calling_inner(tmp_path):
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    cache.search("q")            # miss -> 1 live call, writes cache
    cache.search("q")            # fresh hit -> no extra live call
    assert inner.calls == 1


def test_diskcache_refetches_when_entry_is_stale(tmp_path):
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    cache.search("q")            # miss -> writes cache
    # Age the cache file well past the TTL.
    p = cache._path("q", 4, 1500)
    old = p.stat().st_mtime - 7200
    os.utime(p, (old, old))
    cache.search("q")            # stale -> re-fetch
    assert inner.calls == 2


def test_diskcache_ttl_zero_never_expires(tmp_path):
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=0)
    cache.search("q")
    p = cache._path("q", 4, 1500)
    old = p.stat().st_mtime - 10_000_000
    os.utime(p, (old, old))
    cache.search("q")            # ttl_s=0 -> still a hit
    assert inner.calls == 1


# --- 2. dedup threshold from config ----------------------------------------
def test_config_exposes_dedup_threshold_default():
    cfg = load_config()
    assert cfg.dedup_threshold == pytest.approx(0.85)


def test_make_provider_passes_cache_ttl_from_config(tmp_path):
    from prospector.retrieval import make_provider
    cfg = load_config()
    cfg.retrieval.provider = ["fixture"]
    cfg.retrieval.cache = True
    cfg.retrieval.cache_ttl_s = 999
    prov = make_provider(cfg, fixtures={})
    assert isinstance(prov, DiskCache)
    assert prov.ttl_s == 999


# --- 3. pending-signal write failure ---------------------------------------
def test_save_pending_signal_returns_none_on_write_failure(monkeypatch):
    from prospector import run as run_mod
    cfg = load_config()

    def _boom(*a, **k):
        raise OSError("disk full")

    # Force the atomic temp write to fail; the helper must report None, not a Path.
    monkeypatch.setattr(Path, "write_text", _boom)
    result = run_mod._save_pending_signal("some signal", cfg)
    assert result is None


# --- 4. Store retrieval_degraded column + migration ------------------------
def test_old_db_missing_retrieval_degraded_is_migrated(tmp_path):
    """An existing DB without the column must gain it on Store init, not crash."""
    db_dir = tmp_path / "store"
    db_dir.mkdir()
    db_path = db_dir / "prospector.db"
    # Simulate the prior schema: every column EXCEPT retrieval_degraded.
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE dossiers ("
        "candidate_id TEXT PRIMARY KEY, title TEXT, one_liner TEXT, decision TEXT, "
        "gate_fired TEXT, composite REAL, created_at TEXT, reverify_due_at TEXT, "
        "path TEXT, ambition_tier TEXT, structural_form TEXT, provisional INTEGER DEFAULT 0, "
        "dense_reward REAL, adversarial_confidence REAL, persona TEXT)"
    )
    conn.commit()
    conn.close()

    cfg = load_config()
    cfg.store = {"dir": str(db_dir)}
    from prospector.store import Store
    Store(cfg)  # runs _init_db migration

    conn = sqlite3.connect(str(db_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dossiers)")}
    conn.close()
    assert "retrieval_degraded" in cols


# --- 5. report uses get_price (no PRICING import) --------------------------
def test_report_uses_get_price_not_pricing_import():
    import inspect
    from prospector import report
    src = inspect.getsource(report)
    assert "import PRICING" not in src
    assert "get_price" in src


# --- 6. vet --resume: selection + no NameError on the cost summary ----------
def _dossier(title, decision, *, provisional=False):
    from prospector.models import (Candidate, CheckResult, Decision, Dossier,
                                    ScoreResult, Verdict)
    axes = ["pain_acuity", "money_provability", "automatability",
            "distribution", "defensibility", "build_feasibility"]
    return Dossier(
        candidate=Candidate(title=title, one_liner=f"{title} one-liner"),
        decision=decision,
        score=ScoreResult(scores={a: 3 for a in axes},
                          justification={a: "x" for a in axes}, composite=3.0),
        model_version="test-model",
        created_at="2026-06-18T00:00:00+00:00",
        reverify_due_at="2026-09-18T00:00:00+00:00",
        checks=[CheckResult("pain_reality", Verdict.SUPPORTED, 0.5, "ok")],
        provisional=provisional,
    )


def test_resume_revets_deferred_and_provisional_only(tmp_path, monkeypatch):
    """`vet --resume` must pick up DEFER + provisional candidates (not clean PASSes),
    and must run its cost summary to completion without a NameError on log_path."""
    import argparse
    from prospector.models import Decision
    from prospector.store import Store
    from prospector import run as run_mod

    cfg = load_config()
    cfg.store = {"dir": str(tmp_path)}
    store = Store(cfg)

    deferred = _dossier("Deferred Co", Decision.DEFER)
    provisional = _dossier("Provisional Co", Decision.PASS, provisional=True)
    clean = _dossier("Clean Pass", Decision.PASS)
    for d in (deferred, provisional, clean):
        store.save(d)

    revetted: list[str] = []

    def _fake_vet(cand, *a, **k):
        revetted.append(cand.candidate_id)
        return _dossier(cand.title, Decision.PASS)

    monkeypatch.setattr(run_mod, "vet_candidate", _fake_vet)

    log_path = tmp_path / "prospector.jsonl"
    log_path.write_text("", encoding="utf-8")
    args = argparse.Namespace(publish=False, board=False)

    # Must NOT raise (the log_path NameError regression). Then assert selection.
    run_mod._cmd_resume(args, cfg, op=None, fast_op=None, search=None,
                        store=store, log_path=log_path)

    assert set(revetted) == {deferred.candidate.candidate_id,
                             provisional.candidate.candidate_id}
    assert clean.candidate.candidate_id not in revetted
