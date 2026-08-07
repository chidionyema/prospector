"""E1 hybrid arm: entity-templated queries for the grounding-starved checks.

Why this arm exists (docs/COMMERCIAL_READINESS_PROGRAM.md §3 E1): the existing
LLM/template chain produces PRODUCT-shaped queries ("productized transforms tenant
answers adversarial") that search cannot ground — payer_solvency/distribution
unverifiable:supported ratio is 771 vs 145 on historical kills. The E1 bet is that
queries NAMING the concrete payer/audience entity (slot-filled from cand.who_pays
and cand.tags.audience) surface real "who actually pays / how do you reach them"
pages — because those pages exist for NAMED entities, not for product restatements.

These tests lock the contract:
  - `_entity_queries` slots payer/audience correctly and SKIPS blank slots
  - Distribution queries translate `audience` underscore tokens to spaces
  - `_entity_queries` returns [] when both entity fields are blank (caller falls through)
  - The arm defaults OFF on `Retrieval` (control baseline; gate against accidental
    enabling)
  - Threading through `run_check`: the entity arm produces `query_source="entity_template"`
    with no LLM query-gen call, and the precomputed-queries arm wins over entity templates
    when the latter is empty (the chain is documented above the priority block).
  - `CheckResult.to_dict()` includes the new `query_source` key so the A/B can compute
    per-arm unverifiable-rate offline.
"""
from __future__ import annotations

from prospector.config import Retrieval, load_config
from prospector.models import Candidate, CheckResult, Verdict
from prospector.verify import _entity_queries, run_check

# ---------------------------------------------------------------------------
# 1. _entity_queries: payer is slot-filled
# ---------------------------------------------------------------------------

def test_entity_queries_payer_solvency_slots_payer():
    """Both payer_solvency templates slot the payer in; both must come back."""
    cand = Candidate(title="PropTrace",
                     one_liner="compliance tool for UK landlord portfolio reporting",
                     who_pays="UK landlords")
    qs = _entity_queries(cand, "payer_solvency", 2)
    assert len(qs) == 2
    for q in qs:
        assert "UK landlords" in q, f"payer not slot-filled: {q!r}"


def test_entity_queries_unknown_check_returns_empty():
    """Checks outside the entity arm's domain get [] — caller falls through to the LLM chain."""
    cand = Candidate(title="Test", one_liner="x", who_pays="UK landlords")
    assert _entity_queries(cand, "value_durability", 2) == []


# ---------------------------------------------------------------------------
# 2. _entity_queries: distribution, with underscore→space
# ---------------------------------------------------------------------------

def test_entity_queries_distribution_translates_underscore_to_space():
    """tags.audience='smb_owner' must render as 'smb owner' in the query."""
    cand = Candidate(
        title="Outreach Kit",
        one_liner="distribution tool for small-business marketing",
        tags={"audience": "smb_owner"},
    )
    qs = _entity_queries(cand, "distribution", 2)
    assert len(qs) == 2
    for q in qs:
        assert "smb owner" in q, f"audience not slot-filled with space: {q!r}"
        assert "smb_owner" not in q, f"underscore leaked through: {q!r}"


# ---------------------------------------------------------------------------
# 3. Blank who_pays / missing audience → template skipped, all-blank → []
# ---------------------------------------------------------------------------

def test_entity_queries_blank_who_pays_skips_payer_templates():
    """A payer template whose slot is blank is SKIPPED (would degenerate to product-shaped)."""
    cand = Candidate(title="X", one_liner="y", who_pays="")  # no payer
    qs = _entity_queries(cand, "payer_solvency", 2)
    assert qs == [], "blank payer must skip the payer templates, not return [] slots"


def test_entity_queries_all_blank_returns_empty():
    """No payer, no audience → [] and the caller uses the LLM chain."""
    cand = Candidate(title="X", one_liner="y", who_pays="", tags={})
    assert _entity_queries(cand, "payer_solvency", 2) == []
    assert _entity_queries(cand, "distribution", 2) == []


# ---------------------------------------------------------------------------
# 4. Retrieval arm defaults OFF (control baseline)
# ---------------------------------------------------------------------------

