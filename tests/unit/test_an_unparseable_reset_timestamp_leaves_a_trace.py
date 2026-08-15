"""A reset time we matched but could not parse must not vanish silently.

MEASURED 2026-08-15. `errors._parse_absolute_reset` matched `_RESET_AT_ISO`, handed the capture
to `datetime.fromisoformat`, and on ValueError set `when = None` with no trace. The window that
results is correct and deliberately unchanged — falling through to the caller's
`DEFAULT_EXHAUSTION_S` is the safe guess — but the SILENCE is the same defect the whole
absolute-reset section was written to close: absolute resets parsed to nothing for months
(see errors.py's 2026-08-06 note) and the only symptom was an hourly full-price probe against
a brain that was guaranteed dead.

This test pins the distinction: "the provider stated no reset time" (silent None) versus "the
provider stated one and its format moved under us" (None plus an ERROR).
"""
from __future__ import annotations

import datetime as dt
import logging

from prospector.errors import _parse_absolute_reset, limit_window_seconds

NOW = dt.datetime(2026, 8, 15, 12, 0, 0, tzinfo=dt.timezone.utc)


def test_text_with_no_reset_time_is_silent():
    with _captured() as records:
        assert _parse_absolute_reset("Error: 4290 tokens processed", now=NOW) is None
    assert records == []


def test_a_malformed_iso_reset_returns_none_and_logs_at_error(caplog):
    text = "You've hit your weekly limit. Resets on 2026-13-45T99:99:99Z"

    with caplog.at_level(logging.ERROR, logger="prospector.errors"):
        got = _parse_absolute_reset(text, now=NOW)

    assert got is None                        # window behaviour unchanged
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs, "a reset timestamp we matched and could not read must be visible"


def test_the_bench_window_is_unchanged_by_the_trace():
    """The caller still gets the weekly class default, exactly as before."""
    text = "You've hit your weekly limit. Resets on 2026-13-45T99:99:99Z"
    assert limit_window_seconds(text, now=NOW) == 7 * 24 * 3600


def test_a_well_formed_iso_reset_still_parses():
    got = _parse_absolute_reset("Resets on 2026-08-16T00:00:00Z", now=NOW)
    assert got == 12 * 3600


class _captured:
    """Minimal ERROR-record collector for prospector.errors (caplog fixture not needed)."""

    def __enter__(self):
        self.records: list[logging.LogRecord] = []
        self.logger = logging.getLogger("prospector.errors")

        class _H(logging.Handler):
            def emit(_self, record):
                if record.levelno >= logging.ERROR:
                    self.records.append(record)

        self.handler = _H()
        self.logger.addHandler(self.handler)
        return self.records

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)
        return False
