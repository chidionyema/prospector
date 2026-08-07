"""Batched LLM query-gen (fast tier) — the Leg-B fix for the grounding loop.

Proven failure mode (2026-06-25/26, 5-candidate batch on the retrieval-resilience code):
retrieval no longer starves (retrieval-empty 34→0) BUT unverifiable stayed 93.3% because the
deterministic `_keywords` queries restate the product pitch ("productized transforms tenant
answers adversarial") so search returns off-topic junk (cambridge.org dictionary entries,
web.whatsapp.com, diy.com). The fix: ONE fast-tier call decomposes the idea into real-world
domain queries for all checks. These tests lock the contract:
  - the batched prompt loads and instructs decompose-not-echo
  - gen_queries_batched returns {check: [queries]} and runs on the fast op
  - run_check PREFERS precomputed queries over templates
  - a failed/partial batch call falls back to the deterministic template (no hard-fail)
"""
from __future__ import annotations

from prospector import verify
from prospector.models import CHECKS, Candidate
from prospector.prompts import render


class _RecordingOp:
    """Fake non-critical operator: returns a canned dict, records the call count."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def complete_json(self, system, user, temperature=0.0, **kw):
        self.calls += 1
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _cand():
    return Candidate(
        title="DepoShield",
        one_liner="productized service that transforms tenant answers into deposit disputes",
        hypothesis="gig renters lose deposits to unfair deductions",
        candidate_id="testcand01",
    )


def test_batched_prompt_loads_and_decomposes():
    """The batched prompt must exist and carry the decompose-don't-echo contract."""
    system, user = render(
        "query_gen_batched",
        candidate_json='{"title":"Test"}',
        checks_block="- pain_reality: Real, acute problem?",
    )
    combined = (system + " " + user).lower()
    assert "decompose" in combined
    assert "never" in combined and "product" in combined  # never echo the product name
    # The USER section must carry the substituted checks_block.
    assert "pain_reality" in user


def test_gen_queries_batched_returns_per_check_queries_on_fast_op():
    payload = {
        "pain_reality": ["gig renters deposit deductions complaints UK", "tenancy deposit protection scheme stats"],
        "legality": ["deposit dispute adjudication TDS rules", "claims management regulation FCA tenancy"],
    }
    op = _RecordingOp(payload)
    out = verify.gen_queries_batched(op, _cand(), ["pain_reality", "legality"], n=2)
    assert op.calls == 1  # ONE batched call, not one-per-check
    assert out["pain_reality"] == payload["pain_reality"]
    assert out["legality"] == payload["legality"]
    # The product name must NOT have to appear; queries are whatever the model returned.
    assert all(isinstance(q, str) for qs in out.values() for q in qs)


def test_gen_queries_batched_omits_garbled_checks():
    """A check whose value isn't a clean list is omitted so the caller falls back to template."""
    op = _RecordingOp({"pain_reality": ["good query one", "good query two"], "legality": "not-a-list"})
    out = verify.gen_queries_batched(op, _cand(), ["pain_reality", "legality"], n=2)
    assert "pain_reality" in out
    assert "legality" not in out  # garbled → omitted → template fallback downstream


def test_gen_queries_batched_total_failure_returns_empty():
    """On a fast-chain error the function returns {} (every check falls back to a template)."""
    op = _RecordingOp(RuntimeError("fast chain down"))
    out = verify.gen_queries_batched(op, _cand(), list(CHECKS)[:3], n=2)
    assert out == {}


def test_run_check_prefers_precomputed_over_template(monkeypatch):
    """When precomputed_queries has the check, run_check must use it (not _templated_queries)."""
    captured = {}

    def _fake_search(q, k=0, max_chars=0):
        captured.setdefault("queries", []).append(q)
        return []  # empty → short-circuits to unverifiable, no verdict LLM call

    class _Search:
        search = staticmethod(_fake_search)

    # Guard: if the template path is ever taken, this raises and fails the test.
    def _boom(*a, **k):
        raise AssertionError("template path used despite precomputed queries present")

    monkeypatch.setattr(verify, "_templated_queries", _boom)

    from prospector.config import load_config
    cfg = load_config()
    precomp = {"pain_reality": ["real domain query alpha", "real domain query beta"]}
    res = verify.run_check(object(), _Search(), cfg, _cand(), "pain_reality",
                           query_op=None, precomputed_queries=precomp)
    assert captured["queries"] == ["real domain query alpha", "real domain query beta"]
    assert res.verdict.value == "unverifiable"  # empty passages → short-circuit


def test_run_check_falls_back_to_template_when_precomputed_missing(monkeypatch):
    """A check absent from precomputed_queries must fall back to the deterministic template."""
    called = {"template": False}

    def _fake_templated(cand, check_name, n):
        called["template"] = True
        return ["template fallback query"]

    def _fake_search(q, k=0, max_chars=0):
        return []

    class _Search:
        search = staticmethod(_fake_search)

    monkeypatch.setattr(verify, "_templated_queries", _fake_templated)

    from prospector.config import load_config
    cfg = load_config()
    # precomputed has a DIFFERENT check, so pain_reality must fall back to template.
    precomp = {"legality": ["x", "y"]}
    verify.run_check(object(), _Search(), cfg, _cand(), "pain_reality",
                     query_op=None, precomputed_queries=precomp)
    assert called["template"] is True
