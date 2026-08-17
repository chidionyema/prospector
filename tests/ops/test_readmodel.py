"""R16 + R22 — the ops read model tells the truth about the queue and about the brains.

WHAT THESE PIN, in the words of the two defects they close:

  * **R16.** Backlog is `run.drain_survey` — the same survey the drain spends its bound on and
    the generation brake reads. A console that counts DEFER rows its own way will disagree with
    the rail at exactly the moment it matters (a tombstoned row, an orphan, a stalled row), and
    the rail is the one that decides whether the engine generates.
  * **R22.** `store/provider_health.json` on the live store holds marks for `openrouter/*`,
    `cursor_cli` and `standardcompute` — three deleted tiers — and NO entry for either brain that
    is ruling. A panel rendering that FILE shows an estate that does not exist. The view must be
    keyed to the CONFIGURED chains, and it must never spend the half-open probe slot to build a
    display.
"""
from __future__ import annotations

import json
import sqlite3
import time
import types

import pytest

from prospector import health as _health
from prospector.ops import readmodel as R
from prospector.store import Store


def _cfg(tmp_path, **extra):
    """A cfg with a REAL store_dir. `paths.store_dir` raises rather than defaulting to a
    cwd-relative `store/`, so a test that forgot this fails loudly instead of writing into the
    live store (`scheduler/paths.py:65`). A `Path`, not a str: `Store.__init__` binds
    `cfg.store_dir` and calls `.mkdir` on it directly."""
    return types.SimpleNamespace(store_dir=tmp_path, **extra)


def _rows(tmp_path, rows: list[dict]) -> Store:
    """Write index rows straight into the SQLite index, plus a dossier file for each.

    Straight SQL rather than `store.save(Dossier(...))` because these tests are about COUNTING,
    and building nine full model objects would make the fixture the thing under test.
    """
    store = Store(_cfg(tmp_path))
    (tmp_path / "dossiers").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(store.db)) as conn:
        for r in rows:
            cid = r["candidate_id"]
            decision = r.get("decision", "defer")
            path = tmp_path / "dossiers" / f"{cid}.{decision}.json"
            if r.pop("_write_dossier", True):
                path.write_text(json.dumps({"candidate_id": cid}))
            conn.execute(
                "INSERT INTO dossiers (candidate_id, decision, provisional, tombstone, "
                "created_at, path, lease_owner, lease_until) VALUES (?,?,?,?,?,?,?,?)",
                (cid, decision, int(r.get("provisional", 0)), r.get("tombstone"),
                 r.get("created_at", "2026-08-01T00:00:00+00:00"), str(path),
                 r.get("lease_owner"), r.get("lease_until")))
        conn.commit()
    return store


def _drain_log(tmp_path, *records):
    d = tmp_path / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    (d / R.DRAIN_LOG_FILENAME).write_text(
        "\n".join(json.dumps(r) for r in records) + "\n")


def _ticks(tmp_path, *records):
    d = tmp_path / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ticks.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")


# --------------------------------------------------------------------------- #
# R16 — the counts
# --------------------------------------------------------------------------- #
def test_the_decision_counts_reconcile_to_the_raw_groupby_exactly(tmp_path):
    """R16's own probe: the panel's number and `sqlite3 … GROUP BY decision` must be one number.

    Asserted against a SECOND, independent statement — not against the same call — because the
    point is that no view recomputes this its own way.
    """
    store = _rows(tmp_path, [
        {"candidate_id": "a", "decision": "pass"},
        {"candidate_id": "b", "decision": "kill"},
        {"candidate_id": "c", "decision": "kill"},
        {"candidate_id": "d", "decision": "defer"},
    ])
    view = R.queue_view(_cfg(tmp_path), store=store)

    with sqlite3.connect(str(store.db)) as conn:
        raw = dict(conn.execute(
            "SELECT decision, COUNT(*) FROM dossiers GROUP BY decision").fetchall())

    assert raw, "no rows landed; this test would pass vacuously"
    assert view["by_decision"] == raw == {"pass": 1, "kill": 2, "defer": 1}


