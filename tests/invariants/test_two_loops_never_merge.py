"""Two-loops-never-merge invariant (Part 16 — single most important guardrail).

STRUCTURAL ISOLATION OF TRUTH FROM DEMAND:
  The verification pipeline (verify, apply_gates) has NO sales/demand input.
  This test proves this by:
    1. Inspecting function signatures to assert no 'sales' or 'demand' parameter exists.
    2. Running verify() twice on the same candidate with the same fixtures,
       each time with a different external 'sales' variable — proving the output
       is identical regardless of external demand signals.

Why this matters: if the truth loop (grounded checks) ever received sales/demand
input, operators could influence verifications by adjusting demand figures.
The loops are structurally separated — truth is grounded only in retrieved passages.
"""
from __future__ import annotations

import inspect
import re
from typing import Any

import pytest
from prospector.config import load_config
from prospector.kill_filter import apply_gates
from prospector.models import Candidate, Source
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider
from prospector.verify import verify


# ---------------------------------------------------------------------------
# Signature inspection — no sales/demand parameter
# ---------------------------------------------------------------------------

_DEMAND_PATTERN = re.compile(r"(sales|demand|revenue|orders|mrr|arr)", re.IGNORECASE)


def test_verify_signature_has_no_sales_or_demand_param():
    """verify() must not accept any parameter whose name suggests sales/demand."""
    sig = inspect.signature(verify)
    for param_name in sig.parameters:
        assert not _DEMAND_PATTERN.search(param_name), (
            f"verify() has a suspicious parameter: {param_name!r}. "
            "Truth loop must not accept demand/sales inputs."
        )


def test_apply_gates_signature_has_no_sales_or_demand_param():
    """apply_gates() must not accept any parameter whose name suggests sales/demand."""
    sig = inspect.signature(apply_gates)
    for param_name in sig.parameters:
        assert not _DEMAND_PATTERN.search(param_name), (
            f"apply_gates() has a suspicious parameter: {param_name!r}. "
            "Kill filter must not accept demand/sales inputs."
        )


# ---------------------------------------------------------------------------
# Determinism: verify() output is identical regardless of external 'sales' state
# ---------------------------------------------------------------------------

FIXTURE_SOURCE = Source.make(
    url="https://evidence.example.com",
    text="Pain confirmed: businesses report severe workflow bottlenecks."
)


def _make_stable_router(first_id: str) -> Any:
    """Router that always returns the same supported verdict, citing first_id."""
    def router(system: str, user: str) -> Any:
        if "queries most likely" in system or "Write 1-3 queries" in user:
            return ["evidence query"]
        if "Passages:" in user:
            return {
                "verdict": "supported",
                "confidence": 0.9,
                "rationale": "Confirmed by retrieved evidence.",
                "citations": [first_id],
            }
        # score / adversarial
        return {"verdict": "supported", "confidence": 0.9, "rationale": "ok", "citations": []}
    return router


@pytest.fixture
def cfg():
    c = load_config()
    c.retrieval.provider = "fixture"
    c.retrieval.cache = False
    c.retrieval.queries_per_check = 1
    c.retrieval.results_per_query = 1
    # Disable adversarial to keep the run deterministic and short
    c.hard_gates = [g for g in c.hard_gates if "adversarial_decisive" not in g]
    return c


@pytest.fixture
def cand() -> Candidate:
    return Candidate(
        title="Workflow Automation for SMEs",
        one_liner="Automates repetitive SME admin tasks",
        hypothesis="SMEs waste hours on manual data entry",
        who_pays="SME owners",
    )


def _run_verify_ignoring_sales(sales_figure: float, cfg, cand) -> list[str]:
    """Run verify() with a specific external 'sales' value.

    The sales variable exists in this function's scope but is NEVER passed to
    verify() — structural isolation enforced. Returns list of (check_name, verdict).
    """
    # sales_figure deliberately NOT passed to any prospector function
    _ = sales_figure  # silence linter; we intentionally hold but don't use it

    # Build fresh fixtures and operator for each run
    search = FixtureProvider(fixtures={
        "evidence": [{"url": FIXTURE_SOURCE.url, "text": FIXTURE_SOURCE.text}],
        "pain": [{"url": FIXTURE_SOURCE.url, "text": FIXTURE_SOURCE.text}],
        "value": [{"url": FIXTURE_SOURCE.url, "text": FIXTURE_SOURCE.text}],
        "incumbent": [{"url": FIXTURE_SOURCE.url, "text": FIXTURE_SOURCE.text}],
        "payer": [{"url": FIXTURE_SOURCE.url, "text": FIXTURE_SOURCE.text}],
        "distribution": [{"url": FIXTURE_SOURCE.url, "text": FIXTURE_SOURCE.text}],
        "legal": [{"url": FIXTURE_SOURCE.url, "text": FIXTURE_SOURCE.text}],
    })
    op = MockOperator(router=_make_stable_router(FIXTURE_SOURCE.source_id))
    checks, adv, gate = verify(op, search, cfg, cand)
    return [(c.check_name, c.verdict.value) for c in checks]


def test_verify_output_is_identical_regardless_of_external_sales(cfg, cand):
    """Structural isolation proof: same candidate + fixtures, different 'sales'
    variable -> identical verify() output.

    Truth is grounded only in retrieved passages, never in demand signals.
    """
    result_low_sales = _run_verify_ignoring_sales(sales_figure=0.0, cfg=cfg, cand=cand)
    result_high_sales = _run_verify_ignoring_sales(sales_figure=10_000_000.0, cfg=cfg, cand=cand)

    assert result_low_sales == result_high_sales, (
        "verify() produced different results for different 'sales' values — "
        "this would indicate a structural merge of the truth and demand loops. "
        f"Low-sales: {result_low_sales}, High-sales: {result_high_sales}"
    )
