"""The generation time budget must be able to fire DURING a wave, not only between waves.

WHAT HAPPENED. `store/scheduler/ticks.jsonl` carries three rows reading
`tick_hard_deadline: exceeded 10800s during generation (batch=15); force-exited for relaunch`
(2026-08-13T15:54, 2026-08-14T17:48, 2026-08-14T21:21). A generation phase ran for THREE HOURS
and was killed by the process watchdog.

There was already a rail meant to stop exactly this: `schedule.gen_budget_frac` (0.35), giving
generation 63 minutes of the tick's 10800s deadline before it must hand the rest of the tick to
vetting, artifacts and publish. It never fired. It could not fire. `deadline_mono` was consulted
in ONE place — the `for wave in range(...)` loop in `generate()` — so it could only stop a NEW
wave from starting. Inside a wave there were three nested unbounded joins:

  1. `list(ex.map(_go, indices))`        — blocks until every call in the wave returns
  2. `with ThreadPoolExecutor(...) as ex` — `__exit__` calls `shutdown(wait=True)` and blocks AGAIN
  3. `as_completed(futures)` in `generate_multilane` with no timeout, inside another `with pool:`

A rail that can only fire between waves cannot bound a wave. The 3-hour process kill was the
engine's only real time bound, and force-exiting mid-tick drops whatever was scheduled to run
second — which, by `_generation_pass`'s own design comment, is the vetting that turns a
candidate into a verdict.

WHAT THIS PINS. Not "the timeout constant exists" — that was true while the daemon burned three
hours. It pins the OBSERVABLE CONSEQUENCE: when the budget is exhausted, generation returns the
lanes that answered, in bounded time, and says in its diagnostics which lanes it abandoned.

Note what is deliberately NOT claimed: abandoning a future does not kill the thread running it.
The in-flight HTTP call keeps going until the adapter's own total deadline fires
(`operator.py:_urlopen_read_bounded` / `_read_sse_bounded`). What changes is that generation
stops WAITING. Asserting anything about the thread's death would be asserting something false.
"""
from __future__ import annotations

import time

import pytest

from prospector import generate as gen_mod
from prospector.models import Candidate

# Long enough that a broken bound is unmistakable, short enough not to slow the suite if the
# test itself regresses into actually waiting for it.
STALL_S = 30.0
BUDGET_S = 1.0


def _cand(title: str) -> Candidate:
    return Candidate(title=title, one_liner="x", hypothesis="y", who_pays="z")


@pytest.fixture
def cfg():
    from prospector.config import load_config
    return load_config()


def test_a_stalled_lane_does_not_hold_the_whole_generation_phase(cfg, monkeypatch):
    """The outermost join: `generate_multilane` waits on lanes, and one lane never answers.

    Falsifier: with the old `as_completed(futures)` (no timeout) inside `with pool:`, this
    returns after STALL_S, not after BUDGET_S — so the elapsed-time assertion fails on the
    pre-fix code. It is the elapsed time, not the return value, that distinguishes them: the
    old code returned the fast lane's candidates too, just 30 seconds later.
    """
    # `_run_lane` calls `generate(op, cfg.for_lane(tier), ..., k=lane_counts[tier], ...)` and
    # does not pass the tier itself, so the fake identifies the lane by its distinct quota.
    lane_counts = {"side_hustle": 1, "venture": 2}
    by_k = {1: "side_hustle", 2: "venture"}

    def _fake(op, lane_cfg, *, k=None, **kw):
        tier = by_k[k]
        if tier == "venture":
            time.sleep(STALL_S)          # the lane that never answers in time
            return [_cand("venture-late")]
        return [_cand(f"{tier}-ok")]

    monkeypatch.setattr(gen_mod, "generate", _fake)

    diagnostics: dict = {}
    t0 = time.monotonic()
    out = gen_mod.generate_multilane(
        object(), cfg, lanes=["side_hustle", "venture"], lane_counts=lane_counts,
        signal_text="", diagnostics=diagnostics,
        deadline_mono=time.monotonic() + BUDGET_S)
    elapsed = time.monotonic() - t0

    assert elapsed < STALL_S / 2, (
        f"generate_multilane waited {elapsed:.1f}s against a {BUDGET_S}s budget — the stalled "
        f"lane held the phase, which is the 3-hour tick in miniature")
    assert diagnostics.get("gen_budget_exhausted") is True, (
        "the phase gave up on a lane and did not record it; a batch that is short a whole "
        "ambition tier must not be indistinguishable from one where that tier found nothing")
    assert diagnostics.get("stalled_lanes") == ["venture"], (
        f"the abandoned lane must be NAMED, got {diagnostics.get('stalled_lanes')!r}")
    # The lane that answered still ships. Dropping it would trade a hang for data loss.
    assert [c.title for c in out] == ["side_hustle-ok"], (
        f"the fast lane's candidates must survive the slow lane's abandonment, got "
        f"{[c.title for c in out]!r}")


