"""Multi-lane-by-default (Part 14): a single run produces a MIXED-ambition catalogue,
each idea judged by the bar of its OWN tier.

These tests are offline (MockOperator-style stubs / FixtureProvider) — no live calls.
They cover the four load-bearing properties of the multi-lane design:
  1. for_lane('smb') / for_lane('growth') resolve gates/thresholds/generation correctly
     and DO NOT mutate the base config (the venture default must stay byte-for-byte).
  2. generate_multilane tags every candidate with its lane and respects lane_quota.
  3. classify_tier falls back to the GENERATED tier on parse failure / unknown tier.
  4. a candidate generated as `venture` but classified `side_hustle` is vetted with the
     side_hustle bar (the exact run.py resolution: cfg.for_lane(cand.ambition_tier)).
"""
from __future__ import annotations

from prospector.classify import classify_tier
from prospector.config import load_config
from prospector.generate import generate_multilane
from prospector.models import Candidate


# --------------------------------------------------------------------------- stubs
class _BatchOp:
    """Returns fresh, distinct ideas per call (a model that diverges)."""
    model_version = "stub"

    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, temperature=0.0):
        self.calls += 1
        return [{"title": f"Idea c{self.calls}-{i}", "one_liner": "x",
                 "why_now": "y", "tags": {"sector": "s"}} for i in range(8)]


class _TierOp:
    """Classifier stub: always returns a fixed tier verdict."""
    model_version = "stub"

    def __init__(self, tier):
        self._tier = tier
        self.calls = 0

    def complete_json(self, system, user, temperature=0.0):
        self.calls += 1
        return {"tier": self._tier, "rationale": "stub"}


# --------------------------------------------------------------------------- 1. for_lane
def test_for_lane_smb_and_growth_resolve_without_mutating_base():
    cfg = load_config()
    base_min = cfg.thresholds.min_composite_to_pass
    base_gates = cfg.gate_map()

    smb = cfg.for_lane("smb")
    growth = cfg.for_lane("growth")

    # Thresholds escalate side_hustle(2.0) < smb(2.6) < growth(2.9) < venture(3.2).
    assert smb.thresholds.min_composite_to_pass == 2.6
    assert growth.thresholds.min_composite_to_pass == 2.9

    # smb makes payer_solvency + distribution HARD; growth makes pain_reality HARD.
    smb_gates = smb.gate_map()
    assert "payer_solvency" in smb_gates and "distribution" in smb_gates
    assert "buyer_intent" in smb_gates           # demand gate
    assert "value_durability" not in smb_gates   # no moat required at smb
    assert "pain_reality" in growth.gate_map()

    # Generation framing is lane-specific (merged over the default block).
    assert "SMALL-BUSINESS" in smb.generation["lane_directive"].upper() \
        or "SMALL BUSINESS" in smb.generation["lane_directive"].upper()
    assert "productized_service" in smb.generation["structural_forms"]
    assert "vertical_saas" in growth.generation["structural_forms"]

    # The base config is untouched (resolving a lane returns a COPY).
    assert cfg.thresholds.min_composite_to_pass == base_min
    assert cfg.gate_map() == base_gates
    assert cfg.active_lane == ""


# --------------------------------------------------------------------------- 2. fan-out
def test_generate_multilane_tags_each_candidate_and_respects_quota():
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    lanes = ["side_hustle", "smb", "growth", "venture"]
    counts = {"side_hustle": 4, "smb": 3, "growth": 3, "venture": 2}

    out = generate_multilane(_BatchOp(), cfg, lanes=lanes, lane_counts=counts,
                             signal_text="")

    assert len(out) == sum(counts.values())            # exactly the per-lane quota total
    by_tier: dict[str, int] = {}
    for c in out:
        assert c.ambition_tier in lanes                # every candidate is tagged
        by_tier[c.ambition_tier] = by_tier.get(c.ambition_tier, 0) + 1
    assert by_tier == counts                            # each lane got its quota


