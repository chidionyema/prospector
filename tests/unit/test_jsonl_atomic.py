"""R3 (`docs/COMMERCIAL_READINESS_PROGRAM.md` §2.6) — atomic JSONL appends + tolerant reader.

Every test writes only under `tmp_path`. Nothing here imports a module-bound production path,
and no test touches `store/`: the incidents this repo already paid for (pytest reaching the
production audit log and the durable ledger) both came from a path bound at import time.
`prospector/jsonl_atomic.py` takes its path as an ARGUMENT precisely so this file can be honest
about that, and the scheduler seams below are driven through `cfg.store_dir = tmp_path`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from prospector.jsonl_atomic import (
    TornAppendError,
    append_jsonl,
    iter_jsonl,
    read_jsonl,
    read_jsonl_with_stats,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cfg(tmp_path: Path) -> SimpleNamespace:
    """The smallest cfg the scheduler path helpers accept, rooted in tmp_path.

    `prospector.scheduler.paths.store_dir` RAISES rather than defaulting to a cwd-relative
    "store", so a test that forgot this would fail loudly instead of writing into the live
    store. Passing it explicitly is the contract that fence exists to enforce.
    """
    return SimpleNamespace(store_dir=tmp_path)


# ---------------------------------------------------------------------------
# (a) an append is either fully present or absent, never partial
# ---------------------------------------------------------------------------

def test_append_writes_one_complete_terminated_line(tmp_path):
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"n": 1, "msg": "hello"})
    append_jsonl(p, {"n": 2, "msg": "world"})

    raw = p.read_bytes()
    assert raw.endswith(b"\n"), "every committed record must carry its terminating newline"
    assert raw.count(b"\n") == 2
    assert [r["n"] for r in read_jsonl(p)] == [1, 2]


def test_append_creates_parent_and_leaves_no_temp_files(tmp_path):
    """No tmp+rename: the directory must never hold a sidecar copy of the log.

    A stray `*.tmp` would be the tell that an appender is doing read-modify-rename, which is
    the design this module exists to rule out (see `test_read_modify_rename_destroys_a_concurrent_append`).
    """
    p = tmp_path / "nested" / "deep" / "log.jsonl"
    append_jsonl(p, {"n": 1})
    assert [f.name for f in p.parent.iterdir()] == ["log.jsonl"]


def test_append_refuses_a_record_containing_a_newline(tmp_path):
    p = tmp_path / "log.jsonl"
    with pytest.raises(ValueError):
        append_jsonl(p, '{"a": 1}\n{"b": 2}')
    assert not p.exists()


def test_append_serialises_non_json_values_via_str(tmp_path):
    """Matches the `default=str` every replaced call site used; a stray object must not raise."""
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"path": Path("/x/y"), "n": 1})
    assert read_jsonl(p)[0]["path"] == "/x/y"


def test_short_write_raises_and_is_not_retried(tmp_path, monkeypatch):
    """A short write leaves ONE damaged record and refuses to retry the remainder.

    The retry is what must not happen: under O_APPEND a second write re-seeks to the CURRENT
    end of file, so a peer's complete line can land between the two fragments and turn one
    torn record into two corrupt ones. Asserted mechanically by counting os.write calls.
    """
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"n": 1})
    append_jsonl(p, {"n": 2})

    real_write = os.write
    calls = {"n": 0}

    def half_write(fd, data):
        if b"TORN-MARKER" in data:
            calls["n"] += 1
            return real_write(fd, data[: len(data) // 2])
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", half_write)
    with pytest.raises(TornAppendError):
        append_jsonl(p, {"n": 3, "marker": "TORN-MARKER", "pad": "x" * 200})
    monkeypatch.undo()

    assert calls["n"] == 1, "the remainder of a short write must NOT be retried"

    # Guarantee (a) from the reader's side: the two committed records are intact and complete,
    # and the half-written third is not visible as a record at all.
    rows, stats = read_jsonl_with_stats(p, warn=False)
    assert [r["n"] for r in rows] == [1, 2]
    assert stats.torn_tail_bytes > 0


def test_append_is_atomic_for_a_record_larger_than_pipe_buf(tmp_path):
    """A record far above PIPE_BUF still lands as exactly one contiguous line.

    PIPE_BUF is the pipe guarantee; for a regular file the kernel holds the inode lock across
    the whole O_APPEND write, which is why this module does not cap record size.
    """
    p = tmp_path / "log.jsonl"
    big = {"n": 1, "pad": "y" * 300_000}
    append_jsonl(p, big)
    append_jsonl(p, {"n": 2})
    rows = read_jsonl(p)
    assert [r["n"] for r in rows] == [1, 2]
    assert len(rows[0]["pad"]) == 300_000


# ---------------------------------------------------------------------------
# (b) the reader skips a torn trailing line and returns all intact prior lines
# ---------------------------------------------------------------------------

def test_reader_skips_torn_trailing_line_and_keeps_all_prior(tmp_path):
    p = tmp_path / "log.jsonl"
    for i in range(5):
        append_jsonl(p, {"n": i})
    with open(p, "ab") as fh:                       # a crash-truncated 6th append
        fh.write(b'{"n": 5, "partial": "abc')

    rows, stats = read_jsonl_with_stats(p, warn=False)
    assert [r["n"] for r in rows] == [0, 1, 2, 3, 4]
    assert stats.rows == 5
    assert stats.torn_tail_bytes == len(b'{"n": 5, "partial": "abc')
    assert stats.corrupt_lines == 0


def test_reader_skips_a_truncated_tail_that_is_still_valid_json(tmp_path):
    """The discriminator against the old `json.loads`-per-line readers.

    `{"n": 9}` is a legal JSON prefix of `{"n": 9, "dossiers": 4}`. A reader that decides by
    parsing would hand back a tick that was never committed — with the wrong fields, silently.
    The rule here is positional, not syntactic: no terminating newline, no record.
    """
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"n": 1, "dossiers": 3})
    with open(p, "ab") as fh:
        fh.write(b'{"n": 9}')                        # valid JSON, but unterminated

    rows, stats = read_jsonl_with_stats(p, warn=False)
    assert [r["n"] for r in rows] == [1]
    assert stats.torn_tail_bytes == 8
    assert json.loads('{"n": 9}') == {"n": 9}, "sanity: the skipped tail really did parse"


def test_reader_skips_a_corrupt_mid_file_line_and_keeps_its_neighbours(tmp_path):
    """A torn fragment costs ONE record; the healing appender stops it costing any more.

    Without the heal, an unterminated fragment splices the next record onto itself and every
    later append inherits the damage — one short write would silently destroy the rest of the
    file. `heal=False` below is the control that shows exactly that.
    """
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"n": 0})
    with open(p, "ab") as fh:
        fh.write(b'{"n": 1, "tr\x00nk')               # torn fragment, no newline
    append_jsonl(p, {"n": 2})                        # heals: writes b"\n" + record
    append_jsonl(p, {"n": 3})

    rows, stats = read_jsonl_with_stats(p, warn=False)
    assert [r["n"] for r in rows] == [0, 2, 3], "only the torn record is lost"
    assert stats.corrupt_lines == 1
    assert stats.first_corrupt_lineno == 2
    assert stats.torn_tail_bytes == 0


def test_without_healing_a_torn_fragment_swallows_the_next_record(tmp_path):
    """The control for the test above — and the reason `heal` defaults to True."""
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"n": 0})
    with open(p, "ab") as fh:
        fh.write(b'{"n": 1, "trunk')
    append_jsonl(p, {"n": 2}, heal=False)
    append_jsonl(p, {"n": 3}, heal=False)

    rows, stats = read_jsonl_with_stats(p, warn=False)
    assert [r["n"] for r in rows] == [0, 3], "record 2 was spliced onto the fragment and lost"
    assert stats.corrupt_lines == 1


def test_reader_handles_missing_empty_and_blank_line_files(tmp_path):
    assert read_jsonl(tmp_path / "nope.jsonl") == []
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    assert read_jsonl(empty) == []
    blanks = tmp_path / "blanks.jsonl"
    blanks.write_bytes(b'\n\n{"n": 1}\n\n')
    rows, stats = read_jsonl_with_stats(blanks, warn=False)
    assert rows == [{"n": 1}]
    assert stats.corrupt_lines == 0


def test_reader_tail_keeps_the_last_n_intact_records(tmp_path):
    p = tmp_path / "log.jsonl"
    for i in range(20):
        append_jsonl(p, {"n": i})
    with open(p, "ab") as fh:
        fh.write(b'{"n": 20')
    assert [r["n"] for r in read_jsonl(p, tail=3, warn=False)] == [17, 18, 19]
    assert read_jsonl(p, tail=0, warn=False) == []


def test_reader_streams_without_loading_the_file(tmp_path):
    """`iter_jsonl` must yield before the file is exhausted — these trails reach 350k lines."""
    p = tmp_path / "log.jsonl"
    for i in range(100):
        append_jsonl(p, {"n": i}, fsync=False)
    it = iter_jsonl(p, warn=False)
    assert next(it) == {"n": 0}
    it.close()


# ---------------------------------------------------------------------------
# (c) concurrent appenders do not lose lines
# ---------------------------------------------------------------------------

_WORKER = r"""
import sys
sys.path.insert(0, {root!r})
from prospector.jsonl_atomic import append_jsonl
path, tag, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
for i in range(n):
    append_jsonl(path, {{"tag": tag, "i": i, "pad": "z" * 700}})
