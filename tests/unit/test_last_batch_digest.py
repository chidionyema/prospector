"""The per-tick digest carries WHY the batch died, not just that it did.

THE GAP THIS CLOSES

`diagnose_batch()` has computed a full kill-gate histogram, the unverifiable rate and the
closest-to-passing kills after every batch since before the daemon existed, and
`persist_batch_diagnostics` has written both a JSONL row and a rendered text file every time.
Nothing read either. The digest pushed to the founder's phone said `d=11 pass=0` — the symptom
— and stopped there.

That matters most exactly when steering is being changed. A tech/AI focus is EXPECTED to lower
the pass rate before it raises it, so `pass=0` is not evidence for or against it. The top kill
gate moving off `moat_ungrounded` is.

WHAT IS PINNED, AND WHY EACH ONE

1. The gates are sorted by count. The digest shows the top three; unsorted, "top three" is
   whatever order a Counter happened to serialise in.
2. Unreadable is None, never 0. `kill_gates: {}` reads as "nothing was killed", which on a
   batch that killed everything is the opposite of the truth.
3. It never raises. The caller is the Telegram pusher; a status reader that throws takes the
   daemon's only outward signal down with it.
4. The kills segment sits ahead of spend/providers/backlog. The digest truncates from the TAIL
   at 600 chars, so segment order IS priority order.
5. A snapshot with no `last_batch` key still formats. The gateway and any older caller build
   these dicts by hand.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

from prospector.scheduler.status import (
    _read_last_batch,
    format_status_snapshot,
    status_snapshot,
)


def _cfg(tmp_path: Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(store_dir=str(tmp_path))


def _write_diag(tmp_path: Path, *rows: dict) -> None:
    sd = tmp_path / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    with (sd / "batch_diagnostics.jsonl").open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


_ROW = {
    "ts": "2026-08-09T22:10:00+00:00",
    "kill_gates": {"min_composite": 3, "moat_ungrounded": 7, "incumbency": 2},
    "unverifiable_pct": 41.2,
    "by_market": {"uk": {"vetted": 6}},
    "closest_kills": [[3.05, "A thing"], [2.9, "Another"], [2.1, "Third"], [1.0, "Fourth"]],
    "decisions": {"pass": 0, "kill": 5, "defer": 1},
}


# ---------------------------------------------------------------------------
# 1. Sorted, and the LAST row wins
# ---------------------------------------------------------------------------

def test_gates_come_back_sorted_by_count(tmp_path):
    _write_diag(tmp_path, _ROW)
    got = _read_last_batch(_cfg(tmp_path))
    assert list(got["kill_gates"]) == ["moat_ungrounded", "min_composite", "incumbency"]
    assert got["unverifiable_pct"] == 41.2
    assert got["market"] == "uk"
    assert len(got["closest"]) == 3, "the panel takes three; the reader must not hand over five"


def test_the_last_row_is_the_last_batch(tmp_path):
    _write_diag(tmp_path, {**_ROW, "kill_gates": {"legality": 9}}, _ROW)
    assert list(_read_last_batch(_cfg(tmp_path))["kill_gates"])[0] == "moat_ungrounded"


def test_blank_trailing_lines_do_not_blank_the_read(tmp_path):
    """An interrupted append leaves a newline; the reader must skip back, not report nothing."""
    _write_diag(tmp_path, _ROW)
    with (tmp_path / "scheduler" / "batch_diagnostics.jsonl").open("a") as fh:
        fh.write("\n\n")
    assert _read_last_batch(_cfg(tmp_path))["kill_gates"]


# ---------------------------------------------------------------------------
# 2 + 3. Unreadable is None, and nothing raises
# ---------------------------------------------------------------------------

def test_no_file_is_none_not_zero(tmp_path):
    got = _read_last_batch(_cfg(tmp_path))
    assert got["kill_gates"] is None, "an empty dict reads as 'nothing was killed'"
    assert got["unverifiable_pct"] is None and got["ts"] is None


def test_a_corrupt_last_row_degrades_to_none(tmp_path):
    _write_diag(tmp_path, _ROW)
    with (tmp_path / "scheduler" / "batch_diagnostics.jsonl").open("a") as fh:
        fh.write("{not json\n")
    got = _read_last_batch(_cfg(tmp_path))
    assert got["kill_gates"] is None


def test_a_row_that_is_a_list_does_not_raise(tmp_path):
    sd = tmp_path / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "batch_diagnostics.jsonl").write_text("[1,2,3]\n", encoding="utf-8")
    assert _read_last_batch(_cfg(tmp_path))["kill_gates"] is None


def test_the_reader_does_not_create_the_scheduler_dir(tmp_path):
    """`create=False`: a status READ that makes directories in the live store is a write."""
    _read_last_batch(_cfg(tmp_path))
    assert not (tmp_path / "scheduler").exists()


# ---------------------------------------------------------------------------
# The snapshot carries it, and the digest shows it
# ---------------------------------------------------------------------------

def test_snapshot_exposes_last_batch(tmp_path):
    _write_diag(tmp_path, _ROW)
    snap = status_snapshot(_cfg(tmp_path))
    assert snap["last_batch"]["kill_gates"]["moat_ungrounded"] == 7


def test_digest_names_the_top_gate_and_stays_under_the_cap(tmp_path):
    _write_diag(tmp_path, _ROW)
    msg = format_status_snapshot(status_snapshot(_cfg(tmp_path)))
    assert "moat_ungrounded=7" in msg
    assert "unverif=41.2%" in msg
    assert "[uk]" in msg
    assert len(msg) <= 600, f"digest too long: {len(msg)} chars"


def test_only_the_top_three_gates_reach_the_digest(tmp_path):
    _write_diag(tmp_path, {**_ROW, "kill_gates": {chr(97 + i) * 12: 10 - i for i in range(9)}})
    msg = format_status_snapshot(status_snapshot(_cfg(tmp_path)))
    kills = msg.split("kills ", 1)[1].split(" | ", 1)[0].split(" unverif=", 1)[0]
    assert kills.count("=") == 3, f"the digest is not bounded: {kills!r}"


# ---------------------------------------------------------------------------
# 4 + 5. Priority order, and older callers still format
# ---------------------------------------------------------------------------

def test_the_kills_segment_survives_truncation_and_spend_does_not(tmp_path):
    _write_diag(tmp_path, _ROW)
    snap = status_snapshot(_cfg(tmp_path))
    snap["alerts"] = {"active": [{"title": "x" * 900}], "active_count": 1}
    msg = format_status_snapshot(snap)
    assert len(msg) <= 600 and msg.endswith(" ...")
    assert "moat_ungrounded=7" in msg, "the diagnosis was truncated away; segment order is wrong"


def test_a_snapshot_without_last_batch_still_formats():
    msg = format_status_snapshot({"daemon": {}, "last_tick": None, "spend": {},
                                  "providers": {}, "alerts": {}, "backlog": {}})
    assert "kills —" in msg, "a missing breakdown must read as unknown, not as zero kills"


def test_an_empty_gate_map_reads_as_a_dash(tmp_path):
    _write_diag(tmp_path, {**_ROW, "kill_gates": {}, "unverifiable_pct": None, "by_market": {}})
    msg = format_status_snapshot(status_snapshot(_cfg(tmp_path)))
    assert "kills —" in msg and "unverif" not in msg