def test_backlog_is_the_drains_survey_and_not_a_count_of_defer_rows(tmp_path):
    """A tombstoned DEFER is a catalogue row and is NOT work.

    This is the exact shape that made a backlog read as 406 while the drain could move 360 of
    them: `by_decision` must still count the row (history), `backlog.workable` must not (work).
    A panel that filtered `decision='defer'` itself passes the previous test and fails this one.
    """
    store = _rows(tmp_path, [
        {"candidate_id": "live", "decision": "defer"},
        {"candidate_id": "dead", "decision": "defer", "tombstone": "gone for good"},
    ])
    view = R.queue_view(_cfg(tmp_path), store=store)

    assert view["by_decision"]["defer"] == 2
    assert view["backlog"]["workable"] == 1


def test_a_defer_row_with_no_dossier_on_disk_is_named_orphaned_not_absorbed(tmp_path):
    """An index row whose JSON is missing cannot be drained. Counting it silently is how 15
    consecutive no-op drains reported `attempted: 3` and nobody could see why the number never
    moved (`run.drain_survey`)."""
    store = _rows(tmp_path, [
        {"candidate_id": "ok", "decision": "defer"},
        {"candidate_id": "ghost", "decision": "defer", "_write_dossier": False},
    ])
    view = R.queue_view(_cfg(tmp_path), store=store)

    assert view["backlog"]["workable"] == 1
    assert view["backlog"]["orphaned"] == 1, "the excluded row must be NAMED, not absorbed"


def test_provisional_rows_are_backlog_even_though_they_are_not_deferred(tmp_path):
    """The drain works two populations. A queue view keyed only to DEFER under-reports the work
    by the entire provisional tail — which on the live store is the majority of it."""
    store = _rows(tmp_path, [
        {"candidate_id": "d", "decision": "defer"},
        {"candidate_id": "p", "decision": "pass", "provisional": 1},
    ])
    view = R.queue_view(_cfg(tmp_path), store=store)

    assert view["backlog"]["workable"] == 2


# --------------------------------------------------------------------------- #
# R16 — the leases
# --------------------------------------------------------------------------- #
def test_leases_separate_held_from_expired_from_never_taken(tmp_path):
    """THREE states, not two. `claim()` treats expired and never-taken identically, but an
    operator must not: nothing cleans a lease up — expiry IS the release — so an expired lease is
    the fingerprint of a worker that died mid-vet. Rising `held` is a busy consumer; rising
    `expired` is a crashing one."""
    now = time.time()
    store = _rows(tmp_path, [
        {"candidate_id": "held", "decision": "defer",
         "lease_owner": "consumer-1", "lease_until": now + 600},
        {"candidate_id": "expired", "decision": "defer",
         "lease_owner": "dead-worker", "lease_until": now - 600},
        {"candidate_id": "free", "decision": "defer"},
    ])
    leases = R.queue_view(_cfg(tmp_path), store=store, now=now)["leases"]

    assert leases == {"held": 1, "expired": 1, "unheld": 1, "total": 3}


# --------------------------------------------------------------------------- #
# R16 — the rate and the ETA
# --------------------------------------------------------------------------- #
def test_no_drain_record_gives_a_null_eta_and_says_why(tmp_path):
    """An unmeasured ETA must read as unmeasured. A confident number derived from no data is the
    failure mode memory `a-saturated-metric-prints-as-a-confident-null` records in reverse: the
    operator cannot tell "not measured" from "measured, and fine"."""
    store = _rows(tmp_path, [{"candidate_id": "d", "decision": "defer"}])
    drain = R.queue_view(_cfg(tmp_path), store=store)["drain"]

    assert drain["events"] == 0
    assert drain["rate_per_h"] is None
    assert drain["eta_h"] is None
    assert "no drain recorded" in drain["eta_reason"]


