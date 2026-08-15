"""Two blanket `except Exception` handlers logged our own bugs as somebody else's outage.

`archive.archive_sources` and `coverage.plan_cells` both MUST stay non-fatal — the first runs
inside `publish_pass` upstream of the money rail, the second must never be able to stop the
daemon generating. So the fix is not to let them raise. It is that a `TypeError` from a refactor
used to print as one grey `logger.warning` line, character-identical in shape to a socket timeout
or a locked sqlite file, and there was no traceback to say otherwise.

Both still return their empty value. What is pinned here is the DISTINCTION in the log: an
expected remote/IO condition is an ERROR with a message; an unexpected type is an ERROR that
carries `exc_info` and names itself a bug in our code.
"""
from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace

from prospector import archive, coverage


def _error_records(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---------------------------------------------------------------- archive.archive_sources


def _sources():
    return [SimpleNamespace(url="https://example.com/a", archived_url=None)]


def test_archive_sources_marks_an_unexpected_exception_as_our_bug(monkeypatch, caplog):
    def boom(*_a, **_kw):
        raise TypeError("archive_urls() got an unexpected keyword argument 'save_budget_s'")

    monkeypatch.setattr(archive, "archive_urls", boom)
    with caplog.at_level(logging.ERROR, logger="prospector.archive"):
        assert archive.archive_sources(_sources()) == 0, "a pack must still ship without mementos"

    recs = _error_records(caplog)
    assert recs, "a total archiving failure must be at ERROR"
    assert any(r.exc_info for r in recs), "an unexpected type must carry a traceback"
    assert any("UNEXPECTED" in r.getMessage() for r in recs)


def test_archive_sources_does_not_call_a_remote_failure_a_bug(monkeypatch, caplog):
    def timeout(*_a, **_kw):
        raise OSError("Read timed out (read timeout=10.0)")   # requests.RequestException is an OSError

    monkeypatch.setattr(archive, "archive_urls", timeout)
    with caplog.at_level(logging.ERROR, logger="prospector.archive"):
        assert archive.archive_sources(_sources()) == 0

    recs = _error_records(caplog)
    assert recs
    assert not any("UNEXPECTED" in r.getMessage() for r in recs), \
        "the Internet Archive being slow is not a bug in archive_sources"
    assert not any(r.exc_info for r in recs)


def test_archive_sources_still_reports_a_real_count(monkeypatch):
    monkeypatch.setattr(archive, "archive_urls",
                        lambda *_a, **_kw: {"https://example.com/a": "https://web.archive.org/x"})
    srcs = _sources()
    assert archive.archive_sources(srcs) == 1
    assert srcs[0].archived_url == "https://web.archive.org/x"


# ---------------------------------------------------------------- coverage.plan_cells


def _enabled_cfg(tmp_path):
    db = tmp_path / "prospector.db"
    sqlite3.connect(db).close()
    return SimpleNamespace(store_dir=str(tmp_path), coverage_sampler={"enabled": True}), db


def test_plan_cells_marks_an_unexpected_exception_as_our_bug(tmp_path, monkeypatch, caplog):
    cfg, db = _enabled_cfg(tmp_path)

    def boom(*_a, **_kw):
        raise TypeError("_rank_by_deficit() missing 1 required positional argument")

    monkeypatch.setattr(coverage, "measure", boom)
    with caplog.at_level(logging.ERROR, logger="prospector.coverage"):
        assert coverage.plan_cells(cfg, 3, db_path=db) == [], "generation must fall back to rotation"

    recs = _error_records(caplog)
    assert recs
    assert any(r.exc_info for r in recs), "an unexpected type must carry a traceback"
    assert any("UNEXPECTED" in r.getMessage() for r in recs)


def test_plan_cells_does_not_call_an_index_failure_a_bug(tmp_path, monkeypatch, caplog):
    cfg, db = _enabled_cfg(tmp_path)

    def locked(*_a, **_kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(coverage, "measure", locked)
    with caplog.at_level(logging.ERROR, logger="prospector.coverage"):
        assert coverage.plan_cells(cfg, 3, db_path=db) == []

    recs = _error_records(caplog)
    assert recs
    assert not any("UNEXPECTED" in r.getMessage() for r in recs)
    assert not any(r.exc_info for r in recs)


def test_a_disabled_sampler_is_silent_but_an_invalid_config_is_not(tmp_path, caplog):
    off = SimpleNamespace(store_dir=str(tmp_path), coverage_sampler={"enabled": False})
    with caplog.at_level(logging.ERROR, logger="prospector.coverage"):
        assert coverage.plan_cells(off, 3) == []
    assert not _error_records(caplog), "[] from a switched-off sampler is a value, not a failure"

    caplog.clear()
    bad = SimpleNamespace(store_dir=str(tmp_path),
                          coverage_sampler={"enabled": True, "method": "nonsense"})
    with caplog.at_level(logging.ERROR, logger="prospector.coverage"):
        assert coverage.plan_cells(bad, 3) == []
    assert _error_records(caplog), \
        "[] is also what 'disabled' returns, so an ignored config must be loud"


def test_db_path_for_still_absorbs_a_stub_config(tmp_path):
    assert coverage.db_path_for(SimpleNamespace()) is None       # no store_dir at all
    assert coverage.db_path_for(SimpleNamespace(store_dir=None)) is None
    assert coverage.db_path_for(SimpleNamespace(store_dir=str(tmp_path))) is None  # no DB yet
    (tmp_path / "prospector.db").write_text("")
    assert coverage.db_path_for(SimpleNamespace(store_dir=str(tmp_path))) is not None
