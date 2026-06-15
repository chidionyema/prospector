"""generate() must return the requested count, not whatever the model gives in one shot.

A single large "give me k ideas" call reliably under-delivers, so generate() batches
across rounds until it reaches k, telling the model what it already proposed so it
diverges. A dry-guard stops it when the model is genuinely tapped out.
"""
from __future__ import annotations

from prospector.config import load_config
from prospector.generate import generate


class _BatchOp:
    """Returns 6 fresh, distinct ideas per call (simulates a model that diverges)."""

    model_version = "stub"

    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, temperature=0.0):
        self.calls += 1
        return [{"title": f"Idea c{self.calls}-{i}", "one_liner": "x",
                 "why_now": "y", "tags": {"sector": "s"}} for i in range(6)]


class _DryOp:
    """Always returns the SAME 3 titles — the model has nothing new."""

    model_version = "stub"

    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, temperature=0.0):
        self.calls += 1
        return [{"title": f"Dup {i}", "one_liner": "x", "tags": {}} for i in range(3)]


def test_generate_reaches_requested_count():
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    op = _BatchOp()
    out = generate(op, cfg, signal_text="", k=20)
    assert len(out) == 20                       # exactly the requested count
    assert len({c.title for c in out}) == 20    # all distinct (dedup within run)
    assert op.calls > 1                         # proves it batched, not one-shot


def test_generate_trims_overshoot_to_k():
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    out = generate(_BatchOp(), cfg, signal_text="", k=10)
    assert len(out) == 10  # 6+6=12 produced, trimmed to exactly 10


def test_generate_dry_guard_stops_and_returns_what_exists():
    cfg = load_config()
    # ML Improvement: Disable refinement for this test to match expected call count.
    cfg.generation["refinement_enabled"] = False
    op = _DryOp()
    out = generate(op, cfg, signal_text="", k=20)
    assert len(out) == 3       # only 3 distinct ideas exist
    # Generation now fans out PARALLEL waves across the STRUCTURAL-FORM axis (one call per
    # distinct form), so the dry-guard counts fruitless WAVES, not single calls. With the
    # default form set that's n_forms calls/wave (plus 1 refinement call if enabled). 
    # The guard trips after 2 fruitless waves (wave1 finds the 3, waves 2-3 dry) = 3 waves.
    n_forms = len(cfg.generation.get("structural_forms") or []) or 1
    # Refinement optimized to 1 call per wave: (8 generate + 1 refine) * 3 waves = 27.
    assert op.calls <= 3 * (n_forms + 1)   # dry-guard halts after 2 fruitless waves


def test_generate_returns_empty_on_first_round_error():
    cfg = load_config()

    class _Boom:
        model_version = "boom"

        def complete_json(self, *a, **k):
            raise RuntimeError("model down")

    assert generate(_Boom(), cfg, signal_text="", k=20) == []


def test_generate_canary_avoids_thundering_herd_on_dead_brain(tmp_path):
    """L3+L4: when the primary brain is exhausted, the wave-1 CANARY call trips it once;
    persisted health then makes every other parallel call in the wave SKIP it for free —
    instead of N concurrent calls each re-paying the dead brain's failover. The dead brain
    must be hit ~once, not n_calls times."""
    import json
    from prospector.errors import ProviderExhaustedError
    from prospector.health import ProviderHealth
    from prospector.operator import FallbackOperator, Operator

    class _Op(Operator):
        def __init__(self, name, behaviour):
            self.name = name; self.behaviour = behaviour; self.calls = 0

        def _raw(self, system, user, temperature):
            self.calls += 1
            if isinstance(self.behaviour, Exception):
                raise self.behaviour
            return self.behaviour

    live_ideas = json.dumps([{"title": f"Idea {i}", "one_liner": "x", "tags": {}}
                             for i in range(6)])
    dead = _Op("gemini_cli", ProviderExhaustedError("exhausted: reset after 1h0m0s",
                                                     provider="gemini_cli"))
    live = _Op("claude_cli", live_ideas)
    h = ProviderHealth(tmp_path / "h.json")
    fb = FallbackOperator([("gemini_cli", dead), ("claude_cli", live)], health=h)

    out = generate(fb, cfg=load_config(), signal_text="", k=20)
    assert len(out) > 0                 # live brain carried the run
    assert dead.calls <= 2              # canary trips it; herd avoided (would be ~n_calls)
