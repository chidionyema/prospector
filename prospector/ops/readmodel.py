"""The ops read model — every operator READ, derived once (OPS_CONSOLE_PROGRAM §4, R16/R17/R22).

Three views, one per requirement:

  * `queue_view`    R16 — queue depth keyed to `run.drain_survey` (THE definition of backlog),
                    the lease census (held / expired / free), the measured drain rate and the ETA
                    that follows from it.
  * `pause_view`    R17 — the three pause scopes, each with the role it actually stops, read from
                    the same paths the two loops read.
  * `provider_view` R22 — every CONFIGURED tier and its RAW dead mark.

Three rules this module exists to keep, each of them a scar:

1. **No second derivation.** Backlog comes from `run.drain_survey`, the same call the drain and
   the generation brake make; decision counts come from one SQL through `Store`. A panel that
   counts rows its own way is how a dashboard and a rail come to disagree about whether the queue
   is empty (`one-reader-two-caller-shapes`).
2. **Never spend the half-open probe.** `provider_view` reads `ProviderHealth.dead_until`, never
   `is_dead` — `is_dead` can CLAIM the single probe slot (`health.py::_claim_probe`), so a panel
   refreshing every few seconds would eat the one call whose job is to measure a brain's recovery.
   `tests/ops/test_readmodel.py` asserts `_claim_probe` is never called.
3. **Call it the way the process does.** `operator.moat_primary()` reads a process global installed
   by `config.load_config` (§14.5.1): a cold import answers `{claude_cli}` while the daemon is
   ruling on `[minimax, claude_cli]`. `load_cfg()` here is the only supported entry point, and the
   views take the cfg it returns.

Nothing in this module writes. The pause CONTROL is `prospector/ops/pause.py`.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

#: Where the consumer records a completed drain pass. One line per pass that attempted work —
#: the heartbeat is overwritten every cycle, so it can say what is happening NOW but can never
#: answer "how fast is the queue draining", which is the only input an ETA has.
DRAIN_LOG_FILENAME = "consumer_drains.jsonl"

#: How far back a drain rate is measured by default.
DEFAULT_LOOKBACK_H = 24.0

#: The rate window is never treated as shorter than this, however recent the first event is.
#: Two rows drained four minutes ago is not "30 rows/hour"; a floor keeps one lucky burst from
#: minting an ETA an operator would plan around.
_MIN_RATE_WINDOW_S = 3600.0


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_cfg(path: Optional[str] = None):
    """Load config THE WAY THE ENGINE DOES, installing the process globals with it.

    `config.load_config` calls `operator.set_moat_primary` and `set_minimax_concurrency`
    (`config.py:1141-1142`). Skipping it does not merely omit a field: `operator.moat_primary()`
    then answers `MOAT_PRIMARY_DEFAULT` (`{claude_cli}`) — so a panel would report the brain that
    is ruling and publishing as untrusted. §14.5.1 of the programme is this trap; it is a read
    that is WRONG rather than missing, which is the kind nobody double-checks.
    """
    from prospector.config import load_config

    return load_config(path) if path else load_config()


# --------------------------------------------------------------------------- #
# R16 — queue depth, leases, drain rate, ETA
# --------------------------------------------------------------------------- #
def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()


def drain_log_path(cfg) -> Path:
    from prospector.scheduler import paths as _paths

    return _paths.scheduler_dir(cfg, create=False) / DRAIN_LOG_FILENAME


def _parse_ts(value: Any) -> Optional[float]:
    """Epoch seconds from either an ISO string or a number. None when it will not parse."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def drain_events(cfg, *, since: Optional[float] = None) -> list[dict]:
    """Every recorded drain pass since `since`, newest last, from BOTH producers of the record.

    The drain moved process on 2026-08-15 (the producer/consumer split), so its history is in two
    places and an ETA computed from either alone is wrong for one side of that boundary:

      * `store/scheduler/consumer_drains.jsonl` — the consumer, one line per pass that attempted
        work.
      * `store/scheduler/ticks.jsonl` — `result.resumed`, written when the PRODUCER still drained
        inside its own tick.
    """
    out: list[dict] = []
    from prospector.scheduler import paths as _paths

    for line in _read_lines(drain_log_path(cfg)):
        ts = _parse_ts(line.get("ts"))
        if ts is None or (since is not None and ts < since):
            continue
        # THE OUTCOME, not only the effort. `resumed` counts rows the drain PICKED UP; it says
        # nothing about whether any of them finished. Measured on production 2026-08-18: three
        # consecutive passes each read `resumed: 24, passes: 0, kills: 0, defers: 24` with the
        # backlog stuck at 169 — the drain was re-vetting the same rows into a DEFER every pass,
        # and the console reported a healthy 37.8 rows/hour with an ETA of 21:30 the same day.
        # A rate built from `resumed` alone cannot tell work from a treadmill.
        out.append({"ts": ts, "source": "consumer",
                    "attempted": int(line.get("attempted", 0) or 0),
                    "resumed": int(line.get("resumed", 0) or 0),
                    "passes": int(line.get("passes", 0) or 0),
                    "kills": int(line.get("kills", 0) or 0),
                    "defers": int(line.get("defers", 0) or 0),
                    "leased_skipped": int(line.get("leased_skipped", 0) or 0),
                    "backlog": (int(line["backlog"]) if str(line.get("backlog", "")).lstrip("-").isdigit()
                                else None),
                    "metered_usd": float(line.get("metered_usd", 0) or 0)})

    ticks = _paths.scheduler_dir(cfg, create=False) / "ticks.jsonl"
    for row in _read_lines(ticks):
        res = (row.get("result") or {}).get("resumed") if isinstance(row.get("result"), dict) else None
        if not isinstance(res, dict):
            continue
        ts = _parse_ts(row.get("ts"))
        if ts is None or (since is not None and ts < since):
            continue
        out.append({"ts": ts, "source": "producer_tick",
                    "attempted": int(res.get("attempted", 0) or 0),
                    "resumed": int(res.get("resumed", 0) or 0),
                    "passes": int(res.get("passes", 0) or 0),
                    "kills": int(res.get("kills", 0) or 0),
                    "defers": int(res.get("defers", 0) or 0),
                    "leased_skipped": 0,
                    "backlog": None,
                    "metered_usd": 0.0})
    out.sort(key=lambda e: e["ts"])
    return out


