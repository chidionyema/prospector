"""Read-only engine state for the `🎛 Now` view + the per-tick digest.

WHY THIS MODULE EXISTS. The engine already records every signal a "how is the factory running?"
view could want — heartbeats, ticks, spend, audit, provider health, active alerts, backlog — but
they live in seven files and an LLM has to assemble them per question. `status_snapshot` joins
them into one JSON-safe dict so both the per-tick digest pusher
(`run_scheduled._emit_tick_digest`) and the future Hermes renderer can consume the same shape
without re-deriving it.

Read-only by design. No new on-disk state, no write paths, no clock injection: this module is a
function of the existing files, and the existing files are the source of truth. NEVER RAISES:
every read is independently try/except'd so a single missing or corrupt file degrades that field
to None and the rest of the snapshot is still returned. The Telegram pusher is the caller, and a
status reader that crashes the pusher is the same defect as a ticker that crashes the daemon.

The dry-run gating-row filter (`dry_run != True AND result is not None`) is load-bearing: an
external driver appends ~60 dry-run rows/hour to ticks.jsonl (see `_append_tick`), and until
2026-08-08 the founder saw a "last tick = budget check" rather than the real outcome.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospector.scheduler import paths

logger = logging.getLogger(__name__)


# Cap the tick-log scan. The file is append-only and grows at the daemon cadence; a snapshot
# needs only the trailing window. Mirrors `_TICK_SCAN_LINES` in `run_scheduled.py` so the two
# readers agree on what "recent" means.
_TICK_SCAN_LINES = 5000


def _safe_read_json(path: Path) -> dict | None:
    """Best-effort JSON load. None on any failure — a missing file is not an error here."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("status_snapshot: %s unreadable, ignoring (%s)", path, exc)
        return None


def _read_daemon(cfg) -> dict:
    """Read heartbeat.json. None fields when missing/unreadable."""
    empty = {"pid": None, "phase": None, "last_tick_age_s": None, "ts": None}
    beat = _safe_read_json(paths.scheduler_dir(cfg) / "heartbeat.json")
    if not isinstance(beat, dict):
        return empty
    pid = beat.get("pid")
    phase = beat.get("phase")
    ts = beat.get("ts")
    age: float | None = None
    if isinstance(ts, str) and ts:
        try:
            stamp = datetime.fromisoformat(ts)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            if age < 0:
                # A clock that ran backwards reads as "ahead of now"; clip rather than report
                # a negative age that a downstream format would render as "-5s ago".
                age = 0.0
        except (TypeError, ValueError):
            age = None
    return {"pid": int(pid) if isinstance(pid, (int, float)) else None,
            "phase": phase if isinstance(phase, str) else None,
            "last_tick_age_s": age, "ts": ts if isinstance(ts, str) else None}


def _iter_real_ticks(cfg) -> list[dict]:
    """Read ticks.jsonl (tolerantly) and return every row, NEWEST LAST.

    Tolerates a torn trailing line and JSON decode errors per the
    `prospector.jsonl_atomic.read_jsonl` contract — the daemon appends here too, and the
    snapshot must not raise on a half-written row."""
    try:
        from prospector.jsonl_atomic import read_jsonl
        rows = read_jsonl(paths.scheduler_dir(cfg) / "ticks.jsonl", tail=_TICK_SCAN_LINES,
                          warn=False)
    except (OSError, ValueError) as exc:
        logger.warning("status_snapshot: ticks.jsonl unreadable (%s)", exc)
        return []
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
    return out


def _last_real_tick(cfg) -> dict | None:
    """The newest tick row whose `dry_run` is not True AND whose `result` is a real dict.

    This is the only filter that matters. A dry-run gating row has `dry_run=True` AND
    `result=None` (see `hermes-cron-writes-dry-run-tick-rows.md`); an external driver
    appends these every ~60s and they MUST NOT count as the "last tick" the founder sees
    in the digest — the operator needs the real outcome, not a budget check."""
    rows = _iter_real_ticks(cfg)
    for row in reversed(rows):
        if row.get("dry_run") is True:
            continue
        if not isinstance(row.get("result"), dict):
            continue
        return row
    return None


