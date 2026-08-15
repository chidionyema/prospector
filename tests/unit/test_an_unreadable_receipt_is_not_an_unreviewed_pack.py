"""A corrupt human-review receipt must leave a trace, not pass for "nobody has reviewed this".

MEASURED 2026-08-15. `human_review.load_receipt` returned `None` for a missing file and for an
unreadable one alike, and `status()` turns `None` into `unreviewed`. `unreviewed` is the honest
word for a pack nobody has looked at and the wrong one for a pack whose reviewer's decisions
are sitting in a file we can no longer parse — the second is a defect and produced no signal
of any kind.

Fail-closed is unchanged (a corrupt receipt must never certify anything). What is pinned here
is that the corrupt case is now distinguishable at ERROR while the ordinary missing case stays
silent, so the log is not flooded with a normal condition.
"""
from __future__ import annotations

import logging

from prospector.human_review import load_receipt, receipt_path


def test_a_missing_receipt_is_silent_and_returns_none(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="prospector.human_review"):
        assert load_receipt("packA", tmp_path) is None
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_a_corrupt_receipt_returns_none_but_logs_at_error(tmp_path, caplog):
    receipt_path("packB", tmp_path).write_text("{ not json", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="prospector.human_review"):
        assert load_receipt("packB", tmp_path) is None

    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs, "a corrupt receipt must be distinguishable from a missing one"
    assert "packB" in errs[0].getMessage()


def test_a_receipt_that_is_not_an_object_also_logs_at_error(tmp_path, caplog):
    receipt_path("packC", tmp_path).write_text("[1, 2, 3]", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="prospector.human_review"):
        assert load_receipt("packC", tmp_path) is None

    assert [r for r in caplog.records if r.levelno >= logging.ERROR]
