"""Test for Shadow Moat infrastructure (run.py)."""
from __future__ import annotations

import pytest
import logging
from prospector.run import vet_candidate
from prospector.operator import MockOperator
from prospector.config import load_config
from prospector.models import Candidate
from prospector.retrieval import FixtureProvider

def test_vet_candidate_logs_shadow_moat_drift(caplog):
    caplog.set_level(logging.INFO)
    
    # Provide enough fixtures for all checks
    fixtures = {
        "": [{"url": "http://x", "text": "evidence"}]
    }
    search = FixtureProvider(fixtures=fixtures)

    # The citation is load-bearing, not decoration. This mock used to return
    # `"citations": []`, i.e. a "supported" verdict resting on nothing — and source-or-die
    # correctly refuses that: verify.py:377 downgrades an uncited supported check to
    # unverifiable, every check then reads unverifiable, and the `source_or_die` gate fires.
    # The engine was right and the fixture was wrong; the fix is to make the mock's PASS
    # genuinely grounded, never to relax the gate so the mock's story works.
    #
    # verify.py filters citations against `{s.source_id for s in sources}`, and source_id is
    # a hash of the URL — not the URL itself. Derive it from the provider that will actually
    # serve this check rather than hardcoding the digest, so the test survives any change to
    # how ids are minted.
    source_id = search.search("probe", 1)[0].source_id

    # Primary op: says PASS, grounded in the one source the fixture serves.
    op = MockOperator(router=lambda s, u: {
        "verdict": "supported", "confidence": 1.0, "rationale": "ok",
        "citations": [source_id]
    })

    # Experimental op: says KILL (refuted) — and must CITE, for the same reason the primary op
    # above does. Confidence is recomputed from citations (verify.py:70-133), so an uncited
    # refuted lands at confidence 0.0; since confidence_floor rose to 0.4 (config.yaml, E11 /
    # programme doc §17) such a verdict no longer hard-kills, and this test would be asserting
    # drift that the engine correctly refuses to produce. That refusal is the fix to §11's
    # "refuted-with-zero-citations" gap, not a regression — so the fixture cites, as the
    # comment above insists, rather than the floor being relaxed to keep the mock's story.
    exp_op = MockOperator(router=lambda s, u: {
        "verdict": "refuted", "confidence": 1.0, "rationale": "bad",
        "citations": [source_id]
    })

    cand = Candidate(title="Test Idea", one_liner="x", hypothesis="y", who_pays="z")
    cfg = load_config()
    
    # Run vet
    dossier = vet_candidate(cand, op, search, cfg, experimental_op=exp_op)
    
    # 1. Primary should pass all hard gates (might fail on min_composite scoring)
    assert dossier.gate_fired in (None, "min_composite")
    
    # 2. Shadow Moat should have been called and drift logged
    assert "SHADOW MOAT: Running experimental vet" in caplog.text
    assert "SHADOW MOAT DRIFT" in caplog.text
    assert "Primary=None vs Experimental=value_durability" in caplog.text