def _read_spend(cfg) -> dict:
    """Today's spend as recorded on the most recent tick row.

    The guard (`scheduler/guard.py:158`) re-derives these from `prospector.jsonl` on every
    tick and stamps them on the row, so a tick row is the cheapest correct source — no
    second scan, no disagreement with the figure the tick was logged with. The default of
    None on a fresh store is what the test asserts.

    Spend is read from the LAST tick row regardless of `result`: a guard-skipped tick (PAUSE
    / spend cap) carries the spend figure for the day even though it produced no candidates,
    and so does a dry-run gating row. The "real outcome" filter (`_last_real_tick`) applies
    only to the `last_tick` field, where it matters — a dry-run row in the last_tick slot
    would mislead the founder into reading a budget check as a real batch."""
    rows = _iter_real_ticks(cfg)
    today_usd: float | None = None
    cap_usd: float | None = None
    sub_usd: float | None = None
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        for src_key, dst_key in (("today_spend_usd", "today_usd"),
                                  ("daily_cap_usd", "daily_cap_usd"),
                                  ("today_subscription_usd", "today_subscription_usd")):
            val = row.get(src_key)
            if not isinstance(val, (int, float)):
                continue
            if dst_key == "today_usd" and today_usd is None:
                today_usd = float(val)
            elif dst_key == "daily_cap_usd" and cap_usd is None:
                cap_usd = float(val)
            elif dst_key == "today_subscription_usd" and sub_usd is None:
                sub_usd = float(val)
        if today_usd is not None or cap_usd is not None or sub_usd is not None:
            break
    return {"today_usd": today_usd, "daily_cap_usd": cap_usd,
            "today_subscription_usd": sub_usd, "monthly_usd": None}


def _read_providers(cfg) -> dict:
    """Dead providers + the moat brain list + whether every moat brain is currently dead.

    `moat_blind` is True iff the moat_brains set is non-empty AND every entry has a live
    `dead_until` mark in `provider_health.json`. Reads the same on-disk file as
    `prospector.health.ProviderHealth` so a snapshot cannot disagree with the live gate."""
    store = paths.store_dir(cfg)
    payload = _safe_read_json(store / "provider_health.json") or {}
    providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(providers, dict):
        providers = {}
    dead: list[str] = []
    now = datetime.now(timezone.utc).timestamp()
    for name, entry in providers.items():
        if not isinstance(entry, dict):
            continue
        until = entry.get("dead_until")
        if isinstance(until, (int, float)) and until > now:
            dead.append(str(name))
    moat_brains_raw = payload.get("moat_brains") if isinstance(payload, dict) else None
    moat_brains_list = [str(b) for b in moat_brains_raw] if isinstance(moat_brains_raw, list) else []
    blind = bool(moat_brains_list) and all(b in dead for b in moat_brains_list)

    # moat_blind_reason comes from the ONE function the daemon's own preflight calls, not from
    # a file. This used to JSON-parse `scheduler/DIAGNOSTICS_LATEST.txt`, which is a text report
    # (it opens with a box-drawing rule), so the parse raised on every call, the warning was
    # swallowed as "missing is fine", and `blind_reason` was structurally None forever. No file
    # under `store/scheduler/` contains `moat_blind` at all.
    # `trusted_only=False` matches the generation preflight (`run_scheduled.py:504`): one live
    # brain of any tier means the daemon is not blind. It reads raw `dead_until`, so this cannot
    # consume the half-open probe slot a real verdict call should get.
    blind_reason: str | None = None
    try:
        from prospector.health import moat_blind_reason
        reason = moat_blind_reason(cfg, trusted_only=False)
        blind_reason = reason or None
    except Exception as exc:  # a monitor must never be the thing that breaks a tick
        logger.warning("status_snapshot: moat_blind_reason failed (%s)", exc)

    return {"moat_blind": blind, "dead": dead, "moat_brains": moat_brains_list,
            "blind_reason": blind_reason}


