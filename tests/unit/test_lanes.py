"""Ambition-lane resolution (Part 14). A lane judges a candidate against the bar for its
OWN ambition class; the top-level config is the default `venture` (moat) behaviour, and an
empty active_lane must be byte-for-byte unchanged. Lanes override hard_gates (replace) and
partially override thresholds/weights (merge)."""
from prospector.config import Config, Thresholds


def _base() -> Config:
    return Config(
        hard_gates=[{"value_durability": ["refuted"]}, {"adversarial_decisive": True}],
        weights={"pain_acuity": 0.5, "defensibility": 0.5},
        thresholds=Thresholds(confidence_floor=0.6, min_composite_to_pass=3.2),
        lanes={
            "side_hustle": {
                "hard_gates": [{"buyer_intent": ["refuted"]}, {"legality": ["supported"]}],
                "thresholds": {"min_composite_to_pass": 2.0},
                "weights": {"distribution": 0.9},
            }
        },
    )


def test_empty_lane_is_unchanged():
    cfg = _base()
    assert cfg.for_lane("") is cfg
    assert cfg.for_lane(None) is cfg


def test_unknown_lane_returns_self_unchanged():
    cfg = _base()
    assert cfg.for_lane("does_not_exist") is cfg


def test_lane_replaces_hard_gates_and_resolves_gate_map():
    cfg = _base().for_lane("side_hustle")
    assert cfg.active_lane == "side_hustle"
    # moat gate is gone; the intent/legality gates are operative
    assert "value_durability" not in cfg.gate_map()
    assert cfg.gate_map()["buyer_intent"] == ["refuted"]
    assert cfg.gate_map()["legality"] == ["supported"]


def test_lane_merges_thresholds_and_weights():
    cfg = _base().for_lane("side_hustle")
    # overridden
    assert cfg.thresholds.min_composite_to_pass == 2.0
    assert cfg.weights["distribution"] == 0.9
    # inherited (not in the lane override)
    assert cfg.thresholds.confidence_floor == 0.6
    assert cfg.weights["pain_acuity"] == 0.5


def test_resolution_does_not_mutate_the_base():
    base = _base()
    _ = base.for_lane("side_hustle")
    # base is untouched — for_lane returns a new resolved Config
    assert "value_durability" in base.gate_map()
    assert base.active_lane == ""
