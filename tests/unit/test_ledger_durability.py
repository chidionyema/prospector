"""The spend ledger must reach the disk, not just the page cache.

Measured 2026-08-21 on the R2 snapshot `ledger/prospector-2026-08-21.jsonl.gz`: 1,479,555
records, 50 of them runs of NUL bytes, 89,366 NUL bytes in all. Records 1 through 924,844 --
2026-06-15 to 2026-08-18 08:47 -- are clean. The engine moved to Fly on 2026-08-18. A plain
`logging.FileHandler` flushes to the kernel and never fsyncs, so a stopped VM takes the tail of
the file with it and the filesystem reads the extent back as zeros.

`prospector/scheduler/guard.py` re-derives the daily spend from this file, so the loss is money,
not history.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from prospector import telemetry


@pytest.fixture()
def ledger(tmp_path: Path) -> Path:
    d = tmp_path / "store"
    d.mkdir()
    return d / "prospector.jsonl"


def _record(msg: str = "a decision", **extra) -> logging.LogRecord:
    r = logging.LogRecord("prospector", logging.INFO, __file__, 1, msg, None, None)
    for k, v in extra.items():
        setattr(r, k, v)
    return r


def _money(usd: float = 0.01) -> logging.LogRecord:
    """The exact shape prospector/spend.py:28 emits."""
    return _record("Spend accumulated", event="spend", amount_usd=usd, total_usd=usd)


def test_a_record_is_fsynced_not_merely_flushed(ledger, monkeypatch):
    """The whole defect in one assertion: flush() was happening, fsync() was not."""
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

    h = telemetry.DurableFileHandler(str(ledger), encoding="utf-8", interval_ms=0)
    try:
        h.emit(_record())
    finally:
        h.close()
    assert synced, "the ledger handler wrote a record without ever calling fsync"


def test_the_fsync_is_coalesced_so_a_burst_does_not_pay_per_record(ledger, monkeypatch):
    """546 records landed in one second on 2026-08-18. That must not become 546 fsyncs."""
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

    h = telemetry.DurableFileHandler(str(ledger), encoding="utf-8", interval_ms=60_000)
    try:
        for _ in range(546):
            h.emit(_record())          # decision rows, not money rows
        during_burst = len(synced)
    finally:
        h.close()

    assert during_burst == 1, f"a 546-record burst cost {during_burst} fsyncs, not 1"
    assert len(synced) > during_burst, "close() must fsync whatever the time bound says"


def test_close_fsyncs_even_inside_the_coalescing_window(ledger, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

    h = telemetry.DurableFileHandler(str(ledger), encoding="utf-8", interval_ms=60_000)
    h.emit(_record())
    before = len(synced)
    h.close()
    assert len(synced) == before + 1


def test_an_fsync_that_fails_does_not_break_logging(ledger, monkeypatch):
    """A handler that raises turns one lost record into a lost run. It must swallow and continue."""
    def boom(fd):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(os, "fsync", boom)
    h = telemetry.DurableFileHandler(str(ledger), encoding="utf-8", interval_ms=0)
    try:
        h.emit(_record("first"))
        h.emit(_record("second"))
    finally:
        h.close()
    body = ledger.read_text()
    assert "first" in body and "second" in body


def test_a_typo_in_the_env_var_does_not_disable_durability(ledger, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LEDGER_FSYNC_MS", "two hundred")
    h = telemetry.DurableFileHandler(str(ledger), encoding="utf-8")
    try:
        assert h.interval_s == 0.2
    finally:
        h.close()


def test_the_env_var_can_ask_for_a_fsync_per_record(ledger, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LEDGER_FSYNC_MS", "0")
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    h = telemetry.DurableFileHandler(str(ledger), encoding="utf-8")
    try:
        h.emit(_record())
        h.emit(_record())
        assert len(synced) == 2
    finally:
        h.close()


def test_route_logs_to_file_installs_a_handler_that_fsyncs(ledger, monkeypatch):
    """THE CLASS, not the instance.

    The defect was not that fsync was missing from some function. It was that the money trail
    was wired to a handler which cannot fsync at all. This asserts on the wiring, so swapping
    `DurableFileHandler` back to `logging.FileHandler` fails here even if every test above is
    deleted with it.
    """
    monkeypatch.delenv("PROSPECTOR_JSON_LOG", raising=False)
    original = list(telemetry.logger.handlers)
    try:
        telemetry.route_logs_to_file(str(ledger))
        installed = [h for h in telemetry.logger.handlers
                     if isinstance(h, logging.FileHandler)]
        assert installed, "route_logs_to_file installed no file handler at all"
        for h in installed:
            assert hasattr(h, "_fsync"), (
                f"{type(h).__name__} writes the spend ledger and cannot fsync it"
            )
    finally:
        for h in list(telemetry.logger.handlers):
            telemetry.logger.removeHandler(h)
            h.close()
        for h in original:
            telemetry.logger.addHandler(h)


def test_a_money_row_is_fsynced_immediately_whatever_the_time_bound_says(ledger, monkeypatch):
    """The rows `daily_cap_usd` enforces must not sit in a coalescing window at all.

    Measured on the restored snapshot: rows carrying `event: "spend"` are 41,347 of 1,469,213
    (2.81%), median 1/s and a worst second of 44, so paying one fsync each is affordable in a
    way that paying it for all 1.47M rows is not.
    """
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

    h = telemetry.DurableFileHandler(str(ledger), encoding="utf-8", interval_ms=60_000)
    try:
        h.emit(_record())              # opens the window
        base = len(synced)
        for _ in range(5):
            h.emit(_money())
        assert len(synced) - base == 5, "a spend row waited for the coalescing window"
    finally:
        h.close()


def test_a_decision_row_does_not_buy_an_fsync_inside_the_window(ledger, monkeypatch):
    """The other half of the same rule: 97.19% of the ledger must not pay per row."""
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

    h = telemetry.DurableFileHandler(str(ledger), encoding="utf-8", interval_ms=60_000)
    try:
        h.emit(_record())
        base = len(synced)
        for _ in range(50):
            h.emit(_record())
        assert len(synced) == base
    finally:
        h.close()


def test_the_handler_and_the_guard_key_off_the_same_field(ledger):
    """THE CLASS. `guard.py:150` records that a wrong key on this trail returns a confident
    $0.00 and raises nothing. If the guard's predicate is ever edited, this fails rather than
    letting the two drift into silently fsyncing rows nobody counts."""
    guard_src = Path(telemetry.__file__).parent.joinpath("scheduler", "guard.py").read_text()
    needle = 'd.get("event") == "%s"' % telemetry.MONEY_EVENT
    assert needle in guard_src, (
        f"telemetry.MONEY_EVENT is {telemetry.MONEY_EVENT!r} but guard.py no longer matches on "
        f"{needle!r} -- the durability rule and the spend rule have drifted apart"
    )