def _read_lines(path: Path) -> Iterable[dict]:
    """Every JSON object in a jsonl file. A torn or absent file yields nothing, never raises.

    A monitor that dies on a half-written line is a monitor that is down exactly when the thing
    it watches is busy.
    """
    try:
        raw = Path(path).read_text(errors="replace")
    except (FileNotFoundError, NotADirectoryError, OSError):
        return []
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def consumer_now(cfg, *, now: Optional[float] = None) -> dict:
    """What the consumer is doing at this second, and whether it is still moving.

    WHY THIS EXISTS. Founder, 2026-08-18: "the consumer is a mystery, not enough visibility into
    its state and real time actions, if I asked what it is doing right now and how long left, I
    don't know." Everything needed was already on disk — `consumer_heartbeat.json` carries the
    phase, the pid and the cycle — and no panel read it. The queue page showed a rate and an ETA
    and nothing about the process producing them.

    `consumer_liveness` stays the ONE reader of the heartbeat format, so the alarm and this panel
    can never disagree. This adds only what a panel needs on top of it: how long the current
    phase has been running, in seconds, and a sentence a person can read.

    A WEDGE IS THE INTERESTING CASE. Measured that afternoon: pid 678 alive and sleeping, phase
    "draining", beat 61 minutes old, while the three previous passes took 1m41s, 8m20s and less.
    Nothing anywhere said so. `phase_age_s` is what makes that visible without a shell.
    """
    now = time.time() if now is None else now
    out = {"state": "unknown", "reason": "", "phase": None, "pid": None, "age_s": None,
           "alive": False, "cycle": None, "batch": None, "resumed_total": None,
           "phase_age_s": None, "says": ""}
    try:
        from prospector.consumer import consumer_liveness

        live = consumer_liveness(cfg, now=now)
    except Exception as exc:  # noqa: BLE001 — a panel may never be the thing that breaks
        out["reason"] = f"could not read the consumer heartbeat: {exc}"
        return out

    beat = live.get("beat") or {}
    out.update({k: live.get(k) for k in ("state", "reason", "phase", "pid", "age_s", "alive")})
    for k in ("cycle", "batch", "resumed_total"):
        v = beat.get(k)
        out[k] = int(v) if isinstance(v, (int, float)) else None
    # The beat is rewritten at every phase change, so its age IS the age of this phase.
    out["phase_age_s"] = round(float(live["age_s"]), 1) if live.get("age_s") is not None else None

    phase = out["phase"]
    age = out["phase_age_s"]
    mins = f"{age / 60:.0f} min" if age is not None else "an unknown time"
    if out["state"] == "dead":
        out["says"] = "The consumer is not running. Nothing is draining the queue."
    elif out["state"] == "stopped":
        out["says"] = "The consumer was stopped on purpose. Nothing is draining the queue."
    elif out["state"] == "blocked":
        out["says"] = f"A rail is holding the consumer back on purpose: {live.get('reason') or phase}"
    elif out["state"] == "late":
        out["says"] = (f"The consumer is alive but has been in '{phase}' for {mins} without a new "
                       f"beat. That is longer than it promised, so it is probably stuck on one call.")
    elif phase == "draining":
        out["says"] = f"Re-vetting a batch of parked rows. This pass has been running {mins}."
    elif phase == "idle":
        out["says"] = "Nothing to re-vet. The consumer is waiting for work."
    elif phase in ("skipped", "error"):
        out["says"] = f"Last cycle ended '{phase}': {beat.get('error') or beat.get('skipped_reason') or ''}"
    elif phase == "starting":
        out["says"] = "The consumer just started and has not finished a pass yet."
    else:
        out["says"] = live.get("reason") or f"phase '{phase}'"
    return out


