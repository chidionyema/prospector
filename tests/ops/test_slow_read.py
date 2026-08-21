"""The snapshot layer under the three console views that cannot be read inside a page load.

WHY THIS FILE EXISTS. Measured 2026-08-21 across all 38 entries in `console_api.READS`: median
0.83s, 34 of 38 under 2s, and then `processes` at 141.8s, `deploys` at 12.45s, `automations` at
10.16s. The gateway kills a read at `OPS_READ_TIMEOUT_MS` = 120_000, so /processes had never once
been able to load -- the page was not slow, it was impossible. That is the founder's word
"inconsistent", and `prospector/ops/slow_read.py` is the fix.

What the tests below actually protect, because none of it is obvious from reading the module:

  * the LOCK. A stale or missing snapshot starts a detached refresh. Without exclusion, every
    page load starts another 141-second estate audit and the box forks itself flat -- this estate
    has already paid for that once, at load average 646 (memory
    `a-recursion-fence-guards-only-its-own-doorstep.md`).
  * a FAILING producer must not clobber a good snapshot. `process_audit.py` and
    `deploy_status.py` both exit non-zero as their NORMAL answer, and both talk to Fly and
    GitHub, so a producer failing is a Tuesday, not an exception.
  * an ABSENT snapshot must leave the producer's keys ABSENT. A page that invented
    `sections: []` would render "nothing is installed", which is a lie about the estate rather
    than a statement about the cache.
  * the three readers must never go back to calling `subprocess.run` inline. That is the whole
    defect, and it is one careless revert away from returning, so it is checked in the source.
"""
from __future__ import annotations

import ast
import json
import os
import time
from pathlib import Path

import pytest

