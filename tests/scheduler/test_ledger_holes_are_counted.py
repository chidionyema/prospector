"""A torn ledger line is money that was spent and never counted, so it must not be silent.

Until 2026-08-21 `SchedulerGuard._scan` dropped an unparseable line with a bare `continue` and
its docstring called that robustness. It was, while the only unparseable line was a half-written
last append. It stopped being true on 2026-08-18 08:47:09, when the engine began taking SIGKILL
five seconds into shutdown: `flush()`-only writes died in the page cache, the inode kept the
larger size, and the filesystem returned NUL bytes for the blocks that were never written.
Measured that day on the R2 snapshot of the live ledger: 1,479,555 lines, 50 NUL runs, 89,366 NUL
bytes, the first one after 2026-08-18 08:47:09.

Every one of those runs may have eaten a `{"event": "spend"}` row. The guard therefore reported a
spend LOWER than the truth, and `daily_cap_usd` had room in it that did not exist. Counting does
not repair the sum -- the bytes are gone -- it stops the loss being invisible to whoever reads the
cap. `prospector/telemetry.py` (DurableFileHandler) is what stops new holes appearing.
"""
from __future__ import annotations

import json
from pathlib import Path

from prospector.scheduler.guard import SchedulerGuard

DAY = "2026-06-20"


def _spend(amount: float, ts: str = f"{DAY} 09:00:00") -> bytes:
    return json.dumps({"event": "spend", "amount_usd": amount, "timestamp": ts}).encode() + b"\n"


def _torn() -> bytes:
    """What the filesystem actually hands back: a row that starts and is then NUL to the newline.

    Shaped from the real thing. The first bad line in the live ledger was 4180 bytes of which
    3996 were NUL, so the row is truncated mid-JSON rather than replaced wholesale.
    """
    head = b'{"event": "spend", "amount_usd": 7.5, "timesta'
    return head + b"\x00" * 200 + b"\n"


def _write(store, payload: bytes) -> Path:
    p = Path(store) / "prospector.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return p


def test_a_torn_line_is_counted_instead_of_silently_dropped(tmp_path):
    _write(tmp_path, _spend(2.0) + _torn() + _spend(3.0, f"{DAY} 10:00:00"))
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert d.today_ledger_holes == 1, "the hole the SIGKILL left must reach whoever reads the cap"
    assert d.today_spend_usd == 5.0, "counting a hole must not invent money it cannot recover"


def test_a_clean_ledger_reports_no_holes(tmp_path):
    """The counter has to be able to say zero, or nobody will believe it when it says one."""
    _write(tmp_path, _spend(2.0) + _spend(3.0, f"{DAY} 10:00:00"))
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert d.today_ledger_holes == 0
    assert d.today_spend_usd == 5.0


def test_the_count_survives_the_incremental_scan_that_moves_past_the_hole(tmp_path):
    """The scan resumes from a byte offset, so a hole is READ exactly once. If the count lived
    only in the pass that saw it, the next tick would report a clean ledger over a holed one --
    and the next tick is the one the operator is looking at."""
    p = _write(tmp_path, _spend(2.0) + _torn())
    g1 = SchedulerGuard(tmp_path, 20.0, today=DAY)
    assert g1.evaluate().today_ledger_holes == 1
    with p.open("ab") as f:
        f.write(_spend(1.0, f"{DAY} 11:00:00"))
    d2 = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert d2.today_spend_usd == 3.0, "the appended row must still be counted"
    assert d2.today_ledger_holes == 1, "the hole is still in the file and must still be reported"


def test_many_holes_in_one_pass_all_count(tmp_path):
    _write(tmp_path, _spend(1.0) + _torn() + _torn() + _torn() + _spend(1.0, f"{DAY} 12:00:00"))
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert d.today_ledger_holes == 3


def test_a_checkpoint_written_before_this_change_keeps_its_offset(tmp_path):
    """The cache format gained `holes` without a version bump, on purpose. Bumping it would have
    rejected every checkpoint live in production and forced ONE full re-scan -- 71 s at 158 MB
    when this cache was written, against `prospector-run.sh`'s 110 s timeout, on a ledger that is
    456 MB today. A re-scan that times out is how the guard probe died last time, so a cache with
    no `holes` key must load and keep its offset."""
    p = _write(tmp_path, _spend(2.0))
    g = SchedulerGuard(tmp_path, 20.0, today=DAY)
    g.evaluate()
    cache = g.scan_cache_path
    raw = json.loads(cache.read_text())
    raw.pop("holes", None)                       # exactly what a pre-2026-08-21 cache looks like
    assert raw["offset"] > 0
    cache.write_text(json.dumps(raw))
    offset, newest, days, holes = g._load_scan_cache(p, g._head_sig(p))
    assert offset == raw["offset"], "a legacy checkpoint must not be thrown away"
    assert holes == {}


def test_a_malformed_holes_map_costs_the_count_and_not_the_offset(tmp_path):
    """Same trade in the other direction: the count is a warning, the offset is a 456 MB re-scan.
    A holes map that cannot be read must never be the reason the whole checkpoint is discarded."""
    p = _write(tmp_path, _spend(2.0))
    g = SchedulerGuard(tmp_path, 20.0, today=DAY)
    g.evaluate()
    raw = json.loads(g.scan_cache_path.read_text())
    raw["holes"] = {DAY: "not a number", "2026-06-19": 4}
    g.scan_cache_path.write_text(json.dumps(raw))
    offset, newest, days, holes = g._load_scan_cache(p, g._head_sig(p))
    assert offset == raw["offset"]
    assert holes == {"2026-06-19": 4}, "the readable entries survive, the unreadable one is dropped"


def test_a_hole_on_another_day_does_not_inflate_todays_count(tmp_path):
    """A torn line carries no readable timestamp, so it is attributed to the newest day the ledger
    has shown. A hole that follows yesterday's rows belongs to yesterday, not to the cap in force
    now."""
    _write(tmp_path, _spend(5.0, "2026-06-19 09:00:00") + _torn() + _spend(1.0))
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert d.today_spend_usd == 1.0
    assert d.today_ledger_holes == 0, "yesterday's hole is not today's missing money"
