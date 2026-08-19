"""The drain panel must answer for the engine that is RUNNING, not for this laptop.

On 2026-08-19 the live Fly engine logged "251 stalled (>= 5 unresolved re-vets)" once a minute
while this console — reading `config.store_root()`, which resolves to the laptop store — reported
an empty ledger and a queue with nothing given up on. Production moved to Fly on 2026-08-17 and
the console's store resolver did not follow it.

So these tests pin two separate things, and they fail for different reasons on purpose:

  * `scripts/engine_failover.py drain` grades a ledger the same way the engine does, and its
    reset keeps a backup.
  * `prospector/ops/console_api.py` gets its numbers from that script rather than from a local
    path, and says so out loud when the side it read is not the side that is running.

Incident: `docs/incidents/INC-2026-08-19-drain-retired-on-our-own-outages.json`.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import pytest

from prospector.ops import console_api

REPO = Path(__file__).resolve().parents[2]


def _failover_module():
    """Import the script by path. It is a script, not a package module, and importing it the
    normal way would need a `scripts/__init__.py` that does not exist."""
    spec = importlib.util.spec_from_file_location(
        "engine_failover_under_test", REPO / "scripts" / "engine_failover.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- the grader

def test_a_row_at_the_cap_is_retired_and_one_below_it_is_not():
    ef = _failover_module()
    raw = json.dumps({"a": 5, "b": 4, "c": 5, "d": 1})
    g = ef._drain_grade(raw, 5)
    assert g["rows"] == 4
    assert g["retired"] == ["a", "c"]
    assert g["retired_count"] == 2
    assert g["histogram"] == {"5": 2, "4": 1, "1": 1}


def test_a_missing_or_torn_ledger_is_an_empty_one_not_an_error():
    """`drain_state.load` returns `{}` for both and calls it "a real value"
    (`prospector/drain_state.py:130-131`). If this graded a torn file as an error the console
    would show a red panel for a file the engine reads as "nothing has been tried yet"."""
    ef = _failover_module()
    for raw in ("", "   ", "{not json", "[1, 2, 3]"):
        g = ef._drain_grade(raw, 5)
        assert g == {"rows": 0, "histogram": {}, "retired": [], "retired_count": 0}, raw


def test_a_cap_of_zero_retires_nobody():
    """`schedule.max_resume_attempts: 0` turns the give-up cap off. A grader that compared
    `n >= 0` would retire every row the moment an operator disabled the cap."""
    ef = _failover_module()
    assert _failover_grade_retired(ef, {"a": 99, "b": 5}, 0) == []


def _failover_grade_retired(ef, ledger, cap):
    return ef._drain_grade(json.dumps(ledger), cap)["retired"]


def test_the_laptop_reset_keeps_a_backup_before_it_removes(tmp_path, monkeypatch):
    """The counts are the only record of which rows had been worked and how often. Losing them
    costs re-vet money, so the reset copies before it unlinks."""
    ef = _failover_module()
    monkeypatch.setattr(ef, "LAPTOP_STORE", tmp_path)
    ledger = tmp_path / ef.DRAIN_LEDGER_REL
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"x": 5, "y": 5, "z": 2}))

    out = ef.drain_ledger("laptop", reset=True)

    assert out["ok"] and out["removed"] is True
    assert out["retired_count"] == 2 and out["rows"] == 3
    assert not ledger.exists()
    backup = Path(out["backup"])
    assert backup.exists()
    assert json.loads(backup.read_text()) == {"x": 5, "y": 5, "z": 2}


def test_reading_without_reset_leaves_the_ledger_alone(tmp_path, monkeypatch):
    ef = _failover_module()
    monkeypatch.setattr(ef, "LAPTOP_STORE", tmp_path)
    ledger = tmp_path / ef.DRAIN_LEDGER_REL
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"x": 5}))

    out = ef.drain_ledger("laptop")

    assert out["removed"] is False and out["backup"] is None
    assert ledger.exists()


# --------------------------------------------------------------------------- the console

def _fake_failover(payload: dict, seen: list):
    def run(*argv, timeout=120):
        seen.append(list(argv))
        return json.dumps(payload)
    return run


def test_the_console_never_reads_a_local_store_for_this_view():
    """The regression guard, and the whole point of the change.

    `_drain_ledger` must not resolve a path of its own. The moment it calls `store_root()` again
    it is back to answering for the laptop while the engine runs on Fly.
    """
    src = inspect.getsource(console_api._drain_ledger)
    # The docstring NAMES store_root as the thing this function must not use, so grade the code
    # only. A guard that reads its own explanation is a guard that can never go green.
    # `inspect.getdoc` re-indents, so it will not match the raw text. Cut the literal instead.
    a, b = src.index('"""'), src.index('"""', src.index('"""') + 3) + 3
    body = src[:a] + src[b:]
    assert "store_root" not in body, "the drain view is reading a local store again"
    assert "_failover(" in body, "the drain view must go through scripts/engine_failover.py"
    assert '"drain"' in body