def test_a_budget_that_has_not_expired_still_waits_for_every_lane(cfg, monkeypatch):
    """The other direction, and the reason this is a bound and not a truncation.

    A healthy generation phase measured ~3 min against a 63-min budget. If the bound fired
    early — or fired on a lane that was merely slower than its sibling — it would silently
    shrink every batch. So: with budget to spare, BOTH lanes are collected and nothing is
    recorded as exhausted.
    """
    def _fake(op, lane_cfg, *, k=None, **kw):
        time.sleep(0.05)
        return [_cand(f"k{k}-ok")]

    monkeypatch.setattr(gen_mod, "generate", _fake)
    diagnostics: dict = {}
    out = gen_mod.generate_multilane(
        object(), cfg, lanes=["side_hustle", "venture"],
        lane_counts={"side_hustle": 1, "venture": 2}, signal_text="",
        diagnostics=diagnostics, deadline_mono=time.monotonic() + 60.0)

    assert len(out) == 2, f"both lanes must be collected when the budget is intact, got {out!r}"
    assert "gen_budget_exhausted" not in diagnostics, (
        "a phase that finished inside its budget must not report itself exhausted — that flag "
        "is what the tick digest and the operator's phone read")
    assert "stalled_lanes" not in diagnostics


def test_the_bound_is_what_makes_the_test_above_pass(cfg, monkeypatch):
    """THE FALSIFIER. A green test proves nothing until it is shown to go red on the defect.

    The pre-fix join was `as_completed(futures)` — no timeout — inside `with pool:`. Setting
    `_budget_left` to return None restores exactly that call (`timeout=None`) on the real
    function, in the real module: same submit, same loop, same `finally`. So this measures the
    OLD behaviour, not a reconstruction of it.

    If this test ever fails — i.e. the phase returns fast even with the timeout removed — then
    the test above is passing for some other reason and its guarantee is not the one claimed.
    """
    stall, budget = 4.0, 0.5

    def _fake(op, lane_cfg, *, k=None, **kw):
        if k == 2:
            time.sleep(stall)
        return [_cand(f"k{k}")]

    monkeypatch.setattr(gen_mod, "generate", _fake)
    monkeypatch.setattr(gen_mod, "_budget_left", lambda _d: None)   # = the pre-fix join

    diagnostics: dict = {}
    t0 = time.monotonic()
    gen_mod.generate_multilane(
        object(), cfg, lanes=["side_hustle", "venture"],
        lane_counts={"side_hustle": 1, "venture": 2}, signal_text="",
        diagnostics=diagnostics, deadline_mono=time.monotonic() + budget)
    elapsed = time.monotonic() - t0

    assert elapsed >= stall * 0.8, (
        f"with the timeout removed the phase returned in {elapsed:.1f}s against a {stall}s "
        f"stall — the bounded-wait test above is therefore not measuring the bound")
    assert "gen_budget_exhausted" not in diagnostics, (
        "the pre-fix path had no way to notice; if this flag appears the falsifier is not "
        "reproducing the before-state")


def test_budget_left_never_returns_a_negative_wait(monkeypatch):
    """`as_completed(timeout=<negative>)` is not an error, it is an immediate give-up — which
    is right at the deadline but wrong if a already-finished future is sitting there. The
    helper floors at a small positive value so a completed future is still collected."""
    assert gen_mod._budget_left(None) is None
    past = time.monotonic() - 5000
    left = gen_mod._budget_left(past)
    assert left is not None and left > 0, f"expected a small positive wait, got {left!r}"
    assert left < 1.0, f"an expired deadline must not grant a fresh wait, got {left!r}"
