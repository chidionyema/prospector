"""The tick must end by its own decision, not by a SIGKILL — the k=50 stability rails.

WHAT WAS MEASURED (the reason these rails exist, so nobody re-derives it)

`store/scheduler/launchd.err.log` records FIVE `_TICK_HARD_DEADLINE_S` breaches between
2026-08-13 and 2026-08-15, every one of them at `batch_size: 15`, every one phrased
"exceeded 10800s during generation" — which is the label `run_scheduled` puts on the whole
`run_signal` call, not on candidate drafting. Profiling the last of them (window
10:17:56Z -> 13:17:56Z; every inter-line wall-clock gap attributed to the line before it,
all 10800s accounted for) found:

    vet_candidate completed              18
    survived all gates                    9
    EngineBridge publishes                3
    LLM calls started                   528   (58.7 per surviving candidate)
    minimax spend                     $2.31
    => 1200s of wall clock PER SURVIVING CANDIDATE

`batch_size` is 50. 50 candidates at that cost is roughly ten hours of work inside a
10800s deadline on a 7200s interval, so NO budget makes the batch fit and any number that
claims to is a lie about throughput. What a budget changes is WHICH failure happens:

  before — `_force_exit_hung_tick`'s timer calls `os._exit` mid-candidate. The in-flight
           vet banks nothing, no tick row is written, and the daemon relaunches knowing
           nothing about the thing it most needs to know about.
  after  — the loop cancels un-started vets, keeps every verdict already paid for
           (`store.save` runs inside `vet_candidate`), PARKS each cancelled candidate as a
           DEFER row for the drain, logs the split, and returns. Partial and honest beats
           complete and dead.

WHAT IS PINNED HERE

1. `_vet_budget_cancel`'s three-valued contract, including that 0 is an answer and not a
   "keep going" — the direction a counting bug must never fail in.
2. That cancellation cannot destroy paid-for work: `Future.cancel()` refuses a running vet.
3. That `_generate_pack_content` converts its seconds into ONE deadline shared by both
   generators and by all `_MAX_PACK_GEN_ATTEMPTS` regeneration attempts. A per-attempt
   budget would let a degraded chain spend 3x the number config declares.
4. That `_default_generate` actually passes both budgets down. An unconsumed budget is an
   inert rail, and an inert rail that reads as installed is worse than no rail — the
   artifact budget shipped in exactly that state for several hours on 2026-08-15.
5. That frac 0 means "rail off" (None), never "a zero-second budget".
6. That a cancelled candidate is PARKED as DEFER rather than dropped. Without this the
   stop is a throughput lie: a k=50 batch pays a k=50 generation bill, bins ~32 already-
   selected candidates, and reports "18 vetted, 18 banked" with nothing amiss.
7. That the BACKLOG DRAIN has a wall, and that the three rails above are fractions of what
   the drain LEFT rather than of the whole deadline.

THE SECOND MEASUREMENT (2026-08-15, after the first live k=50 proof run)

The rails above were each individually correct and the tick still could not fit, because
the drain runs FIRST, inside the same hard-deadline Timer, and had no ceiling of any kind.
From the daemon's own log:

    tick 2026-08-15T10:16:59Z   3 rows took 4197s of a 10800s tick (39%) before generation
    tick 2026-08-15T13:23:07Z   row 1 alone took 4127s; row 2 still running at +5885s (55%)

and per row the dominant cost is not the verdict but the CONTENT phase on a row that passes
(1461s of 2844s = 51%; 2331s of 4127s = 56%). So every rail downstream was being handed a
tick that had already been spent, and `run_signal` starting its vet clock when CALLED meant
fractions of the full deadline promised `drain + 0.85 x D` of work inside a `D` fence.

The drain's stop is a plain hard wall rather than a park-and-resume, and that asymmetry is
deliberate: an unreached backlog row keeps its state and its place in the priority sort, so
nothing is discarded. A cancelled vetting candidate had already been paid for.
"""
from __future__ import annotations

import ast
import time
import types
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import pytest

