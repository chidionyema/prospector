"""Per-market observability (spec D6).

An aggregate number hides a dead market: 40% unverifiable across two markets can be one
healthy market averaged with one that grounds nothing at all.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.diagnostics import (
    _market_alarms,
    _market_breakdown,
    diagnose_batch,
    render_batch_diagnostics,
)
from prospector.models import (
    Candidate,
    CheckResult,
    Decision,
    Dossier,
    Source,
    Verdict,
)


def _check(verdict: Verdict, n_sources: int = 2) -> CheckResult:
    return CheckResult(
        check_name="pain_reality", verdict=verdict, confidence=0.8, rationale="r",
        sources=[Source.make(url=f"https://x.example/{i}", text="t")
                 for i in range(n_sources)])


def _dossier(market: str, decision: Decision, verdicts: list[Verdict],
             title: str = "T") -> Dossier:
    return Dossier(
        candidate=Candidate(title=title, one_liner="O", market=market),
        decision=decision,
        checks=[_check(v, 0 if v is Verdict.UNVERIFIABLE else 2) for v in verdicts],
        gate_fired="pain_reality" if decision is Decision.KILL else "")


# ---------------------------------------------------------------------------
# Breakdown
# ---------------------------------------------------------------------------

def test_breakdown_separates_a_healthy_market_from_a_blind_one():
    batch = [
        _dossier("uk", Decision.PASS, [Verdict.SUPPORTED, Verdict.SUPPORTED], "a"),
        _dossier("uk", Decision.KILL, [Verdict.REFUTED, Verdict.SUPPORTED], "b"),
        _dossier("us", Decision.KILL, [Verdict.UNVERIFIABLE, Verdict.UNVERIFIABLE], "c"),
        _dossier("us", Decision.KILL, [Verdict.UNVERIFIABLE, Verdict.UNVERIFIABLE], "d"),
    ]
    r = diagnose_batch(batch, cfg=load_config())
    by_market = r["by_market"]

    assert by_market["uk"]["pass"] == 1
    assert by_market["uk"]["unverifiable_pct"] == 0.0
    assert by_market["us"]["pass"] == 0
    assert by_market["us"]["unverifiable_pct"] == 100.0
    assert by_market["us"]["retrieval_empty_checks"] == 4

    # The aggregate alone would read as a merely mediocre 50%.
    assert r["unverifiable_pct"] == 50.0


def test_single_market_batch_is_not_rendered_with_a_breakdown():
    """The JSON always carries the market, but a single-market run's printed report is
    unchanged — a one-row 'per market' table is noise."""
    batch = [_dossier("uk", Decision.PASS, [Verdict.SUPPORTED])]
    r = diagnose_batch(batch, cfg=load_config())
    assert set(r["by_market"]) == {"uk"}
    assert "Per market" not in render_batch_diagnostics(r)


def test_marketless_batch_produces_no_breakdown():
    batch = [_dossier("", Decision.PASS, [Verdict.SUPPORTED])]
    assert diagnose_batch(batch, cfg=load_config())["by_market"] == {}


def test_render_labels_aggregates_as_cross_market():
    batch = [_dossier("uk", Decision.PASS, [Verdict.SUPPORTED], "a"),
             _dossier("us", Decision.KILL, [Verdict.UNVERIFIABLE], "b")]
    text = render_batch_diagnostics(diagnose_batch(batch, cfg=load_config()))
    assert "Per market" in text
    assert "span ALL markets" in text
    assert "uk" in text and "us" in text


# ---------------------------------------------------------------------------
# Alarms
# ---------------------------------------------------------------------------

def _rows(n: int, decision: str = "kill", **extra) -> list[dict]:
    return [{"decision": decision, "gate_fired": "pain_reality",
             "market": "us", **extra} for _ in range(n)]


def test_zero_yield_in_one_market_points_at_evidence_not_the_bar():
    alarms = _market_alarms(_rows(10), "us", load_config(), min_sample=5)
    codes = {a["code"] for a in alarms}
    assert "market_zero_yield" in codes
    msg = next(a for a in alarms if a["code"] == "market_zero_yield")["message"]
    assert "not the bar" in msg
    assert "prompts/markets/us/" in msg


def test_high_defer_rate_is_flagged_as_infrastructure_not_market_signal():
    alarms = _market_alarms(_rows(10, decision="defer"), "us", load_config(),
                            min_sample=5)
    codes = {a["code"] for a in alarms}
    assert "market_defer_rate" in codes
    msg = next(a for a in alarms if a["code"] == "market_defer_rate")["message"]
    assert "infrastructure signal" in msg


def test_degraded_retrieval_is_flagged():
    rows = _rows(10, retrieval_degraded=1)
    codes = {a["code"] for a in _market_alarms(rows, "us", load_config(), min_sample=5)}
    assert "market_retrieval_degraded" in codes


def test_dossiers_in_a_closed_market_are_an_alarm():
    """Either a probe leaked into the catalogue or the readiness gate was bypassed."""
    rows = _rows(6, decision="pass")
    codes = {a["code"] for a in _market_alarms(rows, "us", load_config(), min_sample=5)}
    assert "market_not_open" in codes


def test_open_market_with_healthy_yield_raises_nothing():
    rows = [{"decision": "pass", "market": "uk"} for _ in range(5)] + \
           [{"decision": "kill", "gate_fired": "legality", "market": "uk"}
            for _ in range(5)]
    assert _market_alarms(rows, "uk", load_config(), min_sample=5) == []


def test_small_sample_is_not_judged():
    assert _market_alarms(_rows(2), "us", load_config(), min_sample=5) == []
