"""The RAISED grounding outage must go through the streak rail, not around it.

`tests/unit/test_infra_abort_streak.py` pins the POLICY (`_infra_exception_action`). This file
pins the WIRING, because the wiring was the bug: `_infra_abort_check` is fed only by dossiers
that a vet RETURNED, and a vet that RAISES `GroundingInfrastructureError` returns nothing. So
before 2026-08-07 the raise reached an unconditional `raise` in `run_signal`, propagated to
`prospector/scheduler/run_scheduled.py:892`, and became `sys.exit(1)`; launchd's KeepAlive then
relaunched the daemon. Measured in `store/scheduler/audit/`: 8 distinct daemon pids in the
00:00 hour of 2026-08-07, 7 in the 23:00 hour of 2026-08-06, against a ~2.5h tick cadence.

Why one bad search collapsed the whole chain (same audit window, 2026-08-06/07):
    ddg  3014 calls,  25 failed  = 0.83% per search
    exa    29 calls,  28 failed  = 96.6%  (DNS flap on api.exa.ai — tier 2 was effectively gone)
    -> whenever ddg missed, the chain rested on claude_cli, which was timing out at 150s.
At ~200 searches per batch a 0.83% per-search failure rate means P(>=1 collapse) = 81%, which
is why this was not a rare event.

These tests drive the REAL `run_signal` loop with `vet_candidate` monkeypatched to raise.
A test that only called `_infra_exception_action` would have passed against the broken code.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from prospector import run as runmod
from prospector.config import load_config
from prospector.errors import GroundingInfrastructureError
from prospector.models import Candidate, Decision, Dossier
from prospector.store import Store


def _candidates(n: int) -> list[Candidate]:
    # Deliberately nonsense, unique titles: the rejection fast-path near-duplicate-matches
    # incoming titles against the real kill log, and a collision would silently drop a
    # candidate before it ever reached the vetting loop, making these tests vacuous.
    return [Candidate(title=f"zzq-grounding-outage-fixture-{i}",
                      one_liner=f"fixture candidate {i}",
                      hypothesis="fixture", who_pays="fixture")
            for i in range(n)]


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """run_signal with everything before the vetting loop stubbed out, and the store
    redirected to tmp so this test cannot write to production state."""
    # PROSPECTOR_STORE_DIR is the documented redirect for every store read/write
    # (prospector/config.py, Config.store_dir); `cfg.store_dir` itself is a read-only property.
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "store"))
    cfg = load_config()
    cfg.operator = "mock"
    # The ancillary chain is mocked for the same reason the moat is, and it is a precondition
    # rather than tidying. `run_signal` builds it EAGERLY (run.py:955) before knowing whether
    # anything will use it, and since the 2026-08-14 directive it is minimax → standardcompute,
    # both key-metered: `_build_operator_chain` raises ProviderExhaustedError at construction
    # wherever the keys are absent. CI has none, so all six cases here died there while passing
    # on every developer machine (run 31793597064). `generate`, `dedup` and `prescreen` — the
    # only consumers of that chain — are stubbed below, so these tests never exercised it.
    cfg.noncritical_operator = ["mock"]

    # ONE vet worker. The streak is counted in `as_completed` COMPLETION order, which with a
    # multi-worker pool is nondeterministic — so "outage, success, outage, ..." submitted can
    # arrive as three outages in a row and legitimately trip the halt. That is correct
    # production behaviour (consecutive-in-completion-order is the honest proxy for "the
    # pipeline is down right now"), but it makes an order-sensitive assertion flaky: caught
    # here when test_a_healthy_ruling_between_outages_resets_the_streak passed alone and
    # failed in a batch run. Serialising makes completion order == submission order.
    monkeypatch.setattr(runmod, "_vet_workers", lambda cfg: 1)

    monkeypatch.setattr(runmod, "dedup", lambda cands, catalogue, **kw: (cands, []))
    monkeypatch.setattr(runmod, "prescreen", lambda op, c, cand: (True, 1.0, "ok", {}))
    monkeypatch.setattr("prospector.novelty.select_diverse_candidates",
                        lambda op, data, k=None: [c for c, _, _ in data])
    return cfg


def _run(cfg, n_candidates, vet_side_effect, monkeypatch, k=None):
    monkeypatch.setattr(runmod, "generate", lambda *a, **kw: _candidates(n_candidates))
    monkeypatch.setattr(runmod, "vet_candidate", vet_side_effect)
    return runmod.run_signal("fixture signal", cfg=cfg, op=MagicMock(),
                             search=object(), store=Store(cfg), k=k)


def _ok_dossier(cand) -> Dossier:
    return Dossier(candidate=cand, decision=Decision.KILL, checks=[],
                   gate_fired="incumbency", reason="fixture ruling")


# ------------------------------------------------------------------ THE regression (1 blip)

def test_one_grounding_outage_does_not_kill_the_batch(wired, monkeypatch):
    """A single tail-query collapse must NOT propagate. Before the fix this raised."""
    seen = []

    def vet(cand, *a, **kw):
        seen.append(cand.title)
        if len(seen) == 1:
            raise GroundingInfrastructureError(
                "ALL grounding providers dead: ['ddg', 'exa', 'claude_cli']")
        return _ok_dossier(cand)

    dossiers = _run(wired, 5, vet, monkeypatch, k=5)

    assert len(seen) == 5, "the batch stopped early instead of riding out one blip"
    assert len(dossiers) == 4, "the four healthy candidates must still have been ruled"


def test_two_consecutive_outages_still_do_not_kill_the_batch(wired, monkeypatch):
    """Threshold is 3. Two consecutive collapses is still 'blip', not 'outage'."""
    seen = []

    def vet(cand, *a, **kw):
        seen.append(cand.title)
        if len(seen) <= 2:
            raise GroundingInfrastructureError("providers dead")
        return _ok_dossier(cand)

    dossiers = _run(wired, 5, vet, monkeypatch, k=5)
    assert len(seen) == 5
    assert len(dossiers) == 3


# ------------------------------------------------- the halt is NOT removed, only streak-gated

def test_a_sustained_outage_still_halts(wired, monkeypatch):
    """The spend rail survives: an outage that never clears must still reach the daemon as a
    GroundingInfrastructureError, so run_scheduled.py can halt. Removing the halt entirely
    would have been a quieter regression than the bug being fixed."""
    monkeypatch.setenv("PROSPECTOR_INFRA_ABORT_STREAK", "3")

    def vet(cand, *a, **kw):
        raise GroundingInfrastructureError("providers dead")

    with pytest.raises(GroundingInfrastructureError):
        _run(wired, 8, vet, monkeypatch, k=8)


def test_many_scattered_outages_below_the_threshold_never_halt(wired, monkeypatch):
    """Total count is not the trigger — only a CONSECUTIVE run is. Two collapses in a batch of
    ten must not halt no matter how the completion order shuffles them.

    NOTE on why this is not the more obvious "outage, success, outage, ..." alternating test:
    the streak is advanced in `as_completed` order, and `as_completed` yields futures that were
    ALREADY finished when it was first called out of a *set*, i.e. in arbitrary order — even
    with a single worker, where execution order is fixed. So no submission pattern containing
    >= 3 collapses can be guaranteed to avoid presenting 3 of them consecutively, and an
    alternating test is irreducibly flaky (observed: passed 5 runs, then failed). The
    streak-RESET property is therefore pinned deterministically at the policy level, in
    tests/unit/test_infra_abort_streak.py::test_a_healthy_verdict_resets_the_streak_before_a_raise.
    This test asserts only the order-INDEPENDENT part: 2 collapses can never reach a
    threshold of 3.
    """
    monkeypatch.setenv("PROSPECTOR_INFRA_ABORT_STREAK", "3")
    seen = []

    def vet(cand, *a, **kw):
        seen.append(cand.title)
        if cand.title.endswith(("-2", "-7")):   # exactly 2 of 10, chosen by identity not order
            raise GroundingInfrastructureError("providers dead")
        return _ok_dossier(cand)

    dossiers = _run(wired, 10, vet, monkeypatch, k=10)
    assert len(seen) == 10, "the batch stopped early on a sub-threshold number of collapses"
    assert len(dossiers) == 8


def test_disabling_the_rail_restores_the_immediate_halt(wired, monkeypatch):
    """threshold 0 disables the streak rail; it must fall back to halting on first sight,
    NOT to swallowing every outage. A disabled brake must never be quieter than no brake."""
    monkeypatch.setenv("PROSPECTOR_INFRA_ABORT_STREAK", "0")

    def vet(cand, *a, **kw):
        raise GroundingInfrastructureError("providers dead")

    with pytest.raises(GroundingInfrastructureError):
        _run(wired, 5, vet, monkeypatch, k=5)


# ----------------------------------------------------------------- the vacuity guard

def test_the_harness_actually_reaches_the_vetting_loop(wired, monkeypatch):
    """Non-vacuous by construction. Every test above asserts on how many times `vet_candidate`
    ran; if dedup/prescreen/novelty ever drop the fixture candidates first, they would all
    pass while proving nothing. This pins that the loop is genuinely reached."""
    seen = []

    def vet(cand, *a, **kw):
        seen.append(cand.title)
        return _ok_dossier(cand)

    dossiers = _run(wired, 3, vet, monkeypatch, k=3)
    assert len(seen) == 3, "the fixture candidates never reached vet_candidate"
    assert len(dossiers) == 3