from prospector.ops import slow_read


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the snapshot directory at a tmp tree. Never write to the real store from a test."""
    monkeypatch.setattr(slow_read, "store_root", lambda: tmp_path)
    return tmp_path


def _register(monkeypatch, name, fn, stale_after=10.0):
    monkeypatch.setitem(slow_read.PRODUCERS, name, (fn, stale_after))


# --------------------------------------------------------------------------- #
# _safe: a view name becomes a filename
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", ["", "../etc/passwd", "a/b", "a.json", "a b", "a-b", ".", "/"])
def test_safe_rejects_anything_that_is_not_a_bare_name(bad):
    with pytest.raises(ValueError):
        slow_read._safe(bad)


@pytest.mark.parametrize("good", ["processes", "deploys", "automations", "a_b", "x1"])
def test_safe_accepts_a_view_name(good):
    assert slow_read._safe(good) == good


def test_paths_live_under_the_store(store):
    assert slow_read.snapshot_path("processes") == store / "ops" / "slow_reads" / "processes.json"
    assert slow_read.lock_path("processes").name == "processes.refreshing"


# --------------------------------------------------------------------------- #
# The lock
# --------------------------------------------------------------------------- #

def test_only_one_caller_can_take_the_lock(store):
    assert slow_read._take_lock("v") is True
    assert slow_read._take_lock("v") is False, "two refreshes would fork two estate audits"


def test_dropping_the_lock_lets_the_next_caller_in(store):
    assert slow_read._take_lock("v") is True
    slow_read._drop_lock("v")
    assert slow_read._take_lock("v") is True


def test_a_stale_lock_is_reclaimed_once(store):
    assert slow_read._take_lock("v") is True
    old = time.time() - slow_read.LOCK_STALE_S - 60
    os.utime(slow_read.lock_path("v"), (old, old))
    assert slow_read._lock_is_live("v") is False
    assert slow_read._take_lock("v") is True, "a killed refresh must not wedge the view forever"
    assert slow_read._lock_is_live("v") is True


def test_dropping_a_lock_that_is_not_there_is_not_an_error(store):
    slow_read._drop_lock("never_taken")  # must not raise: refresh() drops in a finally


# --------------------------------------------------------------------------- #
# load: disk only, never raises
# --------------------------------------------------------------------------- #

def test_no_snapshot_reads_as_absent_and_stale(store):
    got = slow_read.load("processes")
    assert got["have_snapshot"] is False
    assert got["data"] is None
    assert got["stale"] is True
    assert got["age_s"] is None
    assert got["refreshing"] is False


def test_a_truncated_snapshot_reads_as_absent_rather_than_raising(store):
    p = slow_read.snapshot_path("processes")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"captured_at": 1.0, "data": {"sections"', encoding="utf-8")
    got = slow_read.load("processes")
    assert got["have_snapshot"] is False, "a half-written cache must not break the page"


def test_a_snapshot_without_captured_at_reads_as_absent(store):
    p = slow_read.snapshot_path("processes")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"data": {"sections": []}}), encoding="utf-8")
    assert slow_read.load("processes")["have_snapshot"] is False


def test_a_fresh_snapshot_is_not_stale_and_an_old_one_is(store, monkeypatch):
    _register(monkeypatch, "v", lambda cfg: {"x": 1}, stale_after=100.0)
    slow_read._write_atomic("v", {"captured_at": time.time(), "took_s": 2.0, "data": {"x": 1}})
    fresh = slow_read.load("v")
    assert fresh["have_snapshot"] is True and fresh["stale"] is False
    assert fresh["data"] == {"x": 1} and fresh["took_s"] == 2.0
    assert fresh["captured_at_iso"].endswith("+00:00"), "UTC, so two boxes agree on the age"

    slow_read._write_atomic("v", {"captured_at": time.time() - 500, "data": {"x": 1}})
    assert slow_read.load("v")["stale"] is True


# --------------------------------------------------------------------------- #
# refresh: a receipt, never a crash
# --------------------------------------------------------------------------- #

def test_refresh_writes_the_snapshot_and_load_reads_it_back(store, monkeypatch):
    _register(monkeypatch, "v", lambda cfg: {"sections": [{"name": "a"}]})
    receipt = slow_read.refresh("v", cfg=None)
    assert receipt["written"] is True
    assert slow_read.load("v")["data"] == {"sections": [{"name": "a"}]}


def test_a_failing_producer_leaves_the_previous_answer_alone(store, monkeypatch):
    _register(monkeypatch, "v", lambda cfg: {"good": True})
    assert slow_read.refresh("v")["written"] is True

    def boom(cfg):
        raise RuntimeError("fly is down")

    _register(monkeypatch, "v", boom)
    receipt = slow_read.refresh("v")
    assert receipt["written"] is False
    assert "fly is down" in receipt["reason"]
    assert slow_read.load("v")["data"] == {"good": True}, "a stale answer beats an empty one"


def test_a_failing_producer_drops_the_lock(store, monkeypatch):
    def boom(cfg):
        raise RuntimeError("nope")

    _register(monkeypatch, "v", boom)
    slow_read.refresh("v")
    assert slow_read._lock_is_live("v") is False, "one failure would wedge the view for 10 minutes"


def test_refresh_will_not_run_the_producer_while_another_holds_the_lock(store, monkeypatch):
    ran = []
    _register(monkeypatch, "v", lambda cfg: ran.append(1) or {"x": 1})
    assert slow_read._take_lock("v") is True
    receipt = slow_read.refresh("v")
    assert receipt["written"] is False
    assert receipt["reason"] == "another refresh is already running"
    assert ran == [], "the whole point is that the expensive call does not happen twice"


def test_refresh_on_an_unknown_view_is_a_receipt_not_a_keyerror(store):
    receipt = slow_read.refresh("not-a-view")
    assert receipt["written"] is False and "no producer" in receipt["reason"]


def test_the_write_is_atomic_and_leaves_no_temp_file(store, monkeypatch):
    _register(monkeypatch, "v", lambda cfg: {"x": 1})
    slow_read.refresh("v")
    left = list(slow_read.snapshot_path("v").parent.glob("*.tmp"))
    assert left == [], f"a reader would eventually parse one of these: {left}"


# --------------------------------------------------------------------------- #
# serve: what a console read actually calls
# --------------------------------------------------------------------------- #

def test_serve_starts_a_refresh_when_the_snapshot_is_stale(store, monkeypatch):
    started = []
    _register(monkeypatch, "v", lambda cfg: {"x": 1}, stale_after=1.0)
    monkeypatch.setattr(slow_read, "refresh_in_background", lambda v: started.append(v) or True)
    got = slow_read.serve("v")
    assert started == ["v"] and got["refresh_started"] is True and got["refreshing"] is True


def test_serve_does_not_start_a_refresh_when_the_snapshot_is_fresh(store, monkeypatch):
    started = []
    _register(monkeypatch, "v", lambda cfg: {"x": 1}, stale_after=1000.0)
    slow_read._write_atomic("v", {"captured_at": time.time(), "data": {"x": 1}})
    monkeypatch.setattr(slow_read, "refresh_in_background", lambda v: started.append(v) or True)
    assert slow_read.serve("v")["refresh_started"] is False
    assert started == []


def test_serve_does_not_start_a_second_refresh_while_one_is_running(store, monkeypatch):
    started = []
    _register(monkeypatch, "v", lambda cfg: {"x": 1}, stale_after=1.0)
    monkeypatch.setattr(slow_read, "refresh_in_background", lambda v: started.append(v) or True)
    assert slow_read._take_lock("v") is True
    got = slow_read.serve("v")
    assert started == [], "a page open in three tabs must not start three audits"
    assert got["refreshing"] is True and got["refresh_started"] is False


# --------------------------------------------------------------------------- #
# serve_merged: the shape the pages were written against
# --------------------------------------------------------------------------- #

def test_serve_merged_puts_the_producer_fields_at_the_top_level(store, monkeypatch):
    _register(monkeypatch, "v", lambda cfg: {"x": 1}, stale_after=1000.0)
    monkeypatch.setattr(slow_read, "refresh_in_background", lambda v: False)
    slow_read._write_atomic("v", {"captured_at": time.time(), "data": {"sections": [1], "at": "t"}})
    got = slow_read.serve_merged("v")
    assert got["sections"] == [1] and got["at"] == "t"
    assert got["snapshot"]["have_snapshot"] is True
    assert "data" not in got


def test_serve_merged_omits_the_producer_keys_when_there_is_no_snapshot(store, monkeypatch):
    _register(monkeypatch, "v", lambda cfg: {"x": 1}, stale_after=1000.0)
    monkeypatch.setattr(slow_read, "refresh_in_background", lambda v: False)
    got = slow_read.serve_merged("v")
    assert list(got) == ["snapshot"], "an invented empty list reads as 'nothing is installed'"
    assert got["snapshot"]["have_snapshot"] is False


def test_serve_merged_carries_a_list_producer_under_rows(store, monkeypatch):
    _register(monkeypatch, "v", lambda cfg: [1, 2], stale_after=1000.0)
    monkeypatch.setattr(slow_read, "refresh_in_background", lambda v: False)
    slow_read._write_atomic("v", {"captured_at": time.time(), "data": [1, 2]})
    assert slow_read.serve_merged("v")["rows"] == [1, 2]


# --------------------------------------------------------------------------- #
# The wiring, checked in the source
# --------------------------------------------------------------------------- #

_CONSOLE_API = Path(slow_read.__file__).with_name("console_api.py")
_SNAPSHOT_READERS = ("_read_processes", "_read_deploys", "_read_automations")


def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse(_CONSOLE_API.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from console_api.py")


@pytest.mark.parametrize("name", _SNAPSHOT_READERS)
def test_the_slow_readers_serve_a_snapshot_and_never_shell_out(name):
    """The defect was a 141-second subprocess behind a 120-second ceiling. Do not put it back."""
    src = ast.unparse(_fn(name))
    assert "slow_read.serve_merged" in src, f"{name} must serve the snapshot"
    assert "subprocess" not in src, f"{name} shells out again -- the page cannot load"


@pytest.mark.parametrize("view", sorted(slow_read.PRODUCERS))
def test_every_producer_is_a_view_the_console_actually_reads(view):
    from prospector.ops import console_api
    assert view in console_api.READS


def test_the_refresh_action_is_registered_and_refuses_an_unknown_view():
    from prospector.ops import console_api
    assert "snapshot.refresh" in console_api.ACTIONS
    act = console_api.ACTIONS["snapshot.refresh"]
    with pytest.raises(Exception):
        act(None, {"view": "../etc"}, True)
    preview = act(None, {"view": "processes"}, True)
    assert preview["view"] == "processes"
    assert isinstance(preview["reversible"], str) and preview["reversible"]
    assert preview["cost"] and preview["effect"]


def test_a_config_that_will_not_load_reaches_the_receipt(store, monkeypatch, capsys):
    """A snapshot taken WITHOUT config must not look like one taken with it.

    `main` deliberately survives a config it cannot load, because two of the three producers
    never look at one. The failure still has to reach the caller in data: `deploys` is the view
    that would otherwise lose every deploy route and render as though the estate had none.
    """
    import prospector.config as pcfg

    def boom():
        raise RuntimeError("config.yaml is unreadable")

    monkeypatch.setattr(pcfg, "load_config", boom)
    seen: list[object] = []
    monkeypatch.setitem(
        slow_read.PRODUCERS, "processes",
        (lambda cfg: seen.append(cfg) or {"sections": []}, 900.0))

    rc = slow_read.main(["processes"])
    receipt = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert rc == 0
    assert receipt["written"] is True
    assert receipt["config_error"].startswith("RuntimeError:")
    assert "config.yaml is unreadable" in receipt["config_error"]
    assert seen == [None], "the producer still ran, with no config"


def test_a_config_that_loads_leaves_no_error_on_the_receipt(store, monkeypatch, capsys):
    """The other half of the pair: a flag that is always set says nothing."""
    import prospector.config as pcfg

    monkeypatch.setattr(pcfg, "load_config", lambda: {"ok": True})
    monkeypatch.setitem(
        slow_read.PRODUCERS, "processes", (lambda cfg: {"sections": []}, 900.0))

    slow_read.main(["processes"])
    receipt = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert "config_error" not in receipt
