"""Generation can never again starve vetting: the tick hands generation a time budget.

THE INCIDENT THIS ENCODES (store/scheduler/alerts.jsonl, 2026-08-14)

  11:23-15:57Z  critical  barren_streak x18  "produced nothing for 21 ticks in a row"
  20:48:25Z     critical  tick_error         "tick_hard_deadline: exceeded 10800s during
                                              generation (batch=15); force-exited"

A degraded generation chain (MiniMax-M3 truncation-retrying at up to ~30 min per call
slot after claude_cli left the non-critical chain, commit d704595) spent the ENTIRE 3h
tick inside generate()'s wave loop. Vetting, artifacts and publish — the phases that
actually produce dossiers — never ran. The daemon force-exited 21 ticks in a row and the
founder discovered it by asking.

WHAT IS PINNED

1. `_default_generate` passes `gen_time_budget_s = gen_budget_frac x tick deadline` into
   `run_signal`. Without the pass-through the rail in generate() is dead code.
2. The default frac is 0.35 and comes from `schedule.gen_budget_frac`; 0 disables the
   rail explicitly (budget None), it does not mean "a zero-second budget".
3. The commit-time guard (scripts/gen_budget_guard.py, run by
   scripts/verify_engine_change.sh check 4) fires in BOTH directions: exit 0 on the live
   config, exit 1 on a config whose projected generation phase exceeds its share — and
   exit 1 under the measured degraded-day call time, which is the 2026-08-14 shape.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

from prospector.scheduler import run_scheduled

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "scripts" / "gen_budget_guard.py"


def _scrubbed_env(**extra: str) -> dict:
    """The guard's constants are env-overridable; a stray override in the runner's env
    would make these assertions measure the environment, not the guard."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROSPECTOR_")}
    env.update(extra)
    return env


def test_the_tick_passes_generation_a_time_budget(monkeypatch):
    """Fails without the change: run_signal used to be called with no gen_time_budget_s,
    so a degraded chain could legally generate for the whole 10800s tick.

    THE BUDGET IS A FRACTION OF WHAT IS LEFT, NOT OF THE WHOLE DEADLINE — `run_scheduled.py`
    computes `frac * (_TICK_HARD_DEADLINE_S - spent)` on purpose (2026-08-15), so the number
    that arrives here is always a hair BELOW `frac x deadline` by however long the drain and
    the setup above it took.

    This used to assert equality through `pytest.approx`, whose default tolerance is relative
    at 1e-6 — on 3780s that is 3.8 MILLISECONDS. So the test graded how fast the box was, not
    what the code does, and it passed only because a laptop got from T0 to the budget line in
    under 4ms. It failed in CI on 2026-08-17 at `3779.9960958182432 == 3779.9999999999995 ±
    0.00378`, which is the rail working exactly as designed.

    The window below is what the rail actually promises: a budget was passed, it never exceeds
    the configured share, and it is not some unrelated number. A regression to a fraction of
    the FULL deadline still passes here — that is fine, this test's job is the pass-through.
    `test_the_budget_is_a_fraction_of_what_is_left` below owns the remainder property, on a
    frozen clock, because a real one cannot pin it without grading the box.
    """
    seen: dict = {}

    def fake_run_signal(_text, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr("prospector.run.run_signal", fake_run_signal)
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)

    run_scheduled._default_generate(types.SimpleNamespace(schedule={"resume_per_tick": 0}), 15)

    budget = seen.get("gen_time_budget_s")
    share = 0.35 * run_scheduled._TICK_HARD_DEADLINE_S
    assert budget is not None, (
        "generation must get gen_budget_frac x the tick's remaining time, not an unbounded phase"
    )
    assert 0 < budget <= share, (
        f"budget {budget} must be positive and never exceed the configured share {share}"
    )
    assert share - budget < 60, (
        f"budget {budget} is {share - budget:.1f}s below the {share}s share. This test does no "
        f"real work before the budget is computed, so the gap is setup cost only; a minute of it "
        f"means the number came from somewhere else"
    )


