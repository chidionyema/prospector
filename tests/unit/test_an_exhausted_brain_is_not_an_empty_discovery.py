"""Signal discovery must not report a benched brain as "the model returned nothing usable".

MEASURED 2026-08-15. `discover.discover_signals` caught EVERY exception from
`op.complete_json` and returned `[]`. Its caller (`run.py:2864`) then prints

    No signals discovered (model returned nothing usable).

and exits 1 — a statement about the model's ANSWER. When every tier of the operator chain is
out of quota there was no answer at all, so that sentence is false, and the operator reading it
goes looking at prompts and sectors instead of at the quota wall.

The distinction pinned here: a bad RESPONSE still returns `[]` (the caller's message is true
then); an exhausted PROVIDER now raises, because `ProviderExhaustedError` is the estate's
typed failover signal and swallowing it erased the only difference that mattered.
"""
from __future__ import annotations

import pytest

from prospector.discover import discover_signals
from prospector.errors import ProviderExhaustedError


class _Op:
    def __init__(self, raises=None, returns=None):
        self._raises = raises
        self._returns = returns

    def complete_json(self, system, user, temperature=0.9):
        if self._raises is not None:
            raise self._raises
        return self._returns


def test_a_bad_model_response_is_still_an_empty_list():
    assert discover_signals(_Op(raises=ValueError("not json")), None, n=3) == []


def test_a_model_that_answers_with_nothing_usable_is_still_an_empty_list():
    """The genuine empty — the model replied, the reply held no signals."""
    assert discover_signals(_Op(returns={"signals": []}), None, n=3) == []


def test_an_exhausted_operator_raises_instead_of_answering_empty():
    err = ProviderExhaustedError("monthly spend limit reached", provider="claude_cli")
    with pytest.raises(ProviderExhaustedError):
        discover_signals(_Op(raises=err), None, n=3)


def test_the_happy_path_is_unchanged():
    got = discover_signals(
        _Op(returns={"signals": [{"title": "T", "signal_text": "body", "sector": "energy"}]}),
        None, n=1)
    assert got == [{"title": "T", "signal_text": "body", "sector": "energy"}]