def queue_view(cfg, *, store=None, now: Optional[float] = None,
               lookback_h: float = DEFAULT_LOOKBACK_H) -> dict:
    """Queue depth + leases + drain rate + ETA.

    `backlog` is `run.drain_survey(...)`, unmodified — the same survey the drain spends its bound
    on and the generation brake counts. `by_decision` is one `GROUP BY` through `Store`, so the
    panel reconciles to `sqlite3 store/prospector.db "select decision, count(*) … group by 1"`
    exactly; the test asserts that equality rather than trusting it.

    THE EXCLUDED ROWS ARE NAMED, never absorbed. `orphaned` / `stalled` / `unpublishable` are why
    a backlog count can stop falling while the drain reports healthy passes, and a number with no
    explanation beside it is what sent an operator looking at the wrong process for a day
    (`run.py::_with_exclusions`).
    """
    from prospector import drain_state
    from prospector import run as _run
    from prospector.store import Store

    now = time.time() if now is None else now
    store = store or Store(cfg)

    max_att = drain_state.max_attempts(cfg)
    revet_dead = drain_state.revet_provisional_kills(cfg)
    survey = _run.drain_survey(store, max_attempts=max_att, revet_provisional_kills=revet_dead)
    workable = survey.workable

    by_decision = store.counts_by_decision()
    leases = store.lease_census(now=now)

    created = [str(r.get("created_at") or "") for r in workable if r.get("created_at")]
    oldest = min(created) if created else None

    since = now - lookback_h * 3600.0
    events = drain_events(cfg, since=since)
    resumed = sum(e["resumed"] for e in events)
    attempted = sum(e["attempted"] for e in events)
    rate: Optional[float] = None
    window_s: Optional[float] = None
    if events:
        window_s = max(now - events[0]["ts"], _MIN_RATE_WINDOW_S)
        rate = resumed / (window_s / 3600.0)

    # HONEST NULLS. No record, or a record of zero drained rows, produces `eta_h: None` with a
    # reason — never a large number dressed as a forecast. `a-saturated-metric-prints-as-a-
    # confident-null` is the inverse mistake and it is the same class: the operator has to be
    # able to tell "not measured" from "measured, and it is bad".
    eta_h: Optional[float] = None
    eta_reason = ""
    if rate is None:
        eta_reason = f"no drain recorded in the last {lookback_h:g}h"
    elif rate <= 0:
        eta_reason = f"{len(events)} drain pass(es) in {lookback_h:g}h resumed 0 rows"
    elif workable:
        eta_h = len(workable) / rate

    # THE RATE CAN BE MEASURED FROM A SUPERSEDED SOURCE. Drains moved from the producer's tick to
    # the consumer process on 2026-08-15; a rate carried entirely by `producer_tick` rows while a
    # consumer is alive describes a mechanism that is no longer the one doing the work. Rendering
    # that ETA without saying so is `a-probe-that-cannot-tell-periodic-from-daemon` in ETA form.
    # DID THE BACKLOG ACTUALLY FALL. `resumed` counts rows picked up, so a drain that re-vets the
    # same rows into a DEFER every pass reports a healthy rate forever. The consumer writes the
    # backlog it saw on each pass; comparing the oldest recorded one to the count now is the only
    # thing in this view that can tell work from a treadmill.
    with_backlog = [e for e in events if e.get("backlog") is not None]
    outcomes = {
        "passes": sum(int(e.get("passes", 0) or 0) for e in events),
        "kills": sum(int(e.get("kills", 0) or 0) for e in events),
        "defers": sum(int(e.get("defers", 0) or 0) for e in events),
        "leased_skipped": sum(int(e.get("leased_skipped", 0) or 0) for e in events),
        "metered_usd": round(sum(float(e.get("metered_usd", 0) or 0) for e in events), 4),
        "backlog_then": with_backlog[0]["backlog"] if with_backlog else None,
        "backlog_now": len(workable),
        "moved": ((with_backlog[0]["backlog"] - len(workable)) if with_backlog else None),
    }
    # A treadmill is: several passes, rows resumed, and the backlog no lower than when we started.
    treadmill = bool(
        len(with_backlog) >= 2
        and resumed > 0
        and outcomes["moved"] is not None
        and outcomes["moved"] <= 0
    )
    if treadmill:
        eta_h = None
        eta_reason = (
            f"{len(events)} pass(es) re-vetted {resumed} row(s) in the last {lookback_h:g}h and the "
            f"backlog went from {outcomes['backlog_then']} to {outcomes['backlog_now']}. "
            f"{outcomes['defers']} of them deferred again, {outcomes['passes']} finished. These "
            f"rows are being re-read, not drained, so there is no honest ETA to give."
        )

    caveat = ""
    if events and {e["source"] for e in events} == {"producer_tick"}:
        try:
            from prospector.consumer import consumer_liveness

            if consumer_liveness(cfg).get("state") in ("running", "blocked"):
                caveat = ("rate is from producer-era ticks only; the consumer is alive but has "
                          "recorded no drain pass yet, so this ETA describes the old mechanism")
        except Exception:  # noqa: BLE001 — a caveat may never break the view it annotates
            pass

    return {
        "now": _iso(now),
        "by_decision": by_decision,
        "backlog": {
            "workable": len(workable),
            "orphaned": len(survey.orphaned),
            "stalled": len(survey.stalled),
            "unpublishable": len(survey.unpublishable),
            "oldest_created_at": oldest,
        },
        "leases": leases,
        "consumer": consumer_now(cfg, now=now),
        "drain": {
            "outcomes": outcomes,
            "recent": [
                {"ts": _iso(e["ts"]), "source": e["source"], "attempted": e.get("attempted"),
                 "resumed": e.get("resumed"), "passes": e.get("passes"), "kills": e.get("kills"),
                 "defers": e.get("defers"), "backlog": e.get("backlog"),
                 "metered_usd": e.get("metered_usd")}
                for e in events[-8:][::-1]
            ],
            "events": len(events),
            "attempted": attempted,
            "resumed": resumed,
            "window_h": round(window_s / 3600.0, 2) if window_s else None,
            "rate_per_h": round(rate, 3) if rate is not None else None,
            "eta_h": round(eta_h, 2) if eta_h is not None else None,
            "eta_at": _iso(now + eta_h * 3600.0) if eta_h is not None else None,
            "eta_reason": eta_reason,
            "caveat": caveat,
            "sources": sorted({e["source"] for e in events}),
        },
    }


