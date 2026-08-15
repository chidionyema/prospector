"""The content phase is the one phase you must never cut.

THE TRAP WE SET FOR OURSELVES, and what these tests stop coming back.

`schedule.artifact_budget_frac` made the content phase's ceiling a SHARE of what the tick
had left. A share shrinks whenever some OTHER phase runs long — so a healthy artifact chain
(~90s/call, run.py:462) gets killed because generation or the drain was slow. The phase that
did nothing wrong pays.

Measured 2026-08-15, k=50 proof run, candidate f2ac7df9995c334e:

    15:36:08Z WARNING financial_model empty and the phase time budget is already exhausted;
                      skipping the prose-chain retry rather than extending the overrun
    15:36:08Z WARNING Pack content not sellable on attempt 2/3 for f2ac7df9995c334e
    15:36:08Z WARNING Pack content not sellable on attempt 3/3 for f2ac7df9995c334e
    15:36:08Z ERROR   Pack content STILL not sellable after 3 attempts ... publish UNLISTED

Three things were wrong at once, and each has a test below:

  1. The candidate had already PASSED all seven checks. Generation, prescreen, dedup,
     retrieval, seven verdict calls and adversarial review were all paid for. The content
     phase is what converts that spend into something sellable, and it is the cheapest step
     in the tick. Cutting it strands 100% of the upstream cost to save ~90s. When a tick
     cannot afford everything, the phase to cut is GENERATION — fewer candidates costs
     nothing already spent.  -> `test_the_floor_survives_a_drain_that_ate_the_whole_tick`

  2. All three attempts logged in the SAME second. Once the shared deadline passes,
     `generate_artifacts`/`generate_marketing_content` return without calling anything, so
     attempts 2 and 3 were no-ops that only made the log claim the chain failed three times.
     -> `test_a_spent_budget_stops_the_retries_instead_of_burning_them`

  3. The error said "generation produced nothing", which reads as a prose-operator outage
     and sends the next reader to debug the operator. `store/provider_health_noncritical.json`
     was `{}` — the operator was healthy; the ceiling was the thing to change.
     -> `test_the_error_names_the_budget_not_the_operator`
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from prospector.config import load_config
from prospector.scheduler import run_scheduled as RS

_REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 1. the floor

class _Cfg:
    """Minimal stand-in: `_sched` reads `cfg.schedule`, so that is all this needs."""

    def __init__(self, schedule: dict):
        self.schedule = schedule


def test_the_floor_reader_is_bounded_and_defaulted():
    assert RS._artifact_budget_floor_s(_Cfg({})) == RS._ARTIFACT_BUDGET_FLOOR_S
    assert RS._artifact_budget_floor_s(_Cfg({"artifact_budget_floor_s": 900})) == 900.0
    assert RS._artifact_budget_floor_s(_Cfg({"artifact_budget_floor_s": "junk"})) == \
        RS._ARTIFACT_BUDGET_FLOOR_S
    # Negative is meaningless; it must not become a negative ceiling.
    assert RS._artifact_budget_floor_s(_Cfg({"artifact_budget_floor_s": -5})) == 0.0
    # 0 is the documented escape hatch back to pure-share behaviour.
    assert RS._artifact_budget_floor_s(_Cfg({"artifact_budget_floor_s": 0})) == 0.0


def test_the_floor_survives_a_drain_that_ate_the_whole_tick():
    """The exact shape of the f2ac7df9995c334e failure: nothing left to take a share OF.

    This is the case a share can never handle. 0.40 x 0 = 0, and a zero ceiling means the
    content phase never runs, which means a candidate that passed every gate publishes
    UNLISTED. The floor is what makes the answer a real number.
    """
    cfg = _Cfg({"artifact_budget_frac": 0.40, "artifact_budget_floor_s": 1200})
    frac = RS._artifact_budget_frac(cfg)
    floor = RS._artifact_budget_floor_s(cfg)

    for left in (0.0, 100.0, 2000.0):
        share = frac * left
        effective = max(share, floor) if floor > 0 else share
        assert effective >= floor, f"a PASS got {effective}s of content time with {left}s left"

    # And it never LOWERS a healthy budget — the floor is a floor, not a cap.
    generous = frac * 9180.0          # a 10800s tick after a 1620s drain
    assert max(generous, floor) == pytest.approx(generous)


def test_the_live_config_declares_the_floor():
    """A rail that is not in the shipped config is a rail the daemon does not have."""
    cfg = load_config()
    assert RS._artifact_budget_floor_s(cfg) > 0, (
        "config.yaml must declare schedule.artifact_budget_floor_s; without it a slow drain "
        "or a slow generation phase can still starve the content phase to zero")


def test_the_floor_is_actually_applied_where_the_budget_is_computed():
    """Guards against the rail going inert.

    A reader nothing calls is worse than no reader: it reads as installed. This asserts at
    the AST level that `_default_generate` both calls `_artifact_budget_floor_s` and folds
    it into `art_budget` with a `max(...)`.
    """
    src = (_REPO / "prospector" / "scheduler" / "run_scheduled.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_default_generate")
    body = ast.dump(fn)
    assert "_artifact_budget_floor_s" in body, \
        "_default_generate never reads the floor — the rail is inert"
    assert "'max'" in body or '"max"' in body, \
        "_default_generate reads the floor but never applies it with max()"


# ------------------------------------------------- 2. + 3. the retry and the log

def _pack_content_fn() -> ast.FunctionDef:
    src = (_REPO / "prospector" / "run.py").read_text()
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_generate_pack_content")


def test_a_spent_budget_stops_the_retries_instead_of_burning_them():
    """The three attempts share ONE deadline, so past it they are no-ops.

    Pinned structurally: the retry loop must consult `_art_deadline` against
    `monotonic()` and `break`. Without this, the log claims three failures for a chain
    that was never called once — which is what sent the 2026-08-15 diagnosis to the
    wrong subsystem.
    """
    fn = _pack_content_fn()
    loop = next((n for n in ast.walk(fn) if isinstance(n, ast.For)), None)
    assert loop is not None, "_generate_pack_content no longer has its retry loop"

    dumped = ast.dump(loop)
    assert "_art_deadline" in dumped, \
        "the retry loop never consults the shared content deadline"
    assert "monotonic" in dumped, \
        "the retry loop consults the deadline but never compares it to the clock"
    assert any(isinstance(n, ast.Break) for n in ast.walk(loop)), \
        "the retry loop has no break — a spent budget still burns all 3 attempts"


def test_the_error_names_the_budget_not_the_operator():
    """"generation produced nothing" points at the operator. The budget must say so itself.

    The 2026-08-15 log said the operator produced nothing while
    store/provider_health_noncritical.json was `{}` — no dead mark, a healthy chain. The
    final error has to be able to distinguish the two causes.
    """
    fn = _pack_content_fn()
    consts = [n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    blob = " ".join(consts).lower()

    assert "budget" in blob, "the failure message cannot name a budget as the cause"
    assert "artifact_budget_floor_s" in blob, (
        "the message should name the knob that fixes it, so the next reader changes the "
        "ceiling instead of debugging a healthy operator")

    # And the distinction has to be carried by a real flag, not just prose.
    assert "_budget_spent" in ast.dump(fn), \
        "nothing tracks whether the budget, rather than the chain, was the cause"


# ------------------------------------------- 4. the bound on the EXPENSIVE end

def test_the_vet_deadline_bounds_the_CHECKS_and_defers_rather_than_kills():
    """The hole every other budget left open, and the one that actually cost the time.

    Before this, `vet_deadline_mono` reached only `_generate_pack_content`, where it clamped
    the ARTIFACT ceiling (run.py:559-561) — the cheap end, ~90s a call. Query generation,
    retrieval and seven verdict calls, which is where a tick's time actually goes, never saw
    a deadline at all. Measured consequence on 2026-08-15:

        15:22:55Z  Drain budget: 270s for 3 row(s)
        15:47:16Z  ... 1462s already spent on the drain, 338s left

    1462s against a 270s wall — 5.4x — because the wall was checked BETWEEN rows while the
    row itself was unbounded.

    The two things this pins:
      * the loop STOPS (it does not run all seven checks past the deadline), and
      * stopping yields DEFER, never a KILL. An unevaluated check is `retrieval_failed`,
        which is the documented honest verdict — "an exception is never evidence; a failed
        call DEFERS" — applied to running out of time instead of out of quota.
    """
    from prospector import verify as V
    from prospector.config import load_config as _load
    from prospector.models import DEFER_GATE, Candidate, Verdict
    from prospector.operator import MockOperator
    from prospector.retrieval import SearchProvider

    class _NeverSearched(SearchProvider):
        def search(self, query: str, k: int = 4, max_chars: int = 1500):
            raise AssertionError("retrieval ran after the vet deadline had passed")

    cfg = _load()
    cfg.retrieval.provider = "fixture"
    cfg.retrieval.cache = False
    cand = Candidate(title="Budget Bound", one_liner="A test product",
                     hypothesis="People suffer from X", who_pays="SMEs")

    calls: list[str] = []

    def _never_should_run(op, search, cfg_, cand_, name, **kw):
        calls.append(name)
        raise AssertionError(
            f"run_check({name!r}) was called after the vet deadline had already passed — "
            "the deadline does not bound the check loop")

    # A deadline already in the past: not one check may run.
    expired = V._time.monotonic() - 1.0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "run_check", _never_should_run)
        checks, adv, gate = V.verify(op=MockOperator(), search=_NeverSearched(), cfg=cfg,
                                     cand=cand, deadline_mono=expired)

    assert not calls, f"the check loop ran {calls} past its deadline"
    assert adv is None, (
        "the adversarial pass ran after the deadline. Every check DEFERRED, so it had "
        "nothing to argue with — and it is another unbounded brain call on a tick that "
        "has already run out of time.")
    assert checks, "stopping produced no checks at all — the candidate loses its audit trail"
    assert all(c.retrieval_failed for c in checks), \
        "an unevaluated check must be retrieval_failed, which is what makes the gate DEFER"
    assert all(c.verdict is Verdict.UNVERIFIABLE for c in checks), \
        "a check that never ran must be UNVERIFIABLE — never a ruling on unfetched evidence"
    assert gate == DEFER_GATE, (
        f"expected the defer sentinel, got {gate!r}. Running out of TIME must never "
        "manufacture a KILL — that would kill a candidate with our own scheduling.")


def test_a_deadline_of_none_leaves_the_check_loop_exactly_as_it_was():
    """Every CLI caller passes nothing. The bound must be opt-in, byte-for-byte."""
    fn = next(n for n in ast.walk(ast.parse(
        (_REPO / "prospector" / "verify.py").read_text()))
        if isinstance(n, ast.FunctionDef) and n.name == "_verify_inner")
    args = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    assert "deadline_mono" in args, "_verify_inner cannot receive a deadline"

    defaults = dict(zip([a.arg for a in fn.args.args][-len(fn.args.defaults):],
                        fn.args.defaults)) if fn.args.defaults else {}
    dm = defaults.get("deadline_mono")
    assert isinstance(dm, ast.Constant) and dm.value is None, \
        "deadline_mono must default to None so unbounded stays the default"

    # And the guard must be `is not None`, not a truthiness test: monotonic() can be small,
    # and `if deadline_mono:` would silently skip the bound at 0.0.
    src = (_REPO / "prospector" / "verify.py").read_text()
    assert "deadline_mono is not None" in src, \
        "the deadline guard must test `is not None`, not truthiness"


def test_the_wire_from_vet_candidate_to_verify_is_connected():
    """A parameter nothing forwards is an inert rail that reads as installed."""
    src = (_REPO / "prospector" / "run.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "vet_candidate")
    call = next((n for n in ast.walk(fn)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "verify"), None)
    assert call is not None, "vet_candidate no longer calls verify()"
    kw = {k.arg for k in call.keywords}
    assert "deadline_mono" in kw, (
        "vet_candidate does not forward its deadline into verify() — the checks are "
        "unbounded again and the drain/batch walls cannot bind")


def test_the_attempt_count_reported_is_the_count_actually_made():
    """Breaking early must not still report 3 attempts.

    Reporting the configured maximum after stopping at attempt 1 is how the original log
    claimed three failures that never happened.
    """
    fn = _pack_content_fn()
    err = next((n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "error"), None)
    assert err is not None, "_generate_pack_content no longer logs a final error"
    dumped = ast.dump(err)
    assert "attempt" in dumped, "the final error does not report the attempts actually made"
    assert "_MAX_PACK_GEN_ATTEMPTS" not in dumped, (
        "the final error reports the configured maximum, not what was actually attempted — "
        "that is the misreport this test exists to stop")
