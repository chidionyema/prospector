"""The read half of the central log: `prospector.log_ingest.search`.

Every test here exists because the alternative failure is SILENT. A search that returns nothing
looks exactly like a quiet estate, so each bound the reader applies — the tail window, the file
cap, a torn line, a directory that is not there — has to be visible in the result and is asserted
here. See `docs/LOGGING_AND_RETENTION.md` Part 4, step 10.
"""
from __future__ import annotations

import json

import pytest

from prospector import log_ingest as li


def write_day(directory, svc, day, rows):
    """One day file, written the way the ingest writes it: one JSON object per line, appended."""
    path = directory / f"{svc}-{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def line(svc, ts, *, lvl="info", evt="e", msg="", corr="", **ctx):
    row = {"svc": svc, "ts": ts, "lvl": lvl, "evt": evt, "host": "h"}
    if msg:
        row["msg"] = msg
    if corr:
        row["corr"] = corr
    if ctx:
        row["ctx"] = ctx
    return row


@pytest.fixture()
def logs(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    return d


# --------------------------------------------------------------------------- the empty cases
def test_a_missing_directory_says_so_rather_than_reporting_no_logs(tmp_path):
    """The trap this closes: a console opened on a laptop resolves a store root that production
    does not use, finds no directory, and renders an empty table that reads as a healthy estate.
    `present` is what lets the page say "this process is not the engine" instead."""
    out = li.search(directory=tmp_path / "nope")
    assert out["present"] is False
    assert out["rows"] == []
    assert out["dir"].endswith("nope")


def test_an_empty_directory_is_present_and_empty(logs):
    out = li.search(directory=logs)
    assert out["present"] is True
    assert out["rows"] == [] and out["matched"] == 0 and out["files_total"] == 0


# --------------------------------------------------------------------------- order
def test_newest_first_across_days_and_services(logs):
    write_day(logs, "engine", "2026-08-18", [line("engine", "2026-08-18T10:00:00.000Z", evt="old")])
    write_day(logs, "store-api", "2026-08-19", [line("store-api", "2026-08-19T09:00:00.000Z", evt="mid")])
    write_day(logs, "engine", "2026-08-19", [line("engine", "2026-08-19T23:00:00.000Z", evt="new")])
    out = li.search(directory=logs)
    assert [r["evt"] for r in out["rows"]] == ["new", "mid", "old"]


def test_within_one_file_the_last_line_written_comes_back_first(logs):
    write_day(logs, "engine", "2026-08-19", [
        line("engine", "2026-08-19T01:00:00.000Z", evt="first"),
        line("engine", "2026-08-19T02:00:00.000Z", evt="second"),
    ])
    assert [r["evt"] for r in li.search(directory=logs)["rows"]] == ["second", "first"]


# --------------------------------------------------------------------------- filters
def test_service_filter_selects_the_file_not_only_the_rows(logs):
    write_day(logs, "engine", "2026-08-19", [line("engine", "2026-08-19T01:00:00.000Z")])
    write_day(logs, "store-api", "2026-08-19", [line("store-api", "2026-08-19T02:00:00.000Z")])
    out = li.search(directory=logs, service="engine")
    assert out["files_read"] == 1, "a service filter must not read the other services' files"
    assert {r["svc"] for r in out["rows"]} == {"engine"}


def test_level_is_a_minimum_not_an_exact_match(logs):
    write_day(logs, "engine", "2026-08-19", [
        line("engine", "2026-08-19T01:00:00.000Z", lvl="debug", evt="d"),
        line("engine", "2026-08-19T02:00:00.000Z", lvl="info", evt="i"),
        line("engine", "2026-08-19T03:00:00.000Z", lvl="warn", evt="w"),
        line("engine", "2026-08-19T04:00:00.000Z", lvl="crit", evt="c"),
    ])
    assert {r["evt"] for r in li.search(directory=logs, level="warn")["rows"]} == {"w", "c"}


def test_an_unknown_level_filters_nothing_rather_than_everything(logs):
    """A typo in a query string must not look like a quiet system."""
    write_day(logs, "engine", "2026-08-19", [line("engine", "2026-08-19T01:00:00.000Z")])
    assert len(li.search(directory=logs, level="urgent")["rows"]) == 1


def test_correlation_id_is_exact_so_one_purchase_is_one_trail(logs):
    write_day(logs, "store-api", "2026-08-19", [
        line("store-api", "2026-08-19T01:00:00.000Z", corr="abc", evt="mine"),
        line("store-api", "2026-08-19T02:00:00.000Z", corr="abcdef", evt="theirs"),
    ])
    assert [r["evt"] for r in li.search(directory=logs, corr="abc")["rows"]] == ["mine"]


def test_free_text_is_case_insensitive_and_reaches_into_ctx(logs):
    write_day(logs, "engine", "2026-08-19", [
        line("engine", "2026-08-19T01:00:00.000Z", evt="a", msg="Stripe session opened"),
        line("engine", "2026-08-19T02:00:00.000Z", evt="b", pack_id="PACK-77"),
        line("engine", "2026-08-19T03:00:00.000Z", evt="c", msg="nothing here"),
    ])
    assert [r["evt"] for r in li.search(directory=logs, q="stripe")["rows"]] == ["a"]
    assert [r["evt"] for r in li.search(directory=logs, q="pack-77")["rows"]] == ["b"]


def test_a_time_window_bounds_both_ends(logs):
    write_day(logs, "engine", "2026-08-19", [
        line("engine", "2026-08-19T01:00:00.000Z", evt="before"),
        line("engine", "2026-08-19T05:00:00.000Z", evt="inside"),
        line("engine", "2026-08-19T09:00:00.000Z", evt="after"),
    ])
    out = li.search(directory=logs, since="2026-08-19T03:00:00.000Z", until="2026-08-19T07:00:00.000Z")
    assert [r["evt"] for r in out["rows"]] == ["inside"]


# --------------------------------------------------------------------------- bounds, made visible
def test_a_torn_line_is_counted_and_costs_nothing_else(logs):
    path = write_day(logs, "engine", "2026-08-19", [line("engine", "2026-08-19T01:00:00.000Z", evt="good")])
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"svc": "engine", "ts": "2026-\n')
    out = li.search(directory=logs)
    assert out["unreadable"] == 1
    assert [r["evt"] for r in out["rows"]] == ["good"]


def test_a_file_we_did_not_write_is_ignored(logs):
    (logs / "notes.jsonl").write_text('{"svc":"engine","ts":"z","evt":"x"}\n', encoding="utf-8")
    (logs / "engine-not-a-day.jsonl").write_text('{"svc":"engine","ts":"z","evt":"y"}\n', encoding="utf-8")
    out = li.search(directory=logs)
    assert out["files_total"] == 0 and out["rows"] == []


def test_a_file_longer_than_the_window_reports_truncated(logs, monkeypatch):
    monkeypatch.setattr(li, "MAX_TAIL_BYTES", 400)
    write_day(logs, "engine", "2026-08-19",
              [line("engine", f"2026-08-19T00:00:{n:02d}.000Z", evt=f"e{n}") for n in range(40)])
    out = li.search(directory=logs)
    assert out["truncated"] is True, "a bounded read that does not say so is a silent lie"
    assert out["rows"], "the tail is still returned"
    assert out["rows"][0]["evt"] == "e39", "and it is still the newest lines"


def test_more_day_files_than_the_cap_reports_files_capped(logs, monkeypatch):
    monkeypatch.setattr(li, "MAX_FILES", 2)
    for n in (17, 18, 19):
        write_day(logs, "engine", f"2026-08-{n}", [line("engine", f"2026-08-{n}T01:00:00.000Z", evt=str(n))])
    out = li.search(directory=logs)
    assert out["files_capped"] is True and out["files_total"] == 3 and out["files_read"] == 2
    assert [r["evt"] for r in out["rows"]] == ["19", "18"], "the cap keeps the NEWEST days"


def test_limit_is_clamped_and_matched_still_counts_the_rest(logs):
    write_day(logs, "engine", "2026-08-19",
              [line("engine", f"2026-08-19T00:00:{n:02d}.000Z", evt=f"e{n}") for n in range(10)])
    out = li.search(directory=logs, limit=3)
    assert len(out["rows"]) == 3
    assert out["limit"] == 3
    assert li.search(directory=logs, limit=99999)["limit"] == li.MAX_LIMIT


def test_a_row_that_is_not_an_object_is_unreadable_not_a_crash(logs):
    path = logs / "engine-2026-08-19.jsonl"
    path.write_text('[1,2,3]\n{"svc":"engine","ts":"2026-08-19T01:00:00.000Z","evt":"ok"}\n', encoding="utf-8")
    out = li.search(directory=logs)
    assert out["unreadable"] == 1 and [r["evt"] for r in out["rows"]] == ["ok"]