# --------------------------------------------------------------------------- #
# R17 — the three pause scopes
# --------------------------------------------------------------------------- #
#: scope -> (filename, what it stops, what keeps running, who reads it)
#:
#: The semantics are NOT restated prose: each `reader` names the call site that decides, and
#: `tests/ops/test_pause_control.py` arms each file and asserts THAT function refuses. A table
#: describing a fence it does not share code with is a doc, and docs drift.
PAUSE_SCOPES: dict[str, dict[str, str]] = {
    "all": {
        "filename": "PAUSE",
        "stops": "producer + consumer (generation AND drain)",
        "keeps_running": "nothing — this is the liability rail",
        "reader": "scheduler/guard.py::SchedulerGuard.is_paused",
        "note": "CLAUDE.md: a rail with exceptions is not a rail. It halts the whole tick.",
    },
    "generation": {
        "filename": "PAUSE_GENERATION",
        "stops": "producer generation only",
        "keeps_running": "the consumer's drain, and re-vet",
        "reader": "scheduler/run_scheduled.py::_generation_suppressed",
        "note": "The operator half-stop: stop minting new work, keep finishing the old.",
    },
    "consumer": {
        "filename": "PAUSE_CONSUMER",
        "stops": "the consumer's drain only",
        "keeps_running": "producer generation (the queue keeps filling)",
        "reader": "consumer.py::_blocked_reason",
        "note": "Arming this alone grows the backlog by design — watch queue depth.",
    },
}


