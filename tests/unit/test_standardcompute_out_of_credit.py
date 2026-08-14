"""A provider that answers HTTP 200 with an upsell must fail over, not look healthy.

Measured 2026-08-09 in `store/scheduler/launchd.err.log`: StandardCompute, out of free
allowance, answered `POST /v1/chat/completions` with HTTP 200 and put its billing pitch in
`choices[0].message.content`. Nothing raised, so:

  * `FallbackOperator._raw` recorded a SUCCESS and called `_health.clear("standardcompute")`,
    which is why `store/provider_health_noncritical.json` was `{}` — a dead mark could not
    survive even one call;
  * the chain therefore never advanced to `claude_cli`, which was at that moment answering
    moat verdicts normally;
  * `complete_json` re-asked the same dead brain three times and raised `ParseError`.

Thirteen consecutive generation ticks produced zero candidates. These tests pin both halves
of the fix: the classifier must recognise the wording, and the adapter must raise on it.

IT HAPPENED AGAIN, 2026-08-13 — same provider, same clause, ONE NOUN DIFFERENT. The body
below is byte-identical to the 2026-08-09 one except "free usage" became "free TRIAL", which
the alternation did not list. Eight consecutive barren ticks, three signals parked to
`signals/pending/`, nothing published since 2026-08-10T23:06Z. The adapter half of the fix was
never at fault: it asks the classifier, and the classifier said healthy. So the lesson this
file now pins is not "add trial" but that the alternation enumerates a VENDOR'S NOUNS for the
thing an account runs out of, and a vendor renames those in a copy edit. Every member of that
family is tested below, and a new one should be added to the regex the day it is seen.
"""
from __future__ import annotations

import json

import pytest

from prospector.errors import (
    PERMANENT,
    ProviderExhaustedError,
    classify_exhaustion,
    looks_exhausted,
)
from prospector.operator import StandardComputeOperator

# The body as logged, verbatim (197 chars), em dashes and all.
OUT_OF_CREDIT_BODY = (
    "You've used up your free usage — let's keep going.\n\n"
    "Continue at a flat monthly price — no per-token billing, no surprise charges.\n\n"
    "Set up your plan at https://standardcompute.com/dashboard/billing."
)

# The 2026-08-13 body, verbatim from store/scheduler/launchd.err.log:205145 (197 chars).
# One noun apart from the line above, and that one noun cost a day of production.
OUT_OF_TRIAL_BODY = (
    "You've used up your free trial — let's keep going.\n\n"
    "Continue at a flat monthly price — no per-token billing, no surprise charges.\n\n"
    "Set up your plan at https://standardcompute.com/dashboard/billing."
)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _completion(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.fixture
def op(monkeypatch):
    """An adapter whose transport and usage ledger are stubbed.

    `record_usage` is stubbed because it writes to the durable spend ledger; a unit test that
    bills the production ledger has happened in this repo before.
    """
    monkeypatch.setattr("prospector.telemetry.record_usage", lambda **kw: None)
    # Default the transport to a hard failure so a test that forgets `_serve` fails loudly
    # instead of quietly calling the live api.stdcmpt.com (which is what happened on the
    # first run of this file: a real request, answered 401).
    import urllib.request

    def _unstubbed(req, timeout=None):
        raise AssertionError("test reached the network; call _serve() first")

    monkeypatch.setattr(urllib.request, "urlopen", _unstubbed)
    return StandardComputeOperator(api_key="test-key")


def _serve(monkeypatch, payload: dict) -> None:
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(payload))


def test_classifier_reads_the_upsell_as_permanent_exhaustion():
    # Before the fix this returned NOT_EXHAUSTION: no HTTP code, no "<period> limit", and
    # `_BILLING_RE` wants billing within 60 chars of limit/quota/credits/plan/upgrade while
    # the nearest word here is "no per-token billing, no surprise charges".
    assert looks_exhausted(OUT_OF_CREDIT_BODY) is True
    assert classify_exhaustion(OUT_OF_CREDIT_BODY) == PERMANENT


def test_the_2026_08_13_trial_wording_is_permanent_exhaustion():
    """The exact body that produced eight barren ticks. Length is asserted so that a future
    edit to the string cannot quietly stop being the thing that was logged."""
    assert len(OUT_OF_TRIAL_BODY) == 197
    assert looks_exhausted(OUT_OF_TRIAL_BODY) is True
    assert classify_exhaustion(OUT_OF_TRIAL_BODY) == PERMANENT


@pytest.mark.parametrize("noun", [
    "usage", "trial", "credit", "credits", "quota", "allowance", "balance", "tokens", "minutes",
])
def test_every_noun_an_account_can_run_out_of_is_covered(noun):
    """Twice now the outage was one unlisted noun. Enumerate the family, not the sample."""
    assert classify_exhaustion(f"You've used up your free {noun} — let's keep going.") == PERMANENT


def test_the_noun_family_did_not_widen_into_ordinary_prose():
    """The mirror-image defect: benching a live brain over a candidate that says 'used up'."""
    for benign in ("the team used up its budget for offsites last quarter",
                   "we used up the remaining conference swag",
                   "used up all the goodwill with that release"):
        assert classify_exhaustion(benign) != PERMANENT, benign


def test_two_hundred_with_an_upsell_raises_instead_of_returning_it(op, monkeypatch):
    _serve(monkeypatch, _completion(OUT_OF_CREDIT_BODY))
    with pytest.raises(ProviderExhaustedError) as exc:
        op._raw("sys", "user", 0.0)
    # The message must carry the body: a dead mark whose cause is not in the log gets mis-tuned.
    assert "out-of-allowance" in str(exc.value)
    assert "used up your free usage" in str(exc.value)


def test_a_normal_completion_still_passes_through(op, monkeypatch):
    payload = '{"ideas": [{"title": "a real candidate"}]}'
    _serve(monkeypatch, _completion(payload))
    assert op._raw("sys", "user", 0.0) == payload


def test_a_long_completion_discussing_allowances_is_not_an_outage(op, monkeypatch):
    """The length bound is the false-positive guard, so prove it holds.

    A generated candidate may legitimately discuss a SaaS that warns users they have "used up
    your free usage". Killing the brain over that would be the mirror-image defect.
    """
    long_body = (
        '{"ideas": [{"title": "Quota Coach", "one_line": "warns a team before it has '
        'used up your free usage allowance on any SaaS", "notes": "'
        + "padding. " * 200
        + '"}]}'
    )
    _serve(monkeypatch, _completion(long_body))
    assert len(long_body) > StandardComputeOperator._OUT_OF_CREDIT_MAX_CHARS
    assert looks_exhausted(long_body) is True          # the wording alone WOULD match
    assert op._raw("sys", "user", 0.0) == long_body    # but length keeps it a completion
