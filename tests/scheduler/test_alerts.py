"""Real-time alerting: the daemon must turn bad ticks and daemon-death into operator alerts,
de-duplicate noisy conditions, and never let alerting crash the daemon."""
from __future__ import annotations

import json
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prospector.scheduler import alerts
from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path):
    return types.SimpleNamespace(store_dir=str(tmp_path))


# --- alerts_for_tick: pure classification ------------------------------------------------

def test_error_tick_is_critical():
    tick = {"allowed": True, "dry_run": False, "error": "RuntimeError: GEMINI_API_KEY not set",
            "result": None}
    specs = alerts.alerts_for_tick(tick)
    assert len(specs) == 1 and specs[0]["severity"] == alerts.CRITICAL
    assert specs[0]["key"] == "tick_error"


def test_barren_generation_warns():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 0, "passes": 0}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "barren_generation"


def test_zero_yield_warns():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 5, "passes": 0}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "zero_yield"
    assert "5" in specs[0]["title"]


def test_healthy_tick_no_alert():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 5, "passes": 2}}
    assert alerts.alerts_for_tick(tick) == []


def test_all_deferred_is_critical_moat_outage():
    # Every candidate deferred => moat (Claude AND Gemini) down. Must be a distinct CRITICAL
    # outage alert, NOT mislabeled as a calibration "zero yield".
    tick = {"allowed": True, "dry_run": False, "error": None,
            "result": {"dossiers": 4, "passes": 0, "defers": 4}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "moat_deferred"
    assert specs[0]["severity"] == alerts.CRITICAL


def test_partial_defers_zero_yield_is_defer_aware():
    # Some deferred, some vetted-and-killed => still zero_yield, but the title says deferral so
    # the founder isn't pointed only at "calibration".
    tick = {"allowed": True, "dry_run": False, "error": None,
            "result": {"dossiers": 5, "passes": 0, "defers": 2}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "zero_yield"
    assert "deferred" in specs[0]["title"]


def test_missing_defers_field_is_safe():
    # Old ticks (pre-defers telemetry) must still classify as plain zero_yield, never crash.
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 5, "passes": 0}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "zero_yield"


def test_guarded_or_dry_run_never_alerts():
    assert alerts.alerts_for_tick({"allowed": False, "reason": "paused"}) == []
    assert alerts.alerts_for_tick({"allowed": True, "dry_run": True, "result": None}) == []


# --- emit_alert: audit trail + throttled notification ------------------------------------

def test_emit_logs_every_time_but_notifies_once(tmp_path, monkeypatch):
    notified = []
    monkeypatch.setattr(alerts, "_desktop_notify", lambda t, m: notified.append((t, m)))
    monkeypatch.setattr(alerts, "_webhook_post", lambda r: None)
    cfg = _cfg(tmp_path)

    for _ in range(3):
        alerts.emit_alert(cfg, severity=alerts.WARNING, key="zero_yield",
                          title="Zero yield", message="0 PASS", throttle_s=3600)

    lines = (Path(tmp_path) / "scheduler" / "alerts.jsonl").read_text().splitlines()
    assert len(lines) == 3                    # audit trail records EVERY occurrence
    assert len(notified) == 1                 # but the founder is pinged once per throttle window
    assert json.loads(lines[0])["key"] == "zero_yield"


def test_alerting_never_raises(tmp_path, monkeypatch):
    # Even if a sink explodes, emit_alert must return cleanly (daemon resilience).
    def boom(*_a, **_k):
        raise RuntimeError("sink down")
    monkeypatch.setattr(alerts, "_desktop_notify", boom)
    rec = alerts.emit_alert(_cfg(tmp_path), severity=alerts.CRITICAL, key="x",
                            title="t", message="m")
    assert rec["key"] == "x"


# --- liveness watchdog -------------------------------------------------------------------

def _write_heartbeat(tmp_path, *, phase, age_min, interval_s=7200):
    sd = Path(tmp_path) / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).isoformat()
    (sd / "heartbeat.json").write_text(json.dumps(
        {"ts": ts, "pid": 123, "phase": phase, "interval_s": interval_s}))


