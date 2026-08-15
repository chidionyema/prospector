"""The drain must not run into a blind moat either.

`run_scheduled.py` gained a moat precondition for GENERATION on 2026-08-06 (`392ce4c`), and
`tests/scheduler/test_moat_blind_preflight.py` covers it. The DRAIN never had one — and
`vet --resume` on the CLI does not go through the scheduler at all, so nothing the scheduler
learned applied to it.

Measured 2026-08-06 with `operator: [claude_cli]` (a one-brain moat) marked dead for 3033s: the
drain kept running, and every re-vet raised `ProviderExhaustedError`, which `verify.py` turns
into `retrieval_failed` -> DEFER_GATE -> `Decision.DEFER`. Over one 30-minute window that moved
provisional -14 / defer +13 — a net backlog change of -1 for a full pass of subscription-CLI
spend. The rows were relabelled, not resolved.

It is worse than merely wasteful: the drain competes for the same CLI slots as the daemon, and
`392ce4c`'s commit message records the drain's load as implicated in the moat flapping that
minted those provisional rows. A drain that runs while the brain is benched helps keep it benched.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

import prospector.health as H
import prospector.operator as O
from prospector import run as R


@pytest.fixture(autouse=True)
def _pin_the_roster():
    """Every test in this file reasons about TRUSTED vs UNTRUSTED, so none of them may inherit
    whichever roster the previous test happened to leave behind.

    `moat_primary()` reads a module-global (`operator.py:1362`) that `config.load_config`
    writes via `set_moat_primary`. That is correct for the daemon — one process, one config —
    and it makes these tests order-dependent: they were written when the default
    `{"claude_cli"}` was also the live roster, so "minimax" was untrusted by both accident and
    intent. On 2026-08-15 minimax was promoted into `config.yaml moat_primary:`, and from then
    on ANY earlier test in the session that loaded the real config.yaml flipped minimax to
    trusted underneath this file. The result was the worst kind of red: green in isolation,
    red in the full suite, and pointing at the drain rather than at test isolation.

    Pinning here rather than in conftest on purpose — a global autouse reset would also hide
    the config plumbing from the tests that exist to check it (`tests/unit/test_model_config.py`).
    What this file needs is a KNOWN roster, not a suppressed one.
    """
    previous = O._MOAT_PRIMARY  # the RAW global, not moat_primary() — see below
    O.set_moat_primary(["claude_cli"])
    try:
        yield
    finally:
        # Restore the raw value, including `None`. `moat_primary()` folds None into
        # MOAT_PRIMARY_DEFAULT, so restoring what IT returns would leave the roster explicitly
        # set where it had never been set — turning this fixture into the same order-dependence
        # it exists to remove, one level down.
        with O._MOAT_PRIMARY_LOCK:
            O._MOAT_PRIMARY = previous


class _Store:
    """Just enough store for the preflight: it must be reached with a NON-empty backlog,
    otherwise the `no pending` early return would pass these tests for the wrong reason."""

    def all(self, decision=None):
        return [{"candidate_id": "c1", "decision": "defer", "created_at": "2026-06-14"}]

    def provisional(self):
        return [{"candidate_id": "c2", "decision": "pass", "provisional": True,
                 "created_at": "2026-06-15"}]

    @property
    def root(self):
        # Where the drain's attempt ledger would live. Deliberately a path that does not exist:
        # `drain_state.load` returns {} for a missing ledger, so no row here is ever attempt-capped
        # and the backlog stays non-empty — which is what makes the preflight the thing under test.
        return Path("/nonexistent-preflight-store")

    def has_dossier(self, cid):
        # Both rows have a file behind them, so neither is excluded as an orphan. Same reason:
        # an empty backlog would pass these tests via the wrong early return.
        return cid in {"c1", "c2"}

    # The queue lease. These tests never reach a vet — the preflight is the thing under test —
    # but the double must still answer, because a store that cannot lease cannot be drained.
    def claim(self, cid, owner, ttl_s):
        return True

    def release(self, cid, owner):
        return True


def _cfg(operator=("claude_cli",)):
    return types.SimpleNamespace(operator=list(operator))


def _resume(cfg, **kw):
    # limit=0 means "drain nothing" (run.py:1194-1208) — a second, LATER short-circuit that
    # returns a dict with no `skipped` key. That makes it the control: if the preflight did not
    # fire, the call still returns without touching a brain, and the two exits are told apart by
    # `skipped` alone. No operator, search provider or log path is ever used on either path.
    args = types.SimpleNamespace(limit=0, only="all", **kw)
    return R._cmd_resume(args, cfg, None, None, None, _Store())


def test_drain_refuses_when_every_trusted_brain_is_dead():
    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")
    out = _resume(_cfg())

    assert out["attempted"] == 0, "no candidate may be re-vetted into a blind moat"
    assert out["resumed"] == 0
    assert out["backlog"] == 2, "the backlog is still reported honestly — it is not zero, it is unworkable"
    assert "moat blind" in out["skipped"]
    assert "claude_cli" in out["skipped"], "the reason must name the brain and its window"


def test_the_preflight_fires_before_every_other_short_circuit():
    """Ordering matters: `--only` filtering and the `limit<=0` exit both sit AFTER it in
    `_cmd_resume`. If the preflight were placed below them, the common daemon path
    (`resume_deferred`, which passes a positive limit and no `only`) would sail straight past it."""
    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")
    out = _resume(_cfg(), )

    # limit=0 alone would also return attempted==0 — `skipped` is what proves WHICH exit ran.
    assert "skipped" in out, "the limit=0 exit won the race; the preflight is too far down"


def test_a_degraded_chain_still_drains_while_one_trusted_brain_lives():
    """A degraded moat still rules. The guard is a floor, not a fair-weather switch.

    REWRITTEN 2026-08-15 with the narrowing of `MOAT_PRIMARY` to `{"claude_cli"}`. This test
    used to mark `claude_cli` dead and pair it with a live `claude` — a second TRUSTED brain,
    which the paid Anthropic API tier was until it was deleted. There is no such pair to build
    any more, and the test failed in CI naming a brain `_build_operator` now raises on. Same
    defect shape as `tests/faults/test_synthetic_exhaustion_harness.py`, fixed in this branch:
    a test that pins a two-trusted-brain world after the world became one-brain.

    What survives the rewrite is the assertion that actually has teeth, and it is the MIRROR of
    `test_a_live_untrusted_brain_does_not_unblind_the_drain` below. That one proves a dead
    trusted brain is not rescued by a live provisional one; this one proves the converse — a
    dead PROVISIONAL brain must not blind a drain whose trusted brain is up. Without it,
    `moat_blind_reason(trusted_only=True)` could stop filtering to `moat_brains` and start
    refusing on any dead mark anywhere on the chain, and every other test in this file would
    still pass: `minimax`'s mark is invisible to a correct classifier and fatal to a broken one.
    """
    H.get_health().mark_exhausted("minimax", 3600.0, error="usage limit")
    out = _resume(_cfg(operator=("claude_cli", "minimax")))

    assert "skipped" not in out, "the drain must proceed past the preflight"
    assert out["backlog"] == 2


def test_a_live_untrusted_brain_does_not_unblind_the_drain():
    """minimax being up is exactly the condition that mints provisional rows. Letting it satisfy
    the preflight would have the drain re-vet a provisional row into another provisional row."""
    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")
    out = _resume(_cfg(operator=("claude_cli", "minimax")))

    assert "moat blind" in out["skipped"]


def test_healthy_moat_drains_normally():
    out = _resume(_cfg())
    assert "skipped" not in out


def test_drain_and_scheduler_share_one_implementation():
    """A duplicated moat classifier is the same defect shape `errors.looks_exhausted` exists to
    prevent: two copies drift, and the one that drifts is the one nobody is watching.

    On a trusted-only chain the two callers must still agree exactly. Where they now differ is
    a PARAMETER of the shared function, not a second copy of the logic — see the test below.
    """
    from prospector.scheduler import run_scheduled as rs

    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")
    cfg = _cfg()
    assert rs._moat_blind_reason(cfg) == H.moat_blind_reason(cfg) != ""


def test_the_drain_refuses_a_provisional_tail_that_generation_accepts():
    """The asymmetry added 2026-08-08, and the reason it is not an inconsistency.

    Generation may run into a live provisional tail: the rows it mints CAN be ruled, and a
    provisional ruling is finalised later by a re-vet. The DRAIN may not, and this is the
    whole point — its job is to convert `provisional` rows into final ones, and re-vetting a
    provisional row on a provisional brain re-stamps it `provisional`. The row does not move,
    the money is spent, and the drain's own CLI load helps keep the trusted brain benched.

    Measured 2026-08-06 on a one-brain moat marked dead: a 30-minute drain moved provisional
    -14 / defer +13, a net backlog change of -1 for a full pass of subscription-CLI spend.
    """
    from prospector.scheduler import run_scheduled as rs

    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")
    cfg = _cfg(operator=("claude_cli", "minimax"))

    assert rs._moat_blind_reason(cfg) == "", "generation proceeds — minimax can still rule"
    assert "moat blind" in H.moat_blind_reason(cfg), "the drain refuses — it cannot FINALISE"
    assert "moat blind" in _resume(cfg)["skipped"], "and the refusal reaches the real drain"


def test_the_preflight_does_not_burn_the_half_open_probe():
    """Bookkeeping must read the RAW mark (`dead_until`), never `is_dead` — the latter CLAIMS the
    single half-open probe slot, so a status check would spend the recovery attempt a real verdict
    call should get. Self-healing would then depend on nobody looking."""
    import json
    from pathlib import Path

    h = H.get_health()
    h.mark_exhausted("claude_cli", 3600.0, error="usage limit")
    data = json.loads(Path(h._path).read_text())
    data["claude_cli"]["probe_at"] = 0
    Path(h._path).write_text(json.dumps(data))

    _resume(_cfg())
    _resume(_cfg())

    assert h.is_dead("claude_cli") is False, "the probe must still be available to a real call"


def test_no_trusted_brain_configured_is_not_a_quiet_skip():
    """An all-untrusted `operator:` is a config error. Silently skipping every drain forever is
    the worst possible response — it looks exactly like a healthy empty backlog."""
    assert H.moat_blind_reason(_cfg(operator=("minimax",))) == ""
    assert "skipped" not in _resume(_cfg(operator=("minimax",)))