from prospector import run as run_mod
from prospector.scheduler import run_scheduled

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# 1. The stop itself
# --------------------------------------------------------------------------- #
def _pending(n: int) -> list:
    """`n` futures that have never been handed to an executor, so cancel() succeeds."""
    return [Future() for _ in range(n)]


def test_no_budget_never_stops_anything():
    """Every CLI caller passes None. The rail must be invisible to them."""
    futures = _pending(3)
    assert run_mod._vet_budget_cancel(None, futures) is None
    assert not any(f.cancelled() for f in futures)


def test_a_budget_with_time_left_does_not_stop_anything():
    futures = _pending(3)
    assert run_mod._vet_budget_cancel(time.monotonic() + 300, futures) is None
    assert not any(f.cancelled() for f in futures)


def test_a_spent_budget_cancels_every_un_started_vet():
    futures = _pending(4)
    assert run_mod._vet_budget_cancel(time.monotonic() - 1, futures) == 4
    assert all(f.cancelled() for f in futures)


def test_zero_cancellable_is_an_answer_not_a_keep_going():
    """`0` and `None` are different facts: "the budget is spent and there was nothing left
    to cancel" must still stop the loop announcing itself, or the rail fires every
    iteration for the rest of the batch."""
    assert run_mod._vet_budget_cancel(time.monotonic() - 1, []) == 0
    assert run_mod._vet_budget_cancel(time.monotonic() - 1, []) is not None


def test_the_stop_cannot_discard_work_already_paid_for():
    """The whole safety argument for this rail in one test: `Future.cancel()` refuses a vet
    that is already running, so a breach declines to buy more evidence and can never throw
    away evidence we have already bought."""
    started, release = __import__("threading").Event(), __import__("threading").Event()

    def _slow_vet():
        started.set()
        release.wait(5)
        return "a verdict we paid for"

    with ThreadPoolExecutor(max_workers=1) as ex:
        running = ex.submit(_slow_vet)
        queued = [ex.submit(_slow_vet) for _ in range(3)]
        assert started.wait(5), "the first vet never started; the test proves nothing"

        cancelled = run_mod._vet_budget_cancel(time.monotonic() - 1, [running, *queued])

        assert cancelled == 3, "un-started vets must be cancelled"
        assert not running.cancelled(), "a RUNNING vet must survive the budget stop"
        release.set()
        assert running.result(timeout=5) == "a verdict we paid for"


# --------------------------------------------------------------------------- #
# 2. The artifact ceiling reaches the two generators, once
# --------------------------------------------------------------------------- #
_BODY = "## Section\n\n" + ("Real, moat-verified prose that a buyer would pay for. " * 30)
_GOOD_ARTIFACTS = {k: f"# {k}\n\n{_BODY}\n\n## Second section\n\n{_BODY}"
                   for k in ("build_spec", "gtm_plan", "ops_plan", "financial_model")}
_GOOD_MARKETING = [{"type": "listing_page", "copy": "Listing copy that sells the pack. " * 8}]


class _Cand:
    candidate_id = "c" * 16
    tags: dict = {}


@pytest.fixture
def deadline_spy(monkeypatch):
    """Record the `deadline_mono` each generator is handed, per attempt."""
    seen: dict = {"artifacts": [], "marketing": []}
    plan: list = []

    def _fake_artifacts(*a, **k):
        seen["artifacts"].append(k.get("deadline_mono"))
        return plan[min(len(seen["artifacts"]) - 1, len(plan) - 1)]

    def _fake_marketing(*a, **k):
        seen["marketing"].append(k.get("deadline_mono"))
        return list(_GOOD_MARKETING)

    import prospector.artifacts as arts_mod
    monkeypatch.setattr(arts_mod, "generate_artifacts", _fake_artifacts)
    monkeypatch.setattr(arts_mod, "generate_marketing_content", _fake_marketing)
    return seen, plan


def _run(**kw):
    return run_mod._generate_pack_content(
        object(), _Cand(), [], query_op=None, quality_op=None, cfg=None, score=None, **kw)