def _read_alerts(cfg) -> dict:
    """The `_active` map from `alert_state.json`, flattened to a list of alert dicts.

    Values only — the keys duplicate `record["key"]` so the digest can show them without
    keeping a separate map. `_active` is the same field `alerts.active_alerts` reads."""
    payload = _safe_read_json(paths.scheduler_dir(cfg) / "alert_state.json") or {}
    active = payload.get("_active") if isinstance(payload, dict) else None
    if not isinstance(active, dict):
        return {"active": [], "active_count": 0}
    items = []
    for record in active.values():
        if isinstance(record, dict):
            items.append(dict(record))
    return {"active": items, "active_count": len(items)}


def _read_backlog(cfg) -> dict:
    """Backlog from the dossier INDEX — the same two populations the drain works from.

    None on any failure, never 0: a monitor that reports an unreadable count as "empty" is the
    worst possible reading of it.

    This globbed the dossier directory until 2026-08-08 and was wrong three ways at once,
    measured against the live store on that date:

      * `*.pass.json` counts PASSES, not defers. Deferred dossiers are written `*.defer.json`.
        The glob said **76** (the pass count) where the index held **121** defers.
      * Nothing is ever written as `*.provisional.json` — `provisional` is a COLUMN on the
        index row (`store.py:34`), not a filename suffix. The glob therefore reported a
        confident **0** against the index's **154**, and the test that pinned it invented a
        `c.provisional.json` fixture the engine never writes.
      * A file scan disagrees with the index even where the names are right (113 vs 158 on
        2026-08-05). The drain works from the index, so the index is the only number that means
        anything; a monitor that contradicts the engine is worse than no monitor.

    Tombstoned rows are excluded because `drain_survey` excludes them (`run.py:1414-1415`):
    they have no dossier JSON behind them and can never be re-vetted, and 46 of the 189
    tombstones are backlog rows. `total` de-duplicates by candidate_id — a row can be BOTH a
    defer and provisional, so `deferred + provisional` overstates the work that exists.
    """
    deferred: int | None = None
    provisional: int | None = None
    total: int | None = None
    try:
        from prospector.store import Store
        store = Store(cfg)
        def_rows = [r for r in store.all(decision="defer") if not r.get("tombstone")]
        prov_rows = [r for r in store.provisional() if not r.get("tombstone")]
        deferred = len(def_rows)
        provisional = len(prov_rows)
        total = len({r.get("candidate_id") for r in def_rows}
                    | {r.get("candidate_id") for r in prov_rows})
    except Exception as exc:  # sqlite is not just OSError, and a monitor must not raise
        logger.warning("status_snapshot: backlog index unreadable (%s)", exc)
    return {"deferred": deferred, "provisional": provisional, "total": total}


def status_snapshot(cfg) -> dict:
    """Read-only engine state, JSON-safe for cross-process transport.

    Returns a dict with the union asked for in the planning question:
      - daemon:    {pid, phase, last_tick_age_s, ts}
      - last_tick: {ts, dossiers, passes, kills, defers, provisional, cost_usd, duration_s}
                   — None if no tick on record
      - spend:     {today_usd, daily_cap_usd, today_subscription_usd, monthly_usd}
      - providers: {moat_blind, dead, moat_brains, blind_reason}
      - alerts:    {active, active_count}
      - backlog:   {deferred, provisional}

    Never raises. On any read failure, the offending field is None and the rest is
    returned. `cfg` must expose `store_dir` (see `prospector/scheduler/paths.py`); the
    caller of a hand-rolled cfg without it will hit the standard ValueError from that
    module — this function does not soften it, because that ValueError is the fence that
    kept tests out of the live store."""
    daemon = _read_daemon(cfg)
    last = _last_real_tick(cfg)
    last_tick: dict | None = None
    if isinstance(last, dict):
        res = last.get("result") or {}
        last_tick = {
            "ts": last.get("ts"),
            "dossiers": int(res.get("dossiers", 0) or 0),
            "passes": int(res.get("passes", 0) or 0),
            "kills": int(res.get("kills", 0) or 0),
            "defers": int(res.get("defers", 0) or 0),
            "provisional": int(res.get("provisional", 0) or 0),
            "cost_usd": (float(res["total_cost_usd"]) if isinstance(res.get("total_cost_usd"),
                          (int, float)) else None),
            "duration_s": (float(res["duration_s"]) if isinstance(res.get("duration_s"),
                            (int, float)) else None),
        }
    return {
        "daemon": daemon,
        "last_tick": last_tick,
        "spend": _read_spend(cfg),
        "providers": _read_providers(cfg),
        "alerts": _read_alerts(cfg),
        "backlog": _read_backlog(cfg),
    }