def test_the_rate_reads_the_consumer_log_AND_the_producer_ticks(tmp_path):
    """The drain moved process on 2026-08-15. A rate built from either source alone is blind on
    one side of that boundary — and the older source is the one that still has history."""
    now = time.time()
    store = _rows(tmp_path, [{"candidate_id": f"d{i}", "decision": "defer"} for i in range(10)])
    _drain_log(tmp_path, {"ts": now - 3600, "attempted": 3, "resumed": 3})
    _ticks(tmp_path,
           {"ts": now - 7200, "result": {"resumed": {"attempted": 3, "resumed": 2}}},
           {"ts": now - 7200, "result": {}})  # a tick that never drained contributes nothing

    drain = R.queue_view(_cfg(tmp_path), store=store, now=now)["drain"]

    assert drain["events"] == 2
    assert drain["sources"] == ["consumer", "producer_tick"]
    assert drain["resumed"] == 5
    assert drain["rate_per_h"] == pytest.approx(2.5, rel=0.01)   # 5 rows over a 2h window
    assert drain["eta_h"] == pytest.approx(4.0, rel=0.01)        # 10 workable rows


def test_a_recent_burst_cannot_mint_an_optimistic_eta(tmp_path):
    """Two rows drained four minutes ago is not "30 rows/hour". The rate window has a floor, so
    one lucky burst cannot produce a forecast an operator would plan around."""
    now = time.time()
    store = _rows(tmp_path, [{"candidate_id": f"d{i}", "decision": "defer"} for i in range(100)])
    _drain_log(tmp_path, {"ts": now - 240, "attempted": 50, "resumed": 50})

    drain = R.queue_view(_cfg(tmp_path), store=store, now=now)["drain"]

    assert drain["window_h"] == pytest.approx(1.0), "the window must be floored at an hour"
    assert drain["rate_per_h"] == pytest.approx(50.0)
    assert drain["eta_h"] == pytest.approx(2.0)


def test_a_torn_line_in_the_drain_log_is_skipped_not_fatal(tmp_path):
    """A monitor that dies on a half-written line is down exactly when the thing it watches is
    busy. `jsonl_atomic` makes torn lines rare, not impossible."""
    now = time.time()
    store = _rows(tmp_path, [{"candidate_id": "d", "decision": "defer"}])
    d = tmp_path / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    (d / R.DRAIN_LOG_FILENAME).write_text(
        json.dumps({"ts": now - 3600, "attempted": 1, "resumed": 1}) + "\n{\"ts\": \"tor")

    drain = R.queue_view(_cfg(tmp_path), store=store, now=now)["drain"]
    assert drain["events"] == 1 and drain["resumed"] == 1


def test_the_zero_row_case_reports_a_rate_but_no_eta(tmp_path):
    """Passes that resumed nothing are still evidence — of a drain that is running and moving
    nothing. That must not read the same as "not measured"."""
    now = time.time()
    store = _rows(tmp_path, [{"candidate_id": "d", "decision": "defer"}])
    _drain_log(tmp_path, {"ts": now - 3600, "attempted": 3, "resumed": 0})

    drain = R.queue_view(_cfg(tmp_path), store=store, now=now)["drain"]
    assert drain["events"] == 1 and drain["eta_h"] is None
    assert "resumed 0 rows" in drain["eta_reason"]


# --------------------------------------------------------------------------- #
# R22 — provider health
# --------------------------------------------------------------------------- #
def _health_files(tmp_path, monkeypatch, moat: dict, noncritical: dict | None = None):
    moat_path = tmp_path / "provider_health.json"
    nc_path = tmp_path / "provider_health_noncritical.json"
    moat_path.write_text(json.dumps(moat))
    nc_path.write_text(json.dumps(noncritical or {}))
    monkeypatch.setattr(_health, "get_health", lambda: _health.ProviderHealth(moat_path))
    monkeypatch.setattr(_health, "get_noncritical_health",
                        lambda: _health.ProviderHealth(nc_path))