# --------------------------------------------------------------------------- 3. fallback
def test_classify_falls_back_to_generated_tier_on_unknown_or_parse_failure():
    cfg = load_config()
    cand = Candidate(title="x", ambition_tier="growth")

    # Unknown tier (not in active_lanes) => keep the generated tier.
    assert classify_tier(_TierOp("not_a_real_tier"), cand, cfg) == "growth"

    # Parse failure / empty response (plain stub returns {}) => keep generated tier.
    class _Empty:
        model_version = "stub"
        def complete_json(self, system, user, temperature=0.0):
            return {}
    assert classify_tier(_Empty(), cand, cfg) == "growth"

    # Exception in the call => keep generated tier (never raises, never drops).
    class _Boom:
        model_version = "stub"
        def complete_json(self, system, user, temperature=0.0):
            raise RuntimeError("backend down")
    assert classify_tier(_Boom(), cand, cfg) == "growth"


def test_a_candidate_with_no_tier_gets_no_tier_back_when_classification_fails():
    """The fallback must keep what the candidate HAD — and a legacy candidate had nothing.

    Until 2026-08-06 the fallback was `cand.ambition_tier or allowed[0]`, so all three failure
    paths returned `active_lanes[0]` = "side_hustle" for a tier-less candidate, while logging
    "keeping generated tier 'side_hustle'" about a tier nothing had generated. 97 of 154 PASS
    dossiers carry an empty tier, and `listing.pricing` puts side_hustle on rung 1 (2900) against
    the empty tier's default rung 2 (4900) — so a brain outage during the backfill would have cut
    the untiered back catalogue by a third on zero evidence. An empty return is the caller's
    problem to handle; a fabricated tier is nobody's, until it reaches the money rail.
    """
    cfg = load_config()

    class _Empty:
        model_version = "stub"
        def complete_json(self, system, user, temperature=0.0):
            return {}

    class _Boom:
        model_version = "stub"
        def complete_json(self, system, user, temperature=0.0):
            raise RuntimeError("backend down")

    for op in (_TierOp("not_a_real_tier"), _Empty(), _Boom()):
        cand = Candidate(title="a legacy pack with no tier", ambition_tier="")
        assert classify_tier(op, cand, cfg) == "", (
            f"{type(op).__name__} invented a tier for a candidate that never had one"
        )

    # ...and a SUCCESSFUL classification of a tier-less candidate still returns the answer,
    # otherwise the fix would have made the backfill useless rather than safe.
    cand = Candidate(title="a legacy pack with no tier", ambition_tier="")
    assert classify_tier(_TierOp("growth"), cand, cfg) == "growth"


def test_classification_is_not_sampled_creatively():
    """A routing decision that also sets a price rung must not be drawn at temperature 0.7.

    `complete_json` defaults to 0.7 (operator.py:115) and classify.py called it with no
    temperature at all, so the tier — and therefore the rung in `listing.pricing.tier_rung_index`
    — was partly a dice roll across otherwise identical runs.
    """
    seen = {}

    class _Recording:
        model_version = "stub"
        def complete_json(self, system, user, temperature=0.7, **kw):
            seen["temperature"] = temperature
            return {"tier": "smb"}

    cand = Candidate(title="x", ambition_tier="growth")
    assert classify_tier(_Recording(), cand, load_config()) == "smb"
    assert seen["temperature"] == 0.0, (
        f"classify sampled at temperature {seen['temperature']} — the same candidate can come "
        f"back on a different rung run to run"
    )


# --------------------------------------------------------------------------- 4. bar fits idea
def test_candidate_reclassified_is_vetted_against_its_classified_lane():
    """A venture-generated idea classified as side_hustle must be vetted on the side_hustle
    bar. This replicates the exact run.py resolution: after classify, the cfg handed to
    vet_candidate is cfg.for_lane(cand.ambition_tier)."""
    cfg = load_config()
    cand = Candidate(title="A small repeatable gig", ambition_tier="venture")

    # classify re-homes it (side_hustle is in active_lanes).
    cand.ambition_tier = classify_tier(_TierOp("side_hustle"), cand, cfg)
    assert cand.ambition_tier == "side_hustle"

    vet_cfg = cfg.for_lane(cand.ambition_tier)          # the exact line in run_signal
    assert vet_cfg.active_lane == "side_hustle"
    # The side_hustle bar (demand/deliverability), NOT the venture moat bar, reaches verify.
    gates = vet_cfg.gate_map()
    assert "buyer_intent" in gates
    assert "value_durability" not in gates
    assert vet_cfg.thresholds.min_composite_to_pass == 2.5
