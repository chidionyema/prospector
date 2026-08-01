"""WS2-P1: bounded wave check-parallelism inside verify() (2026-07-31).

check_parallelism=N runs N checks concurrently per wave, but gates are evaluated
in run-order at each wave boundary. These tests prove the semantics that matter:

1. Parity: a full clean run yields the SAME check set, order, and gate as serial.
2. Kill-fast holds: a wave-1 hard fail still returns the same first_failing_gate
   and never reaches later waves; the only extra work is the rest of that wave.
3. par=1 is byte-identical serial behaviour (the config default).

Harness conventions follow tests/unit/test_kill_fast.py (MockOperator router +
FixtureProvider keyed on query substrings).
"""
from __future__ import annotations

import re
from typing import Any

import pytest
from prospector.config import load_config
from prospector.models import Candidate
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider
from prospector.verify import verify


@pytest.fixture
def cfg():
    c = load_config()
    c.retrieval.provider = "fixture"
    c.retrieval.cache = False
    c.retrieval.queries_per_check = 1
    c.retrieval.results_per_query = 1
    return c


@pytest.fixture
def cand() -> Candidate:
    return Candidate(
        title="Test Opportunity",
        one_liner="A test product",
        hypothesis="People suffer from X",
        who_pays="SMEs",
    )


def _fixture_provider() -> FixtureProvider:
    """One passage per check family, keyed on query substrings (see test_kill_fast)."""
    return FixtureProvider(fixtures={
        "pain": [{"url": "https://pain.example.com", "text": "acute pain confirmed by survey data"}],
        "commoditised": [{"url": "https://value.example.com", "text": "value holds; strong moat persists"}],
        "value": [{"url": "https://value.example.com", "text": "value holds; strong moat persists"}],
        "incumbent": [{"url": "https://inc.example.com", "text": "no dominant incumbent found"}],
        "payer": [{"url": "https://pay.example.com", "text": "SMEs have budget for this"}],
        "distribution": [{"url": "https://dist.example.com", "text": "self-serve channel available"}],
        "legal": [{"url": "https://legal.example.com", "text": "fully compliant"}],
    })


def _router(verdict_for_check: dict[str, str], verdict_calls: list[str]):
    """Router returning a configured verdict per check (default: supported+cited).
    Appends the check name to verdict_calls for every verdict call it serves."""
    def router(system: str, user: str) -> Any:
        if "queries most likely" in system or "Write 1-3 queries" in user:
            for name in ("pain_reality", "value_durability", "incumbency",
                         "payer_solvency", "distribution", "legality"):
                if name in user:
                    return [f"{name} check"]
            return ["generic query"]
        if "Passages:" not in user:
            # score / adversarial calls
            return {"verdict": "supported", "confidence": 0.9, "rationale": "ok",
                    "citations": [], "decisive": False, "attacks": []}
        m = re.search(r"\[([a-f0-9]{16})\]", user)
        first_id = m.group(1) if m else ""
        for name, verdict in verdict_for_check.items():
            if name in user:
                verdict_calls.append(name)
                return {"verdict": verdict, "confidence": 0.85,
                        "rationale": f"{name} verdict", "citations": [first_id]}
        # any check not explicitly configured: supported + cited
        m2 = re.search(r"(pain_reality|value_durability|incumbency|payer_solvency|"
                       r"distribution|legality)", user)
        if m2:
            verdict_calls.append(m2.group(1))
        return {"verdict": "supported", "confidence": 0.85, "rationale": "ok",
                "citations": [first_id]}
    return router


def _run(cfg, cand, par: int, verdict_for_check: dict[str, str]):
    cfg.retrieval.check_parallelism = par
    calls: list[str] = []
    op = MockOperator(router=_router(verdict_for_check, calls))
    checks, adv, gate = verify(op, _fixture_provider(), cfg, cand,
                               skip_adversarial=True)
    return checks, gate, calls


def test_clean_run_parity_serial_vs_par2(cfg, cand):
    """A run with no gate fires must produce the same checks, same order, same
    (absent) gate at par=2 as at par=1."""
    checks_1, gate_1, _ = _run(cfg, cand, 1, {})
    checks_2, gate_2, _ = _run(cfg, cand, 2, {})
    assert gate_1 == gate_2
    assert [c.check_name for c in checks_1] == [c.check_name for c in checks_2]
    assert [c.verdict.value for c in checks_1] == [c.verdict.value for c in checks_2]


def test_kill_fast_holds_at_par2(cfg, cand):
    """value_durability (first config gate, wave 1) refuted at par=2: same
    first_failing_gate as serial, later waves never run — at most the first
    wave's checks execute."""
    kill = {"value_durability": "refuted"}
    checks_1, gate_1, _ = _run(cfg, cand, 1, kill)
    checks_2, gate_2, calls_2 = _run(cfg, cand, 2, kill)

    assert gate_1 == "value_durability"
    assert gate_2 == gate_1

    # Serial stops after exactly the killing check; par=2 may also carry the
    # other check of the same wave (kept — it is a real grounded verdict), but
    # NEVER anything from a later wave.
    assert len(checks_1) == 1
    assert 1 <= len(checks_2) <= 2
    run_order_wave1 = {checks_1[0].check_name} | set(
        c.check_name for c in checks_2)
    assert len(run_order_wave1) <= 2, (
        f"par=2 kill-fast leaked past wave 1: {sorted(run_order_wave1)}")
    # No verdict call for anything beyond the first wave
    assert len(set(calls_2)) <= 2, f"later-wave verdict calls fired: {calls_2}"


def test_par1_matches_original_kill_fast_exactly(cfg, cand):
    """par=1 (the dataclass default) is the original serial loop: exactly one
    check on a first-gate kill."""
    checks, gate, _ = _run(cfg, cand, 1, {"value_durability": "refuted"})
    assert gate == "value_durability"
    assert len(checks) == 1
    assert checks[0].check_name == "value_durability"
