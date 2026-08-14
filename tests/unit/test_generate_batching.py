"""generate() must return the requested count, not whatever the model gives in one shot.

A single large "give me k ideas" call reliably under-delivers, so generate() batches
across rounds until it reaches k, telling the model what it already proposed so it
diverges. A dry-guard stops it when the model is genuinely tapped out.
"""
from __future__ import annotations

import time

from prospector.config import load_config
from prospector.generate import generate, plan_wave


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


def test_plan_wave_min_ask_concentrates_small_remainders():
    """The daemon's real shape: batch_size 15 over 4 lanes -> per-lane k of 4.

    The legacy formula floored n_calls at the lens count, so that remainder fanned out as
    5 calls x ask=1 — five full MiniMax-M3 reasoning preambles for four ideas (measured
    2026-08-14, launchd.err.log: every "Produce up to N DISTINCT" read 1). min_ask=5
    concentrates it into ONE call asking for all four."""
    # (remaining, n_axis/forms, n_lenses, max_per_call, min_ask)
    assert plan_wave(4, 8, 5, 10, min_ask=5) == (1, 4)
    # A bigger remainder splits into ceil(13/5)=3 calls of ask=5, not 8 calls of ask=1-2.
    assert plan_wave(13, 8, 5, 10, min_ask=5) == (3, 5)
    # min_ask=1 is the escape hatch: byte-for-byte the historical fan-out (5 calls x 1).
    assert plan_wave(4, 8, 5, 10, min_ask=1) == (5, 1)


def test_plan_wave_respects_caps():
    # ask can never exceed max_per_call, n_calls can never exceed the axis.
    n_calls, ask = plan_wave(100, 4, 5, 10, min_ask=5)
    assert n_calls == 4 and ask == 10
    # Degenerate inputs clamp instead of raising or dividing by zero.
    assert plan_wave(0, 0, 0, 0, min_ask=0) == (1, 1)


def test_generate_deadline_already_past_makes_no_model_calls():
    """The 2026-08-14 force-exit rail: past the generation budget, NO new wave starts.

    Fails without the deadline_mono check in the wave loop: generate() would run its
    full wave fan-out regardless of how much of the tick generation has already eaten."""
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    op = _BatchOp()
    diags: dict = {}
    out = generate(op, cfg, signal_text="", k=20,
                   deadline_mono=time.monotonic() - 1, diagnostics=diags)
    assert out == []
    assert op.calls == 0, "a wave started after the budget was exhausted"
    assert diags.get("gen_budget_exhausted") is True, (
        "the caller must be able to tell 'budget cut generation short' from 'model dry'"
    )


def test_generate_deadline_in_future_changes_nothing():
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    op = _BatchOp()
    out = generate(op, cfg, signal_text="", k=20,
                   deadline_mono=time.monotonic() + 3600)
    assert len(out) == 20 and op.calls > 1  # identical to the unbounded run


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
            self.name = name
            self.behaviour = behaviour
            self.calls = 0

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
