"""Four persistence readers returned the same empty value for "nothing there" and "it broke".

The discriminator from the batch contract is not "does it return empty" but "can the CALLER tell
empty-because-nothing-matched from empty-because-it-broke". These four could not:

* `jsonl_atomic.iter_jsonl` — an unopenable file returned an empty iterator, and its ERROR log was
  gated on `warn`, which every live caller passes as False (`scheduler/status.py:85`,
  `scheduler/run_scheduled.py:1288,1779`). `status.py:85` even wraps the call in
  `except (OSError, ValueError)`: a handler that could never fire.
* `drain_state.load` — a corrupt ledger gave every backlog row its budget back, silently
  re-engaging the generation freeze `gate-on-the-rate-not-the-stock` exists to avoid.
* `usage_wall.read` — a malformed marker read as "no wall", so the daemon spawns `claude -p` into
  a wall the other daemon already recorded.
* `archive._cache_load` — an unloadable cache re-queries the Internet Archive forever.

Each keeps its empty (all four fail in the direction that keeps working, which is right). What is
pinned here is that the broken case is now DISTINGUISHABLE — by `ReadStats.read_error` where the
caller can act, and by an ERROR log where it cannot, with the genuine-absence case staying silent.
"""
from __future__ import annotations

import json
import logging

from prospector import archive, drain_state, usage_wall
from prospector.jsonl_atomic import append_jsonl, read_jsonl_with_stats


def _errors(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---------------------------------------------------------------- jsonl_atomic.iter_jsonl


def test_read_stats_separates_an_unreadable_file_from_an_empty_one(tmp_path, caplog):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    rows, st = read_jsonl_with_stats(empty, warn=False)
    assert rows == [] and st.read_error is None and st.clean

    missing = tmp_path / "never-written.jsonl"
    rows, st = read_jsonl_with_stats(missing, warn=False)
    assert rows == [] and st.read_error is None and st.clean, \
        "a file nothing has appended to yet is an ordinary empty, not a failure"

    # A directory is unopenable as a file on every platform, and needs no mode bits (so the test
    # means the same thing when the suite runs as root).
    unreadable = tmp_path / "locked.jsonl"
    unreadable.mkdir()
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="prospector.jsonl_atomic"):
        rows, st = read_jsonl_with_stats(unreadable, warn=False)
    assert rows == []
    assert st.read_error is not None, "0 rows from an unopenable file is not evidence of 0 rows"
    assert st.clean is False
    assert _errors(caplog), "warn=False governs CONTENT tolerance and must not silence an open failure"


def test_a_readable_file_with_rows_reports_no_read_error(tmp_path):
    p = tmp_path / "ticks.jsonl"
    append_jsonl(p, {"n": 1}, fsync=False)
    append_jsonl(p, {"n": 2}, fsync=False)
    rows, st = read_jsonl_with_stats(p, warn=False)
    assert rows == [{"n": 1}, {"n": 2}]
    assert st.read_error is None and st.clean


# ---------------------------------------------------------------- drain_state.load


def test_a_corrupt_attempt_ledger_is_not_an_untried_backlog(tmp_path, caplog):
    with caplog.at_level(logging.ERROR):
        assert drain_state.load(tmp_path) == {}
    assert not _errors(caplog), "no ledger yet is a real answer: nothing has been tried"

    p = drain_state.ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"a": 1, ')                     # torn write
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        assert drain_state.load(tmp_path) == {}
    assert _errors(caplog), "silently resetting every row's budget re-engages the generation freeze"

    p.write_text('["not", "an", "object"]')
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        assert drain_state.load(tmp_path) == {}
    assert _errors(caplog)


def test_a_good_attempt_ledger_still_loads(tmp_path):
    p = drain_state.ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"cand-1": 3}))
    assert drain_state.load(tmp_path) == {"cand-1": 3}
    assert drain_state.attempts_for(tmp_path, "cand-1") == 3


# ---------------------------------------------------------------- usage_wall.read


def test_a_malformed_usage_wall_marker_is_not_an_absent_one(tmp_path, monkeypatch, caplog):
    marker = tmp_path / "claude_usage_limit.json"
    monkeypatch.setenv("PROSPECTOR_USAGE_WALL_MARKER", str(marker))

    with caplog.at_level(logging.ERROR, logger="prospector.usage_wall"):
        assert usage_wall.read(now=1000.0) is None
    assert not _errors(caplog), "no marker at all is the ordinary case and must stay silent"

    for bad in ('{"reset_at": ', '["not", "an", "object"]',
                '{"observed_by": "otto"}', '{"reset_at": "soon"}'):
        marker.write_text(bad)
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="prospector.usage_wall"):
            assert usage_wall.read(now=1000.0) is None, "fail OPEN stays the contract"
        assert _errors(caplog), f"a marker that exists and is unusable must be loud: {bad!r}"


def test_an_expired_wall_is_silent_and_a_live_one_still_reads(tmp_path, monkeypatch, caplog):
    marker = tmp_path / "claude_usage_limit.json"
    monkeypatch.setenv("PROSPECTOR_USAGE_WALL_MARKER", str(marker))

    marker.write_text(json.dumps({"reset_at": 500.0, "observed_by": "otto"}))
    with caplog.at_level(logging.ERROR, logger="prospector.usage_wall"):
        assert usage_wall.read(now=1000.0) is None
    assert not _errors(caplog), "a wall that has LIFTED is a fact, not a failure"

    marker.write_text(json.dumps({"reset_at": 1600.0, "observed_by": "otto"}))
    assert usage_wall.read(now=1000.0)["observed_by"] == "otto"
    assert usage_wall.blocked_for(now=1000.0) == 600.0


# ---------------------------------------------------------------- archive._cache_load


def test_an_unloadable_citation_cache_is_not_a_cold_one(tmp_path, caplog):
    missing = tmp_path / "citation_archive.json"
    with caplog.at_level(logging.ERROR, logger="prospector.archive"):
        assert archive._cache_load(missing) == {}
    assert not _errors(caplog), "first run has no cache; that is not an error"

    missing.write_text("{oops")
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="prospector.archive"):
        assert archive._cache_load(missing) == {}
    assert _errors(caplog), "a cache that never loads pays the rate limit on every publish"

    missing.write_text(json.dumps({"https://x": {"memento": "m", "ts": 1}}))
    assert archive._cache_load(missing) == {"https://x": {"memento": "m", "ts": 1}}