def test_every_configured_tier_is_listed_even_with_no_mark(tmp_path, monkeypatch):
    """THE R22 DEFECT, in one assertion. The live health file names only dead tiers, so a panel
    that renders the file lists `cursor_cli` and `standardcompute` and omits both live brains."""
    _health_files(tmp_path, monkeypatch, {"cursor_cli": {"dead_until": time.time() + 3600}})
    cfg = _cfg(tmp_path, operator=["minimax", "claude_cli"],
               noncritical_operator=["minimax"], artifact_operator=["claude_cli"],
               marketing_operator=[], retrieval=types.SimpleNamespace(provider=["ddg"]))

    view = R.provider_view(cfg)
    names = [t["name"] for t in view["tiers"]]

    assert "minimax" in names and "claude_cli" in names
    assert all(t["state"] == "live" for t in view["tiers"] if t["name"] != "cursor_cli")
    assert [o["name"] for o in view["orphan_marks"]] == ["cursor_cli"], (
        "a mark for a tier no chain names is not engine state; it is litter, and must be "
        "reported as such rather than rendered as a dead brain")


def test_the_panel_never_claims_the_half_open_probe(tmp_path, monkeypatch):
    """R22's probe. `is_dead` CLAIMS the single probe slot (`health.py::_claim_probe`), so a
    console refreshing every few seconds would eat the one call whose job is to measure whether a
    benched brain has recovered — and bench it for another window every time someone looked."""
    _health_files(tmp_path, monkeypatch, {"minimax": {"dead_until": time.time() + 600,
                                                     "strikes": 2, "probe_at": 0}})
    claims: list = []
    monkeypatch.setattr(_health.ProviderHealth, "_claim_probe",
                        lambda self, name: claims.append(name) or True)
    monkeypatch.setattr(_health.ProviderHealth, "is_dead",
                        lambda self, name: pytest.fail("provider_view called is_dead"))

    cfg = _cfg(tmp_path, operator=["minimax", "claude_cli"])
    view = R.provider_view(cfg)

    assert claims == [], "the view spent the half-open probe slot"
    assert [t["state"] for t in view["tiers"] if t["name"] == "minimax"] == ["dead"]


def test_trusted_final_follows_the_loaded_config_not_the_cold_import(tmp_path, monkeypatch):
    """§14.5.1. `operator.moat_primary()` reads a process global installed by `load_config`; a
    cold import answers `{claude_cli}` while the daemon rules on `[minimax, claude_cli]`. A panel
    that got this wrong would show the brain that is publishing as untrusted."""
    from prospector import operator as _operator

    _health_files(tmp_path, monkeypatch, {})
    cfg = _cfg(tmp_path, operator=["minimax", "claude_cli"])

    _operator.set_moat_primary(["minimax", "claude_cli"])
    try:
        view = R.provider_view(cfg)
        trusted = {t["name"]: t["trusted_final"] for t in view["tiers"]}
        assert trusted == {"minimax": True, "claude_cli": True}
        assert view["trusted_final"] == ["claude_cli", "minimax"]

        _operator.set_moat_primary(["claude_cli"])
        again = R.provider_view(cfg)
        assert {t["name"]: t["trusted_final"] for t in again["tiers"]} == {
            "minimax": False, "claude_cli": True}, (
            "the view cached or hardcoded the trusted roster instead of reading it")
    finally:
        _operator.set_moat_primary(["minimax", "claude_cli"])


def test_the_noncritical_chain_is_asked_of_the_builder_not_the_config_line(tmp_path, monkeypatch):
    """`run._noncritical_order` STRIPS forbidden tiers (claude_cli, founder directive 2026-08-14).
    The config line and the chain the process builds are different lists, and the panel owes the
    operator the second one — memory `a-probe-must-call-it-the-way-the-process-does`."""
    _health_files(tmp_path, monkeypatch, {})
    cfg = _cfg(tmp_path, operator=["minimax"],
               noncritical_operator=["claude_cli", "minimax"])

    view = R.provider_view(cfg)
    noncritical = [t["name"] for t in view["tiers"]
                   if any(r["role"] == "noncritical" for r in t["roles"])]

    assert "claude_cli" not in noncritical, (
        "the panel reported a tier the engine would refuse to put on this chain")
    assert noncritical == ["minimax"]
