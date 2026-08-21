"""ALERT.txt must be able to say "nothing is wrong right now".

MEASURED 2026-08-06 on the live store:

    $ cat store/scheduler/ALERT.txt
    2026-08-05T15:29:37.097979+00:00  🚨 [critical] Moat degraded: 4/4 verdicts ruled by
    FALLBACK brain

while the newest real batch in `ticks.jsonl` had `'provisional': 0`. `emit_alert` overwrote that
file and **nothing ever cleared it**, so the one artefact whose entire job is to answer "is
anything wrong right now?" could only ever show the worst thing that had ever happened. An
operator who glances at it learns nothing, which is worse than no file: it reads as a live
CRITICAL.

The fix is a resolution path (`resolve_alert`) plus an active set inside `alert_state.json`, and
these tests pin the parts that are easy to get subtly wrong — chiefly that a PAUSED or dry-run
tick must NOT count as recovery, because `alerts_for_tick` returns `[]` for those too.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from prospector.scheduler import alerts
from prospector.scheduler import run_scheduled as rs
from prospector.scheduler.alerts import (
    CRITICAL,
    TICK_ALERT_KEYS,
    WARNING,
    active_alerts,
    alerts_for_tick,
    emit_alert,
    reconcile_alert_txt,
    resolve_alert,
)


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    # No desktop popups and no webhook POSTs from a test run.
    monkeypatch.setattr("prospector.scheduler.alerts._desktop_notify", lambda *a, **k: None)
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    return types.SimpleNamespace(store_dir=str(tmp_path))


def _alert_txt(cfg) -> str:
    return (Path(cfg.store_dir) / "scheduler" / "ALERT.txt").read_text()


def _tick(**over) -> dict:
    t = {"ts": "2026-08-06T02:00:00+00:00", "allowed": True, "dry_run": False,
         "result": {"dossiers": 5, "passes": 2, "defers": 0, "provisional": 0}, "error": None}
    t.update(over)
    return t


# ── the file can now say "no" ────────────────────────────────────────────────

def test_resolving_the_last_alert_writes_an_all_clear_not_a_stale_critical(cfg):
    emit_alert(cfg, severity=CRITICAL, key="moat_provisional",
               title="Moat degraded: 4/4 verdicts ruled by FALLBACK brain", message="…")
    assert "Moat degraded" in _alert_txt(cfg)
    assert set(active_alerts(cfg)) == {"moat_provisional"}

    assert resolve_alert(cfg, key="moat_provisional", reason="clean tick") is True

    txt = _alert_txt(cfg)
    assert "No active alerts" in txt
    assert "Moat degraded" not in txt
    assert active_alerts(cfg) == {}
    assert txt.split()[0].startswith("2026-"), (
        "the all-clear carries a timestamp on purpose: 'nothing is wrong' and 'the alerting layer "
        "stopped running weeks ago' must not render identically"
    )


def test_resolving_one_of_several_never_hides_the_others(cfg):
    emit_alert(cfg, severity=CRITICAL, key="moat_deferred", title="Moat outage", message="a")
    emit_alert(cfg, severity=WARNING, key="zero_yield", title="Zero yield", message="b")
    resolve_alert(cfg, key="zero_yield", reason="recovered")

    txt = _alert_txt(cfg)
    assert "Moat outage" in txt
    assert "Zero yield" not in txt
    assert set(active_alerts(cfg)) == {"moat_deferred"}


def test_resolving_something_that_was_never_active_is_a_no_op(cfg):
    assert resolve_alert(cfg, key="zero_yield", reason="nothing to clear") is False


def test_a_throttled_repeat_keeps_the_condition_active(cfg):
    """Throttling governs the PUSH, not the truth.

    The desktop notification is once per hour for a persistent condition; if the second (throttled)
    occurrence skipped the active set, a condition that is still happening would silently drop out
    of ALERT.txt — the same write-only defect, mirrored.
    """
    emit_alert(cfg, severity=CRITICAL, key="tick_error", title="Tick FAILED", message="one",
               throttle_s=3600)
    emit_alert(cfg, severity=CRITICAL, key="tick_error", title="Tick FAILED", message="two",
               throttle_s=3600)
    assert set(active_alerts(cfg)) == {"tick_error"}
    assert "two" in _alert_txt(cfg), "the banner must reflect the latest occurrence"


def test_a_resolution_is_recorded_in_the_audit_trail(cfg):
    emit_alert(cfg, severity=CRITICAL, key="tick_error", title="Tick FAILED", message="boom")
    resolve_alert(cfg, key="tick_error", reason="clean tick at 02:00")

    rows = [json.loads(line) for line in
            (Path(cfg.store_dir) / "scheduler" / "alerts.jsonl").read_text().splitlines()]
    assert [r["severity"] for r in rows] == ["critical", "info"]
    assert rows[1]["title"].startswith("RESOLVED:")
    assert rows[1]["resolves_ts"] == rows[0]["ts"], (
        "without the recovery row the trail shows conditions that fire forever and never end"
    )


def test_resolution_clears_the_throttle_so_a_recurrence_notifies_immediately(cfg):
    """A condition that recovered and came back is a new event, not a continuing one."""
    state = Path(cfg.store_dir) / "scheduler" / "alert_state.json"
    emit_alert(cfg, severity=CRITICAL, key="tick_error", title="Tick FAILED", message="boom",
               throttle_s=3600)
    assert "tick_error" in json.loads(state.read_text())

    resolve_alert(cfg, key="tick_error", reason="recovered")
    assert "tick_error" not in json.loads(state.read_text()), (
        "leaving the throttle entry would swallow the next failure for the rest of the hour "
        "opened by the previous one"
    )


# ── what counts as recovery ─────────────────────────────────────────────────

def test_a_clean_tick_clears_the_stale_critical(cfg, monkeypatch):
    monkeypatch.setattr(rs, "_trailing_barren_count", lambda _c, window=50: 0)
    emit_alert(cfg, severity=CRITICAL, key="moat_provisional", title="Moat degraded", message="…")

    rs._emit_tick_alerts(cfg, _tick())

    assert active_alerts(cfg) == {}
    assert "No active alerts" in _alert_txt(cfg)


@pytest.mark.parametrize("tick,why", [
    (_tick(allowed=False, result=None),
     "a guard-skipped tick (PAUSE / spend cap) never ran generation, so it proves nothing"),
    (_tick(dry_run=True),
     "a dry run is a manual diagnostic, not the daemon doing work"),
    (_tick(error="ProviderExhaustedError: moat down"),
     "an errored tick is itself an alert; it cannot also be evidence of recovery"),
    (_tick(result=None),
     "no result dict means the batch produced nothing to judge"),
])
def test_a_tick_that_did_not_really_run_never_counts_as_recovery(cfg, monkeypatch, tick, why):
    """`alerts_for_tick` returns [] for all of these, so 'no specs' alone is not health.

    Keying recovery off an empty spec list would let dropping `store/scheduler/PAUSE` in place
    quietly clear a live moat outage.
    """
    monkeypatch.setattr(rs, "_trailing_barren_count", lambda _c, window=50: 0)
    emit_alert(cfg, severity=CRITICAL, key="moat_deferred", title="Moat outage", message="…")

    rs._emit_tick_alerts(cfg, tick)

    # Membership, not equality: the errored case legitimately ADDS `tick_error` on top. What must
    # never happen is the pre-existing outage disappearing.
    assert "moat_deferred" in active_alerts(cfg), why
    assert "Moat outage" in _alert_txt(cfg), why


def test_a_tick_that_raises_one_condition_does_not_clear_that_one(cfg, monkeypatch):
    monkeypatch.setattr(rs, "_trailing_barren_count", lambda _c, window=50: 0)
    emit_alert(cfg, severity=CRITICAL, key="moat_deferred", title="Moat outage", message="…")

    # 5 dossiers, 0 passes -> zero_yield raised; moat_deferred not raised -> cleared.
    rs._emit_tick_alerts(cfg, _tick(result={"dossiers": 5, "passes": 0, "defers": 0,
                                            "provisional": 0}))

    assert set(active_alerts(cfg)) == {"zero_yield"}
    assert "Zero yield" in _alert_txt(cfg)


def test_the_watchdog_owns_liveness_in_both_directions(cfg, monkeypatch):
    """A clean tick must NOT clear `liveness`: the tick cadence is 2h, the watchdog's is 15 min."""
    monkeypatch.setattr(rs, "_trailing_barren_count", lambda _c, window=50: 0)
    emit_alert(cfg, severity=CRITICAL, key="liveness", title="Generation daemon is DOWN",
               message="stuck in 'generating' for 147 min")

    rs._emit_tick_alerts(cfg, _tick())
    assert set(active_alerts(cfg)) == {"liveness"}, (
        "clearing it from the tick path would leave the file green for up to two hours after the "
        "daemon actually died"
    )

    monkeypatch.setattr(rs, "_liveness", lambda _c: (True, "heartbeat 3 min old, phase=idle"))
    assert rs._run_watchdog(cfg) == 0
    assert active_alerts(cfg) == {}


