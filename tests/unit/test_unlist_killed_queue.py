"""The unlist queue: nothing is dropped, and nothing is retired that was not done.

`tools/unlist_killed.py` drains the queue `decay._queue_unlist` writes to when a re-vet turns
a published PASS into a KILL. Losing an entry here means a pack the engine has killed stays on
sale — the exact condition found by hand on 2026-08-06, when 4 re-vetted KILLs were still
selling because nothing drained this file at all.

The queue was then emptied with `QUEUE.write_text("")` (§23.6), which loses every entry that
arrived during the `fly ssh` round-trip. These tests pin the replacement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import unlist_killed as uk  # noqa: E402

from prospector import paths  # noqa: E402
from prospector.jsonl_atomic import append_jsonl, read_jsonl  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.STORE_ROOT_ENV, str(tmp_path))
    (tmp_path / "scheduler").mkdir(parents=True)
    return tmp_path


def _entry(cid: str) -> dict:
    return {"candidate_id": cid, "title": f"pack {cid}", "gate_fired": "value_durability"}


def test_commit_retires_what_was_processed(store):
    for cid in ("aaa", "bbb"):
        append_jsonl(uk._queue(), _entry(cid))

    entries = uk._read_queue()
    assert uk._commit(entries) == 2

    assert read_jsonl(uk._queue()) == []
    assert [e["candidate_id"] for e in read_jsonl(uk._done())] == ["aaa", "bbb"]


def test_an_entry_queued_during_the_unlist_survives_the_commit(store, capsys):
    """The lost update, in the order it actually happens.

    `_read_queue` → fly round-trip (decay appends here) → `_commit`. The new entry was never
    processed, so it must still be queued afterwards; it must NOT appear in the done log.
    """
    append_jsonl(uk._queue(), _entry("aaa"))
    entries = uk._read_queue()

    append_jsonl(uk._queue(), _entry("late"))     # decay.py, mid-round-trip

    uk._commit(entries)

    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["late"]
    assert [e["candidate_id"] for e in read_jsonl(uk._done())] == ["aaa"]
    assert "1 entry(s) arrived while unlisting" in capsys.readouterr().out


def test_the_old_truncating_commit_would_have_dropped_it(store):
    """Same sequence, old code. Kept so the fix is measured against a demonstrated loss."""
    append_jsonl(uk._queue(), _entry("aaa"))
    uk._read_queue()
    append_jsonl(uk._queue(), _entry("late"))
    uk._queue().write_text("", encoding="utf-8")

    assert read_jsonl(uk._queue()) == []          # "late" is gone, unprocessed and untraceable


def test_read_queue_does_not_empty_the_queue(store):
    """The unlist only succeeds after `fly ssh` returns. A read that consumed the queue would
    lose everything whenever Fly was unreachable."""
    append_jsonl(uk._queue(), _entry("aaa"))
    assert len(uk._read_queue()) == 1
    assert len(uk._read_queue()) == 1


def test_a_failed_run_leaves_the_queue_intact(store, monkeypatch, capsys):
    """A row still IsListed=1 after the UPDATE must leave the queue untouched for a re-run."""
    append_jsonl(uk._queue(), _entry("aaa"))
    monkeypatch.setattr(uk, "_ssh_sql", lambda sql: "aaa|1\n")
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])

    assert uk.main() == 1
    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["aaa"]
    assert not uk._done().exists()


def test_dry_run_touches_nothing(store, monkeypatch, capsys):
    append_jsonl(uk._queue(), _entry("aaa"))

    def _forbidden(sql):
        raise AssertionError("--dry-run reached the live catalogue")

    monkeypatch.setattr(uk, "_ssh_sql", _forbidden)
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py", "--dry-run"])

    assert uk.main() == 0
    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["aaa"]
    assert "would unlist aaa" in capsys.readouterr().out


def test_an_empty_queue_is_not_an_error(store, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])
    monkeypatch.setattr(uk, "_ssh_sql", lambda sql: (_ for _ in ()).throw(AssertionError("called")))
    assert uk.main() == 0


def test_a_successful_run_retires_the_queue(store, monkeypatch, capsys):
    append_jsonl(uk._queue(), _entry("aaa"))
    calls: list[str] = []

    def _fake(sql):
        calls.append(sql)
        return "aaa|0\n" if sql.startswith("SELECT") and len(calls) > 2 else "aaa|1\n"

    monkeypatch.setattr(uk, "_ssh_sql", _fake)
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])

    assert uk.main() == 0
    assert any(s.startswith("UPDATE Packs SET IsListed=0") for s in calls)
    assert read_jsonl(uk._queue()) == []
    assert [e["candidate_id"] for e in read_jsonl(uk._done())] == ["aaa"]
