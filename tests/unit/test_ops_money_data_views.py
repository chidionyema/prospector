"""The Money and Data screens report absence as absence.

These two views exist to answer "can we take money" and "would we get the data back". The way a
screen like that fails is not by crashing — it is by painting a missing answer the same colour as
a healthy one. So the cases pinned here are the missing ones: an unreachable rail, a gate that
never ran, a drill that has never happened, a backup check that could not run.

No network. The store-API caller is injected into `money_view`, and `data_view` takes a root, so
both run against fixtures on disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from prospector.ops.data import DRILL_STALE_DAYS, data_view
from prospector.ops.money import MISSING_READS, money_view


# ── money ────────────────────────────────────────────────────────────────────
def _caller(routes: dict):
    """A stand-in for the gateway's store-API caller. A route mapped to an Exception raises it."""

    def call(method: str, path: str, **_kw):
        resp = routes[path]
        if isinstance(resp, Exception):
            raise resp
        return resp

    return call


def _ok(url: str, body: dict) -> dict:
    return {"status": 200, "url": url, "body": body, "http_error": None}


STATS = _ok("/catalog/stats", {"listed": 12, "registered": 20})


def test_live_rail_reads_live_and_warns_about_nothing():
    view = money_view(None, _caller({
        "/healthz/money-rail": _ok("/healthz/money-rail", {
            "mode": "live", "provider": "stripe", "environment": "prod",
            "decidedAtUtc": "2026-08-17T09:00:00Z"}),
        "/catalog/stats": STATS,
    }))
    assert view["rail"]["state"] == "live"
    assert view["warnings"] == []


def test_test_mode_is_a_warning_not_a_detail():
    view = money_view(None, _caller({
        "/healthz/money-rail": _ok("/healthz/money-rail", {
            "mode": "test", "provider": "stripe", "environment": "prod",
            "decidedAtUtc": "2026-08-17T09:00:00Z"}),
        "/catalog/stats": STATS,
    }))
    assert view["rail"]["state"] == "test"
    assert any("TEST" in w for w in view["warnings"])


def test_a_gate_that_never_decided_is_not_reported_as_a_mode():
    """`decidedAtUtc` null means nothing checked the rail. That is worse than `test`, and it must
    not read as `test` just because `mode` happens to say so."""
    view = money_view(None, _caller({
        "/healthz/money-rail": _ok("/healthz/money-rail", {
            "mode": "test", "provider": "stripe", "decidedAtUtc": None}),
        "/catalog/stats": STATS,
    }))
    assert view["rail"]["state"] == "never-ran"
    assert any("never" in w for w in view["warnings"])


def test_an_unreachable_rail_is_a_state_not_a_mode():
    view = money_view(None, _caller({
        "/healthz/money-rail": ConnectionError("connection refused"),
        "/catalog/stats": STATS,
    }))
    assert view["rail"]["state"] == "unreachable"
    assert view["rail"]["mode"] is None
    assert "connection refused" in view["rail"]["error"]
    assert any("failed measurement" in w for w in view["warnings"])


def test_http_error_does_not_become_a_verdict():
    view = money_view(None, _caller({
        "/healthz/money-rail": {"status": 503, "url": "/healthz/money-rail",
                                "body": None, "http_error": "Service Unavailable"},
        "/catalog/stats": STATS,
    }))
    assert view["rail"]["state"] == "unreachable"
    assert "503" in view["rail"]["error"]


def test_unsellable_is_the_gap_between_registered_and_listed():
    view = money_view(None, _caller({
        "/healthz/money-rail": _ok("/healthz/money-rail", {
            "mode": "live", "decidedAtUtc": "2026-08-17T09:00:00Z"}),
        "/catalog/stats": STATS,
    }))
    assert view["shelf"]["unsellable"] == 8


def test_every_named_gap_says_what_would_close_it():
    """A gap without its route is an observation. With the route it is a work item."""
    assert MISSING_READS
    for gap in MISSING_READS:
        assert gap["needs"].strip(), gap
        assert gap["why"].strip(), gap


# ── data ─────────────────────────────────────────────────────────────────────
def _root(tmp_path: Path) -> Path:
    (tmp_path / "ops" / "config").mkdir(parents=True)
    return tmp_path


