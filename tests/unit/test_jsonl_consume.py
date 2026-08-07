"""`consume_jsonl` — draining a queue without deleting what arrived mid-drain.

The defect being closed (COMMERCIAL_READINESS_PROGRAM §23.6): `tools/unlist_killed.py:113`
emptied `store/scheduler/pending_unlist.jsonl` with `QUEUE.write_text("")` after reading it.
`decay._queue_unlist` appends to that file from the unattended re-vet sweep, so every entry
added between the read and the truncation was deleted unprocessed — and each of those entries
is a pack the engine re-vetted to KILL that stays for sale on mumchimp.com.

`test_the_truncating_drain_loses_the_interleaved_append` reproduces that loss deterministically
first, so the rest of this file is measuring a fix against a demonstrated failure rather than
against an argument.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from prospector.jsonl_atomic import append_jsonl, consume_jsonl, read_jsonl

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── the defect ────────────────────────────────────────────────────────────────
def test_the_truncating_drain_loses_the_interleaved_append(tmp_path):
    """The old shape, spelled out. No timing, no threads: just the order of operations."""
    q = tmp_path / "q.jsonl"
    append_jsonl(q, {"n": 1})

    entries = read_jsonl(q)              # drainer reads the queue
    append_jsonl(q, {"n": 2})            # producer appends while the drainer works
    q.write_text("", encoding="utf-8")   # drainer commits: the old `QUEUE.write_text("")`

    assert entries == [{"n": 1}]         # record 2 was never processed
    assert read_jsonl(q) == []           # and is no longer queued: it is simply gone


def test_consume_keeps_the_interleaved_append(tmp_path):
    """The same sequence through consume_jsonl: record 2 comes back to the caller."""
    q = tmp_path / "q.jsonl"
    append_jsonl(q, {"n": 1})

    entries = read_jsonl(q)
    append_jsonl(q, {"n": 2})
    drained = consume_jsonl(q)

    assert drained == [{"n": 1}, {"n": 2}]
    # The caller processed only entries; the extra is its to re-queue, and it HAS it.
    assert [e for e in drained if e not in entries] == [{"n": 2}]


# ── behaviour ─────────────────────────────────────────────────────────────────
def test_returns_records_and_empties_the_file(tmp_path):
    q = tmp_path / "q.jsonl"
    for n in range(5):
        append_jsonl(q, {"n": n})
    assert consume_jsonl(q) == [{"n": n} for n in range(5)]
    assert q.read_bytes() == b""
    assert consume_jsonl(q) == []


def test_missing_file_returns_empty_and_creates_nothing(tmp_path):
    q = tmp_path / "nope.jsonl"
    assert consume_jsonl(q) == []
    assert not q.exists()


def test_a_torn_tail_is_neither_consumed_nor_deleted(tmp_path):
    """Bytes after the last newline are an append in flight. Taking them would consume a
    record the producer has not finished writing; deleting them would corrupt it."""
    q = tmp_path / "q.jsonl"
    q.write_bytes(b'{"n": 1}\n{"n": 2}\n{"n": 3, "part')

    assert consume_jsonl(q) == [{"n": 1}, {"n": 2}]
    assert q.read_bytes() == b'{"n": 3, "part'


def test_a_file_with_no_committed_record_is_left_exactly_as_found(tmp_path):
    q = tmp_path / "q.jsonl"
    q.write_bytes(b'{"n": 1, "unfinis')
    assert consume_jsonl(q) == []
    assert q.read_bytes() == b'{"n": 1, "unfinis'


def test_corrupt_but_terminated_lines_are_dropped_not_replayed_forever(tmp_path):
    q = tmp_path / "q.jsonl"
    q.write_bytes(b'{"n": 1}\nnot json at all\n{"n": 2}\n')
    assert consume_jsonl(q) == [{"n": 1}, {"n": 2}]
    assert q.read_bytes() == b""


def test_blank_lines_are_ignored(tmp_path):
    q = tmp_path / "q.jsonl"
    q.write_bytes(b'{"n": 1}\n\n\n{"n": 2}\n')
    assert consume_jsonl(q) == [{"n": 1}, {"n": 2}]


# ── the lock, across real processes ───────────────────────────────────────────
_PRODUCER = """
import sys
sys.path.insert(0, {root!r})
from prospector.jsonl_atomic import append_jsonl
tag, count, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
for i in range(count):
    append_jsonl(path, {{"tag": tag, "i": i}}, fsync=False)
"""


def test_no_record_is_lost_when_producers_append_during_a_drain(tmp_path):
    """Four separate processes append while this one drains repeatedly.

    The assertion is conservation: every record a producer wrote is either in something a
    drain returned or still in the file at the end, exactly once. That is the property the
    truncating drain violated, and it cannot be proved in one process — `flock` is between
    open file descriptions, so a single-process test would pass even with no lock at all.
    """
    q = tmp_path / "q.jsonl"
    per_producer = 150
    tags = ["a", "b", "c", "d"]
    script = _PRODUCER.format(root=str(REPO_ROOT))

    procs = [
        subprocess.Popen([sys.executable, "-c", script, tag, str(per_producer), str(q)])
        for tag in tags
    ]

    drained: list = []
    while any(p.poll() is None for p in procs):
        drained.extend(consume_jsonl(q, fsync=False))
    for p in procs:
        assert p.wait(timeout=60) == 0
    drained.extend(consume_jsonl(q, fsync=False))       # whatever landed after the last poll

    leftover = read_jsonl(q)
    seen = [json.dumps(r, sort_keys=True) for r in drained + leftover]

    expected = {
        json.dumps({"tag": tag, "i": i}, sort_keys=True)
        for tag in tags for i in range(per_producer)
    }
    assert len(seen) == len(set(seen)), "a record was returned twice"
    assert set(seen) == expected, (
        f"{len(expected - set(seen))} record(s) lost, "
        f"{len(set(seen) - expected)} invented"
    )
