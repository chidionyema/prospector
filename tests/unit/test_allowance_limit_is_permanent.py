"""An allowance limit is PERMANENT exhaustion, not backpressure.

Regression for 2026-08-06. The Claude Code CLI announces a spent allowance like this
(captured verbatim from store/scheduler/launchd.err.log at 10:24:36Z):

    ..."fast_mode_disabled_reason":"sdk_opt_in_required","subtype":"success",
    "api_error_status":429,"result":"You've hit your monthly spend limit · raise it at
    claude.ai/settings/usage?from=cc_cli_limit_message"

`_PERMANENT_MARKERS` held "usage limit" but the CLI says SPEND limit. Two consequences,
both observed live:

  1. With the 429 present, the message classified TRANSIENT (60s) on the incidental HTTP
     code alone, so the daemon re-probed a hard monthly cap every 60 seconds — the live
     log shows strikes 2, 3 and 4 escalating inside three seconds.
  2. WITHOUT a 429 the message classified NOT_EXHAUSTION, which is the dangerous half: a
     failure `looks_exhausted` misses never becomes ProviderExhaustedError, so verify.py
     takes its generic-exception path and a billing failure is recorded as an
     `unverifiable` CHECK instead of deferring the candidate. See
     test_graceful_degradation.test_crashed_verdict_call_defers_never_kills.

Mutation test: delete `_ALLOWANCE_LIMIT_RE` from the disjunction in `classify_exhaustion`
and the first two cases below fail.
"""
from __future__ import annotations

import pytest

from prospector.errors import (
    NOT_EXHAUSTION,
    PERMANENT,
    TRANSIENT,
    classify_exhaustion,
    looks_exhausted,
)

# Verbatim from the live daemon log, 2026-08-06T10:24:36Z.
REAL_CLI_LIMIT_ERROR = (
    'claude cli exhausted after 2 attempts: claude cli exit 1: e_state":"off",'
    '"fast_mode_disabled_reason":"sdk_opt_in_required","subtype":"success",'
    '"api_error_status":429,"result":"You\'ve hit your monthly spend limit '
    '· raise it at claude.ai/settings/usage?from=cc_cli_limit_message'
)


@pytest.mark.parametrize("text", [
    REAL_CLI_LIMIT_ERROR,
    # The same announcement with no HTTP code attached — the case that scored
    # NOT_EXHAUSTION and therefore never raised ProviderExhaustedError at all.
    "You've hit your monthly spend limit",
    "you have hit your weekly spend limit",
    "daily limit reached for this account",
])
def test_allowance_limits_are_permanent(text):
    assert classify_exhaustion(text) == PERMANENT
    assert looks_exhausted(text) is True


@pytest.mark.parametrize("text", [
    "HTTP 429 rate limit, retry later",
    "overloaded_error",
    "too many requests",
])
def test_backpressure_is_still_transient(text):
    """The 2026-08-06 fix that separated backpressure from exhaustion must survive.

    A rate limit wants a shorter queue, not an hour on the bench. "rate limit" must not be
    swept up by the allowance regex — that would re-create the outage this project already
    paid for once."""
    assert classify_exhaustion(text) == TRANSIENT


@pytest.mark.parametrize("text", [
    "connection reset after 4291 bytes",
    "req_id=a429f0 timeout",
    "Error: 4290 tokens",
    "billing address invalid",
    "401 unauthorized",
])
def test_non_exhaustion_stays_clean(text):
    """The word-boundary guards must not regress: these benched a LIVE brain for an hour,
    nine times in seventy minutes, on 2026-08-06."""
    assert classify_exhaustion(text) == NOT_EXHAUSTION
    assert looks_exhausted(text) is False