def _store(root: Path) -> Path:
    """The STATE directory, which in production is a Fly volume and not under the repo at all."""
    return root / "store"


def test_no_backup_declaration_is_unknown_not_ok(tmp_path):
    view = data_view(None, root=_root(tmp_path), store=_store(tmp_path))
    assert view["copy"]["status"] == "unknown"
    assert any("could not run" in w for w in view["warnings"])


def test_a_drill_that_never_ran_says_never(tmp_path):
    view = data_view(None, root=_root(tmp_path), store=_store(tmp_path))
    assert view["drill"]["state"] == "never"
    assert view["drill"]["ran_at"] is None


@pytest.mark.parametrize(
    "ok,age_days,expected",
    [(True, 1, "ok"), (True, DRILL_STALE_DAYS + 5, "stale"), (False, 1, "failed")],
)
def test_drill_state_from_the_receipt(tmp_path, ok, age_days, expected):
    from datetime import datetime, timedelta, timezone

    root = _root(tmp_path)
    receipt = _store(root) / "ops" / "restore_drill.json"
    receipt.parent.mkdir(parents=True)
    ran = datetime.now(timezone.utc) - timedelta(days=age_days)
    receipt.write_text(json.dumps({
        "ran_at": ran.isoformat().replace("+00:00", "Z"), "ok": ok, "took_s": 4.2,
        "what": "RESTORE_DRILL " + ("PASS" if ok else "FAIL")}))

    assert data_view(None, root=root, store=_store(root))["drill"]["state"] == expected


def test_an_unreadable_receipt_is_not_a_pass(tmp_path):
    root = _root(tmp_path)
    receipt = _store(root) / "ops" / "restore_drill.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("{not json")
    assert data_view(None, root=root, store=_store(root))["drill"]["state"] == "unreadable"


def test_rpo_refuses_to_state_a_window_it_cannot_measure(tmp_path):
    view = data_view(None, root=_root(tmp_path), store=_store(tmp_path))
    assert view["rpo"]["hours"] is None
    assert "cannot be stated" in view["rpo"]["what"]


# --------------------------------------------------------------------------- #
# The drill: where its receipt lives, and whether anything ever runs it.
# --------------------------------------------------------------------------- #
def test_the_drill_and_the_screen_look_at_the_same_place(tmp_path, monkeypatch):
    """`data.py` read `<repo>/store/ops/restore_drill.json`; the drill writes under the STORE.

    On Fly the code is /app and the store is /data/store, so the screen read a path nothing
    writes and reported "never proven" however many drills passed.
    """
    import importlib
    import sys

    store = tmp_path / "volume" / "store"
    (store / "ops").mkdir(parents=True)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(store))

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    drill = importlib.import_module("restore_drill")
    importlib.reload(drill)
    assert drill.DEFAULT_STORE == store, (
        "the drill defaults to a store derived from __file__, so on Fly it drills an empty "
        "directory that restores perfectly and proves nothing")

    receipt = drill.write_receipt(store, ok=True, took_s=1.0, report="RESTORE_DRILL PASS")
    assert receipt.exists()

    root = _root(tmp_path)
    assert data_view(None, root=root)["drill"]["state"] == "ok", (
        "the screen cannot see the receipt the drill just wrote")


def test_something_actually_runs_the_drill():
    """A drill nobody schedules is a screen that reads `never` forever, and it did."""
    conf = (Path(__file__).resolve().parents[2]
            / "deploy" / "engine" / "supervisord.conf").read_text()
    assert "[program:restore-drill]" in conf, (
        "nothing on the engine runs scripts/restore_drill.py, so DAT-2 can only ever say the "
        "restore has never been proven")
    block = conf.split("[program:restore-drill]", 1)[1].split("[program:", 1)[0]
    assert "scripts/restore_drill.py" in block
    assert "receipt.sh restore_drill.py" in block, "the run must leave a receipt Hermes can grade"
    interval = int(block.split("periodic.sh", 1)[1].split()[0])
    assert interval <= DRILL_STALE_DAYS * 86400 / 4, (
        f"a {interval}s cadence cannot keep a receipt inside the {DRILL_STALE_DAYS}-day window")
