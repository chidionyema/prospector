"""A day-file is an interleaving of runs, and it must say so.

WHY (measured 2026-07-31, and it cost a wrong verdict twice in one session)
--------------------------------------------------------------------------
`store/scheduler/audit/<day>.jsonl` is appended by whoever is running: the launchd daemon, a
backfill driver, and any manual `prospector vet` in a terminal, all at once. Rows carried no
process identity, so reading a day-file as though it described one run is an error the data
itself invites — and it is the error I made, twice, on 2026-07-31.

WHY `seq` AND NOT JUST `ts`
--------------------------
Because the clock on this machine has been wrong. `store/scheduler/audit/1970-01-01.jsonl` holds
13 rows of REAL work — `"event":"search","provider":"ddg","query":"startup sanity check"` with
genuine 91-second network timeouts — stamped 1970-01-01T00:02:23Z. The same window left 8,779
rows in `store/prospector.jsonl` and 110 rows in `store/scheduler/ticks.jsonl`, monotonic from
1970-01-01T00:02:30 to 1970-01-03T11:33:30, after which the log resumes at 2026-07-28T00:50.
Those rows are not fabricated and must not be deleted: they are a daemon that ran for ~60 hours
believing it was 1970. A per-process counter still orders them; a timestamp does not.

WHY THE DROP COUNTER
--------------------
`audit()` swallows every exception, so a sink that cannot write is indistinguishable from an
engine doing nothing. On 2026-08-01 the engine ruled 102 candidates (77 kill / 24 pass / 1 defer
in `store/prospector.db`) and wrote 23,236 ledger rows, while `2026-08-01.jsonl` was never
created at all. Whatever the cause, the log's silence about its own silence is why it can no
longer be reconstructed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from prospector import audit as audit_mod
from prospector.audit import audit, dropped_rows, run_id


@pytest.fixture()
def audit_dir(tmp_path, monkeypatch):
    d = tmp_path / "audit"
    monkeypatch.setattr(audit_mod, "_AUDIT_DIR", d)
    return d


def _rows(audit_dir: Path) -> list[dict]:
    files = sorted(audit_dir.glob("*.jsonl"))
    assert files, f"no audit file written under {audit_dir}"
    return [json.loads(l) for f in files for l in f.read_text().splitlines() if l.strip()]


def test_every_row_carries_the_identity_of_the_run_that_wrote_it(audit_dir):
    audit("search", provider="ddg", query="q", status="ok")
    row, = _rows(audit_dir)
    assert row["run_id"] == run_id()
    assert isinstance(row["pid"], int) and row["pid"] > 0
    assert row["seq"] >= 1


def test_seq_orders_a_run_even_when_the_timestamps_are_worthless(audit_dir):
    """The 1970 case: rows whose `ts` is meaningless must still be orderable."""
    for i in range(5):
        audit("search", provider="ddg", query=f"q{i}", status="ok")
    rows = _rows(audit_dir)
    seqs = [r["seq"] for r in rows]
    assert seqs == sorted(seqs) and len(set(seqs)) == 5, (
        "a strictly increasing per-process counter is the only ordering that survives a clock "
        "that reads 1970 — store/scheduler/audit/1970-01-01.jsonl is real"
    )


def test_a_caller_cannot_overwrite_the_identity_fields(audit_dir):
    """`**fields` comes last, so identity has to be written before it, not after."""
    audit("search", run_id="attacker", pid=1, seq=999, provider="ddg")
    row, = _rows(audit_dir)
    assert row["run_id"] == run_id(), "a row whose run_id came from its payload is worse than none"
    assert row["pid"] != 1
    assert row["seq"] != 999


def test_two_processes_writing_the_same_day_file_stay_separable(tmp_path):
    """The actual production shape: daemon + manual run appending concurrently.

    Real subprocesses, because `run_id` is minted at import — an in-process fake would share it
    and prove nothing.
    """
    d = tmp_path / "audit"
    script = textwrap.dedent("""
        import os, sys
        os.environ["PROSPECTOR_AUDIT_DIR"] = sys.argv[1]
        from prospector.audit import audit
        for i in range(4):
            audit("search", provider="ddg", query=f"proc-{sys.argv[2]}-{i}", status="ok")
    """)
    for tag in ("a", "b"):
        r = subprocess.run([sys.executable, "-c", script, str(d), tag],
                           capture_output=True, text=True, cwd=Path(__file__).parents[2])
        assert r.returncode == 0, r.stderr

    rows = _rows(d)
    assert len(rows) == 8
    by_run: dict[str, list] = {}
    for r in rows:
        by_run.setdefault(r["run_id"], []).append(r)
    assert len(by_run) == 2, (
        "two runs collapsed into one identity; grouping a day-file by run is the whole point"
    )
    for run_rows in by_run.values():
        assert [r["seq"] for r in run_rows] == [1, 2, 3, 4]
        assert len({r["query"].split("-")[1] for r in run_rows}) == 1, (
            "rows attributed to a run must all come from that run"
        )


# ── the sink must not fail silently ─────────────────────────────────────────

def test_a_failing_sink_is_counted_and_named_instead_of_swallowed(tmp_path, monkeypatch, caplog):
    """Reproduce the 2026-08-01 shape: writes impossible, engine unaffected, and NOT silent."""
    monkeypatch.setattr(audit_mod, "_AUDIT_DIR", tmp_path / "nope")
    monkeypatch.setattr(audit_mod, "_dropped", 0)
    monkeypatch.setattr(audit_mod, "_drop_reason", "")

    def boom(*_a, **_k):
        raise OSError("Read-only file system")

    monkeypatch.setattr(Path, "mkdir", boom)

    with caplog.at_level("ERROR"):
        for _ in range(3):
            audit("search", provider="ddg", query="q", status="ok")  # must not raise

    n, reason = dropped_rows()
    assert n == 3, "silence about silence is why 2026-08-01 cannot be reconstructed"
    assert "Read-only file system" in reason
    assert sum("AUDIT SINK FAILING" in r.message for r in caplog.records) == 1, (
        "once, not per row — a broken disk must not become a log flood"
    )


def test_a_failing_sink_still_never_raises_into_the_pipeline(tmp_path, monkeypatch):
    """The original contract stands: observability cannot kill a grounded run mid-verdict."""
    monkeypatch.setattr(audit_mod, "_AUDIT_DIR", tmp_path / "nope")

    def boom(*_a, **_k):
        raise RuntimeError("anything at all")

    monkeypatch.setattr(Path, "mkdir", boom)
    audit("verify_search", check="pain_reality", candidate_id="abc")  # no raise = pass