# ── the store this fix actually lands on ────────────────────────────────────

def _legacy_store(cfg) -> Path:
    """Reproduce the live store as it stood on 2026-08-06, byte-for-byte in shape.

    `alert_state.json` holds ONLY throttle timestamps — no `_active` key, because the active set
    did not exist when these were written — while `ALERT.txt` carries a CRITICAL banner from
    2026-08-05T15:29. Both files copied from `store/scheduler/` on the day of the fix.
    """
    sdir = Path(cfg.store_dir) / "scheduler"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "alert_state.json").write_text(json.dumps({
        "barren_generation": "2026-08-05T14:26:45.957926+00:00",
        "zero_yield": "2026-07-31T10:38:22.632048+00:00",
        "moat_provisional": "2026-08-05T15:29:37.097979+00:00",
        "liveness": "2026-08-05T01:36:07.469779+00:00",
        "moat_deferred": "2026-06-24T21:13:37.113692+00:00",
        "tick_error": "2026-08-02T20:16:19.292609+00:00",
        "barren_streak": "2026-08-05T14:43:27.701366+00:00",
    }))
    (sdir / "ALERT.txt").write_text(
        "2026-08-05T15:29:37.097979+00:00  🚨 [critical] Moat degraded: 4/4 verdicts ruled by "
        "FALLBACK brain\nThe trusted moat was exhausted…\n")
    return sdir


