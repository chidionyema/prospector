"""Real-time operator alerts for the always-on generation daemon.

The daemon runs unattended (founder decision 2026-06-20). The failure mode that burned us was a
broken run going UNNOTICED for hours: the engine detected `zero_yield` / `quality_decay` and tick
errors, but only whispered them to a log file nobody was watching. This module turns those signals
into alerts that reach the founder the moment they happen.

Sinks (best-effort, each independent — one failing never blocks the others or the daemon):
  1. `store/scheduler/alerts.jsonl`  — append-only audit trail of every alert (always written).
  2. `store/scheduler/ALERT.txt`      — the single latest alert, for a gl_anceable check.
  3. macOS desktop notification        — via `osascript`; works because LaunchAgents run in the
                                         user's GUI session. Swallows errors on non-mac/headless.
  4. webhook POST (opt-in)             — if `ALERT_WEBHOOK_URL` is set (Slack/Discord/generic
                                         incoming webhook). Off by default to honour "no infra
                                         beyond your own server"; the founder opts in by setting it.

Throttling: identical alert `key`s are de-duplicated within `throttle_s` (default 1h) so a
persistent condition (e.g. zero_yield every 2h tick) notifies once per window, not forever — but
EVERY occurrence is still written to alerts.jsonl for the audit trail.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

_ICON = {CRITICAL: "🚨", WARNING: "⚠️", INFO: "ℹ️"}


def _scheduler_dir(cfg) -> Path:
    d = Path(getattr(cfg, "store_dir", "store")) / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(cfg) -> Path:
    return _scheduler_dir(cfg) / "alert_state.json"


def _load_state(cfg) -> dict:
    p = _state_path(cfg)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(cfg, state: dict) -> None:
    try:
        _state_path(cfg).write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to persist alert state: %s", exc)


def _throttled(cfg, key: str, throttle_s: int, now: datetime) -> bool:
    """True if `key` was already notified within `throttle_s`. Records this notify time when False."""
    state = _load_state(cfg)
    last = state.get(key)
    if last is not None:
        try:
            if (now - datetime.fromisoformat(last)).total_seconds() < throttle_s:
                return True
        except ValueError:
            pass
    state[key] = now.isoformat()
    _save_state(cfg, state)
    return False


def _desktop_notify(title: str, message: str) -> None:
    """Fire a macOS notification. Best-effort: any failure (non-mac, headless) is swallowed."""
    try:
        # Escape double quotes for AppleScript string literals.
        t = title.replace('"', '\\"')
        m = message.replace('"', '\\"')
        subprocess.run(
            ["osascript", "-e", f'display notification "{m}" with title "{t}"'],
            check=False, timeout=10, capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _webhook_post(record: dict) -> None:
    """POST the alert to ALERT_WEBHOOK_URL if set. Opt-in; best-effort; stdlib only."""
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return
    import urllib.request

    # Slack/Discord both accept a JSON body with a `text`/`content` field; send a generic shape
    # plus a human line so it renders in either.
    line = f"{_ICON.get(record.get('severity'), '')} [{record.get('severity')}] {record.get('title')}: {record.get('message')}"
    payload = json.dumps({"text": line, "content": line, "alert": record}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as exc:  # noqa: BLE001 — a flaky webhook must never break the daemon
        logger.warning("Alert webhook POST failed: %s", exc)


def emit_alert(cfg, *, severity: str, key: str, title: str, message: str,
               throttle_s: int = 3600, **fields) -> dict:
    """Record an alert and (unless throttled) push it to the notification sinks.

    `key` groups alerts for throttling (e.g. "zero_yield", "tick_error", "liveness"). The full
    record is ALWAYS appended to alerts.jsonl; only the desktop/webhook push is throttled.
    Returns the alert record. Never raises — alerting must not be able to crash the daemon.
    """
    now = datetime.now(timezone.utc)
    record = {"ts": now.isoformat(), "severity": severity, "key": key,
              "title": title, "message": message, **fields}

    sdir = _scheduler_dir(cfg)
    try:
        with open(sdir / "alerts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as exc:
        logger.error("Failed to append alert: %s", exc)

    if _throttled(cfg, key, throttle_s, now):
        logger.info("Alert '%s' throttled (within %ds window); logged only", key, throttle_s)
        return record

    # The push sinks are best-effort and individually defensive, but a monkeypatched/buggy sink must
    # still never propagate: alerting can not be allowed to crash the daemon it is meant to guard.
    try:
        (sdir / "ALERT.txt").write_text(
            f"{record['ts']}  {_ICON.get(severity,'')} [{severity}] {title}\n{message}\n",
            encoding="utf-8")
        _desktop_notify(f"Prospector: {title}", message)
        _webhook_post(record)
        logger.warning("ALERT [%s] %s: %s", severity, title, message)
    except Exception:  # noqa: BLE001 — alerting must not be able to take down the daemon
        logger.exception("Alert push failed (alert was still recorded to alerts.jsonl)")
    return record


def alerts_for_tick(tick: dict) -> list[dict]:
    """Derive zero or more alert specs from a completed tick dict (pure — easy to unit-test).

    Conditions, worst-first:
      - tick errored                       -> CRITICAL (the daemon hit an exception this cycle)
      - generation barren (0 dossiers)     -> WARNING  (produced nothing to even judge)
      - zero yield (dossiers>0, passes==0) -> WARNING  (factory ran but stocked nothing)
    A guard-skipped tick (PAUSE / spend cap) is NOT an alert — that is intended, controlled idle.
    Returns a list of dicts ready to splat into emit_alert(**spec).
    """
    if not tick.get("allowed") or tick.get("dry_run"):
        return []

    if tick.get("error"):
        return [{"severity": CRITICAL, "key": "tick_error",
                 "title": "Generation tick FAILED",
                 "message": str(tick["error"])[:300], "ts_tick": tick.get("ts")}]

    res = tick.get("result")
    if not isinstance(res, dict):
        return []
    dossiers = int(res.get("dossiers", 0) or 0)
    passes = int(res.get("passes", 0) or 0)

    if dossiers == 0:
        return [{"severity": WARNING, "key": "barren_generation",
                 "title": "Generation produced 0 candidates",
                 "message": "A real batch ran but generated nothing to vet (dedup/generation DEFER?).",
                 "ts_tick": tick.get("ts")}]
    if passes == 0:
        return [{"severity": WARNING, "key": "zero_yield",
                 "title": f"Zero yield: {dossiers} candidates, 0 PASS",
                 "message": ("A full batch was vetted and nothing survived. Likely an ungrounded "
                             "moat (0 web retrieval -> all unverifiable) or a calibration regression."),
                 "ts_tick": tick.get("ts")}]
    return []