def test_retrieval_hybrid_entity_checks_defaults_empty():
    """Arm must default OFF. Setting it from any config edit is a deliberate change."""
    assert Retrieval().hybrid_entity_checks == []


# ---------------------------------------------------------------------------
# 5. _run_check seam: entity arm takes the priority slot, no LLM query-gen call
# ---------------------------------------------------------------------------

class _EmptySearch:
    """Search stub: all queries return [] (no passages → short-circuit to UNVERIFIABLE,
    no verdict LLM call fires)."""
    def search(self, query, k=0, max_chars=0):
        return []


class _LLMOp:
    """Op stub: every method raises AssertionError so the entity path's success proves
    no LLM query-gen call fired (E1 is non-LLM, that is the whole point)."""
    def __getattr__(self, name):
        def _boom(*a, **k):
            raise AssertionError(f"LLM op.{name} called — entity arm must not invoke LLM")
        return _boom


def _cand_with_payer():
    return Candidate(
        title="PropTrace",
        one_liner="compliance tool for UK landlord portfolio reporting",
        hypothesis="landlords lose tens of thousands to notices done wrong",
        who_pays="UK landlords",
        candidate_id="teste1cand01",
    )


def test_run_check_entity_arm_sets_query_source_and_skips_llm():
    """hybrid_entity_checks=['payer_solvency'] + non-blank who_pays → entity_template,
    no LLM query-gen call, and the resulting query names the payer."""
    cfg = load_config()
    cfg.retrieval.cache = False
    cfg.retrieval.queries_per_check = 2
    cfg.retrieval.fast_queries = 2
    cfg.retrieval.hybrid_entity_checks = ["payer_solvency"]
    cfg.retrieval.template_checks = []  # isolate the entity arm from the template fallback
    cfg.retrieval.llm_query_gen = False  # so precomputed_queries is empty

    result = run_check(_LLMOp(), _EmptySearch(), cfg, _cand_with_payer(),
                       "payer_solvency", query_op=None, precomputed_queries=None)

    # The no-passages short-circuit path: UNVERIFIABLE + degraded + queries stamped.
    assert result.verdict.value == "unverifiable"
    assert result.degraded is True
    assert result.query_source == "entity_template"
    # Both templates slot the payer in; the candidate.named payer must appear.
    assert "UK landlords" in result.queries[0]


def test_run_check_precomputed_arm_wins_over_entity_when_entity_empty():
    """When hybrid_entity_checks excludes the check, precomputed ties to llm_batched.

    The chain (priority 0 entity → 1 precomputed → 2 template → 3 per-check LLM) puts
    precomputed ABOVE the entity arm only when the entity is empty; this case asserts
    the per-check structural win: hybrid_entity_checks=[] drops the entity branch
    entirely, so the precomputed (llm_batched) path stamps the result.
    """
    cfg = load_config()
    cfg.retrieval.cache = False
    cfg.retrieval.queries_per_check = 2
    cfg.retrieval.fast_queries = 2
    cfg.retrieval.hybrid_entity_checks = []  # entity arm off
    cfg.retrieval.template_checks = []
    cfg.retrieval.llm_query_gen = True  # so precomputed is the real path, not a coincidence

    precomp = {"payer_solvency": ["precomputed domain query"]}
    result = run_check(_LLMOp(), _EmptySearch(), cfg, _cand_with_payer(),
                       "payer_solvency", query_op=None, precomputed_queries=precomp)

    assert result.query_source == "llm_batched"
    assert result.queries == ["precomputed domain query"]


# ---------------------------------------------------------------------------
# 6. CheckResult.to_dict() exposes query_source so the A/B can compute per-arm rates
# ---------------------------------------------------------------------------

def test_checkresult_to_dict_includes_query_source():
    """The instrumentation field must round-trip through to_dict; otherwise the
    offline A/B cannot read which arm produced a given row."""
    cr = CheckResult(check_name="payer_solvency", verdict=Verdict.UNVERIFIABLE,
                     confidence=0.0, rationale="x", query_source="entity_template")
    d = cr.to_dict()
    assert "query_source" in d
    assert d["query_source"] == "entity_template"
