"""A dead brain and a refused rewrite must not look the same to the caller.

`shelf_copy_repair.rewrite_one` used to catch every exception from the brain call, print it,
and return None. None is also what it returns when the rewrite ran and graded badly. So an
outage arrived at the caller as "this line cannot be improved", and `run.py`'s own error
branch — which logs at ERROR and sets `one_liner_repair_failed` — could never run.

That is the swallowed-failure class `test_swallowed_failures_can_only_go_down.py` ratchets
against, and it is what put `prospector/shelf_copy_repair.py` over the baseline and left
main red on 2026-08-17.
"""
from __future__ import annotations

import pytest

from prospector.shelf_copy_repair import RewriteUnavailable, rewrite_one


class _DeadOp:
    """A brain whose every call fails, the way an exhausted provider does."""

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, system: str, user: str) -> dict:
        self.calls += 1
        raise RuntimeError("All operators unavailable — check API keys and credentials")


class _RefusingOp:
    """A brain that answers, but with copy that never grades clean."""

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, system: str, user: str) -> dict:
        self.calls += 1
        # Second person, which `voice_breaches` refuses on every attempt.
        return {"one_liner": "You get a probate clear-out concierge for your relative's home"}


def test_a_failed_call_raises_instead_of_returning_none():
    op = _DeadOp()
    with pytest.raises(RewriteUnavailable) as caught:
        rewrite_one(op, "Probate clear-out concierge", "This is the line to repair.")
    # The cause is preserved, so the operator sees WHICH failure benched the brain rather
    # than a generic "rewrite unavailable".
    assert "All operators unavailable" in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_a_failed_call_does_not_burn_the_retry():
    """One dead call ends the attempt. Retrying a benched provider costs latency and
    changes nothing — the retry exists to correct BAD COPY, not to wait out an outage."""
    op = _DeadOp()
    with pytest.raises(RewriteUnavailable):
        rewrite_one(op, "t", "l", attempts=2)
    assert op.calls == 1, f"a dead brain was called {op.calls} times, not once"


def test_a_refusal_still_returns_none_and_uses_every_attempt():
    """The other half of the contract. A rewrite that runs and grades badly is a finished
    answer: None, after both attempts, with no exception."""
    op = _RefusingOp()
    assert rewrite_one(op, "Probate clear-out concierge", "A line that breaches.",
                       attempts=2) is None
    assert op.calls == 2, f"a refusal used {op.calls} attempts, not 2"


def test_the_two_outcomes_are_distinguishable():
    """The whole point, stated as one assertion: a caller with no other information can
    tell an outage from a refusal."""
    refusal = rewrite_one(_RefusingOp(), "t", "A line that breaches.", attempts=1)
    try:
        rewrite_one(_DeadOp(), "t", "A line that breaches.", attempts=1)
        outage = None
    except RewriteUnavailable as exc:
        outage = exc
    assert refusal is None
    assert outage is not None and isinstance(outage, RewriteUnavailable)
