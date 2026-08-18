"""A benched brain, and its recovery, have to survive the log buffer.

WHY THIS FILE EXISTS. On 2026-08-18 the founder asked, twice, "when MiniMax comes back up does
it self repair?". The engine does repair itself — `operator.py` calls `health.clear()` on the
first successful call — but proving it took an SSH session and an inference from a MISSING key,
because `clear()` deletes the mark and `fly logs --no-tail` holds about a hundred lines, roughly
four minutes on a generating daemon. A system that heals silently is indistinguishable from one
that never broke.

These tests pin the append-only trail that makes the healing visible: benched, half-open probe,
recovered — with the numbers each transition actually had.
"""
from __future__ import annotations

import json

import pytest

from prospector.health import (
    _EVENTS_KEEP,
    DEFAULT_EXHAUSTION_S,
    ProviderHealth,
    recent_events,
)


@pytest.fixture()
def health(tmp_path):
    clock = {"t": 1_000_000.0}
    h = ProviderHealth(path=tmp_path / "provider_health.json", clock=lambda: clock["t"])
    return h, clock, tmp_path / "provider_events.jsonl"


def test_a_bench_writes_a_row_that_says_why_and_for_how_long(health):
    h, _clock, events = health
    h.mark_exhausted("minimax", DEFAULT_EXHAUSTION_S, error="Token Plan usage limit reached (2056)")

    rows = [json.loads(ln) for ln in events.read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "benched"
    assert row["provider"] == "minimax"
    assert row["chain"] == "moat"
    assert row["strikes"] == 1
    assert row["dead_for_s"] == 3600.0
    assert row["probe_in_s"] == 120.0, "the first re-probe is a measurement, not the window"
    assert "2056" in row["error"], (
        "a bench row with no reason is the defect this replaces: nine marks in 70 minutes on "
        "2026-08-06 and not one of them said why"
    )


def test_recovery_is_recorded_and_is_the_answer_to_did_it_self_repair(health):
    h, clock, events = health
    h.mark_exhausted("minimax", DEFAULT_EXHAUSTION_S, error="429")
    clock["t"] += 38 * 60          # the real gap measured on 2026-08-18
    h.clear("minimax")

    kinds = [json.loads(ln)["kind"] for ln in events.read_text().splitlines()]
    assert kinds == ["benched", "recovered"]

    rec = json.loads(events.read_text().splitlines()[-1])
    assert rec["down_for_s"] == pytest.approx(2280.0)
    assert rec["strikes"] == 1
    # And the mark itself is gone, which is exactly why the row has to exist.
    assert h.dead_until("minimax") is None


def test_clearing_a_brain_that_was_never_benched_records_nothing(health):
    h, _clock, events = health
    h.clear("minimax")
    assert not events.exists(), (
        "every successful call clears; if that wrote a row the log would be one line per call"
    )


def test_the_half_open_probe_is_its_own_row(health):
    h, clock, events = health
    h.mark_exhausted("claude_cli", DEFAULT_EXHAUSTION_S, error="spend limit")
    clock["t"] += 121              # past the first probe gap
    assert h.is_dead("claude_cli") is False, "the probe slot was claimed, so this call goes out"

    rows = [json.loads(ln) for ln in events.read_text().splitlines()]
    assert [r["kind"] for r in rows] == ["benched", "probe"]
    assert rows[-1]["strikes"] == 1


def test_the_noncritical_chain_is_labelled_not_merged(tmp_path):
    """One feed, two chains. A non-critical bench and a moat bench have different consequences
    and read identically in the log today."""
    events = tmp_path / "provider_events.jsonl"
    ProviderHealth(path=tmp_path / "provider_health.json").mark_exhausted("minimax", 60)
    ProviderHealth(path=tmp_path / "provider_health_noncritical.json").mark_exhausted("minimax", 60)

    chains = [json.loads(ln)["chain"] for ln in events.read_text().splitlines()]
    assert chains == ["moat", "noncritical"]


def test_reading_is_newest_first_and_survives_a_torn_line(health):
    h, clock, events = health
    for i in range(3):
        h.mark_exhausted("minimax", 60 + i, error=f"call {i}")
        clock["t"] += 1
    with open(events, "a", encoding="utf-8") as fh:
        fh.write('{"kind": "benched", "provider": "trunc\n')      # a half-written append

    rows = recent_events(10, path=events)
    assert [r["error"] for r in rows] == ["call 2", "call 1", "call 0"], (
        "newest first, and a torn line is skipped rather than raised on — this is what the "
        "console renders when something has already gone wrong"
    )
    assert rows[0]["ts_iso"].endswith("Z")
    assert recent_events(2, path=events) == rows[:2]


def test_a_missing_log_reads_as_no_history_not_as_an_error(tmp_path):
    assert recent_events(10, path=tmp_path / "nope.jsonl") == []


def test_the_log_is_bounded(health):
    h, clock, events = health
    for _ in range(_EVENTS_KEEP * 2 + 5):
        h.mark_exhausted("minimax", 60)
        clock["t"] += 1
    lines = events.read_text().splitlines()
    assert _EVENTS_KEEP <= len(lines) <= _EVENTS_KEEP * 2, (
        f"the trail must not grow without limit; it holds {len(lines)} lines"
    )


def test_a_write_failure_never_breaks_the_bench_it_is_recording(tmp_path, caplog):
    """The audit trail runs on the failure path. A read-only volume must cost a log line, not
    the mark itself."""
    h = ProviderHealth(path=tmp_path / "provider_health.json",
                       events_path=tmp_path / "no-such-dir" / "x" / "e.jsonl")
    (tmp_path / "no-such-dir").write_text("this is a file, so mkdir of a child fails")

    h.mark_exhausted("minimax", 60, error="boom")

    assert h.dead_until("minimax") is not None, "the bench itself must still be recorded"
    assert any("Could not record provider event" in r.message for r in caplog.records), (
        "an audit trail that stopped writing must not look like a quiet week"
    )