def test_liveness_missing_heartbeat_is_dead(tmp_path):
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok and "never run" in reason


def test_liveness_fresh_sleeping_is_alive(tmp_path):
    _write_heartbeat(tmp_path, phase="sleeping", age_min=10)
    ok, _ = rs._liveness(_cfg(tmp_path))
    assert ok


def test_liveness_stuck_generating_is_dead(tmp_path):
    # Derived from the deadline rather than hardcoded. _liveness computes
    # stall_min = _TICK_HARD_DEADLINE_S/60 + 10, so any fixed age here stops testing the
    # thing it names as soon as the deadline is retuned — which is exactly what happened:
    # a hardcoded 90 was a real assertion at the 75-min deadline and became a failure the
    # moment it moved to 3h. The constant's own comment warns about this trap on the
    # production side; the test carried the same bug.
    stall_min = rs._TICK_HARD_DEADLINE_S / 60 + 10
    _write_heartbeat(tmp_path, phase="generating", age_min=stall_min + 15)
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok and "generating" in reason


def test_liveness_generating_within_deadline_is_alive(tmp_path):
    # The other half of the coupling, and the reason the test above is not enough on its
    # own: a watchdog that declared every 'generating' heartbeat dead would still satisfy
    # it, while force-exiting healthy long batches into the relaunch livelock the deadline
    # exists to prevent. A batch still inside its budget must be left alone.
    stall_min = rs._TICK_HARD_DEADLINE_S / 60 + 10
    _write_heartbeat(tmp_path, phase="generating", age_min=stall_min - 15)
    ok, _ = rs._liveness(_cfg(tmp_path))
    assert ok


def test_liveness_overdue_sleeping_is_dead(tmp_path):
    # interval 2h + 35 grace = ~155 min budget; 200 min old => dead.
    _write_heartbeat(tmp_path, phase="sleeping", age_min=200)
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok


def test_watchdog_emits_alert_when_down(tmp_path, monkeypatch):
    fired = []
    monkeypatch.setattr(alerts, "_desktop_notify", lambda t, m: fired.append((t, m)))
    monkeypatch.setattr(alerts, "_webhook_post", lambda r: None)
    rc = rs._run_watchdog(_cfg(tmp_path))   # no heartbeat => down
    assert rc == 1 and len(fired) == 1
    assert "DOWN" in fired[0][0]


def test_barren_streak_escalates_to_critical():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 0, "passes": 0}}
    specs = alerts.alerts_for_tick(tick, consecutive_barren=3)
    assert len(specs) == 1 and specs[0]["severity"] == alerts.CRITICAL
    assert specs[0]["key"] == "barren_streak"
    assert "claude /login" in specs[0]["message"]


def test_barren_below_streak_threshold_stays_warning():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 0, "passes": 0}}
    specs = alerts.alerts_for_tick(tick, consecutive_barren=2)
    assert specs and specs[0]["key"] == "barren_generation"
    assert specs[0]["severity"] == alerts.WARNING