"""


def test_concurrent_process_appenders_lose_no_lines(tmp_path):
    """Real OS processes, real O_APPEND, real interleaving — nothing is lost or split.

    Separate processes (not threads) because that is the production shape: `ticks.jsonl` is
    written by the daemon AND by an out-of-repo driver, and `audit/<day>.jsonl` by the daemon,
    backfills and manual CLI runs at once. Records are padded past a page so any interleaving
    defect shows up as a torn line rather than being hidden by a small write.
    """
    p = tmp_path / "log.jsonl"
    script = _WORKER.format(root=str(REPO_ROOT))
    procs = [
        subprocess.Popen([sys.executable, "-c", script, str(p), f"p{k}", "150"])
        for k in range(4)
    ]
    for proc in procs:
        assert proc.wait(timeout=180) == 0

    rows, stats = read_jsonl_with_stats(p, warn=False)
    assert stats.corrupt_lines == 0, "an interleaved append would show up here"
    assert stats.torn_tail_bytes == 0
    assert len(rows) == 600
    assert p.read_bytes().count(b"\n") == 600
    for k in range(4):
        assert sorted(r["i"] for r in rows if r["tag"] == f"p{k}") == list(range(150))


def test_read_modify_rename_destroys_a_concurrent_append(tmp_path):
    """The receipt for rejecting tmp+rename. Deterministic, not a race.

    The naive appender reads the file, adds its line, and renames the copy over the original.
    Anything a peer appended in that window was never in the copy, so the rename deletes it.
    The O_APPEND design under the identical interleaving keeps all three records.
    """
    naive = tmp_path / "naive.jsonl"
    append_jsonl(naive, {"n": 1})
    snapshot = naive.read_bytes()                    # naive appender reads...
    append_jsonl(naive, {"n": 2})                    # ...peer process appends here...
    tmp = tmp_path / "naive.jsonl.tmp"               # ...naive appender renames its copy over
    tmp.write_bytes(snapshot + b'{"n": 3}\n')
    os.replace(tmp, naive)
    assert [r["n"] for r in read_jsonl(naive)] == [1, 3], "row 2 was destroyed by the rename"

    ok = tmp_path / "ok.jsonl"
    for n in (1, 2, 3):
        append_jsonl(ok, {"n": n})
    assert [r["n"] for r in read_jsonl(ok)] == [1, 2, 3]


# ---------------------------------------------------------------------------
# The scheduler seams, driven through cfg.store_dir = tmp_path
# ---------------------------------------------------------------------------

def test_append_tick_is_atomic_and_readers_survive_a_torn_tail(tmp_path):
    from prospector.scheduler import run_scheduled as rs

    cfg = _cfg(tmp_path)
    rs._append_tick(cfg, {"allowed": True, "result": {"dossiers": 2, "passes": 1}})
    for _ in range(3):
        rs._append_tick(cfg, {"allowed": True, "result": {"dossiers": 0, "passes": 0}})

    ticks = tmp_path / "scheduler" / "ticks.jsonl"
    assert ticks.read_bytes().endswith(b"\n")
    assert len(read_jsonl(ticks)) == 4

    with open(ticks, "ab") as fh:                    # the daemon, mid-append, during our read
        fh.write(b'{"allowed": true, "result": {"dossiers"')

    agg = rs._aggregate_ticks(cfg)
    assert agg["ticks"] == 4
    assert agg["candidates"] == 2
    assert agg["passes"] == 1
    # ticks[-1] is treated as the just-appended current tick and excluded; ticks[1] and [2] are
    # barren; ticks[0] produced a dossier and breaks the streak.
    assert rs._trailing_barren_count(cfg) == 2


def test_emit_alert_appends_atomically_under_tmp_path(tmp_path, monkeypatch):
    from prospector.scheduler import alerts as al

    for sink in ("_desktop_notify", "_webhook_post", "_telegram_push"):
        monkeypatch.setattr(al, sink, lambda *a, **k: None)

    cfg = _cfg(tmp_path)
    al.emit_alert(cfg, severity=al.CRITICAL, key="moat_blind", title="T", message="M")
    al.emit_alert(cfg, severity=al.WARNING, key="barren_streak", title="T2", message="M2")

    log = tmp_path / "scheduler" / "alerts.jsonl"
    assert log.read_bytes().endswith(b"\n")
    assert [r["key"] for r in read_jsonl(log)] == ["moat_blind", "barren_streak"]

    with open(log, "ab") as fh:                      # torn append from a concurrent daemon
        fh.write(b'{"ts": "2026-08-07T00:00:00+00:00", "key": "zero_y')
    assert al.resolve_alert(cfg, key="moat_blind", reason="recovered") is True

    rows, stats = read_jsonl_with_stats(log, warn=False)
    assert stats.corrupt_lines == 1, "only the torn fragment is lost"
    assert rows[-1]["key"] == "moat_blind", "the resolution must not be spliced onto the fragment"
    assert rows[-1]["title"].startswith("RESOLVED")


def test_scheduler_paths_still_refuse_a_cfg_without_store_dir():
    """The fence that keeps this whole file out of the production store."""
    from prospector.scheduler import paths

    with pytest.raises(ValueError, match="refusing to guess"):
        paths.store_dir(SimpleNamespace())
