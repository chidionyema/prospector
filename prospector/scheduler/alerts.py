"""Real-time operator alerts for the always-on generation daemon.

The daemon runs unattended (founder decision 2026-06-20). The failure mode that burned us was a
broken run going UNNOTICED for hours: the engine detected `zero_yield` / `quality_decay` and tick
errors, but only whispered them to a log file nobody was watching. This module turns those signals
into alerts that reach the founder the moment they happen.

Sinks (best-effort, each independent — one failing never blocks the others or the daemon):
  1. `store/scheduler/alerts.jsonl`  — append-only audit trail of every alert (always written).
  2. `store/scheduler/ALERT.txt`      — the alerts that are still UNRESOLVED, for a glanceable
                                         check. Rewritten from the active set on every emit AND
                                         on every resolution, so it can say "no active alerts";
                                         until 2026-08-06 it was write-only and therefore only
                                         ever showed the worst thing that had ever happened.
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

from prospector.scheduler import paths

logger = logging.getLogger(__name__)

CRITICAL = "critical"
WARNING = "warning"

# How many backlogged candidates the daemon re-vets per tick. Duplicated from
# `run_scheduled._RESUME_PER_TICK_DEFAULT` rather than imported, because `run_scheduled`
# imports this module. `tests/unit/test_scheduler_resume_drain.py` asserts the two agree, so
# the copy cannot drift silently — which matters, since these strings are the ONLY thing the
# operator sees, and until 2026-08-05 they promised an "auto re-vet" that no code performed.
_RESUME_HINT = 3
INFO = "info"

_ICON = {CRITICAL: "🚨", WARNING: "⚠️", INFO: "ℹ️"}


def _scheduler_dir(cfg) -> Path:
    # See prospector/scheduler/paths.py — this used to default to a cwd-relative "store",
    # which is how a test double ends up writing the operator's real alert log.
    return paths.scheduler_dir(cfg)


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
        except (TypeError, ValueError):
            pass
    state[key] = now.isoformat()
    _save_state(cfg, state)
    return False


# Reserved slot inside alert_state.json holding the alerts that are still UNRESOLVED, keyed by
# alert key. Underscore-prefixed so it can never collide with a real key (every key emitted by
# `alerts_for_tick` and the watchdog is a bare identifier: tick_error, zero_yield, liveness, …).
# Kept in the same file rather than a new one so the throttle map and the active set cannot
# disagree about what is happening.
_ACTIVE = "_active"

# The banner written when nothing is unresolved. It carries a timestamp on purpose: "no alert"
# and "the alerting layer stopped running three weeks ago" must not look identical.
_ALL_CLEAR = "✅ [ok] No active alerts"


def _mark_active(cfg, record: dict) -> None:
    state = _load_state(cfg)
    active = state.get(_ACTIVE)
    if not isinstance(active, dict):
        active = {}
    active[record["key"]] = record
    state[_ACTIVE] = active
    _save_state(cfg, state)
    _rewrite_alert_txt(cfg, active)


def _alert_txt_body(record: dict) -> str:
    return (f"{record['ts']}  {_ICON.get(record.get('severity'), '')} "
            f"[{record.get('severity')}] {record.get('title')}\n{record.get('message')}\n")


def _rewrite_alert_txt(cfg, active: dict) -> None:
    """Rewrite the glanceable file from the CURRENT active set — not from the last event.

    ALERT.txt used to be write-only: `emit_alert` overwrote it and nothing ever cleared it. On
    2026-08-06 it still showed a `moat_provisional` CRITICAL from 2026-08-05T15:29 while the most
    recent real batch had 0 provisional verdicts — i.e. the one file whose entire job is to answer
    "is anything wrong right now?" answered with the worst thing that had ever happened. A glance
    that cannot say "no" is not a check.

    With several conditions active the newest wins the banner, and the rest are listed under it,
    so clearing one never hides another.
    """
    try:
        p = _scheduler_dir(cfg) / "ALERT.txt"
        if not active:
            p.write_text(f"{datetime.now(timezone.utc).isoformat()}  {_ALL_CLEAR}\n",
                         encoding="utf-8")
            return
        ordered = sorted(active.values(), key=lambda r: str(r.get("ts", "")), reverse=True)
        body = _alert_txt_body(ordered[0])
        if len(ordered) > 1:
            body += "\nAlso unresolved:\n" + "".join(
                f"  - [{r.get('severity')}] {r.get('title')} ({r.get('ts')})\n" for r in ordered[1:])
        p.write_text(body, encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to rewrite ALERT.txt: %s", exc)


def resolve_alert(cfg, *, key: str, reason: str) -> bool:
    """Mark `key` recovered: drop it from the active set and rewrite ALERT.txt. Returns True if
    it was actually active.

    Clearing the throttle entry too is deliberate. Throttling exists so a *persistent* condition
    notifies once an hour; a condition that recovered and then came back is a new event, and the
    founder should hear about it immediately rather than at the end of a window opened by the
    previous occurrence.

    The resolution is appended to alerts.jsonl so the audit trail records the recovery as well as
    the failure — otherwise the trail shows a condition that fires forever and never ends.
    """
    state = _load_state(cfg)
    active = state.get(_ACTIVE)
    if not isinstance(active, dict) or key not in active:
        return False

    resolved = active.pop(key)
    state[_ACTIVE] = active
    state.pop(key, None)  # throttle entry — see docstring
    _save_state(cfg, state)

    record = {"ts": datetime.now(timezone.utc).isoformat(), "severity": INFO, "key": key,
              "title": f"RESOLVED: {resolved.get('title')}", "message": reason,
              "resolves_ts": resolved.get("ts")}
    try:
        with open(_scheduler_dir(cfg) / "alerts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as exc:
        logger.error("Failed to append alert resolution: %s", exc)

    _rewrite_alert_txt(cfg, active)
    logger.warning("RESOLVED [%s] %s: %s", key, resolved.get("title"), reason)
    return True


def active_alerts(cfg) -> dict:
    """The unresolved alerts, keyed by alert key. Read-only view for probes and status output."""
    active = _load_state(cfg).get(_ACTIVE)
    return dict(active) if isinstance(active, dict) else {}


def reconcile_alert_txt(cfg) -> dict:
    """Force ALERT.txt to match the active set, and return that set.

    `resolve_alert` only rewrites the file when it actually removed something, which leaves one
    case permanently wrong: a store written by the OLD code. On 2026-08-06 the live
    `store/scheduler/alert_state.json` held seven throttle entries and NO `_active` key at all —
    the active set had never existed — while `ALERT.txt` still showed a CRITICAL from
    2026-08-05T15:29. Every `resolve_alert` call on the next clean tick would return False (nothing
    to remove), so the stale banner would have survived the fix that was written to kill it.

    Calling this at the end of a clean tick makes the file a function of current state rather than
    of the last state TRANSITION, so it converges no matter what it inherited.
    """
    active = active_alerts(cfg)
    _rewrite_alert_txt(cfg, active)
    return active


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

    # BEFORE the throttle check, and outside it: throttling governs the PUSH (one desktop
    # notification per hour for a persistent condition), not the truth of what is wrong. A
    # throttled occurrence that did not refresh the active set would let a condition drop out of
    # ALERT.txt while it was still happening — the same write-only bug in the other direction.
    _mark_active(cfg, record)

    if _throttled(cfg, key, throttle_s, now):
        logger.info("Alert '%s' throttled (within %ds window); logged only", key, throttle_s)
        return record

    # The push sinks are best-effort and individually defensive, but a monkeypatched/buggy sink must
    # still never propagate: alerting can not be allowed to crash the daemon it is meant to guard.
    try:
        _desktop_notify(f"Prospector: {title}", message)
        _webhook_post(record)
        logger.warning("ALERT [%s] %s: %s", severity, title, message)
    except Exception:  # noqa: BLE001 — alerting must not be able to take down the daemon
        logger.exception("Alert push failed (alert was still recorded to alerts.jsonl)")
    return record


# Every key `alerts_for_tick` can produce. The caller resolves the ones a healthy tick did NOT
# raise, so this list is the contract between "what a tick can complain about" and "what a good
# tick clears". A new condition added below without its key here would fire and then never clear —
# `test_alert_resolution.py::test_every_key_alerts_for_tick_can_emit_is_declared_resolvable`
# drives the real function over real tick shapes to keep the two in step.
TICK_ALERT_KEYS = ("tick_error", "barren_generation", "barren_streak",
                   "moat_deferred", "moat_provisional", "zero_yield")


def alerts_for_tick(tick: dict, consecutive_barren: int = 0) -> list[dict]:
    """Derive zero or more alert specs from a completed tick dict (pure — easy to unit-test).

    Conditions, worst-first:
      - tick errored                       -> CRITICAL (the daemon hit an exception this cycle)
      - generation barren (0 dossiers)     -> WARNING  (produced nothing to even judge);
                                              CRITICAL once `consecutive_barren` >= 3 — a barren
                                              STREAK means the generation chain is dead (expired
                                              `claude /login`, exhausted provider credits), not a
                                              one-off dedup/DEFER blip. Proven 2026-07-28: 26 days
                                              of hourly-throttled WARNINGs while the engine was down.
      - all candidates deferred            -> CRITICAL (moat outage — nothing could be vetted)
      - moat degraded (provisional > 0)    -> CRITICAL (trusted moat down; cheap tail ruled)
      - zero yield (dossiers>0, passes==0) -> WARNING  (factory ran but stocked nothing)
    A guard-skipped tick (PAUSE / spend cap) is NOT an alert — that is intended, controlled idle.
    `consecutive_barren` is the number of ticks in the CURRENT barren streak BEFORE this one
    (the caller counts trailing dossiers==0 rows in ticks.jsonl).
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
    defers = int(res.get("defers", 0) or 0)
    provisional = int(res.get("provisional", 0) or 0)

    if dossiers == 0:
        if consecutive_barren >= 3:
            return [{"severity": CRITICAL, "key": "barren_streak",
                     "title": f"Generation DEAD: {consecutive_barren + 1} consecutive barren ticks",
                     "message": ("The generation chain has produced nothing for "
                                 f"{consecutive_barren + 1} ticks in a row — this is an outage, not "
                                 "a blip. Check, in order: (1) `claude -p \"OK\"` works — an expired "
                                 "subscription login fails instantly with api_error; fix with "
                                 "`claude /login`. (2) Tail-provider credits (minimax status_code "
                                 "2056 = token plan exhausted). (3) launchd.err.log for "
                                 "'generation chain exhausted'."),
                     "ts_tick": tick.get("ts")}]
        return [{"severity": WARNING, "key": "barren_generation",
                 "title": "Generation produced 0 candidates",
                 "message": "A real batch ran but generated nothing to vet (dedup/generation DEFER?).",
                 "ts_tick": tick.get("ts")}]
    if defers >= dossiers and defers > 0:
        # Every candidate deferred — the moat (Claude AND Gemini) is exhausted or grounding is
        # down. This is an infra OUTAGE, not a calibration result; flag it distinctly + loudly.
        return [{"severity": CRITICAL, "key": "moat_deferred",
                 "title": f"Moat outage: all {defers} candidates DEFERRED",
                 "message": ("Verification could not run — every moat provider exhausted (or "
                             "grounding is down). Nothing was vetted. The daemon re-vets "
                             f"{_RESUME_HINT} of the backlog at the head of each tick; "
                             "`vet --resume` drains the rest in one pass."),
                 "ts_tick": tick.get("ts")}]
    if provisional > 0:
        # The trusted moat (Claude/Gemini) was exhausted, so the guardrailed cheap tail
        # (deepseek/minimax) ruled these verdicts PROVISIONALLY. They never publish and auto
        # re-vet. This is an infra DEGRADATION the all-DEFER `moat_deferred` check misses (a
        # provisional batch defers nothing), so without this the moat can be down for hours and
        # the founder hears nothing. Fire CRITICAL — "if it fails for ANY reason, I need to know".
        return [{"severity": CRITICAL, "key": "moat_provisional",
                 "title": f"Moat degraded: {provisional}/{dossiers} verdicts ruled by FALLBACK brain",
                 "message": ("The trusted moat was exhausted, so the cheap tail "
                             "(deepseek/minimax) ruled these candidates PROVISIONALLY — they will "
                             "NOT publish. The daemon re-vets "
                             f"{_RESUME_HINT} of the DEFER/provisional backlog at the head of each "
                             "tick once the moat recovers; `vet --resume` drains the rest in one "
                             "pass. Restore a trusted brain (claude_cli on the subscription, or "
                             "fund the Anthropic API)."),
                 "ts_tick": tick.get("ts")}]
    if passes == 0:
        extra = f" ({defers} deferred — partial moat trouble)" if defers else ""
        # Diagnostic-aware: if the audit log shows ZERO verify_search rows for this
        # tick, the verifier never reached the search block — different signal than
        # "ran but everything came back unverifiable". The former is "verifier dead";
        # the latter is "verifier works but the moat is too strict / retrieval starved".
        # Note: the audit log is append-only per UTC day; reading it requires the
        # diagnostics module to be wired up. For now we emit the generic zero_yield
        # alert; a follow-up adds a pre-flight audit-count check before alerting.
        return [{"severity": WARNING, "key": "zero_yield",
                 "title": f"Zero yield: {dossiers} candidates, 0 PASS{extra}",
                 "message": ("A full batch was vetted and nothing survived. Likely an ungrounded "
                             "moat or a calibration regression. Cross-check "
                             "store/scheduler/audit/<today>.jsonl: zero verify_search rows means "
                             "the verifier never reached search (verifier dead); rows present "
                             "with all-unverifiable verdicts means retrieval starved or the "
                             "moat is too strict (see DIAGNOSTICS_LATEST.txt)."),
                 "ts_tick": tick.get("ts")}]
    return []
