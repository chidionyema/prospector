"""Search observability invariants (P0, 2026-06-24).

The web_calls=0 alarm we got was a false alarm: the metric was structurally broken
because no search provider incremented it. These tests pin the contract:

  1. Every search call (any provider) increments web_calls — including errors.
  2. Every search call writes one audit row with the shape we can replay.
  3. DiskCache distinguishes hit vs miss in the audit log.
  4. FallbackSearchProvider records the ACTUAL provider that answered, not 'fallback'.
  5. verify.run_check writes its own audit row so we can prove the verifier reached
     the search block even if the provider counter is broken.
  6. Search failure (exception) still increments web_calls and writes an audit row.

If any of these fail, we are back to guessing what happened. They MUST stay green.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from prospector import audit
from prospector.retrieval import (
    BraveSearchProvider,
    DiskCache,
    ExaSearchProvider,
    FallbackSearchProvider,
    FixtureProvider,
)

# ----------------------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _tmp_audit_dir(tmp_path, monkeypatch):
    """Point PROSPECTOR_AUDIT_DIR at a per-test tmp dir so we never pollute prod."""
    monkeypatch.setenv("PROSPECTOR_AUDIT_DIR", str(tmp_path / "audit"))
    audit._AUDIT_DIR = Path(str(tmp_path / "audit"))
    audit._AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    yield tmp_path / "audit"


@pytest.fixture
def web_calls_snapshot():
    """Snapshot the global web_calls counter before a test, return a delta helper."""
    from prospector.telemetry import _USAGE, _USAGE_BY_PROVIDER
    snap = {}
    for phase, usage in _USAGE.items():
        snap[phase] = dict(usage)
    for prov, usage in _USAGE_BY_PROVIDER.items():
        snap[f"by_provider:{prov}"] = dict(usage)
    return snap


def _delta(snap, phase=None):
    """Aggregate web_calls/calls delta across ALL phases.

    PHASE is a contextvar; prior tests may have set it to 'vetting' / 'signal_pipeline' /
    etc. without resetting, so we sum across phases instead of assuming 'main'.
    """
    from prospector.telemetry import _USAGE
    keys = ("calls", "web_calls")
    if phase is not None:
        before = snap.get(phase, {})
        after = _USAGE.get(phase, {})
        return {k: after.get(k, 0) - before.get(k, 0) for k in keys}
    # Aggregate over all phases present in either snap or _USAGE.
    out = {k: 0 for k in keys}
    phases = set(snap.keys()) | set(_USAGE.keys())
    for ph in phases:
        if ph.startswith("by_provider:"):
            continue
        before = snap.get(ph, {})
        after = _USAGE.get(ph, {})
        for k in keys:
            out[k] += after.get(k, 0) - before.get(k, 0)
    return out


def _audit_rows(event=None):
    """Read all audit rows written by the test (single today's file under tmp)."""
    rows = []
    for p in audit._AUDIT_DIR.glob("*.jsonl"):
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if event is None or row.get("event") == event:
                rows.append(row)
    return rows


# ----------------------------------------------------------------------------------
# Core invariants
# ----------------------------------------------------------------------------------

def test_exa_search_increments_web_calls(web_calls_snapshot, monkeypatch):
    """ExaSearchProvider.search() must record_usage(web=True, provider='exa')."""
    # Stub the exa_py.Exa client so we don't hit the network.
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    fake_item = MagicMock(url="https://example.com/x", highlights=None, text="hello world")
    fake_result = MagicMock(results=[fake_item])
    with patch("exa_py.Exa") as MockExa:
        MockExa.return_value.search.return_value = fake_result
        ExaSearchProvider().search("test query", k=2, max_chars=800)

    d = _delta(web_calls_snapshot)
    assert d.get("web_calls", 0) >= 1, f"Exa search did not increment web_calls: delta={d}"


def test_brave_search_increments_web_calls(web_calls_snapshot, monkeypatch):
    """BraveSearchProvider.search() must record_usage(web=True, provider='brave')."""
    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    fake = {"web": {"results": [
        {"url": "https://example.com/a", "description": "hi", "title": "t"}]}}
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = fake
        with patch("prospector.retrieval._resolve", return_value=("<html>hi</html>", "t")):
            BraveSearchProvider().search("test query", k=2, max_chars=800)
    d = _delta(web_calls_snapshot)
    assert d.get("web_calls", 0) >= 1, f"Brave search did not increment web_calls: delta={d}"


def test_fixture_search_increments_web_calls(web_calls_snapshot):
    """Even FixtureProvider (used in tests + golden set) must increment web_calls."""
    fixtures = {"haulage": [{"url": "https://x/a", "text": "haulage fuel duty rebate info"}]}
    FixtureProvider(fixtures=fixtures, raise_on_miss=False).search("haulage fuel duty", k=2)
    d = _delta(web_calls_snapshot)
    assert d.get("web_calls", 0) >= 1, f"Fixture search did not increment web_calls: delta={d}"


def test_search_failure_still_increments_web_calls(web_calls_snapshot, monkeypatch):
    """If a provider raises, web_calls must STILL increment — the call happened."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    with patch("exa_py.Exa") as MockExa:
        MockExa.return_value.search.side_effect = RuntimeError("network down")
        with pytest.raises(RuntimeError):
            ExaSearchProvider().search("test query", k=2, max_chars=800)
    d = _delta(web_calls_snapshot)
    assert d.get("web_calls", 0) >= 1, \
        f"Exa failure did not increment web_calls (we lose observability on errors): delta={d}"


def test_search_writes_audit_row():
    """Every search call writes exactly one audit row with the required shape."""
    import os

    from prospector.retrieval import ExaSearchProvider
    os.environ["EXA_API_KEY"] = "test-key"
    fake_item = MagicMock(url="https://example.com/x", highlights=None, text="hi")
    with patch("exa_py.Exa") as MockExa:
        MockExa.return_value.search.return_value = MagicMock(results=[fake_item])
        ExaSearchProvider().search("audit row test", k=1)
    rows = _audit_rows(event="search")
    assert len(rows) >= 1
    r = rows[-1]
    for field in ("ts", "event", "provider", "query", "k", "max_chars", "returned_n",
                  "status"):
        assert field in r, f"audit row missing {field}: {r}"
    assert r["provider"] == "exa"
    assert r["status"] in ("ok", "empty")


# ----------------------------------------------------------------------------------
# DiskCache + FallbackSearchProvider observability
# ----------------------------------------------------------------------------------

def test_disk_cache_hit_and_miss_recorded(web_calls_snapshot, tmp_path):
    """DiskCache wraps every call — first miss records cache_hit=False, second hit True."""
    inner = FixtureProvider(fixtures={"hello": [{"url": "https://x/a", "text": "hello world"}]},
                            raise_on_miss=False)
    cache = DiskCache(inner, cache_dir=tmp_path / "c", ttl_s=3600)
    cache.search("hello world", k=1)
    cache.search("hello world", k=1)  # should hit
    rows = _audit_rows(event="search")
    assert len(rows) >= 2
    last_two = rows[-2:]
    cache_marks = [r.get("cache_hit") for r in last_two]
    assert False in cache_marks and True in cache_marks, \
        f"DiskCache did not record cache_hit for both miss and hit: {cache_marks}"


def test_fallback_records_actual_provider(web_calls_snapshot, monkeypatch):
    """FallbackSearchProvider must record the provider that answered, not 'fallback'."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    fake_item = MagicMock(url="https://example.com/x", text="hi")
    fixture = FixtureProvider(fixtures={}, raise_on_miss=True)  # always raises FixtureMiss
    exa = ExaSearchProvider()
    chain = FallbackSearchProvider([("fixture", fixture), ("exa", exa)])
    with patch("exa_py.Exa") as MockExa:
        MockExa.return_value.search.return_value = MagicMock(results=[fake_item])
        chain.search("hello", k=1)
    rows = _audit_rows(event="search")
    exa_rows = [r for r in rows if r.get("provider") == "exa"]
    assert exa_rows, f"Fallback did not record the actual answering provider as 'exa': {rows}"
    fallback_rows = [r for r in rows if r.get("provider") == "fallback"]
    assert not fallback_rows, f"Fallback incorrectly recorded provider='fallback': {fallback_rows}"


# ----------------------------------------------------------------------------------
# verify.run_check audit
# ----------------------------------------------------------------------------------

def test_verify_run_check_writes_audit_row(monkeypatch):
    """run_check must write its own audit row so we can prove the verifier reached search."""
    from prospector.config import load_config
    from prospector.models import Candidate
    from prospector.operator import MockOperator
    from prospector.verify import run_check

    cfg = load_config("config.yaml")
    cfg.retrieval.queries_per_check = 0  # force the deterministic template path
    cfg.retrieval.template_checks = ["pain_reality"]
    cfg.retrieval.fast_queries = 1
    op = MockOperator(responses={})  # not used — short-circuit if no passages
    fixtures = {"generic": [{"url": "https://x/a", "text": "people want this"}]}
    search = FixtureProvider(fixtures=fixtures, raise_on_miss=False)
    cand = Candidate(title="Test Idea", one_liner="x", who_pays="buyer",
                     why_now="now", tags={}, automatability=0.5)

    run_check(op, search, cfg, cand, "pain_reality")

    rows = _audit_rows(event="verify_search")
    assert rows, "verify.run_check did not write a verify_search audit row"
    r = rows[-1]
    for field in ("ts", "event", "check", "candidate_id", "queries_n", "passages_n",
                  "retrieval_failed", "short_circuit_empty"):
        assert field in r, f"verify_search audit row missing {field}: {r}"
    assert r["event"] == "verify_search"
    assert r["check"] == "pain_reality"


# ----------------------------------------------------------------------------------
# Schema check
# ----------------------------------------------------------------------------------

def test_search_audit_row_schema_is_stable():
    """Pin the audit row schema so consumers can rely on it."""
    # Trigger one audit row.
    FixtureProvider(fixtures={"hello": [{"url": "https://x", "text": "hi"}]},
                    raise_on_miss=False).search("hello world", k=1)
    rows = _audit_rows(event="search")
    assert rows, "no audit row written"
    r = rows[-1]
    required = {"ts", "event", "provider", "query", "k", "max_chars", "returned_n",
                "latency_ms", "status"}
    missing = required - set(r.keys())
    assert not missing, f"audit row missing fields: {missing}"