def test_no_artifact_budget_leaves_both_generators_unbounded(deadline_spy):
    """Byte-for-byte the pre-rail behaviour for every CLI caller."""
    seen, plan = deadline_spy
    plan.append(dict(_GOOD_ARTIFACTS))
    _run()
    assert seen["artifacts"] == [None]
    assert seen["marketing"] == [None]


def test_the_artifact_budget_reaches_both_generators(deadline_spy):
    """Fails before the wire-up: `run.py` had no parameter to receive the fraction
    `run_scheduled._artifact_budget_frac` had been resolving since that morning, so both
    generators were called with `deadline_mono=None` and the rail was inert."""
    seen, plan = deadline_spy
    plan.append(dict(_GOOD_ARTIFACTS))
    before = time.monotonic()
    _run(artifact_time_budget_s=4320)
    after = time.monotonic()

    for who in ("artifacts", "marketing"):
        assert len(seen[who]) == 1 and seen[who][0] is not None, f"{who} left unbounded"
        assert before + 4320 <= seen[who][0] <= after + 4320, (
            f"{who} got a deadline that is not now + the budget")


def test_one_deadline_is_shared_by_the_generators_and_by_every_retry(deadline_spy):
    """A PER-ATTEMPT budget would let a degraded chain spend `_MAX_PACK_GEN_ATTEMPTS` x the
    number config declares — the unbounded behaviour this replaces, in instalments."""
    seen, plan = deadline_spy
    plan.append({**_GOOD_ARTIFACTS, "build_spec": ""})   # attempt 1: an outage
    plan.append({**_GOOD_ARTIFACTS, "build_spec": ""})   # attempt 2: still out
    plan.append(dict(_GOOD_ARTIFACTS))                   # attempt 3: recovered

    _run(artifact_time_budget_s=4320)

    everything = seen["artifacts"] + seen["marketing"]
    assert len(seen["artifacts"]) > 1, "the retry loop did not run; the test proves nothing"
    assert len(set(everything)) == 1, (
        f"the deadline was recomputed per call/attempt: {everything}")


def test_the_batch_deadline_clamps_the_per_candidate_ceiling(deadline_spy):
    """WITHOUT THIS THE BATCH RAIL IS NOT A GUARANTEE. `_vet_budget_cancel` can only cancel
    vets that have not started; every vet already running keeps going, and with
    `_vet_workers` of them in flight — each holding a 4320s artifact ceiling — the batch
    sails past the tick's hard deadline having "stopped". Whichever instant is sooner wins."""
    seen, plan = deadline_spy
    plan.append(dict(_GOOD_ARTIFACTS))
    batch_stops_in_60s = time.monotonic() + 60

    _run(artifact_time_budget_s=4320, vet_deadline_mono=batch_stops_in_60s)

    assert seen["artifacts"] == [batch_stops_in_60s], (
        "a running vet was allowed to spend 72 minutes of artifact budget past the batch stop")
    assert seen["marketing"] == [batch_stops_in_60s]


def test_the_clamp_never_shortens_a_ceiling_that_is_already_tighter(deadline_spy):
    """The clamp is a ceiling, not an override: a per-candidate budget that expires before
    the batch does must keep its own, earlier deadline."""
    seen, plan = deadline_spy
    plan.append(dict(_GOOD_ARTIFACTS))
    far_off = time.monotonic() + 9180

    before = time.monotonic()
    _run(artifact_time_budget_s=30, vet_deadline_mono=far_off)

    assert seen["artifacts"][0] < far_off
    assert before + 30 <= seen["artifacts"][0] <= time.monotonic() + 30


def test_the_batch_deadline_alone_still_bounds_the_content_phase(deadline_spy):
    """`artifact_budget_frac: 0` turns the per-candidate rail off. That must not also turn
    off the batch's bound on content work — an operator disabling one rail should not
    silently lose the other."""
    seen, plan = deadline_spy
    plan.append(dict(_GOOD_ARTIFACTS))
    batch = time.monotonic() + 120
    _run(artifact_time_budget_s=None, vet_deadline_mono=batch)
    assert seen["artifacts"] == [batch]