def test_a_clean_tick_clears_a_banner_inherited_from_the_pre_fix_store(cfg, monkeypatch):
    """The regression that would have shipped silently.

    `resolve_alert` rewrites ALERT.txt only when it actually REMOVED something. On a store written
    by the old code nothing is in the active set, so every one of the six resolve calls returns
    False and the stale CRITICAL survives — the fix would be green in tests, deployed, and the
    operator would still be looking at yesterday's banner forever.
    """
    _legacy_store(cfg)
    monkeypatch.setattr(rs, "_trailing_barren_count", lambda _c, window=50: 0)
    assert active_alerts(cfg) == {}, "precondition: the pre-fix store has no active set at all"

    rs._emit_tick_alerts(cfg, _tick())

    txt = _alert_txt(cfg)
    assert "No active alerts" in txt
    assert "Moat degraded" not in txt, (
        "a file that only converges on a state TRANSITION can never recover from a state it "
        "inherited"
    )


def test_reconciling_never_invents_an_all_clear_over_a_live_condition(cfg):
    """It rewrites from the active set, so it must not be a blanket 'write OK'."""
    emit_alert(cfg, severity=CRITICAL, key="moat_deferred", title="Moat outage", message="…")
    assert set(reconcile_alert_txt(cfg)) == {"moat_deferred"}
    assert "Moat outage" in _alert_txt(cfg)
    assert "No active alerts" not in _alert_txt(cfg)