def pause_view(cfg, *, now: Optional[float] = None) -> dict:
    """All three scopes, armed or not, with the body of whoever armed them.

    EXISTENCE is the semantic, in all three readers (`guard.is_paused`, the generation check and
    `consumer._blocked_reason` all call `.exists()`), so the body written by `ops/pause.py` is
    provenance only and an empty file armed by hand behaves identically.

    The body is read tolerantly: `ops/pause.py` writes JSON, an operator with a shell writes a
    sentence, and both must reach the panel. A pause that renders without a reason is the same
    to the reader as a crash.

    Re-read every cycle by the engine — no restart is needed to arm or clear one — which is why
    this panel can be a CONTROL rather than a request.
    """
    from prospector.scheduler import paths as _paths

    now = time.time() if now is None else now
    sched = _paths.scheduler_dir(cfg, create=False)
    scopes = []
    for scope, meta in PAUSE_SCOPES.items():
        path = sched / meta["filename"]
        armed = path.exists()
        body: dict = {}
        mtime = None
        if armed:
            # A HAND-ARMED PAUSE MUST STILL SAY WHY. Every runbook in the estate documents
            # `touch store/scheduler/PAUSE`, and an operator in an incident writes a sentence
            # into it rather than JSON. Until 2026-08-20 that sentence was thrown away here —
            # `json.loads` raised, `body` was reset to `{}`, and the console rendered the engine
            # stopped with `reason: null`. Measured that day on the live container: the
            # generation pause armed during the console outage carried a full explanation on
            # disk and showed the founder nothing at all, which is precisely the state
            # `ops/pause.py` warns about ("an unexplained pause reads as a crash").
            # So: JSON wins when it parses, and plain text becomes the reason when it does not.
            try:
                mtime = path.stat().st_mtime
                text = path.read_text(errors="replace").strip()
            except OSError:
                text = ""
            if text:
                try:
                    parsed = json.loads(text)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    body = parsed
                else:
                    body = {"actor": "hand", "reason": text}
        scopes.append({
            "scope": scope, "path": str(path), "armed": armed,
            "armed_at": _iso(mtime),
            "age_s": round(now - mtime, 1) if mtime else None,
            "actor": body.get("actor"), "reason": body.get("reason"),
            **{k: meta[k] for k in ("stops", "keeps_running", "reader", "note")},
        })
    return {"now": _iso(now), "scopes": scopes,
            "any_armed": any(s["armed"] for s in scopes)}


# --------------------------------------------------------------------------- #
# R22 — provider health, truthfully
# --------------------------------------------------------------------------- #
def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _configured_chains(cfg) -> list[tuple[str, list[str], str]]:
    """(role, tiers, which health file records them) for every chain the engine builds.

    `noncritical` is asked of `run._noncritical_order(cfg)` rather than read off the config value,
    because that function STRIPS forbidden tiers (`_NONCRITICAL_FORBIDDEN`, claude_cli): the
    config line and the chain the process builds are not the same list, and the panel must show
    the second one.
    """
    from prospector import run as _run

    noncritical = _as_list(getattr(cfg, "noncritical_operator", None))
    builder = getattr(_run, "_noncritical_order", None)
    if callable(builder):
        try:
            noncritical = list(builder(cfg))
        except Exception:  # noqa: BLE001 — a panel never fails on a chain it is only reporting
            pass

    retrieval = getattr(cfg, "retrieval", None)
    return [
        ("verdict", _as_list(getattr(cfg, "operator", None)), "moat"),
        ("noncritical", noncritical, "noncritical"),
        ("artifact", _as_list(getattr(cfg, "artifact_operator", None)), "moat"),
        ("marketing", _as_list(getattr(cfg, "marketing_operator", None)), "moat"),
        ("grounding", _as_list(getattr(retrieval, "provider", None)), "moat"),
    ]