# --------------------------------------------------------------------------- #
# 3. The daemon actually passes them
# --------------------------------------------------------------------------- #
class _FrozenClock:
    """A `time` stand-in whose monotonic only moves when a test moves it.

    Everything except `monotonic` falls through to the real module, so code under test that
    calls `time.sleep`/`time.time` behaves normally. Used instead of `time.sleep` because a
    budget assertion that measures the wall clock is a load detector, not a regression
    detector — two such assertions went red on unchanged code under `-n auto` on 2026-08-15.
    """

    def __init__(self, t0: float = 10_000.0):
        self.t = t0

    def monotonic(self) -> float:
        return self.t

    def __getattr__(self, name):  # only reached for attributes not defined above
        return getattr(time, name)


def _default_generate_kwargs(monkeypatch, schedule: dict, drain_seconds: float = 0.0) -> dict:
    seen: dict = {}
    clock = _FrozenClock()

    def fake_run_signal(_text, **kwargs):
        seen.update(kwargs)
        return []

    def fake_drain(_cfg, _n):
        clock.t += drain_seconds  # the drain is unbudgeted; it just burns tick time
        return None

    monkeypatch.setattr(run_scheduled, "time", clock)
    monkeypatch.setattr(run_scheduled, "_drain_pass", fake_drain)
    monkeypatch.setattr("prospector.run.run_signal", fake_run_signal)
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)
    run_scheduled._default_generate(types.SimpleNamespace(schedule=schedule), 50)
    return seen


def test_the_tick_hands_down_all_three_budgets(monkeypatch):
    seen = _default_generate_kwargs(monkeypatch, {"resume_per_tick": 0})
    tick = run_scheduled._TICK_HARD_DEADLINE_S
    assert seen.get("gen_time_budget_s") == pytest.approx(0.35 * tick)
    assert seen.get("artifact_time_budget_s") == pytest.approx(0.40 * tick)
    assert seen.get("vet_time_budget_s") == pytest.approx(0.85 * tick)


def test_the_budgets_are_fractions_of_what_the_drain_left_not_of_the_whole_tick(monkeypatch):
    """The hole the first live k=50 proof run opened on 2026-08-15, before it ever reached
    vetting.

    `_default_generate` re-vets backlog BEFORE it generates, and that drain runs inside the
    hard-deadline Timer with no budget of its own. `run_signal` then starts its vet clock when
    it is CALLED. So fractions of the full deadline promised `drain + 0.85 x D` seconds of work
    inside a `D`-second fence: the clean stop would itself have been overrun by the force-exit
    it exists to prevent, and the tick would die by `os._exit(2)` with the batch unsaved —
    exactly the failure the rails were built for, re-entered through the back door.

    Not a corner case, and the real figure is worse than the ~1200s/candidate generation
    profile suggested: on the daemon's own log the 10:16:59Z tick spent 4197s of 10800s (39%)
    on 3 drained rows before generation began, and the 13:23:07Z tick was still draining at
    +5885s (55%). See `_DRAIN_BUDGET_FRAC` for the per-row breakdown.
    """
    tick = run_scheduled._TICK_HARD_DEADLINE_S
    drain = 0.30 * tick
    seen = _default_generate_kwargs(monkeypatch, {"resume_per_tick": 3}, drain_seconds=drain)
    left = tick - drain

    assert seen["vet_time_budget_s"] == pytest.approx(0.85 * left), (
        "the vetting rail was sized off the whole deadline, so it would have kept vetting "
        f"until {drain + 0.85 * tick:.0f}s into a {tick}s tick")
    assert seen["gen_time_budget_s"] == pytest.approx(0.35 * left)
    assert seen["artifact_time_budget_s"] == pytest.approx(0.40 * left)

    # The property that actually matters, stated as the fence rather than as arithmetic.
    assert drain + seen["vet_time_budget_s"] < tick, (
        "the tick would still be vetting when the force-exit timer fires")