def test_every_key_alerts_for_tick_can_emit_is_declared_resolvable():
    """Drive the real function over real tick shapes — a new condition must not be unclearable."""
    shapes = [
        (_tick(error="boom"), 0),
        # The moat-preflight skip: no `result` dict ever gets written on this path.
        (_tick(moat_blind=True, reason="all trusted brains carry live dead marks",
               batch_size=None, result=None), 0),
        (_tick(result={"dossiers": 0, "passes": 0, "defers": 0, "provisional": 0}), 0),
        (_tick(result={"dossiers": 0, "passes": 0, "defers": 0, "provisional": 0}), 5),
        (_tick(result={"dossiers": 4, "passes": 0, "defers": 4, "provisional": 0}), 0),
        (_tick(result={"dossiers": 4, "passes": 0, "defers": 0, "provisional": 4}), 0),
        (_tick(result={"dossiers": 4, "passes": 0, "defers": 0, "provisional": 0}), 0),
    ]
    emitted = {s["key"] for tick, barren in shapes
               for s in alerts_for_tick(tick, consecutive_barren=barren)}
    assert emitted == set(TICK_ALERT_KEYS), (
        f"TICK_ALERT_KEYS is the contract between what a tick can complain about and what a good "
        f"tick clears; drift = an alert that fires and never clears. missing from the constant: "
        f"{emitted - set(TICK_ALERT_KEYS)}; declared but unreachable: {set(TICK_ALERT_KEYS) - emitted}"
    )


# --- the all-clear must reach the same place the alarm did ---------------------------------
#
# Until 2026-08-21 `resolve_alert` appended the resolution to alerts.jsonl, rewrote ALERT.txt,
# logged a warning -- and called no sink at all. So whoever was told a condition broke was never
# told it recovered, and every loop this module opened had to be closed by a human going and
# looking. The founder's words: "we need to close loops asap".

def test_a_resolution_reaches_the_sinks_not_just_the_log(cfg, monkeypatch):
    seen = []
    monkeypatch.setattr(alerts, "_desktop_notify", lambda t, m: seen.append(("desktop", t, m)))
    monkeypatch.setattr(alerts, "_webhook_post", lambda r: seen.append(("webhook", r)))
    monkeypatch.setattr(alerts, "_telegram_push", lambda r: seen.append(("telegram", r)))

    alerts.emit_alert(cfg, severity=alerts.CRITICAL, key="moat_blind",
                      title="Moat BLIND", message="no trusted brain live")
    seen.clear()

    assert alerts.resolve_alert(cfg, key="moat_blind", reason="a brain recovered") is True
    kinds = [s[0] for s in seen]
    assert kinds == ["desktop", "webhook", "telegram"], kinds
    pushed = next(s[1] for s in seen if s[0] == "telegram")
    assert pushed["key"] == "moat_blind"
    assert pushed["title"].startswith("RESOLVED:")
    assert pushed["severity"] == alerts.INFO


def test_the_all_clear_goes_through_the_same_classification_as_the_alarm(cfg, monkeypatch):
    """An all-clear may never reach somewhere the alarm could not. Same door, same lock."""
    pushed = []
    monkeypatch.setattr(alerts, "_desktop_notify", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "_webhook_post", lambda r: None)
    monkeypatch.setattr(alerts, "_load_hermes_sender",
                        lambda: (lambda line, **kw: pushed.append((line, kw)) or True))

    alerts.emit_alert(cfg, severity=alerts.WARNING, key="barren_generation",
                      title="one barren tick", message="nothing generated")
    pushed.clear()
    alerts.resolve_alert(cfg, key="barren_generation", reason="a tick produced rows")
    assert pushed == [], "a LOCAL_ONLY key announced its recovery to the phone"


def test_announcing_a_recovery_can_never_lose_the_recovery(cfg, monkeypatch):
    """The resolution is durable on disk BEFORE any sink runs. A sink that explodes is noise,
    never data loss -- the same never-raises promise `emit_alert` already keeps."""
    monkeypatch.setattr(alerts, "_desktop_notify", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "_webhook_post", lambda r: None)

    alerts.emit_alert(cfg, severity=alerts.CRITICAL, key="consumer_down",
                      title="drain died", message="no consumer")

    def boom(_):
        raise RuntimeError("sink is on fire")
    monkeypatch.setattr(alerts, "_telegram_push", boom)

    assert alerts.resolve_alert(cfg, key="consumer_down", reason="drain came back") is True
    assert "consumer_down" not in alerts.active_alerts(cfg)
    trail = [json.loads(x) for x in
             (Path(cfg.store_dir) / "scheduler" / "alerts.jsonl").read_text().splitlines()]
    assert any(r["title"].startswith("RESOLVED:") for r in trail)
