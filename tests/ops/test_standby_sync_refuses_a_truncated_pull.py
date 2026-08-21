"""The standby mirror must never be replaced by a fragment of itself.

`~/.prospector/standby/` is the disaster-recovery copy of the money files for a business whose
production engine runs in one Fly app. `cmd_sync` pulls them with `fly ssh sftp get` under a
600s timeout, and the only completeness test it had was `size > 0`.

`size > 0` is a PROXY for "the transfer finished", and it grades nothing: a transfer cut off at
any point is still non-empty, so it passed, and the atomic `tmp.replace(dest)` on the next line
then destroyed the last good copy.

Measured 2026-08-20 from `~/.prospector/logs/com.prospector-control.standby-sync.log`. The
mirror tracked the source exactly for hours -- 407,230,958 bytes at 18:50 rising to 407,981,598
at 20:26. Then three consecutive pulls were cut by the timeout and promoted anyway:

    20:42   sync: prospector.jsonl  17,170,432 bytes
    21:10   sync: prospector.jsonl  10,027,008 bytes
    21:38   sync: prospector.jsonl  25,296,896 bytes

Each line reads as a success. The standby ledger ended at 6.2% of the source, ending mid-record
in June, and nothing anywhere said so.

TWO CONDITIONS, TWO TREATMENTS, and conflating them is its own defect. A SHRINK is refused: the
ledger is append-only, so smaller means cut. A RAGGED TAIL is trimmed, never refused: the source
is being appended to while it is read, so a transfer that finished perfectly normally can still
end mid-record, and refusing on that would reject good copies intermittently. That distinction
came from peer session wt-storeroot-1e, against the first version of this file, which refused on
a bad last line.

Each test below fails if its guard is removed.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _failover_module(standby: Path):
    """Import the script by path: it is a script, not a package module.

    STANDBY is a module constant resolved at import time, and `_shrink_is_waived` reads its
    one-shot token out of it, so each test gets a module bound to its own tmp directory.
    """
    spec = importlib.util.spec_from_file_location(
        "engine_failover_sync_under_test", REPO / "scripts" / "engine_failover.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.STANDBY = standby
    mod.event = lambda *a, **k: None        # the real one writes to the control directory
    return mod


def _ledger(path: Path, rows: int, *, ragged: bool = False) -> Path:
    body = "".join(
        json.dumps({"timestamp": f"2026-08-20 0{i % 10}:00:00,000", "cost_usd": 0.01}) + "\n"
        for i in range(rows)
    )
    if ragged:
        body += '{"timestamp": "2026-08-20 09:00:00,000", "cost_'   # writer caught mid-record
    path.write_text(body, encoding="utf-8")
    return path


def _sqlite(path: Path, rows: int) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE listing (id INTEGER PRIMARY KEY, body TEXT)")
    con.executemany("INSERT INTO listing (body) VALUES (?)",
                    [("x" * 200,) for _ in range(rows)])
    con.commit()
    con.close()
    return path


# --------------------------------------------------------------------- shrink: refuse

def test_a_smaller_pull_never_replaces_the_copy_already_held(tmp_path):
    """The exact shape of the incident: 25 MB arriving on top of 408 MB."""
    ef = _failover_module(tmp_path)
    dest = _ledger(tmp_path / "prospector.jsonl", 400)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 20)

    reason = ef._rejects_arrival(tmp, dest, "prospector.jsonl", None)

    assert reason, "a pull smaller than the standby copy was accepted"
    assert "smaller" in reason
    assert "ALLOW_SHRINK" in reason, "the refusal must name its own override"


def test_the_db_is_covered_by_the_same_rule(tmp_path):
    """prospector.db is a money file too, and it is not line-oriented.

    The tail trim cannot apply to it, so the shrink rule is what covers it. A truncated sqlite
    pull is smaller than the copy held, which is exactly what that rule refuses.
    """
    ef = _failover_module(tmp_path)
    dest = _sqlite(tmp_path / "prospector.db", rows=4000)
    tmp = _sqlite(tmp_path / "prospector.db.partial", rows=10)
    assert tmp.stat().st_size < dest.stat().st_size

    reason = ef._rejects_arrival(tmp, dest, "prospector.db", None)

    assert reason and "smaller" in reason


def test_a_complete_larger_pull_is_accepted(tmp_path):
    """The guard must not wedge the rail it protects."""
    ef = _failover_module(tmp_path)
    dest = _ledger(tmp_path / "prospector.jsonl", 10)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 400)

    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", None) == ""


def test_the_first_pull_is_accepted_when_nothing_is_held_yet(tmp_path):
    """Bootstrap: on an empty standby directory anything complete beats nothing."""
    ef = _failover_module(tmp_path)
    dest = tmp_path / "prospector.jsonl"
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 5)

    assert not dest.exists()
    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", None) == ""


# --------------------------------------------------------------------- ragged tail: trim

def test_a_ragged_tail_is_trimmed_and_the_copy_is_kept(tmp_path):
    """A GOOD transfer of a live append-only file can end mid-record.

    Refusing on that would reject a complete-enough copy, return non-zero and page somebody
    about a file that was fine. The partial record carries nothing, so it is cut.
    """
    ef = _failover_module(tmp_path)
    dest = _ledger(tmp_path / "prospector.jsonl", 10)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 400, ragged=True)
    before = tmp.stat().st_size

    trimmed = ef._trim_partial_tail(tmp)

    assert trimmed > 0, "the incomplete trailing record was left on the file"
    assert tmp.stat().st_size == before - trimmed
    assert tmp.read_text().endswith("\n")
    json.loads(tmp.read_text().splitlines()[-1])          # the new last line is a whole record
    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", None) == "", "a trimmed good pull was refused"


def test_a_file_already_ending_on_a_record_is_left_alone(tmp_path):
    ef = _failover_module(tmp_path)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 50)
    before = tmp.read_bytes()

    assert ef._trim_partial_tail(tmp) == 0
    assert tmp.read_bytes() == before


def test_a_last_record_with_no_closing_newline_is_not_trimmed(tmp_path):
    """The final record can be complete and simply unterminated. That is not a ragged tail."""
    ef = _failover_module(tmp_path)
    tmp = tmp_path / "prospector.jsonl.partial"
    tmp.write_text('{"a": 1}\n{"a": 2}', encoding="utf-8")

    assert ef._trim_partial_tail(tmp) == 0
    assert tmp.read_text() == '{"a": 1}\n{"a": 2}'


def test_the_trim_reads_only_the_tail_of_a_large_file(tmp_path):
    """This runs every 15 minutes against a file in the hundreds of megabytes.

    Reading the whole file would make the guard itself the cost. The check seeks, so a file far
    larger than the read window must still be trimmed correctly.
    """
    ef = _failover_module(tmp_path)
    big = _ledger(tmp_path / "big.jsonl", 40_000, ragged=True)
    assert big.stat().st_size > ef._TAIL_WINDOW, "only meaningful past the seek window"

    assert ef._trim_partial_tail(big) > 0
    assert big.read_text().endswith("\n")


# --------------------------------------------------------------------- the override

def test_the_shrink_override_is_one_shot_and_deletes_itself(tmp_path):
    """An env var set once in a plist stays set forever, silently, with the guard gone.

    Same shape as an expired dead mark that nobody sees again. So the switch is a file that the
    sync consumes: it waves through exactly one shrink and then the guard is back.
    """
    ef = _failover_module(tmp_path)
    dest = _ledger(tmp_path / "prospector.jsonl", 400)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 20)
    token = tmp_path / "ALLOW_SHRINK"
    token.write_text("")

    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", None) == "", "the override was not honoured"
    assert not token.exists(), "the override survived being used; the guard is now off for good"

    second = _ledger(tmp_path / "second.partial", 20)
    assert ef._rejects_arrival(second, dest, "prospector.jsonl", None), "the guard did not come back"


# ------------------------------------------------------- the source size: the real check

def test_a_pull_shorter_than_the_source_is_refused_even_when_it_beats_the_local_copy(tmp_path):
    """The hole in grading an arrival against local history, found by peer wt-storeroot-4a.

    A fragment already on disk becomes the floor. Measured 2026-08-20 that floor was 25 MB
    against a 408 MB source, so a pull cut at half the file is comfortably larger than the floor,
    lands on a newline, and would be enshrined as the next floor. Only the source size can tell
    a finished transfer from a stopped one.
    """
    ef = _failover_module(tmp_path)
    dest = _ledger(tmp_path / "prospector.jsonl", 20)            # the fragment already held
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 200)    # bigger than it, still cut
    source = _ledger(tmp_path / "source.jsonl", 400).stat().st_size

    reason = ef._rejects_arrival(tmp, dest, "prospector.jsonl", source)

    assert reason, "a pull that stopped short of the source was accepted"
    assert "stopped short" in reason
    assert not (tmp_path / "ALLOW_SHRINK").exists()


def test_a_pull_that_reached_the_end_of_the_source_is_accepted(tmp_path):
    ef = _failover_module(tmp_path)
    dest = _ledger(tmp_path / "prospector.jsonl", 20)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 400)

    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", tmp.stat().st_size) == ""


def test_a_pull_larger_than_the_measured_source_is_accepted(tmp_path):
    """The file is appended to between the size probe and the end of the transfer.

    Requiring equality would refuse a healthy copy of a live file every time the engine wrote a
    row mid-pull, which on this ledger is most pulls.
    """
    ef = _failover_module(tmp_path)
    dest = _ledger(tmp_path / "prospector.jsonl", 20)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 400)
    stale_probe = _ledger(tmp_path / "source.jsonl", 390).stat().st_size

    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", stale_probe) == ""


def test_the_override_also_waives_a_short_pull_and_is_still_one_shot(tmp_path):
    ef = _failover_module(tmp_path)
    dest = _ledger(tmp_path / "prospector.jsonl", 20)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 200)
    source = _ledger(tmp_path / "source.jsonl", 400).stat().st_size
    (tmp_path / "ALLOW_SHRINK").write_text("")

    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", source) == ""
    assert not (tmp_path / "ALLOW_SHRINK").exists()
    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", source), "the guard did not come back"


def test_an_unreachable_source_probe_reports_none_rather_than_a_number(tmp_path):
    """A failed probe must never read as "the source is 0 bytes" or crash the sync."""
    ef = _failover_module(tmp_path)
    ef.sh = lambda *a, **k: (1, "", "could not connect")
    assert ef._source_size("prospector.jsonl") is None


def test_the_source_probe_reads_the_byte_count_out_of_wc(tmp_path):
    ef = _failover_module(tmp_path)
    ef.sh = lambda *a, **k: (0, "407981598\n", "")
    assert ef._source_size("prospector.jsonl") == 407981598


def test_a_probe_that_answers_with_no_number_is_not_treated_as_an_answer(tmp_path):
    ef = _failover_module(tmp_path)
    ef.sh = lambda *a, **k: (0, "Connecting to fdaa:...\n", "")
    assert ef._source_size("prospector.jsonl") is None


# ------------------------------------------------------- the database: size cannot answer it

def test_a_torn_database_is_refused_even_at_exactly_the_right_size(tmp_path):
    """`fly ssh sftp get` copies a database that is being written.

    A copy can finish, arrive at the right length, and still hold pages from two different states
    of the file. It opens fine and fails on the first read - during a failover, not during the
    sync. Only a scan catches it, which is why size is not the whole test for this file.
    """
    ef = _failover_module(tmp_path)
    dest = _sqlite(tmp_path / "prospector.db", rows=400)
    good = _sqlite(tmp_path / "good.db", rows=400)
    torn = tmp_path / "prospector.db.partial"
    body = bytearray(good.read_bytes())
    body[1024:4096] = b"\x00" * 3072          # a page from nowhere, same total length
    torn.write_bytes(bytes(body))
    assert torn.stat().st_size == good.stat().st_size

    reason = ef._rejects_arrival(torn, dest, "prospector.db", torn.stat().st_size)

    assert reason, "a torn database passed because its length was right"
    assert "integrity" in reason


def test_a_whole_database_passes_the_scan(tmp_path):
    ef = _failover_module(tmp_path)
    dest = _sqlite(tmp_path / "prospector.db", rows=100)
    tmp = _sqlite(tmp_path / "prospector.db.partial", rows=400)

    assert ef._rejects_arrival(tmp, dest, "prospector.db", tmp.stat().st_size) == ""


def test_the_ledger_is_not_put_through_the_sqlite_scan(tmp_path):
    """The integrity check is keyed on the name, so a jsonl must never reach it."""
    ef = _failover_module(tmp_path)
    ef._db_is_intact = lambda path: pytest.fail("the ledger was sent to the sqlite scan")
    dest = _ledger(tmp_path / "prospector.jsonl", 20)
    tmp = _ledger(tmp_path / "prospector.jsonl.partial", 400)

    assert ef._rejects_arrival(tmp, dest, "prospector.jsonl", tmp.stat().st_size) == ""
