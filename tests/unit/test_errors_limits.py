"""Limit classification and reset-window parsing.

WHY THIS FILE EXISTS (2026-08-06). `parse_reset_seconds` read only RELATIVE durations
(`retryDelayMs`, "reset after 6h54m27s"). Claude Code states its limits as an ABSOLUTE wall-clock
reset, so those messages parsed to nothing, fell back to `DEFAULT_EXHAUSTION_S` (3600s), and the
daemon re-probed a brain that was guaranteed dead once an hour for up to a WEEK. Nothing
distinguished a 5-hour window from a weekly cap from a spent account.

The clock is pinned in every test here: a reset-time parser that is only correct at the moment it
was written is not a parser.
"""
from __future__ import annotations

import datetime as dt

import pytest

from prospector.errors import (
    LIMIT_NONE,
    LIMIT_SESSION_5H,
    LIMIT_WEEKLY,
    PERMANENT,
    classify_exhaustion,
    classify_limit,
    limit_window_seconds,
    parse_reset_seconds,
)

NOW = dt.datetime(2026, 8, 6, 12, 0, 0, tzinfo=dt.timezone.utc)


# --- the regression that motivated the change ------------------------------------------------

def test_five_hour_limit_is_exhaustion_at_all():
    """The DANGEROUS half: a limit `looks_exhausted` misses never becomes a
    ProviderExhaustedError, so verify.py takes its generic-exception path and the outage is
    recorded as an `unverifiable` check instead of deferring the candidate. Measured returning
    NOT_EXHAUSTION ("") before the fix."""
    assert classify_exhaustion("5-hour limit reached; try again later") == PERMANENT
    assert classify_exhaustion("You have hit your session limit") == PERMANENT
    assert classify_exhaustion("weekly limit reached") == PERMANENT


def test_hour_limit_prose_does_not_false_positive():
    """`\\d+-hour limit` must not widen into any sentence containing 'hour' and 'limit'."""
    assert classify_exhaustion("we limit requests per hour to keep latency low") != PERMANENT


def test_word_boundary_regression_still_holds():
    """The 2026-08-06 substring bug: a token/byte count containing 429/402 benched a live brain."""
    for benign in ("Error: 4290 tokens processed",
                   "connection reset after 4291 bytes",
                   "req_id=a429f0 timeout"):
        assert classify_exhaustion(benign) == "", benign


# --- limit CLASSES ----------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("You've hit your weekly limit.", LIMIT_WEEKLY),
    ("limit resets next Monday", LIMIT_WEEKLY),
    ("5-hour limit reached", LIMIT_SESSION_5H),
    ("five hour limit reached", LIMIT_SESSION_5H),
    ("You have hit your session limit", LIMIT_SESSION_5H),
    ("Error: 4290 tokens processed", LIMIT_NONE),
])
def test_classify_limit(text, expected):
    assert classify_limit(text) == expected


def test_weekly_wins_over_session_wording():
    """Weekly is the only class nothing automatic clears, so a message that reads as both must
    classify weekly: the asymmetry of the mistake is a week of hourly probes vs one delayed
    half-open probe."""
    assert classify_limit("weekly limit reached for this session") == LIMIT_WEEKLY


# --- absolute reset times ---------------------------------------------------------------------

def test_absolute_iso_reset():
    got = limit_window_seconds("You've hit your weekly limit. Resets on 2026-08-09T00:00:00Z",
                               now=NOW)
    assert got == pytest.approx(2.5 * 24 * 3600)


def test_absolute_clock_reset_later_today():
    assert limit_window_seconds("Your limit will reset at 5pm.", now=NOW) == pytest.approx(5 * 3600)


def test_absolute_clock_reset_already_passed_means_tomorrow():
    """'resets at 9am' seen at noon means TOMORROW 9am, not a negative window."""
    assert limit_window_seconds("resets at 9am", now=NOW) == pytest.approx(21 * 3600)


def test_past_absolute_reset_yields_no_window():
    """An already-expired reset is not a window; the caller falls back to its own default rather
    than treating a stale timestamp as authoritative."""
    assert parse_reset_seconds("resets at 2026-08-01T00:00:00Z", now=NOW) is None


def test_absurd_future_reset_is_clamped():
    """A mis-parse must not bench a brain for a month."""
    got = limit_window_seconds("resets at 2027-01-01T00:00:00Z", now=NOW)
    assert got == pytest.approx(7 * 24 * 3600)


# --- precedence -------------------------------------------------------------------------------

