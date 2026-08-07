"""The 2026-08-07 monthly-spend-limit outage, driven end to end through the failover chain.

WHY THIS FILE EXISTS. §29.5 of docs/COMMERCIAL_READINESS_PROGRAM.md originally claimed this
outage was invisible to `classify_exhaustion`, so no dead mark was written and nothing failed
over. That was retracted the same day: the claim had been reasoned from a fragment that a
REPORTING script had truncated to 180 characters, not from the payload. The payload classifies
`permanent`, and the receipt is full of `ProviderExhaustedError` — a class `run_claude_cli`
raises only under `if looks_exhausted(...)`.

The retraction left a real hole, which these tests fill: the self-heal path was asserted, never
exercised. E3 could not exercise it, because it calls `run_claude_cli` directly
(`tools/experiments/e3_concurrency_knee.py:112`) and never builds an `Operator` — a transport
probe measured through a failover chain would be measuring the chain. So the outage is replayed
here through `FallbackOperator` instead, on the VERBATIM payload out of
`tools/experiments/e3_concurrency_knee_receipts.json`.

Nothing here spends: both brains are fakes.
"""
from __future__ import annotations

import re

from prospector.errors import (
    PERMANENT,
    TRANSIENT,
    ProviderExhaustedError,
    classify_exhaustion,
    limit_window_seconds,
)
from prospector.health import DEFAULT_EXHAUSTION_S, ProviderHealth
from prospector.operator import FallbackOperator, Operator

# Verbatim from the receipt: the detail `claude_cli.py` built for the call that died, produced
# by the code as it stood BEFORE cause_context existed (no ' | ' cause prefix). Note it carries
# BOTH an `api_error_status":429` and the spend-limit sentence — the tie PERMANENT must win.
OBSERVED_DETAIL = (
    'claude cli exit 1: _state":"off","fast_mode_disabled_reason":"sdk_opt_in_required",'
    '"subtype":"success","api_error_status":429,'
    '"result":"You\'ve hit your monthly spend limit · raise it at '
    'claude.ai/settings/usage?from=cc_cli_limit_message",'
    '"type":"result","duration_ms":1327,"uuid":"842b889a-add6-4404-8d6b-fb5d5de539a3"}'
)


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class _Brain(Operator):
    def __init__(self, name, behaviour):
        self.name = name
        self.behaviour = behaviour
        self.calls = 0

    def _raw(self, system, user, temperature):
        self.calls += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


def _chain(h):
    """claude_cli dies on the observed payload; minimax is the next non-critical tier."""
    head = _Brain("claude_cli", ProviderExhaustedError(
        f"claude cli exhausted after 1 attempts: {OBSERVED_DETAIL}", provider="claude_cli"))
    tail = _Brain("minimax", '{"ok": true}')
    return FallbackOperator([("claude_cli", head), ("minimax", tail)], health=h), head, tail


def test_the_observed_payload_classifies_permanent():
    """The load-bearing fact of the §29.5 retraction. If this ever fails, the retraction is
    wrong and the original claim was right — so it is pinned rather than left as prose."""
    assert classify_exhaustion(OBSERVED_DETAIL) == PERMANENT


def test_permanent_beats_the_429_carried_in_the_same_payload():
    """This payload states `api_error_status":429` AND a spent allowance. Read as backpressure
    it earns a 60s bench and 60 further probes an hour into a provider with no allowance left;
    PERMANENT-wins-ties is what stops that, and only this payload proves the tie is reachable
    in the wild rather than only in a hand-written test string.

    The second assertion is the non-vacuity guard: strip the `result` sentence and the SAME
    payload classifies TRANSIENT, so the 429 really is competing here and the tie is not being
    won by default."""
    assert '"api_error_status":429' in OBSERVED_DETAIL
    assert "monthly spend limit" in OBSERVED_DETAIL
    assert classify_exhaustion(OBSERVED_DETAIL) == PERMANENT

    without_cause = re.sub(r'"result":"[^"]*",', "", OBSERVED_DETAIL)
    assert classify_exhaustion(without_cause) == TRANSIENT, (
        "the 429 must be what the spend limit is outranking; if this payload no longer reads "
        "as transient without its cause, the tie is not being tested at all")


def test_the_outage_fails_over_to_minimax_and_marks_claude_cli_dead(tmp_path):
    """The whole self-heal claim, in one assertion set: next tier serves, dead mark written."""
    clk = _Clock()
    h = ProviderHealth(tmp_path / "h.json", clock=clk)
    fb, head, tail = _chain(h)

    assert fb.complete_json("s", "u") == {"ok": True}, "minimax must serve the call"
    assert head.calls == 1 and tail.calls == 1
    assert h.is_dead("claude_cli"), "a spent allowance must leave a trace"
    assert not h.is_dead("minimax")
    # 3600s, not the 60s transient floor: the window follows the CLASSIFICATION.
    assert h.dead_until("claude_cli") - clk.t == DEFAULT_EXHAUSTION_S


def test_the_dead_brain_is_not_re_probed_by_a_LATER_CHAIN(tmp_path):
    """The point of PERSISTING the mark, as opposed to tripping the in-run breaker.

    This test originally made two calls on ONE chain and asserted the second skipped the dead
    brain. It passed with `mark_exhausted` deleted — the circuit breaker skips a hard-tripped
    brain on its own, so the assertion was pinning the breaker and the health file was free to
    rot. A second chain over the same file has FRESH breakers, so only the persisted mark can
    make it skip: that is the cross-process property the health file exists for.
    """
    clk = _Clock()
    h = ProviderHealth(tmp_path / "h.json", clock=clk)
    fb, head, tail = _chain(h)
    fb.complete_json("s", "u")
    assert head.calls == 1

    fb2, head2, tail2 = _chain(h)          # new breakers, same persisted health
    assert fb2.complete_json("s", "u") == {"ok": True}
    assert head2.calls == 0, f"re-probed a brain marked dead in a prior run: {head2.calls}"
    assert tail2.calls == 1


def test_a_monthly_limit_takes_the_hourly_default_and_that_is_deliberate():
    """A KNOWN, MEASURED GAP, pinned so it is a decision rather than an accident.

    `classify_limit` knows two classes, session-5h and weekly (`errors.py:283-293`); a MONTHLY
    spend limit matches neither, so `limit_window_seconds` returns None and the caller falls
    back to DEFAULT_EXHAUSTION_S = 3600s. The brain is therefore re-probed hourly until the
    billing month rolls over, and `_moat_blind_reason` un-blinds the daemon for one tick each
    time.

    Lengthening it was considered and REJECTED on two measurements, not on taste:
      * `health.py:167` clamps every window to `_MAX_DEAD_S` = 24h, so a "one month" window
        cannot exist anyway — the most a longer class could buy is 24 probes/day -> 1/day;
      * a spend limit is the one limit an operator can clear at will, and it WAS raised by
        hand during this very outage. Trading ~24 fast-failing probes a day (the observed
        failures returned in ~1.3s) for up to 24h of silence after a raise is the worse side
        of that trade.
    Revisit only with evidence that the hourly probe costs more than the staleness does.
    """
    assert limit_window_seconds(OBSERVED_DETAIL) is None
    assert DEFAULT_EXHAUSTION_S == 3600.0