def _write_ticks(cfg, rows):
    p = Path(cfg.store_dir) / "scheduler"
    p.mkdir(parents=True, exist_ok=True)
    (p / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def _barren(dossiers=0, **kw):
    return {"allowed": True, "dry_run": False, "error": None,
            "result": {"dossiers": dossiers, "passes": 0}, **kw}


def test_trailing_barren_count_excludes_current_and_breaks_on_yield(tmp_path):
    cfg = _cfg(tmp_path)
    # oldest → newest: productive, barren, barren, barren(current)
    _write_ticks(cfg, [_barren(dossiers=5), _barren(), _barren(), _barren()])
    assert rs._trailing_barren_count(cfg) == 2  # current row excluded, streak stops at dossiers=5


def test_trailing_barren_count_skips_guard_rows_and_breaks_on_error(tmp_path):
    cfg = _cfg(tmp_path)
    _write_ticks(cfg, [
        _barren(error="boom"),                     # breaks the streak
        _barren(),
        {"allowed": False, "dry_run": False, "result": None},  # guard-skip: ignored
        _barren(dry_run=True),                     # dry-run: ignored
        _barren(),                                 # current tick
    ])
    assert rs._trailing_barren_count(cfg) == 1


def test_trailing_barren_count_missing_file_is_zero(tmp_path):
    assert rs._trailing_barren_count(_cfg(tmp_path)) == 0


# --- delivery classification: nothing is silent by DEFAULT ---------------------------------
#
# The defect these grade, measured on the live store 2026-08-21: `store/scheduler/alerts.jsonl`
# held 10 rows over 18 hours, every one severity `critical`, every one key `process-audit` --
# and `process-audit` was not in TELEGRAM_KEYS, so `_telegram_push` returned on its first line.
# `ALERT_WEBHOOK_URL` was not set either. Ten critical alerts reached nobody, and NO TEST FAILED,
# because the miss case of an allow-list is `return`. Every key added in future was born
# undeliverable the same way.

def _emit_alert_key_literals() -> set[str]:
    """Every string literal handed to `emit_alert(key=...)` anywhere in the repo.

    An AST walk, not a regex: `key="python"` appears all over this repo in CI lane tables and in
    house-spec gates that have nothing to do with alerting, and a regex collects all of them.
    Only a call whose callee is named `emit_alert` counts.
    """
    import ast
    root = Path(__file__).resolve().parents[2]
    found: set[str] = set()
    for path in root.rglob("*.py"):
        parts = set(path.parts)
        if parts & {"tests", ".venv", "node_modules", "build", "dist", "__pycache__"}:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name != "emit_alert":
                continue
            for kw in node.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    found.add(kw.value.value)
    return found


def _classified(key: str) -> bool:
    return (key in alerts.TELEGRAM_KEYS or key in alerts.LOCAL_ONLY_KEYS
            or key.startswith(alerts.TELEGRAM_KEY_PREFIXES))


def test_every_emitted_key_is_explicitly_classified():
    """A new alert key must be DECIDED about. It may not arrive undeliverable by default.

    Three shapes of key, because all three exist and only one of them is greppable:
      - a literal at the `emit_alert` call site;
      - a key inside an `alerts_for_tick` spec, splatted in as `emit_alert(cfg, **spec)`, which
        is why `TICK_ALERT_KEYS` is the repo's own declared contract for that set;
      - a COMPUTED key -- `service_health.alert_key(name)` builds `service_down:<name>` from a
        table, so a service added to that table would otherwise arrive silent. Classify the
        generator via a prefix, and drive the real function to prove the prefix still matches.
    """
    universe = _emit_alert_key_literals() | set(alerts.TICK_ALERT_KEYS)
    assert "process-audit" in universe, "the walk found no call sites; it has stopped grading"
    assert len(universe) >= 8, f"suspiciously few keys found: {sorted(universe)}"

    unclassified = sorted(k for k in universe if not _classified(k))
    assert not unclassified, (
        "These alert keys are neither delivered nor deliberately local:\n  "
        + "\n  ".join(unclassified)
        + "\n\nPut each one in alerts.TELEGRAM_KEYS (it reaches the founder) or in "
          "alerts.LOCAL_ONLY_KEYS (with the reason it must not). Silence by default is the "
          "defect this test exists to prevent."
    )


def test_a_computed_service_key_is_covered_by_the_prefix_not_by_luck():
    """Drive the real generator. A prefix that stops matching must fail here, not in an outage."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        import service_health
    except Exception:  # noqa: BLE001 -- import needs flyctl-adjacent deps on some hosts
        import pytest
        pytest.skip("service_health not importable here")
    SERVICES = service_health.SERVICES
    assert SERVICES, "empty service table -- this test would pass while grading nothing"
    for name in SERVICES:
        assert _classified(service_health.alert_key(name)), name


def test_the_keys_that_were_silent_during_the_outage_now_deliver():
    """Named individually and on purpose: each was CRITICAL and each reached nobody."""
    for key in ("process-audit", "supervisor", "autopause_failed", "backlog_cap_unreadable"):
        assert alerts._delivers(key), key


def test_an_unclassified_key_is_loud_never_silent(caplog):
    """The inverse of the old default. Unknown means DELIVER AND WARN, not drop on the floor."""
    import logging
    with caplog.at_level(logging.WARNING):
        assert alerts._delivers("some_key_nobody_classified") is True
    assert any("not classified" in r.getMessage()
               for r in caplog.records), caplog.text


def test_a_local_only_key_stays_local():
    assert alerts._delivers("barren_generation") is False


def test_a_condition_that_clears_itself_does_not_page():
    """The bound on the fix above, and it is the more important half.

    Making unclassified keys deliver is only safe while the SELF-HEALING ones are named and held
    back. `moat_deferred` and `moat_provisional` are finalised by `vet --resume` with no human in
    the loop, and the outage behind them already pages as `moat_blind`. Deliver them and the rail
    reports one condition twice and pages for a state that fixes itself, which is how a channel
    gets muted -- and a muted rail is an unwired rail with extra steps.
    """
    for key in ("moat_deferred", "moat_provisional"):
        assert alerts._delivers(key) is False, key
    assert alerts._delivers("moat_blind") is True


# --- the debounce key carries WHAT is wrong, so the rail speaks on change ------------------

def test_the_digest_ignores_a_count_that_flaps_but_not_the_set_that_changed():
    """process-audit's count oscillates 31 -> 32 -> 30 -> 31 as unrelated checks flap.

    Digesting the MESSAGE would produce a new key each time, defeating the debounce and putting
    an hourly message on the founder's phone -- the exact noise that got the last channel turned
    off. The identity is the sorted set of failing NAMES.
    """
    names = ["deploy engine", "deploy queue", "runner registration"]
    a = alerts._identity_digest({"identity": "|".join(sorted(names)),
                                 "message": "process audit: 31 failing\n..."})
    b = alerts._identity_digest({"identity": "|".join(sorted(names)),
                                 "message": "process audit: 32 failing\n... different wording"})
    assert a == b, "a flapping count changed the identity; the rail would repeat hourly"

    c = alerts._identity_digest({"identity": "|".join(sorted(names + ["moat blind"]))})
    assert c != a, "a check that started failing did NOT change the identity; the rail is deaf"

    assert alerts._identity_digest({"identity": "|".join(sorted(names[::-1]))}) == a, \
        "ordering alone changed the identity"


def test_without_an_identity_the_message_is_the_identity():
    assert (alerts._identity_digest({"message": "same"})
            == alerts._identity_digest({"message": "same"}))
    assert (alerts._identity_digest({"message": "a"})
            != alerts._identity_digest({"message": "b"}))


def test_an_unchanged_condition_is_quieter_than_the_push_throttle_above_it():
    """This is what makes the digest strictly a reduction in volume, never an increase.

    `emit_alert` throttles the push at 3600s per key. If the debounce window were shorter than
    that, adding a digest could only ever let MORE messages through. It must be longer.
    """
    assert alerts._UNCHANGED_S > 3600.0


def test_emit_alert_records_the_identity_it_deduped_on(tmp_path, monkeypatch):
    """'Why did this not fire?' is unanswerable after the fact unless the basis is on disk."""
    monkeypatch.setattr(alerts, "_desktop_notify", lambda *a, **k: None)
    cfg = _cfg(tmp_path)
    rec = alerts.emit_alert(cfg, severity=alerts.CRITICAL, key="process-audit",
                            title="t", message="m", identity="a|b")
    assert rec["identity"] == "a|b"
    line = json.loads((Path(tmp_path) / "scheduler" / "alerts.jsonl").read_text().splitlines()[0])
    assert line["identity"] == "a|b"
