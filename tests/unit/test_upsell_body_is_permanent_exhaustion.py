"""A provider that answers HTTP 200 with an upsell must fail over, not look healthy.

WHAT THIS FILE USED TO BE, and why it is not that any more. It was
`test_standardcompute_out_of_credit.py`, and half of it drove `StandardComputeOperator`
directly. That adapter was DELETED on 2026-08-15 by founder directive (see the record at
`prospector/operator.py:754`), so the import at the top of that file could not resolve and
the whole pytest run died at COLLECTION -- one dead subject took the entire suite with it,
which is how a deleted provider failed CI on a storefront pull request.

The adapter half is gone with its adapter, deliberately and not by oversight: the guard it
pinned (`_OUT_OF_CREDIT_MAX_CHARS`, the length bound that stopped a candidate DISCUSSING an
allowance from benching the brain) lived on that class, and no surviving adapter carries it.
Re-pointing those three tests at MiniMax or DeepSeek would have asserted an invariant those
classes do not have, which is a green test guarding nothing.

WHAT SURVIVES IS THE HALF THAT WAS NEVER ABOUT ONE VENDOR. `classify_exhaustion` is shared by
every metered adapter (`prospector/errors.py`), and the incident it was written for can recur
on any of them, because the defect was never in the transport -- it was in reading a billing
pitch as a completion.

THE INCIDENT, twice. Measured 2026-08-09 in `store/scheduler/launchd.err.log`: the provider,
out of free allowance, answered `POST /v1/chat/completions` with HTTP 200 and put its billing
pitch in `choices[0].message.content`. Nothing raised, so `FallbackOperator._raw` recorded a
SUCCESS and cleared the dead mark -- `store/provider_health_noncritical.json` was `{}` because
a mark could not survive even one call -- the chain never advanced to a live brain, and
`complete_json` re-asked the same dead provider three times. Thirteen consecutive generation
ticks produced zero candidates.

IT HAPPENED AGAIN, 2026-08-13 -- same clause, ONE NOUN DIFFERENT. The body was byte-identical
except "free usage" became "free TRIAL", which the alternation did not list. Eight barren
ticks, three signals parked to `signals/pending/`, nothing published for a day. So the lesson
this file pins is not "add trial": it is that the alternation enumerates A VENDOR'S NOUNS for
the thing an account runs out of, and a vendor renames those in a copy edit. Every member of
that family is tested below, and a new one belongs in the regex the day it is seen.
"""
from __future__ import annotations

import pytest

from prospector.errors import (
    PERMANENT,
    classify_exhaustion,
    looks_exhausted,
)

# The body as logged on 2026-08-09, verbatim (197 chars), em dashes and all. The vendor is
# named here because this is a QUOTED LOG LINE, not a live dependency -- the string is the
# evidence, and editing it to remove the name would break the thing it is evidence of.
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