def test_stated_reset_beats_class_default():
    """The provider knows when its own quota returns; a class default is only a guess."""
    text = "weekly limit reached. Resets on 2026-08-07T12:00:00Z"
    assert limit_window_seconds(text, now=NOW) == pytest.approx(24 * 3600)


def test_class_default_used_when_nothing_stated():
    assert limit_window_seconds("5-hour limit reached", now=NOW) == 5 * 3600
    assert limit_window_seconds("weekly limit reached", now=NOW) == 7 * 24 * 3600


def test_no_limit_and_no_reset_returns_none():
    """None means 'use your own default' — it must not collapse to 0, which would read as
    'this provider is fine' and resurrect a benched brain."""
    assert limit_window_seconds("Error: 4290 tokens processed", now=NOW) is None


# --- existing relative parsing must be untouched ----------------------------------------------

def test_relative_shapes_unchanged():
    assert parse_reset_seconds('{"retryDelayMs": 90000}') == pytest.approx(90.0)
    assert parse_reset_seconds("quota will reset after 6h54m27s") == pytest.approx(24867.0)


# ---------------------------------------------------------------------------
# cause_context — a truncation that drops the cause is an outage with no trace
#
# 2026-08-07: the account hit its monthly spend limit mid-run. `claude_cli.py` built its error
# detail from `proc.stdout.strip()[-300:]`, and with `--output-format json` the last 300 chars
# are trailing metadata, so the phrase naming the cause was sliced away. The classifier saw
# NOT_EXHAUSTION, no permanent dead mark was written, nothing failed over, and the harness
# spent 50 more calls into a provider already known to be dead.
# ---------------------------------------------------------------------------

# Faithful to the observed payload: the real 300-char tail held ONLY metadata
# (…fast_mode_disabled_reason…subtype…api_error_st), so the cause sat further back than that.
_SPEND_LIMIT_PAYLOAD = (
    '{"type":"result","is_error":true,'
    '"result":"API Error: Your monthly spend limit has been reached.",'
    '"session_id":"9f2c1b7e-4a3d-4c8e-b1f0-77aa2e5d9c31",'
    '"uuid":"c41e8a02-6b55-4f19-9d33-2ec7b40af6d8",'
    '"modelUsage":{"claude-opus-5":{"inputTokens":1204,"outputTokens":0,'
    '"cacheReadInputTokens":88210,"cacheCreationInputTokens":0,"costUSD":0.0}},'
    '"permission_denials":[],"num_turns":1,"duration_ms":812,"duration_api_ms":790,'
    '"total_cost_usd":0.0,"fast_mode_state":"off",'
    '"fast_mode_disabled_reason":"sdk_opt_in_required","subtype":"success",'
    '"api_error_status":400}'
)


def test_tail_slice_loses_the_cause_but_cause_context_recovers_it():
    """The regression, stated as the two classifications it produced."""
    from prospector.errors import cause_context, classify_exhaustion

    # The defect is only real if the cause is genuinely outside the tail window.
    assert len(_SPEND_LIMIT_PAYLOAD) - _SPEND_LIMIT_PAYLOAD.find("monthly spend limit") > 300

    tail_only = _SPEND_LIMIT_PAYLOAD.strip()[-300:]
    assert classify_exhaustion(f"claude cli exit 1: {tail_only}") == "", (
        "the tail slice must still be shown to lose the cause — if this starts passing, the "
        "payload padding no longer reproduces the 2026-08-07 shape and the test is vacuous")

    recovered = cause_context(_SPEND_LIMIT_PAYLOAD)
    assert "monthly spend limit" in recovered
    assert classify_exhaustion(f"claude cli exit 1: {recovered} | {tail_only}") == "permanent"


def test_cause_context_is_shape_agnostic():
    """Prose, JSON and a bare fragment all carry the marker to the classifier."""
    from prospector.errors import cause_context, classify_exhaustion

    for text in ("Credit balance is too low. Please add funds.",
                 '{"error":{"message":"Your credit balance is too low"},"x":1}',
                 "...blah... credit balance is too low ...blah..."):
        assert classify_exhaustion(cause_context(text)) == "permanent", text


def test_cause_context_is_empty_when_there_is_no_cause():
    """No marker anywhere → empty, so the caller falls back to its tail slice unchanged."""
    from prospector.errors import cause_context

    assert cause_context('{"type":"result","subtype":"success","result":"fine"}') == ""
    assert cause_context("") == ""


def test_cause_context_does_not_repeat_one_sentence_per_marker():
    """Overlapping windows collapse; three markers in a phrase must not print it three times."""
    from prospector.errors import cause_context

    out = cause_context("credit balance is too low and usage limit reached")
    assert out.count("credit balance is too low") == 1