def test_a_drain_that_eats_the_whole_tick_yields_no_negative_budget(monkeypatch):
    """A budget that has gone negative is a deadline already in the past, which cancels every
    vet before it starts — a tick that looks busy and rules nothing. Clamp at zero-left."""
    tick = run_scheduled._TICK_HARD_DEADLINE_S
    seen = _default_generate_kwargs(monkeypatch, {"resume_per_tick": 3},
                                    drain_seconds=2.0 * tick)
    for kwarg in ("gen_time_budget_s", "artifact_time_budget_s", "vet_time_budget_s"):
        assert seen[kwarg] >= 0.0, f"{kwarg} went negative: {seen[kwarg]}"


def test_the_batch_budget_lands_below_the_force_exit_timer(monkeypatch):
    """A rail that fires at the same instant as the thing it exists to pre-empt is a coin
    toss. The vetting stop must leave room for the publish/telemetry/drain work that
    follows `run_signal` inside the same tick and carries no budget of its own."""
    seen = _default_generate_kwargs(monkeypatch, {"resume_per_tick": 0})
    assert seen["vet_time_budget_s"] < run_scheduled._TICK_HARD_DEADLINE_S
    headroom = run_scheduled._TICK_HARD_DEADLINE_S - seen["vet_time_budget_s"]
    assert headroom >= 900, f"only {headroom:.0f}s left after vetting for publish + drain"


@pytest.mark.parametrize("key,kwarg", [
    ("gen_budget_frac", "gen_time_budget_s"),
    ("artifact_budget_frac", "artifact_time_budget_s"),
    ("vet_budget_frac", "vet_time_budget_s"),
])
def test_frac_zero_disables_each_rail_explicitly(monkeypatch, key, kwarg):
    """0 must mean "rail off" (None). A zero-second budget would cancel every vet before it
    started and produce a tick that looks busy and rules nothing."""
    seen = _default_generate_kwargs(monkeypatch, {"resume_per_tick": 0, key: 0})
    assert seen.get(kwarg) is None


def test_the_vet_budget_reader_is_bounded_and_defaulted():
    frac = run_scheduled._vet_budget_frac
    assert frac(types.SimpleNamespace(schedule={})) == 0.85
    assert frac(types.SimpleNamespace(schedule={"vet_budget_frac": 0.5})) == 0.5
    assert frac(types.SimpleNamespace(schedule={"vet_budget_frac": "lots"})) == 0.85
    # Negative can never become a deadline already in the past at t=0.
    assert frac(types.SimpleNamespace(schedule={"vet_budget_frac": -1})) == 0.0


def test_the_live_config_declares_the_rails_rather_than_relying_on_defaults():
    """Params live in config, not in constants (project rule). This also catches the case
    where a key is documented in a comment and never actually added to the mapping."""
    import yaml
    schedule = yaml.safe_load((REPO / "config.yaml").read_text())["schedule"]
    assert schedule["artifact_budget_frac"] == 0.40
    assert schedule["vet_budget_frac"] == 0.85
    assert schedule["gen_budget_frac"] + schedule["artifact_budget_frac"] <= 1.0