def test_the_budget_is_a_fraction_of_what_is_left(monkeypatch):
    """The 2026-08-15 rule: all three budgets are fractions of the time REMAINING in the tick,
    never of the whole deadline.

    The hole it closed: the drain runs inside the hard-deadline Timer but has no budget of its
    own, so fractions of the FULL deadline promised `drain + 0.85 x D` of work inside a `D`
    fence. Measured that day, the drain alone could take a third of a tick.

    A real clock cannot pin this. The elapsed time between T0 and the budget line is a few
    milliseconds of setup, so `frac x left` and `frac x deadline` differ by less than the noise
    — which is exactly how the pass-through test above ended up asserting wall-clock speed to a
    millionth and failing in CI. Freezing the clock makes the difference 300 seconds and the
    assertion exact.
    """
    seen: dict = {}
    calls = {"n": 0}

    def frozen_monotonic() -> float:
        """T0 on the first call, T0 + 300s on every call after it.

        `_default_generate` takes its T0 on its first line, so the first call is the tick's
        start and every later one is the moment a budget is computed.
        """
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 300.0

    def fake_run_signal(_text, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr("prospector.run.run_signal", fake_run_signal)
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)
    monkeypatch.setattr(run_scheduled.time, "monotonic", frozen_monotonic)

    run_scheduled._default_generate(types.SimpleNamespace(schedule={"resume_per_tick": 0}), 15)

    left = run_scheduled._TICK_HARD_DEADLINE_S - 300.0
    whole = 0.35 * run_scheduled._TICK_HARD_DEADLINE_S
    assert seen.get("gen_time_budget_s") == 0.35 * left, (
        f"with 300s of the tick already spent, generation must get 0.35 x {left}s of REMAINING "
        f"time. A fraction of the whole deadline would be {whole}s, which overruns the fence "
        f"the budget exists to stay inside"
    )


def test_gen_budget_frac_zero_disables_the_rail(monkeypatch):
    seen: dict = {}

    def fake_run_signal(_text, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr("prospector.run.run_signal", fake_run_signal)
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)

    cfg = types.SimpleNamespace(schedule={"resume_per_tick": 0, "gen_budget_frac": 0})
    run_scheduled._default_generate(cfg, 15)

    assert seen.get("gen_time_budget_s") is None, (
        "frac 0 must mean 'rail off' (None), never 'a zero-second budget that kills "
        "every wave before it starts'"
    )


def test_gen_budget_frac_reader_is_bounded_and_defaulted():
    assert run_scheduled._gen_budget_frac(types.SimpleNamespace(schedule={})) == 0.35
    assert run_scheduled._gen_budget_frac(
        types.SimpleNamespace(schedule={"gen_budget_frac": 0.5})) == 0.5
    # Garbage falls back to the default rather than crashing the tick.
    assert run_scheduled._gen_budget_frac(
        types.SimpleNamespace(schedule={"gen_budget_frac": "lots"})) == 0.35
    # Negative can never become a negative deadline (instant budget exhaustion).
    assert run_scheduled._gen_budget_frac(
        types.SimpleNamespace(schedule={"gen_budget_frac": -1})) == 0.0


def test_guard_passes_the_live_config():
    """Direction 1: the config the daemon is running right now must clear its own guard."""
    r = subprocess.run(
        [sys.executable, str(GUARD), "--config", str(REPO / "config.yaml")],
        capture_output=True, text=True, env=_scrubbed_env(), cwd=REPO,
    )
    assert r.returncode == 0, f"guard failed the LIVE config:\n{r.stdout}{r.stderr}"


def test_guard_fails_a_config_whose_generation_share_cannot_fit(tmp_path):
    """Direction 2a: a config-only breach — a gen_budget_frac too small for the projected
    phase — must exit 1. Fails without the guard (the old check compared an inert value)."""
    import yaml

    cfg = yaml.safe_load((REPO / "config.yaml").read_text())
    cfg.setdefault("schedule", {})["gen_budget_frac"] = 0.01  # 108s share of a 10800s tick
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(cfg))

    r = subprocess.run(
        [sys.executable, str(GUARD), "--config", str(bad)],
        capture_output=True, text=True, env=_scrubbed_env(), cwd=REPO,
    )
    assert r.returncode == 1, f"guard waved through an unfittable config:\n{r.stdout}{r.stderr}"


def test_guard_fails_under_the_measured_degraded_day():
    """Direction 2b: the 2026-08-14 shape. With the legacy fan-out (min_ask=1) and the
    degraded-day per-call time (truncation retries pushed call slots toward the 600s
    operator deadline, operator.py _TOTAL_DEADLINE_S), the projection must breach."""
    import yaml

    cfg_path = REPO / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg.setdefault("generation", {})["min_ask"] = 1  # the pre-change fan-out
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(cfg, f)
        legacy = f.name
    try:
        r = subprocess.run(
            [sys.executable, str(GUARD), "--config", legacy],
            capture_output=True, text=True,
            env=_scrubbed_env(PROSPECTOR_GEN_P50_CALL_S="600"), cwd=REPO,
        )
        assert r.returncode == 1, (
            f"guard passed the 2026-08-14 failure shape:\n{r.stdout}{r.stderr}"
        )
    finally:
        os.unlink(legacy)


def test_guard_fails_loud_on_unreadable_config(tmp_path):
    r = subprocess.run(
        [sys.executable, str(GUARD), "--config", str(tmp_path / "absent.yaml")],
        capture_output=True, text=True, env=_scrubbed_env(), cwd=REPO,
    )
    assert r.returncode == 1, "a guard that cannot evaluate must fail, not wave through"
