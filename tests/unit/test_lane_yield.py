"""Tests for G9: measured lane quotas.

The properties that matter are not "does it pick the lane I expect" — they are the four
guarantees that make this safe to switch on: it reallocates without changing the total, it
never starves a lane to zero, it fails open to the static quota, and it cannot be driven by
DEFER rows. Each has its own test.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from prospector.lane_yield import _apportion, measured_lane_quota
from prospector.run import _lane_counts

LANES = ["side_hustle", "smb", "growth", "venture"]


def _make_db(tmp_path, rows):
    """rows: list of (ambition_tier, decision, composite, provisional)."""
    db = tmp_path / "prospector.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE dossiers (candidate_id TEXT PRIMARY KEY, ambition_tier TEXT, "
                 "decision TEXT, composite REAL, provisional INTEGER DEFAULT 0)")
    for i, (lane, dec, comp, prov) in enumerate(rows):
        conn.execute("INSERT INTO dossiers VALUES (?,?,?,?,?)", (f"c{i}", lane, dec, comp, prov))
    conn.commit()
    conn.close()
    return db


def _cfg(tmp_path, **gen):
    return SimpleNamespace(store_dir=tmp_path, generation=dict(gen),
                           lane_quota={"side_hustle": 3, "smb": 5, "growth": 4, "venture": 3})


# ----- _apportion -------------------------------------------------------------


def test_apportion_sums_to_total_and_floors_at_one():
    q = _apportion({"a": 0.97, "b": 0.01, "c": 0.01, "d": 0.01}, 15, ["a", "b", "c", "d"])
    assert sum(q.values()) == 15
    assert all(v >= 1 for v in q.values())
    assert q["a"] == max(q.values())


def test_apportion_total_equal_to_lane_count_gives_everyone_exactly_one():
    assert _apportion({"a": 9.0, "b": 0.1}, 2, ["a", "b"]) == {"a": 1, "b": 1}


def test_apportion_zero_weights_falls_back_to_floors():
    assert _apportion({"a": 0.0, "b": 0.0}, 10, ["a", "b"]) == {"a": 1, "b": 1}


# ----- measured_lane_quota ----------------------------------------------------


def test_measured_quota_reallocates_without_changing_the_total(tmp_path):
    """Switching modes must not change how many candidates a run generates — only where
    they land. Otherwise the cost of a tick moves as a side effect of a quality experiment
    and the two are indistinguishable in the spend ledger."""
    rows = ([("smb", "pass", 0.9, 0)] * 40 + [("smb", "kill", None, 0)] * 10
            + [("venture", "kill", None, 0)] * 50)
    _make_db(tmp_path, rows)
    q = measured_lane_quota(_cfg(tmp_path), LANES, 15)
    assert q is not None
    assert sum(q.values()) == 15
    assert q["smb"] > q["venture"]


def test_a_barren_lane_is_never_starved_to_zero(tmp_path):
    """venture has 0 PASS in 50 here. A lane that is never generated into can never produce
    the evidence that would revive it, which makes an unreserved weighting self-confirming
    rather than measured."""
    rows = [("smb", "pass", 1.0, 0)] * 200 + [("venture", "kill", None, 0)] * 200
    _make_db(tmp_path, rows)
    q = measured_lane_quota(_cfg(tmp_path), LANES, 15)
    assert q["venture"] >= 1
    # The uniform 20% reserve buys more than the bare floor at this batch size.
    assert q["venture"] >= 2, q


def test_weighting_is_on_value_not_on_pass_count(tmp_path):
    """Both lanes pass at exactly 50%. The one whose passes score higher must win, because
    optimising the pass COUNT is the failure mode the founder rule forbids."""
    rows = ([("smb", "pass", 0.30, 0)] * 100 + [("smb", "kill", None, 0)] * 100
            + [("growth", "pass", 0.90, 0)] * 100 + [("growth", "kill", None, 0)] * 100)
    _make_db(tmp_path, rows)
    q = measured_lane_quota(_cfg(tmp_path), LANES, 15)
    assert q["growth"] > q["smb"], q


def test_defers_cannot_drive_the_split(tmp_path):
    """A lane buried in DEFERs is queued, not bad. Two stores identical but for a pile of
    deferred rows must produce the same quota — otherwise a moat outage silently rewrites
    the generation budget."""
    base = [("smb", "pass", 0.8, 0)] * 30 + [("growth", "kill", None, 0)] * 30
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _make_db(a, base)
    _make_db(b, base + [("growth", "defer", None, 0)] * 500)
    assert measured_lane_quota(_cfg(a), LANES, 15) == measured_lane_quota(_cfg(b), LANES, 15)


def test_provisional_rows_cannot_drive_the_split(tmp_path):
    """A provisional PASS can never publish, so it must not buy its lane a bigger share."""
    base = [("smb", "pass", 0.8, 0)] * 30 + [("growth", "kill", None, 0)] * 30
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _make_db(a, base)
    _make_db(b, base + [("growth", "pass", 1.0, 1)] * 200)
    assert measured_lane_quota(_cfg(a), LANES, 15) == measured_lane_quota(_cfg(b), LANES, 15)


def test_no_db_fails_open_to_none(tmp_path):
    assert measured_lane_quota(_cfg(tmp_path), LANES, 15) is None


def test_no_ruled_rows_fails_open_to_none(tmp_path):
    _make_db(tmp_path, [("smb", "defer", None, 0)] * 20)
    assert measured_lane_quota(_cfg(tmp_path), LANES, 15) is None


def test_ruled_rows_but_no_passes_fails_open_to_none(tmp_path):
    """There is no value signal to allocate on. Say so, rather than handing every lane an
    identical share dressed up as a measurement."""
    _make_db(tmp_path, [("smb", "kill", None, 0)] * 50)
    assert measured_lane_quota(_cfg(tmp_path), LANES, 15) is None


def test_total_below_lane_count_fails_open_to_none(tmp_path):
    _make_db(tmp_path, [("smb", "pass", 0.9, 0)] * 50)
    assert measured_lane_quota(_cfg(tmp_path), LANES, 3) is None


# ----- the wiring in run._lane_counts ----------------------------------------


def test_default_mode_is_static_and_byte_identical(tmp_path):
    """No `lane_quota_mode` key at all must reproduce today's numbers exactly."""
    _make_db(tmp_path, [("smb", "pass", 0.9, 0)] * 100)
    cfg = _cfg(tmp_path)
    assert _lane_counts(cfg, LANES, None) == {"side_hustle": 3, "smb": 5,
                                              "growth": 4, "venture": 3}