def provider_view(cfg, *, now: Optional[float] = None, events_limit: int = 60) -> dict:
    """Every configured tier, its role(s), whether it may rule FINALLY, and its RAW dead mark.

    WHAT THIS FIXES (R22). `store/provider_health.json` on the live store holds marks for
    `openrouter/*`, `cursor_cli` and `standardcompute` — every one of them a deleted tier — and
    NO entry for either brain that is actually ruling. A panel that renders the FILE therefore
    lists nothing that exists and omits everything that does. This renders the CONFIGURED tiers
    and looks each one up; marks for tiers no chain names are reported separately as `orphan_marks`
    rather than shown as engine state.

    `dead_until` is the RAW read (`health.py:123`). `is_dead` would claim the half-open probe slot
    and bench a recovering brain for another window; a bookkeeping read must never spend the one
    call that measures recovery.
    """
    from prospector import health as _health
    from prospector.operator import moat_primary

    now = time.time() if now is None else now
    trusted = set(moat_primary())
    files = {"moat": _health.get_health(), "noncritical": _health.get_noncritical_health()}

    tiers: dict[str, dict] = {}
    for role, names, file_key in _configured_chains(cfg):
        for pos, name in enumerate(names):
            entry = tiers.setdefault(name, {
                "name": name, "roles": [], "health_file": file_key,
                "trusted_final": name in trusted,
            })
            entry["roles"].append({"role": role, "position": pos})

    for name, entry in tiers.items():
        health = files.get(entry["health_file"], files["moat"])
        until = health.dead_until(name)
        raw = health._load().get(name) or {}          # noqa: SLF001 — the file, verbatim, for audit
        entry["dead_until"] = _iso(until)
        entry["dead_for_s"] = round(until - now, 1) if until else None
        entry["state"] = "dead" if until else "live"
        entry["strikes"] = raw.get("strikes")
        entry["last_error"] = (raw.get("last_error") or "")[:200] or None

    known = set(tiers)
    orphans = []
    for file_key, health in files.items():
        for name, raw in (health._load() or {}).items():   # noqa: SLF001
            if name in known:
                continue
            until = float(raw.get("dead_until", 0) or 0)
            orphans.append({"name": name, "health_file": file_key,
                            "dead_until": _iso(until) if until else None,
                            "expired": until <= now})

    ordered = sorted(tiers.values(), key=lambda t: (t["roles"][0]["role"], t["roles"][0]["position"]))
    return {
        "now": _iso(now),
        "trusted_final": sorted(trusted),
        "tiers": ordered,
        "orphan_marks": sorted(orphans, key=lambda o: o["name"]),
        "moat_blind": _health.moat_blind_reason(cfg, trusted_only=False),
        "drain_blind": _health.moat_blind_reason(cfg, trusted_only=True),
        # WHAT HAPPENED, not just what is true now. The tiers above are a snapshot, and a
        # snapshot cannot answer "did it repair itself?" — the mark is deleted on recovery, so
        # a healed outage and an outage that never happened render identically. These rows are
        # the transitions themselves: benched, half-open probe, recovered.
        "events": _health.recent_events(events_limit),
    }


# --------------------------------------------------------------------------- #
# One call for a surface that wants the lot
# --------------------------------------------------------------------------- #
def snapshot(cfg=None) -> dict:
    """All three views. What a phone card and a desk page both render."""
    cfg = cfg if cfg is not None else load_cfg()
    return {"queue": queue_view(cfg), "pause": pause_view(cfg), "providers": provider_view(cfg)}


def main(argv: Optional[list[str]] = None) -> int:
    """`python -m prospector.ops.readmodel [--json]` — the same views, for a surface that is not
    Python (the Telegram gateway lives in another repo and shells out)."""
    import argparse

    ap = argparse.ArgumentParser(description="Ops read model (R16/R17/R22)")
    ap.add_argument("--view", choices=["all", "queue", "pause", "providers"], default="all")
    ap.add_argument("--config", default=os.environ.get("PROSPECTOR_CONFIG") or None)
    args = ap.parse_args(argv)

    cfg = load_cfg(args.config)
    view = {"all": snapshot, "queue": queue_view,
            "pause": pause_view, "providers": provider_view}[args.view]
    print(json.dumps(view(cfg), indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