# --------------------------------------------------------------------------- #
# 4. The three-hop wiring, checked in the source
# --------------------------------------------------------------------------- #
def _calls_in(func_name: str, callee: str) -> list:
    tree = ast.parse((REPO / "prospector" / "run.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == func_name)
    return [c for c in ast.walk(fn)
            if isinstance(c, ast.Call)
            and (getattr(c.func, "id", None) or getattr(c.func, "attr", None)) == callee]


def test_run_signal_forwards_the_artifact_budget_into_every_vet():
    """A STRUCTURAL check, and named as one: it proves the kwarg is written at the call
    site, not that a budget survives a live vet. It exists because the hop it guards has
    no cheap runtime test — `vet_candidate` only reaches `_generate_pack_content` after a
    full moat run — and because this is exactly the hop that was missing while the rail
    read as installed."""
    submits = _calls_in("run_signal", "submit")
    vet_submits = [c for c in submits
                   if any(getattr(a, "id", None) == "vet_candidate" for a in c.args)]
    assert vet_submits, "run_signal no longer submits vet_candidate; update this test"
    assert any(kw.arg == "artifact_time_budget_s" for c in vet_submits for kw in c.keywords), (
        "the artifact budget is resolved by the daemon and dropped before vet_candidate")


def test_vet_candidate_forwards_the_artifact_budget_into_the_content_phase():
    calls = _calls_in("vet_candidate", "_generate_pack_content")
    assert calls, "vet_candidate no longer generates pack content; update this test"
    assert any(kw.arg == "artifact_time_budget_s" for c in calls for kw in c.keywords)


def test_the_vetting_loop_consults_the_batch_budget():
    calls = _calls_in("run_signal", "_vet_budget_cancel")
    assert calls, "run_signal never calls the batch-budget stop; the rail is inert"
    assert any(getattr(a, "id", None) == "_vet_deadline" for c in calls for a in c.args), (
        "the stop is called with something other than the vetting deadline")


# --------------------------------------------------------------------------- #
# 5. The cancelled candidates are parked, not dropped
# --------------------------------------------------------------------------- #
class _Store:
    def __init__(self, fail=False):
        self.saved = []
        self.fail = fail

    def save(self, d):
        if self.fail:
            raise RuntimeError("disk full")
        self.saved.append(d)


def _cancelled_future():
    f = Future()
    assert f.cancel()
    return f


def test_a_budget_cancelled_candidate_is_parked_as_defer_not_dropped(monkeypatch):
    """THE POINT OF k=50. A cancelled vet is a candidate that generation, prescreen, dedup
    and diversity selection have already been paid for; dropping it buys a k=50 bill for a
    k~18 yield and reports nothing wrong. It must land in the drain instead."""
    built = []
    monkeypatch.setattr(run_mod, "build_dossier",
                        lambda **kw: built.append(kw) or types.SimpleNamespace(**kw))
    f1, f2 = _cancelled_future(), _cancelled_future()
    fut_meta = {f1: 1, f2: 2}
    kept = ["cand-1", "cand-2"]
    store, dossiers = _Store(), []

    n = run_mod._defer_unstarted_candidates(
        fut_meta, kept, set(), store=store, cfg=object(),
        op=types.SimpleNamespace(model_version="m1"), dossiers=dossiers)

    assert n == 2
    assert len(store.saved) == 2, "parked candidates never reached the store"
    assert len(dossiers) == 2, "parked candidates are missing from the batch's own tally"
    assert {b["cand"] for b in built} == {"cand-1", "cand-2"}
    assert all(b["gate_fired"] == "vet_budget_spent" for b in built)
    assert all(b["checks"] == [] and b["score"] is None for b in built), (
        "a parked candidate must not carry invented checks or a score")


def test_parking_ignores_futures_another_rail_cancelled(monkeypatch):
    """The infra rails cancel futures too. This function reports and parks only its own
    work; inheriting theirs would double-count the stop and re-park a row twice."""
    monkeypatch.setattr(run_mod, "build_dossier",
                        lambda **kw: types.SimpleNamespace(**kw))
    theirs, mine = _cancelled_future(), _cancelled_future()
    store, dossiers = _Store(), []
    n = run_mod._defer_unstarted_candidates(
        {theirs: 1, mine: 2}, ["a", "b"], {theirs},
        store=store, cfg=object(), op=types.SimpleNamespace(model_version=""),
        dossiers=dossiers)
    assert n == 1
    assert store.saved[0].cand == "b"


def test_a_running_or_finished_future_is_never_parked(monkeypatch):
    """Only cancelled futures are un-started work. Parking a future that RAN would write a
    DEFER over a verdict we already paid for — the one thing the whole rail promises not
    to do."""
    monkeypatch.setattr(run_mod, "build_dossier",
                        lambda **kw: types.SimpleNamespace(**kw))
    done = Future()
    done.set_result("a real verdict")
    store, dossiers = _Store(), []
    n = run_mod._defer_unstarted_candidates(
        {done: 1}, ["a"], set(), store=store, cfg=object(),
        op=types.SimpleNamespace(model_version=""), dossiers=dossiers)
    assert n == 0 and store.saved == [] and dossiers == []


def test_a_failed_park_is_logged_and_never_kills_the_batch(monkeypatch):
    """Losing one parked candidate costs a re-generation; letting the exception out costs
    every verdict this tick has already banked and not yet returned."""
    monkeypatch.setattr(run_mod, "build_dossier",
                        lambda **kw: types.SimpleNamespace(**kw))
    dossiers = []
    n = run_mod._defer_unstarted_candidates(
        {_cancelled_future(): 1}, ["a"], set(), store=_Store(fail=True),
        cfg=object(), op=types.SimpleNamespace(model_version=""), dossiers=dossiers)
    assert n == 0 and dossiers == []


def test_the_budget_gate_reads_as_defer_and_does_not_manufacture_an_outage():
    """`vet_budget_spent` must decide DEFER, clear the gate name (no real gate fired), and
    say WHY in its own words. The retrieval wording would claim an outage that did not
    happen — the `2102bacc6dd75cf9.kill.json` defect, where a fail-safe wore a verdict's
    clothes."""
    from prospector.dossier import build_dossier
    from prospector.models import Candidate, Decision

    cand = Candidate(title="T")
    d = build_dossier(cand=cand, checks=[], adversarial=None,
                      gate_fired="vet_budget_spent", score=None,
                      cfg=types.SimpleNamespace(active_persona="default"),
                      op_model_version="m")
    assert d.decision == Decision.DEFER
    assert d.gate_fired is None, "no gate fired; recording one corrupts the kill stats"
    assert "budget" in d.reason.lower()
    assert "could not retrieve" not in d.reason.lower()


# --------------------------------------------------------------------------- #
# 6. The backlog drain's own wall — the tick's largest unbounded consumer
# --------------------------------------------------------------------------- #
def test_the_drain_budget_reader_is_bounded_and_defaulted():
    frac = run_scheduled._drain_budget_frac
    assert frac(types.SimpleNamespace(schedule={})) == 0.15
    assert frac(types.SimpleNamespace(schedule={"drain_budget_frac": 0.5})) == 0.5
    assert frac(types.SimpleNamespace(schedule={"drain_budget_frac": "loads"})) == 0.15
    # Negative would be a deadline already in the past at t=0: every row skipped, a drain
    # that reports it ran and re-vetted nothing.
    assert frac(types.SimpleNamespace(schedule={"drain_budget_frac": -1})) == 0.0
    # >1 would promise the drain more than the tick has.
    assert frac(types.SimpleNamespace(schedule={"drain_budget_frac": 4})) == 1.0


def _drain_pass_kwargs(monkeypatch, schedule: dict, n_resume: int = 3) -> dict:
    seen: dict = {}

    def fake_resume_deferred(_cfg, **kwargs):
        seen.update(kwargs)
        return {"resumed": 0}

    monkeypatch.setattr("prospector.run.resume_deferred", fake_resume_deferred)
    run_scheduled._drain_pass(types.SimpleNamespace(schedule=schedule), n_resume)
    return seen


def test_the_drain_receives_a_wall_and_a_per_row_artifact_ceiling(monkeypatch):
    """The drain ran FIRST in every tick and was the one phase with no ceiling at all —
    4197s of a 10800s tick (39%) on 2026-08-15T10:16:59Z, 5885s+ (55%) on the 13:23:07Z tick.

    Both numbers are needed, not just the wall: 51-56% of a drained row's cost is the content
    phase, so bounding the pass without bounding the phase inside it moves the overrun one
    level down rather than removing it.
    """
    seen = _drain_pass_kwargs(monkeypatch, {})
    tick = run_scheduled._TICK_HARD_DEADLINE_S
    assert seen["budget_s"] == pytest.approx(0.15 * tick)
    assert seen["artifact_time_budget_s"] == pytest.approx(0.40 * 0.15 * tick)
    assert seen["publish"] is True, "a drained PASS must still be able to reach the shelf"


def test_the_drain_wall_leaves_the_rest_of_the_tick_to_the_batch(monkeypatch):
    """The property the whole change exists for, stated as the fence rather than arithmetic:
    drain + vetting must land inside the force-exit timer, whatever the drain costs."""
    seen = _drain_pass_kwargs(monkeypatch, {})
    tick = run_scheduled._TICK_HARD_DEADLINE_S
    left = tick - seen["budget_s"]
    vet = run_scheduled._vet_budget_frac(types.SimpleNamespace(schedule={})) * left
    assert seen["budget_s"] + vet < tick, (
        "the tick would still be vetting when _force_exit_hung_tick fires")


@pytest.mark.parametrize("frac", [0, -1])
def test_frac_zero_or_negative_leaves_the_drain_unbounded_never_zero_second(monkeypatch, frac):
    """0 must mean "wall off" (None). A zero-second wall would skip every row and report a
    drain that ran — the counters-lie shape this file exists to keep out."""
    seen = _drain_pass_kwargs(monkeypatch, {"drain_budget_frac": frac})
    assert seen["budget_s"] is None
    assert seen["artifact_time_budget_s"] is None


def test_a_drain_with_no_rows_never_calls_resume_at_all(monkeypatch):
    called = []
    monkeypatch.setattr("prospector.run.resume_deferred",
                        lambda *a, **k: called.append(1) or {})
    assert run_scheduled._drain_pass(types.SimpleNamespace(schedule={}), 0) is None
    assert not called


def test_resume_deferred_turns_the_duration_into_a_deadline_for_the_loop(monkeypatch):
    """`budget_s` is a DURATION at the scheduler boundary and an absolute instant inside the
    loop. Taking the instant AFTER the operators are built keeps their network calls out of
    the drain's budget — the same reason `run_signal` takes its deadlines where it does."""
    seen: dict = {}

    def fake_cmd_resume(_args, _cfg, _op, _fast, _search, _store, **kwargs):
        seen.update(kwargs)
        return {}

    monkeypatch.setattr(run_mod, "_cmd_resume", fake_cmd_resume)
    monkeypatch.setattr("prospector.operator.make_operator", lambda *a, **k: object())
    monkeypatch.setattr(run_mod, "_make_search", lambda *a, **k: object())
    monkeypatch.setattr(run_mod, "Store", lambda *a, **k: types.SimpleNamespace(
        root="/tmp", get=lambda *a: None))

    before = time.monotonic()
    run_mod.resume_deferred(types.SimpleNamespace(store_dir=Path("/tmp")),
                            limit=3, budget_s=600.0, artifact_time_budget_s=99.0)
    assert seen["artifact_time_budget_s"] == 99.0
    assert before + 600.0 <= seen["deadline_mono"] <= time.monotonic() + 600.0

    seen.clear()
    run_mod.resume_deferred(types.SimpleNamespace(store_dir=Path("/tmp")), limit=3)
    assert seen["deadline_mono"] is None, "no budget must mean no wall, not a wall at t=0"


def test_the_live_config_declares_the_drain_wall():
    import yaml
    schedule = yaml.safe_load((REPO / "config.yaml").read_text())["schedule"]
    assert schedule["drain_budget_frac"] == 0.15
    # The drain is the FIRST phase; whatever it takes comes off the top of everything else.
    # This is the arithmetic that must hold for the tick to end by decision.
    assert schedule["drain_budget_frac"] + (
        1 - schedule["drain_budget_frac"]) * schedule["vet_budget_frac"] < 1.0


def test_the_drain_loop_actually_consults_the_deadline_and_forwards_both_budgets():
    """Source-level, because the defect class here is an inert rail: `artifact_budget_frac`
    shipped wired-to-nothing for several hours on 2026-08-15, and the drain's call to
    `vet_candidate` was the one call site in the file that passed neither budget."""
    tree = ast.parse((REPO / "prospector" / "run.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_cmd_resume")
    args = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    assert {"deadline_mono", "artifact_time_budget_s"} <= args

    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "vet_candidate"]
    assert calls, "the drain no longer calls vet_candidate — this test is pinning nothing"
    kw = {k.arg for k in calls[0].keywords}
    assert {"artifact_time_budget_s", "vet_deadline_mono"} <= kw, (
        "the drain's vet is unbounded again; its content phase was 51-56% of a row's cost")

    # And the wall must be READ, not merely accepted as a parameter.
    src = ast.dump(fn)
    assert "deadline_mono" in src and "monotonic" in src