def test_measured_mode_is_used_when_asked_for(tmp_path):
    _make_db(tmp_path, [("smb", "pass", 1.0, 0)] * 200
             + [("side_hustle", "kill", None, 0)] * 200)
    cfg = _cfg(tmp_path, lane_quota_mode="measured")
    q = _lane_counts(cfg, LANES, None)
    assert sum(q.values()) == 15
    assert q["smb"] > q["side_hustle"]


def test_measured_mode_falls_back_to_static_when_the_store_is_empty(tmp_path):
    cfg = _cfg(tmp_path, lane_quota_mode="measured")
    assert _lane_counts(cfg, LANES, None) == {"side_hustle": 3, "smb": 5,
                                              "growth": 4, "venture": 3}


def test_explicit_k_still_scales_the_whole_fan_out(tmp_path):
    """`--candidates k` semantics are unchanged by the mode."""
    _make_db(tmp_path, [("smb", "pass", 1.0, 0)] * 200)
    cfg = _cfg(tmp_path, lane_quota_mode="measured")
    q = _lane_counts(cfg, LANES, 30)
    assert sum(q.values()) == 30
    assert all(v >= 1 for v in q.values())


def test_zero_exploration_reserve_still_keeps_the_floor(tmp_path):
    """Even with the reserve dialled to 0, no lane may reach 0 — that is the floor's job."""
    _make_db(tmp_path, [("smb", "pass", 1.0, 0)] * 500
             + [("venture", "kill", None, 0)] * 500)
    cfg = _cfg(tmp_path, lane_quota_mode="measured", lane_exploration_reserve=0.0)
    q = _lane_counts(cfg, LANES, None)
    assert min(q.values()) >= 1
    assert sum(q.values()) == 15