def _fmt_age(seconds: float | None) -> str:
    """A compact "Xs/Xm/Xh ago" string. None → "—". Never empty."""
    if seconds is None:
        return "—"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if s < 0:
        s = 0.0
    if s < 60:
        return f"{int(s)}s"
    if s < 3600:
        return f"{int(s // 60)}m"
    if s < 86400:
        return f"{int(s // 3600)}h"
    return f"{int(s // 86400)}d"


def _fmt_money(v: float | None) -> str:
    """USD figure with two decimals; None → "—". Never empty (digest must be ≤600 chars)."""
    if v is None:
        return "—"
    try:
        return f"${float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_count(v: Any) -> str:
    """Int with no decimals, or "—" on None/non-numeric. Keeps the digest compact."""
    if v is None:
        return "—"
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return str(v)


def format_status_snapshot(snap: dict) -> str:
    """One Telegram-ready message (≤ 600 chars). Pure stdlib; no Telegram deps.

    The format is intentionally compact: a single line the founder can glance at on a
    phone. Symbols are ASCII (`!`, `?`, `|`); emoji are kept only where the test asserts
    them (`⚠` for an active alert). Length is bounded so the message fits in any sane
    Telegram render even on the busiest tick."""
    daemon = snap.get("daemon") or {}
    last = snap.get("last_tick")
    spend = snap.get("spend") or {}
    providers = snap.get("providers") or {}
    alerts = snap.get("alerts") or {}
    backlog = snap.get("backlog") or {}

    phase = daemon.get("phase") or "idle"
    age = _fmt_age(daemon.get("last_tick_age_s"))
    pid = daemon.get("pid")
    pid_s = f" pid={pid}" if isinstance(pid, int) else ""

    cost_s = ""
    if isinstance(last, dict):
        ts = (last.get("ts") or "")[:19]
        dossiers = _fmt_count(last.get("dossiers"))
        passes = _fmt_count(last.get("passes"))
        defers = _fmt_count(last.get("defers"))
        tick_line = (f"tick@{ts} d={dossiers} pass={passes} def={defers}"
                     if ts else f"tick d={dossiers} pass={passes} def={defers}")
        cost = last.get("cost_usd")
        if isinstance(cost, (int, float)):
            cost_s = f" ${float(cost):.2f}"
    else:
        tick_line = "no tick on record — idle"

    today = _fmt_money(spend.get("today_usd"))
    cap = _fmt_money(spend.get("daily_cap_usd"))
    sub = _fmt_money(spend.get("today_subscription_usd"))
    spend_line = f"spend {today}/{cap} sub {sub}"

    if providers.get("moat_blind"):
        providers_line = "providers MOAT BLIND"
    else:
        dead = providers.get("dead") or []
        if dead:
            providers_line = f"providers {len(dead)} dead: {','.join(dead[:3])}"
        else:
            providers_line = "providers healthy"

    active = alerts.get("active") or []
    if active:
        first = active[0]
        title = str(first.get("title") or first.get("key") or "alert")
        alerts_line = f"⚠ {title}"
    else:
        alerts_line = "alerts clear"

    deferred = backlog.get("deferred")
    provisional = backlog.get("provisional")
    total = backlog.get("total")
    backlog_line = (f"backlog def={_fmt_count(deferred)} prov={_fmt_count(provisional)}"
                    # `def + prov` double-counts the rows that are both, so state the de-duped
                    # total rather than let the reader add two numbers that overlap.
                    + (f" = {total}" if isinstance(total, int) else "")
                    if deferred is not None or provisional is not None
                    else "backlog —")

    msg = (f"Prospector {phase} ({age} ago{pid_s}) | {tick_line}{cost_s} | {spend_line} | "
           f"{providers_line} | {backlog_line} | {alerts_line}")
    # Hard cap: tests assert ≤ 600 chars. Truncate with a tail marker so the operator
    # sees a message was cut rather than thinking the snapshot was complete.
    if len(msg) > 600:
        msg = msg[:596] + " ..."
    return msg
