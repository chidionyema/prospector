"""Test for Stochastic Full-Vetting (verify.py)."""
from __future__ import annotations

from typing import Any
import pytest
from prospector.config import load_config
from prospector.models import Candidate, Verdict, Source
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider
from prospector.verify import verify

@pytest.fixture
def cfg():
    return load_config()

@pytest.fixture
def cand():
    return Candidate(title="Test", one_liner="x", hypothesis="y", who_pays="z")

# A refuting mock must CITE the passage it was served. Confidence is recomputed from citations
# (verify.py:70-133), so `"citations": []` yields confidence 0.0 regardless of what the router
# claims — and with confidence_floor at 0.4 (config.yaml, E11 / programme doc §17) a 0.0-confidence
# refutation no longer hard-kills. These tests are about the SHORT-CIRCUIT mechanism, so they must
# trip it with a verdict the engine actually accepts as decisive; otherwise they silently stop
# testing kill-fast and start testing the floor.
def _refuter(source_id: str) -> MockOperator:
    return MockOperator(router=lambda s, u: {
        "verdict": "refuted", "confidence": 1.0,
        "rationale": "dead", "citations": [source_id]
    })


def test_verify_short_circuits_normally(cfg, cand):
    """Normally, verify stops at the first hard fail."""
    # Mock search that returns one passage for value_durability
    # The template query for value_durability contains "obsolete" and "commoditised".
    fixtures = {
        "obsolete commoditised": [{"url": "http://x", "text": "dead"}]
    }
    search = FixtureProvider(fixtures=fixtures)

    # source_id is a hash of the URL, not the URL — derive it from the provider that will
    # actually serve this check rather than hardcoding a digest.
    op = _refuter(search.search("obsolete commoditised", 1)[0].source_id)

    checks, adv, gate = verify(op, search, cfg, cand, skip_adversarial=True)

    # Should only have 1 check (value_durability) if it's the first in run_order
    assert len(checks) == 1
    assert gate == "value_durability"

def test_verify_runs_all_with_full_vet(cfg, cand):
    """With full_vet=True, verify runs ALL checks even if some fail."""
    # Use catch-all fixture ("") so every check gets evidence.
    fixtures = {
        "": [{"url": "http://x", "text": "evidence"}]
    }
    search = FixtureProvider(fixtures=fixtures)

    op = _refuter(search.search("probe", 1)[0].source_id)

    checks, adv, gate = verify(op, search, cfg, cand, skip_adversarial=True, full_vet=True)

    # Should run all checks (usually 6)
    assert len(checks) > 1
    assert gate is not None # Still records the FIRST failing gate


def test_an_uncited_refutation_does_not_short_circuit_at_the_confidence_floor(cfg, cand):
    """§11 gap 3, now closed by confidence_floor=0.4: an UNCITED refutation must not hard-kill.

    verify.py:377 already downgrades an uncited *supported* check to unverifiable, but the
    equivalent rail for *refuted* is the confidence floor: citations drive the computed
    confidence, so a refutation resting on nothing scores 0.0 and now sits below the floor.
    Pinning it here because it is the safety property the floor bought, and the three tests
    above were previously asserting its opposite.
    """
    fixtures = {"": [{"url": "http://x", "text": "evidence"}]}
    search = FixtureProvider(fixtures=fixtures)

    uncited = MockOperator(router=lambda s, u: {
        "verdict": "refuted", "confidence": 1.0, "rationale": "dead", "citations": []
    })

    checks, adv, gate = verify(uncited, search, cfg, cand, skip_adversarial=True)

    assert len(checks) > 1, "an uncited refutation must not short-circuit the run"
    assert all(c.confidence == 0.0 for c in checks if c.verdict.value == "refuted"), \
        "confidence must be recomputed from citations, not taken from the model's claim"
    assert cfg.thresholds.confidence_floor > 0.0, \
        "this test is vacuous if the floor is inert — see programme doc §17"