def test_it_says_so_when_the_side_it_read_is_not_the_side_that_is_running(monkeypatch):
    seen: list = []
    monkeypatch.setattr(console_api, "_failover", _fake_failover(
        {"side": "laptop", "active_side": "fly", "rows": 0, "retired_count": 0,
         "max_attempts": 5, "error": None}, seen))

    out = console_api._read_drain(None, {"side": "laptop"})

    assert any("engine is running on fly" in w for w in out["warnings"]), out["warnings"]
    assert seen == [["drain", "--side", "laptop", "--json"]]


def test_a_clean_read_of_the_active_side_warns_about_nothing(monkeypatch):
    seen: list = []
    monkeypatch.setattr(console_api, "_failover", _fake_failover(
        {"side": "fly", "active_side": "fly", "rows": 3, "retired_count": 0,
         "max_attempts": 5, "error": None}, seen))

    assert console_api._read_drain(None, {})["warnings"] == []
    assert seen == [["drain", "--side", "active", "--json"]]


def test_retired_rows_are_never_reported_as_a_bare_number(monkeypatch):
    """251 rows read as "the pipeline cannot rule on these". They were rows whose budget an
    outage had spent. The count travels with that sentence or it will be misread again."""
    monkeypatch.setattr(console_api, "_failover", _fake_failover(
        {"side": "fly", "active_side": "fly", "rows": 253, "retired_count": 251,
         "max_attempts": 5, "error": None}, []))

    warnings = console_api._read_drain(None, {})["warnings"]

    assert any("251 candidate(s)" in w and "outage spent that budget" in w
               for w in warnings), warnings


def test_a_cap_of_zero_is_called_out_rather_than_shown_as_a_healthy_zero(monkeypatch):
    monkeypatch.setattr(console_api, "_failover", _fake_failover(
        {"side": "fly", "active_side": "fly", "rows": 9, "retired_count": 0,
         "max_attempts": 0, "error": None}, []))

    assert any("give-up cap is off" in w
               for w in console_api._read_drain(None, {})["warnings"])


def test_an_unknown_side_is_refused_rather_than_quietly_clamped():
    with pytest.raises(ValueError, match="unknown side"):
        console_api._read_drain(None, {"side": "somewhere-else"})


# --------------------------------------------------------------------------- the write

def test_the_preview_reads_but_does_not_reset(monkeypatch):
    seen: list = []
    monkeypatch.setattr(console_api, "_failover", _fake_failover(
        {"side": "fly", "active_side": "fly", "rows": 253, "retired_count": 251,
         "max_attempts": 5, "error": None, "ledger_path": "/data/store/x.json"}, seen))

    out = console_api._act_drain_reset(None, {}, True)

    assert all("--reset" not in argv for argv in seen), seen
    assert "251 retired row(s) become drainable again" in out["effect"]
    assert out["reversible"].startswith("Yes")


def test_applying_it_resets_and_reports_what_it_released(monkeypatch):
    seen: list = []

    def run(*argv, timeout=120):
        seen.append(list(argv))
        if "--reset" in argv:
            return json.dumps({"side": "fly", "active_side": "fly", "rows": 0, "retired_count": 0,
                               "max_attempts": 5, "error": None, "removed": True,
                               "backup": "/data/store/x.json.bak-20260819T000000Z",
                               "ledger_path": "/data/store/x.json"})
        return json.dumps({"side": "fly", "active_side": "fly", "rows": 253, "retired_count": 251,
                           "max_attempts": 5, "error": None, "ledger_path": "/data/store/x.json"})

    monkeypatch.setattr(console_api, "_failover", run)

    out = console_api._act_drain_reset(None, {}, False)

    assert seen[-1] == ["drain", "--side", "active", "--json", "--reset"]
    assert out["rows_released"] == 253 and out["retired_released"] == 251
    assert out["backup"].endswith(".bak-20260819T000000Z")


def test_a_side_it_cannot_read_is_not_a_side_it_will_clear(monkeypatch):
    """A failed read is not an empty ledger. Clearing on the strength of one would delete a file
    nobody has seen, and the backup would be of nothing."""
    monkeypatch.setattr(console_api, "_failover", _fake_failover(
        {"side": "fly", "active_side": "fly", "error": "fly ssh exited 1", "rows": 0,
         "retired_count": 0, "max_attempts": 5}, []))

    with pytest.raises(RuntimeError, match="will not be cleared"):
        console_api._act_drain_reset(None, {}, True)


def test_both_are_registered_and_the_write_is_not_refused():
    assert console_api.READS["drain"] is console_api._read_drain
    assert console_api.ACTIONS["drain.reset"] is console_api._act_drain_reset
    assert "drain.reset" not in console_api.REFUSED_ACTIONS
