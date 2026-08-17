"""The console gateway — one JSON contract over the six ops read models.

WHY THIS EXISTS
---------------
`docs/ADMIN_CONSOLE_PROGRAM.md` replaces the Streamlit console with a Next.js app. That app runs
in Node, so it cannot import `prospector.ops` — it has to spawn Python. It could spawn the six
modules' own `main()` entry points, but they have six different argv shapes: `--view`,
`--runs/--run/--candidate`, a positional `arm|disarm|show`, a positional `show|set`. Six argv
shapes in TypeScript is six places to get an argument wrong, and an argument gone wrong on a
pause control is an engine that does not stop.

So: one dispatcher, one contract.

    python -m prospector.ops.console_api read <view> [--arg k=v ...]
    python -m prospector.ops.console_api act  <action> --payload '<json>' [--confirm <token>]

Exactly one JSON object goes to stdout. Nothing else ever does — a stray `print` upstream would
make the response unparseable, so stdout is captured and re-emitted on stderr while the real
document is written to the real stdout (`_quiet_stdout`).

THE THREE RULES THIS FILE ENFORCES
----------------------------------
1. **No metric is computed here.** Every number is whatever `prospector.ops.*` returned. This file
   dispatches, times, and serialises. When the console and the drain disagree about the backlog,
   it is because someone counted twice; this file makes that impossible by never counting.

2. **Reads cannot write.** `read` never imports the write half of `pause`/`routing` and never
   touches `config_editor`. The verb in argv is the fence.

3. **Writes need a confirmation token, and the token check is HERE, not in the UI.** A fence in
   the keyboard is a fence a second caller walks around (`ops/pause.py` says the same thing about
   scopes). `act --preview` returns what would change plus a token; `act` without a valid token is
   refused and the refusal is logged like any other intent.

WHAT IT DELIBERATELY CANNOT DO
------------------------------
No price write. `prospector/bridge.py` is the money rail: one `PriceDecision` mints the Stripe
Price and writes the catalogue row together so they cannot drift. There is no action verb here
that touches a price, and `ADMIN_CONSOLE_PROGRAM.md` §7 specifies the flow for whoever builds it.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from prospector import content_contract

#: Bumped when the JSON contract changes shape. The web app asserts on it at boot, so a console
#: talking to an older engine says so instead of rendering blanks.
CONTRACT_VERSION = 1

#: Confirmation tokens are derived from a salt that lives on disk beside the intent log, so the
#: token a preview issued survives the Node process that asked for it (Next.js API routes are
#: stateless and a phone refresh is a new request).
SALT_FILENAME = ".console_salt"

#: How long a preview's token stays valid. Long enough to read the preview on a phone, short
#: enough that a token found in a shell history tomorrow is dead.
CONFIRM_TTL_S = 600


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@contextmanager
def _quiet_stdout():
    """Capture anything the engine prints so it cannot corrupt the JSON document.

    `run.drain_survey`, config loading and several readers print progress. One stray line and
    `JSON.parse` fails in the browser with a message that blames the console.
    """
    real = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    try:
        yield
    finally:
        sys.stdout = real
        noise = buf.getvalue()
        if noise.strip():
            sys.stderr.write(noise)


def _envelope(kind: str, name: str, started: float, *, data: Any = None,
              error: Optional[str] = None, error_kind: Optional[str] = None) -> dict:
    """Every response has the same shape, and every response is dated.

    `as_of` is not decoration. Every screen in the console states when its data was read, because
    stale data that looks live is the defect this console has had repeatedly (a landing page once
    read `Engine idle` off a 16-day-old job while the consumer was ruling).
    """
    now = time.time()
    return {
        "ok": error is None,
        "contract": CONTRACT_VERSION,
        kind: name,
        "as_of": now,
        "as_of_iso": _now_iso(),
        "took_ms": round((now - started) * 1000.0, 1),
        "data": data,
        "error": error,
        "error_kind": error_kind,
    }


def _fail(kind: str, name: str, started: float, exc: BaseException) -> dict:
    return _envelope(kind, name, started, error=f"{exc}", error_kind=type(exc).__name__)


def _cfg(config_path: Optional[str] = None):
    """The ONLY way this module gets a config.

    `readmodel.load_cfg` installs the process globals. A cold `import prospector.operator` answers
    `moat_primary() == {claude_cli}` while the daemon rules on `[minimax, claude_cli]`, so a panel
    that skipped this step would report the wrong roster with total confidence.
    """
    from .readmodel import load_cfg

    return load_cfg(config_path)


def _store_ops_dir(cfg) -> Path:
    from prospector.scheduler import paths as _paths

    d = _paths.store_dir(cfg) / "ops"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def _read_status(cfg, args: dict) -> dict:
    """The `/` screen: is it running, is it healthy, and how do I know.

    Composed from the read models rather than from any new derivation. The heartbeats are the one
    thing read directly here, because they are two files with no reader in `ops/` yet.
    """
    from .readmodel import pause_view, provider_view, queue_view
    from .routing import routing_view

    out: dict[str, Any] = {"heartbeats": _heartbeats(cfg), "alerts": _alerts(cfg)}
    out["stuck"] = _stuck(cfg, args)
    out["supervisor"] = _supervisor_view()
    out["pause"] = pause_view(cfg)
    out["providers"] = provider_view(cfg)
    out["queue"] = queue_view(cfg, lookback_h=float(args.get("lookback_h") or 24.0))
    try:
        out["routing"] = routing_view(cfg)
    except Exception as exc:  # StaleProcessGlobal and friends are information, not a crash
        out["routing"] = {"error": f"{exc}", "error_kind": type(exc).__name__}
    out["spend"] = _spend_headline(cfg)
    return out


def _supervisor_view() -> dict:
    """Whether launchd actually HOLDS each engine job, and its pid if it does.

    A heartbeat says the process was alive a minute ago. It cannot say whether anything will
    start it again when it dies. On 2026-08-16 `com.prospector.scheduler` was not loaded into
    launchd at all, so KeepAlive had nothing to keep alive and the daemon stayed dead until a
    human ran `launchctl bootstrap` at a terminal. No screen showed that. It is also the exact
    state the Restart control acts on, so it belongs next to the button.

    `loaded` is tri-state and stays that way here: None means "could not ask launchctl", which is
    not the same as "not loaded" and must not be rendered as a fault.
    """
    from .supervisor import JOBS, job_state

    jobs = []
    for label in sorted(JOBS):
        try:
            jobs.append(job_state(label))
        except Exception as exc:  # noqa: BLE001 — one unreadable job must not blank the panel
            rec: dict[str, Any] = {"label": label, "loaded": None, "pid": None,
                                   "role": JOBS[label].get("role", "unknown")}
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["reason"] = "could not ask launchctl"
            jobs.append(rec)
    return {"jobs": jobs}


#: Phases that are DOING something rather than waiting for something. They write no `next_check`
#: because they cannot predict one, so their age measures work, not silence.
_WORKING_PHASES = frozenset({"draining", "starting", "generating"})

#: Past this, a working phase is still not called dead — the pid says that — but it is flagged so
#: an operator can see a hang. Comfortably above the longest vet measured (4127s,
#: `consumer.py:704`).
_WORKING_OVERDUE_S = 7200.0


def _heartbeats(cfg) -> dict:
    """Producer and consumer liveness, with the age of each beat spelled out.

    A heartbeat is overwritten every cycle, so it says what is happening NOW and nothing about
    history. `stale` is computed against the beat's own declared interval where it has one, so a
    slow-by-design role is not reported as dead.
    """
    from prospector.scheduler import paths as _paths

    sched = _paths.scheduler_dir(cfg)
    now = time.time()
    out = {}
    for role, filename, default_every in (("producer", "heartbeat.json", 60),
                                          ("consumer", "consumer_heartbeat.json", 60)):
        path = sched / filename
        rec: dict[str, Any] = {"role": role, "path": str(path), "present": path.exists()}
        if path.exists():
            try:
                body = json.loads(path.read_text(errors="replace"))
            except Exception as exc:  # noqa: BLE001
                body = {}
                rec["read_error"] = f"{exc}"
            rec["beat"] = body
            rec["pid"] = body.get("pid")
            rec["phase"] = body.get("phase")
            rec["code"] = body.get("code")
            ts = body.get("ts")
            rec["ts"] = ts
            age = _age_s(ts, now)
            rec["age_s"] = age
            every = float(body.get("beat_every_s") or default_every)
            # Three missed beats, floored at 5 minutes: below that a single slow cycle reads as a
            # dead role, which is the false alarm that trains an operator to ignore the panel.
            rec["stale_after_s"] = max(every * 3.0, 300.0)

            # A PROMISE BEATS A GUESS. Every sleeping beat carries `next_check`, the moment that
            # cycle intends to wake (`consumer.py:342`). Measuring lateness from the promise is
            # what the writer asked for and the reader ignored: one fixed threshold has to be
            # wrong for at least one of two cadences 5x apart (`idle_s` 60s, `blocked_s` 300s).
            promised = body.get("next_check")
            if isinstance(promised, (int, float)) and promised > 0:
                rec["next_check"] = float(promised)
                rec["late_s"] = round(max(0.0, now - float(promised)), 1)
                rec["stale"] = rec["late_s"] > rec["stale_after_s"]
            elif body.get("phase") in _WORKING_PHASES:
                # NO promise, because the phase has no predictable end. The consumer writes
                # `draining` BEFORE the drain precisely so a hang is visible, and one vet was
                # measured at 4127s against a ~251s median — so a 300s clock calls a working
                # process dead every time the tail happens. It is not silent, it is busy.
                rec["stale"] = False
                rec["working_s"] = age
                rec["overdue"] = age is not None and age > _WORKING_OVERDUE_S
                rec["why"] = (f"{body.get('phase')} — this phase does not promise a wake time, so "
                              f"age is how long it has been working, not how long it has been "
                              f"silent")
            else:
                rec["stale"] = (age is None) or (age > rec["stale_after_s"])
            rec["alive"] = bool(rec["pid"]) and _pid_alive(rec["pid"]) and not rec["stale"]
        else:
            rec.update({"age_s": None, "stale": True, "alive": False,
                        "why": "no heartbeat file — the role has never run, or store/ is not the "
                               "one the daemon writes to"})
        out[role] = rec
    return out


def _pid_alive(pid: Any) -> bool:
    """Does that pid exist. NOT proof it is our process — a recycled pid answers yes.

    That is why `alive` also requires a fresh beat: the beat proves it is ours, the pid proves it
    has not exited since. Neither alone is enough (memory: macos ps/launchctl probes report a
    false pass).
    """
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _age_s(ts: Any, now: float) -> Optional[float]:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, now - parsed.timestamp())


def _alerts(cfg) -> dict:
    """Whatever the alert rail currently holds. An empty result is 'no alarms', never a blank."""
    from prospector.scheduler import paths as _paths

    sched = _paths.scheduler_dir(cfg)
    state = sched / "alert_state.json"
    active: list[dict] = []
    note = None
    if state.exists():
        try:
            body = json.loads(state.read_text(errors="replace"))
            for key, rec in (body.get("_active") or {}).items():
                if isinstance(rec, dict):
                    active.append({"key": key, **rec})
        except Exception as exc:  # noqa: BLE001
            note = f"alert_state.json unreadable: {exc}"
    active.sort(key=lambda r: (r.get("severity") != "critical", str(r.get("ts") or "")))
    banner = sched / "ALERT.txt"
    return {
        "active": active,
        "count": len(active),
        "note": note,
        "banner": banner.read_text(errors="replace")[:4000] if banner.exists() else None,
        "banner_path": str(banner),
    }


def _stuck(cfg, args: dict) -> dict:
    """Candidates that started and never finished, on the front page instead of three clicks in.

    The engine cannot write its own `candidate_done` when it is killed (`run.py:1063`), so work
    that died leaves no error anywhere — only a missing row. That made a dead batch invisible
    until someone opened the run. `runs.unfinished` names each one, and only the ones that need
    a human are counted: work still being vetted is not a fault.
    """
    from .runs import unfinished

    try:
        view = unfinished(days=int(args.get("days") or 3))
    except Exception as exc:  # noqa: BLE001 — a broken audit read is information, not a 500
        return {"error": f"{exc}", "error_kind": type(exc).__name__, "needs_attention": None,
                "needs_attention_null_reason": "the audit log could not be read, so whether work "
                                               "is stuck is unmeasured — treat this as unknown, "
                                               "not as clear"}
    worst = [e for e in view["items"] if e["state"] != "in_flight"]
    return {
        "needs_attention": view["needs_attention"],
        "in_flight": view["counts"]["in_flight"],
        "counts": view["counts"],
        "window_days": view["window_days"],
        "stall_after_min": int(view["stall_after_s"] // 60),
        # Capped for the front page. `needs_attention` above is the FULL count, so a long tail
        # is never silently reported as a short one.
        "items": worst[:8],
        "shown": min(len(worst), 8),
        "note": view["note"],
        # WHAT THE ENGINE WILL FIX BY ITSELF, separated from what it cannot. `unfinished` above
        # is read from the audit log and is a HISTORY: it still names work that died four days
        # ago even after the candidate has been recovered. The in-flight ledger is the LIVE
        # answer — a record is deleted the moment a verdict exists — so this is the count that
        # actually falls to zero, and the one that says whether a human has to do anything.
        "awaiting_recovery": _awaiting_recovery(cfg),
    }


def _awaiting_recovery(cfg) -> dict:
    """Abandoned work the next `vet --resume` will re-vet on its own.

    Every drain pass starts with `run._recover_orphans`, so this number needs no operator action
    and falls without one. It is reported anyway: work that is queued for repair and work that is
    lost look identical from the audit log, and the founder has to be able to tell them apart.
    """
    from .. import inflight
    from .runs import _store

    try:
        view = inflight.survey(_store(cfg).root)
    except Exception as exc:  # noqa: BLE001
        return {"count": None, "count_null_reason": f"the in-flight ledger could not be read: "
                                                    f"{exc}"}
    return {"count": view["counts"]["orphaned"], "in_progress": view["counts"]["live"],
            "unreadable": view["counts"]["unreadable"], "dir": view["dir"],
            "note": "these are re-vetted automatically at the start of every drain pass; "
                    "nothing to do"}


def _spend_headline(cfg) -> dict:
    """The four numbers the `/` screen needs, lifted from `spend_view` without re-deriving any.

    A cap of 0.0 is DISARMED, and it says so. Rendering it as "£0.00 cap" reads as the tightest
    possible ceiling when it is the absence of one.
    """
    from .spend import spend_view

    view = spend_view(cfg)
    ledger = view.get("ledger") or {}
    cap = ledger.get("cap_usd")
    return {
        "today_usd": ledger.get("today_usd"),
        "cap_usd": cap,
        "cap_armed": bool(cap),
        "warn_at_usd": ledger.get("warn_at_usd"),
        "hours_left_today": view.get("hours_left_today"),
        "day": view.get("day"),
        "source": view.get("source"),
        "warnings": view.get("warnings") or [],
    }


def _read_queue(cfg, args: dict) -> dict:
    from .readmodel import queue_view

    return queue_view(cfg, lookback_h=float(args.get("lookback_h") or 24.0))


def _read_providers(cfg, args: dict) -> dict:
    from .readmodel import provider_view

    return provider_view(cfg)


def _read_routing(cfg, args: dict) -> dict:
    from .routing import routing_view

    return routing_view(cfg)


def _read_spend(cfg, args: dict) -> dict:
    from .spend import spend_view

    return spend_view(cfg)


def _read_money(cfg, args: dict) -> dict:
    """PAY-1 on a screen. The rail's own answer, fetched through the gateway's own caller so the
    view module can be tested without a network."""
    from .money import money_view

    return money_view(cfg, _store_call)


def _read_data(cfg, args: dict) -> dict:
    """DAT-1, DAT-2, DAT-4 and AST-1 on a screen, each read from the control that owns it."""
    from .data import data_view

    return data_view(cfg)


def _read_metrics(cfg, args: dict) -> dict:
    from .metrics import snapshot

    window = args.get("window_days")
    return snapshot(cfg, window_days=float(window) if window else None)


def _read_runs(cfg, args: dict) -> dict:
    from .runs import run_index

    return run_index(days=int(args.get("days") or 3))


def _read_run(cfg, args: dict) -> dict:
    from .runs import run_view

    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("read run needs --arg run_id=<id>")
    return run_view(cfg, run_id, days=int(args.get("days") or 3))


def _read_candidate(cfg, args: dict) -> dict:
    from .runs import candidate_view

    cid = str(args.get("candidate_id") or "").strip()
    if not cid:
        raise ValueError("read candidate needs --arg candidate_id=<id>")
    return candidate_view(cfg, cid, days=int(args.get("days") or 3),
                          run_id=(args.get("run_id") or None))


def _read_config(cfg, args: dict) -> dict:
    """Every knob the console offers, grouped by what it DOES, with its current value.

    Read-only. The write path is the `config.set` action, which goes through
    `config_editor.write_config` and its line-surgical rewriter — never through a re-serialise,
    which once destroyed 1,173 comment lines of calibration record.

    `writable` is MEASURED, not declared: each knob is probed by running the real rewriter on a
    changed copy and seeing whether it resolves the line. A hardcoded "yes" would let the UI offer
    a save that the writer then refuses, which reads to the operator as a broken button rather
    than as an unreachable key.
    """
    from prospector.control_center import config_editor as ce

    raw, readable = ce._read_config_raw()
    path = ce._config_path()
    text = ""
    if readable:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            readable = False

    probes = _probe_all(text, raw) if readable else {}
    knobs = []
    for spec in KNOBS:
        key = tuple(spec["path"])
        current = _dig(raw, key)
        if not readable:
            probe = {"writable": False, "reason": "config.yaml could not be read"}
        elif current is None:
            probe = {"writable": False,
                     "reason": f"{'.'.join(key)} is not present in config.yaml. The rewriter "
                               f"never adds a key — it edits lines that exist."}
        else:
            reason = probes.get(key)
            probe = {"writable": reason is None, "reason": reason}
        knobs.append({
            **spec,
            "key": ".".join(key),
            "current": current,
            "present": current is not None,
            "moat_affecting": _key_is_moat_affecting(ce, key),
            **probe,
        })

    groups: dict[str, list] = {}
    for k in knobs:
        groups.setdefault(k["group"], []).append(k)

    return {
        "path": str(path),
        "readable": bool(readable),
        "mtime": ce.get_config_mtime(),
        "hash": ce.config_hash(raw) if readable else None,
        "lines": len(text.splitlines()),
        "groups": [{"group": g, "blurb": GROUP_BLURBS.get(g, ""), "knobs": v}
                   for g, v in sorted(groups.items(), key=lambda kv: GROUP_ORDER.index(kv[0]))],
        "certification": ce.load_certification(),
        "history": ce.read_history(limit=int(args.get("history_limit") or 50)),
        "backups": ce.list_backups(),
        "moat_affecting_keys": sorted([list(k) for k in ce.MOAT_AFFECTING_KEYS]),
        "writer": "prospector/control_center/yaml_surgery.py via config_editor.write_config",
        "writer_note": "Any path that writes this file without going through yaml_surgery is a "
                       "defect. yaml.safe_dump on this file measured 2034 lines in, 981 out — "
                       "1173 comment lines destroyed, including founder directives and "
                       "calibration receipts.",
    }


def _key_is_moat_affecting(ce, key: tuple) -> bool:
    """Does this key sit under a moat-affecting root.

    `MOAT_AFFECTING_KEYS` holds roots as well as leaves (`('schedule',)`, `('thresholds',)`), so
    a prefix match is the right test. Asking `is_moat_affecting` per knob would mean building a
    changed config for each one just to answer a label.
    """
    for entry in ce.MOAT_AFFECTING_KEYS:
        e = tuple(entry)
        if key[:len(e)] == e:
            return True
    return False


def _probe_all(text: str, raw: dict) -> dict[tuple, Optional[str]]:
    """Ask the REAL rewriter, in ONE pass, which knobs it can locate.

    This is how the console knows that `schedule.batch_size` — the wave size — cannot be edited:
    `schedule:` is a multi-line FLOW mapping (`schedule: { cadence: daily, batch_size: 50, ...`)
    and `yaml_surgery` edits block-style `key: value` lines. It refuses rather than guessing,
    which is correct; the console's job is to say so out loud instead of offering a dead button.

    One `apply_edits` call for all knobs, not one per knob. Probing individually measured 4.0s on
    a 2,316-line config — a four-second page load on a phone, to answer a question one pass
    answers. `apply_edits` returns the paths it could not resolve, which is exactly the answer.
    """
    from prospector.control_center import yaml_surgery as ys

    edits: dict[tuple, Any] = {}
    for spec in KNOBS:
        key = tuple(spec["path"])
        current = _dig(raw, key)
        if current is None:
            continue
        edits[key] = _probe_value(spec, current)
    if not edits:
        return {}
    try:
        _, unresolved = ys.apply_edits(text, edits)
    except Exception as exc:  # noqa: BLE001
        return {k: f"rewriter raised: {exc}" for k in edits}
    blocked = {tuple(u) for u in unresolved}
    return {k: (f"could not locate a single scalar line for: {'.'.join(k)}"
                if k in blocked else None)
            for k in edits}


def _probe_value(spec: dict, current: Any) -> Any:
    """A value guaranteed different from the current one, of the right type."""
    kind = spec["kind"]
    if kind == "bool":
        return not bool(current)
    if kind == "int":
        return int(current) + 1
    if kind == "float":
        return float(current) + 0.01
    if kind == "list":
        return list(current)[:-1] if len(current or []) > 1 else list(current or []) + ["__probe"]
    return f"{current}__probe"


def _read_intents(cfg, args: dict) -> dict:
    """The audit log, newest first. Refusals are in here too, and that is the point.

    A control that logs only its successes cannot answer "why did nobody publish yesterday".
    """
    path = _store_ops_dir(cfg) / "intents.jsonl"
    limit = int(args.get("limit") or 200)
    rows: list[dict] = []
    unreadable = 0
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                unreadable += 1
                continue
            if isinstance(rec, dict):
                rows.append(rec)
    rows.reverse()
    return {"path": str(path), "present": path.exists(), "total": len(rows),
            "unreadable_lines": unreadable, "rows": rows[:limit]}


def _store_api() -> tuple[str, str]:
    """Where the live shelf is, and the key that opens its internal doors.

    The catalogue is read from Store.Api, NOT from `store/listings/*.json`. The local glob has
    been wrong the whole time: 77 files on disk against 59 selling packs. The shelf the buyer
    sees is the database behind the API, and that is the only thing worth showing an operator
    who is about to pull a pack.
    """
    origin = (os.environ.get("STORE_API_ORIGIN")
              or os.environ.get("PROSPECTOR_ENTITLEMENTS_API")
              or "https://api.mumchimp.com").rstrip("/")
    key = os.environ.get("STORE_INTERNAL_API_KEY", "")
    return origin, key


def _store_call(method: str, path: str, *, body: Optional[dict] = None,
                internal: bool = False, timeout: float = 20.0) -> dict:
    import urllib.error
    import urllib.request

    origin, key = _store_api()
    if internal and not key:
        raise RuntimeError("STORE_INTERNAL_API_KEY is not set, so the internal catalogue doors "
                           "are closed. Load .env before starting the console.")
    url = f"{origin}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if internal:
        req.add_header("X-Internal-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode(errors="replace")
            return {"status": resp.status, "body": json.loads(raw) if raw.strip() else None,
                    "url": url}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        return {"status": exc.code, "body": raw[:2000], "url": url, "http_error": True}
    except Exception as exc:  # noqa: BLE001
        # An outage is the END of a measurement, not a datum. It must never come back as an
        # empty catalogue, which reads as "the shelf is empty".
        raise RuntimeError(f"could not reach the store API at {url}: {exc}") from exc


def _read_catalogue(cfg, args: dict) -> dict:
    """The live shelf, as the buyer's API reports it.

    The route is `GET /catalog`, verified at `store_platform/src/Store.Api/Program.cs:255`. It is
    NOT `/v1/catalog`; this repo has already had one session invent a versioned path and then
    read its 404 as an outage.

    It returns only packs that are `IsListed` and not `HiddenFromCatalogue`, because it is the
    buyer's endpoint. There is no internal endpoint that lists withdrawn packs, so an unlisted
    pack cannot be browsed here — the caller is told that rather than shown a shorter list with
    no explanation.
    """
    resp = _store_call("GET", "/catalog")
    body = resp.get("body")
    items = body.get("items") if isinstance(body, dict) else body
    if not isinstance(items, list):
        raise RuntimeError(f"the store API answered {resp['status']} with a shape this console "
                           f"does not recognise: {str(body)[:300]}")
    return {"origin": _store_api()[0], "status": resp["status"], "count": len(items),
            "items": items,
            "shows": "listed packs only",
            "note": "GET /catalog is the buyer's endpoint: it returns packs that are IsListed "
                    "and not HiddenFromCatalogue. Withdrawn packs are absent, and no internal "
                    "endpoint lists them — to put one back you need its id.",
            "source": "Store.Api GET /catalog (Program.cs:255), not store/listings/*.json"}


def _read_pack(cfg, args: dict) -> dict:
    """One pack: what the shelf holds, plus who moved its price and when.

    `GET /catalog/{id}` (Program.cs:329) answers 404 for a pack that is not listed, deliberately
    — the public product page is served from it, and a withdrawn pack's claims must not stay
    readable. So a 404 here means "not on the shelf", which is NOT the same as "no such pack".
    The price history below is the internal endpoint and answers either way.
    """
    pack_id = str(args.get("id") or "").strip()
    if not pack_id:
        raise ValueError("read pack needs --arg id=<pack id>")
    pack = _store_call("GET", f"/catalog/{pack_id}")
    out: dict[str, Any] = {
        "id": pack_id, "status": pack["status"], "pack": pack.get("body"),
        "listed": pack["status"] == 200,
        "listed_note": ("on the shelf" if pack["status"] == 200 else
                        "GET /catalog/{id} answered 404. That means the pack is withdrawn OR "
                        "does not exist — this endpoint deliberately does not distinguish the "
                        "two, so the catalogue never discloses which ids it once carried."),
    }
    try:
        hist = _store_call("GET", f"/internal/catalog/{pack_id}/price-history", internal=True)
        out["price_history"] = hist.get("body")
        out["price_history_status"] = hist["status"]
        # The internal route answers 404 only when the pack row itself is absent (Program.cs:1292
        # `db.Packs.FindAsync` then `Results.NotFound()`), and it does not care whether the pack
        # is listed. So the PAIR of statuses separates the two cases the public route deliberately
        # merges: 200 here + 404 there is a real pack that is off the shelf.
        if hist["status"] == 200:
            out["exists"] = True
            if not out["listed"]:
                out["listed_note"] = ("This pack exists and is OFF the shelf. The public route "
                                      "404s on it by design; the internal price history answered "
                                      "200, which is how we know the row is there.")
        elif hist["status"] == 404:
            out["exists"] = False
            out["listed_note"] = ("No pack with that id. The internal price-history route "
                                  "answered 404, and that route answers for withdrawn packs too.")
        else:
            out["exists"] = None
    except Exception as exc:  # noqa: BLE001
        out["price_history"] = None
        out["price_history_error"] = f"{exc}"
        out["exists"] = None
    out["price_note"] = ("Price is READ ONLY here. prospector/bridge.py mints the Stripe Price "
                         "and writes the catalogue row as one PriceDecision so they cannot "
                         "drift. See docs/ADMIN_CONSOLE_PROGRAM.md §7.")
    return out


def _act_catalogue_listing(cfg, payload: dict, preview: bool) -> dict:
    """Pull a pack off the shelf, or put it back.

    Uses `PATCH /internal/catalog/{id}/listing` and NOTHING else. That endpoint exists precisely
    because the obvious alternative is destructive: re-POSTing the pack to `/internal/catalog`
    with `IsListed=false` goes through an UPSERT that assigns ProviderProductId, ProviderPriceId
    and DossierRef from the request unconditionally — so pulling a pack that way silently nulls
    its Stripe ids. A moderation action would destroy the money rail. This door can only reach
    the listing bit.
    """
    pack_id = str(payload.get("id") or "").strip()
    if not pack_id:
        raise ValueError("catalogue.set_listing needs a pack id")
    if "listed" not in payload:
        raise ValueError("catalogue.set_listing needs listed: true or false")
    listed = bool(payload["listed"])
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        # The API refuses an unexplained delisting too. Refusing here as well means the operator
        # is told before the round trip, not after.
        raise ValueError("a reason is required — an unexplained delisting reads as a bug")

    if preview:
        # Reuse the read. It already pairs the public 404 with the internal price-history status,
        # which is the only way to tell "withdrawn" from "no such pack" — and telling the
        # operator "already off the shelf" when the id is a typo would be a lie.
        seen = _read_pack(cfg, {"id": pack_id})
        body = seen.get("pack") if isinstance(seen.get("pack"), dict) else {}
        now_listed = bool(seen.get("listed"))
        return {
            "action": "catalogue.set_listing", "id": pack_id,
            "found": seen.get("exists"),
            "title": (body or {}).get("title"),
            "currently_listed": now_listed,
            "currently_listed_basis": seen.get("listed_note"),
            "no_change": now_listed == listed,
            "after": listed,
            "effect": ("the pack becomes buyable on mumchimp.com"
                       if listed else "the pack disappears from the shelf; existing buyers keep "
                                      "their entitlement"),
            "warning": (None if listed else
                        "Relisting is refused by the API when the pack has no content key — "
                        "'cannot list a pack with no deliverable content'."),
            "endpoint": f"PATCH /internal/catalog/{pack_id}/listing",
            "touches_price": False,
        }

    resp = _store_call("PATCH", f"/internal/catalog/{pack_id}/listing",
                       body={"IsListed": listed, "Reason": reason}, internal=True)
    ok = 200 <= int(resp["status"]) < 300
    receipt = {"ts": _now_iso(), "actuator": "store.catalogue.set_listing", "id": pack_id,
               "actor": str(payload.get("actor") or "console"), "reason": reason,
               "nonce": str(payload.get("nonce") or ""),
               "applied": ok, "changed": ok, "listed": listed,
               "status": resp["status"], "response": resp.get("body"),
               "endpoint": f"PATCH /internal/catalog/{pack_id}/listing"}
    _record_intent(cfg, receipt)
    return receipt


def _read_tools(cfg, args: dict) -> dict:
    """The operator CLI catalogue. See `TOOLS` for why it is a table and not a directory scan."""
    root = _repo_root()
    out = []
    for tool in TOOLS:
        rel = tool["path"]
        out.append({**tool, "exists": (root / rel).exists()})
    return {"root": str(root), "tools": out,
            "note": "Run any of these with the `tools.run` action, using the tool's `id`. What "
                    "makes it safe is the preview, the confirmation token and the rollback "
                    "snapshot — not a hidden button. `risk` says what undo covers: 'local' means "
                    "all of it, 'external' means the local half only."}


def _read_undo(cfg, args: dict) -> dict:
    """The rollback points that exist, newest first."""
    from prospector.ops import undo as undo_mod

    snaps = undo_mod.list_snapshots()
    return {"snapshots": snaps, "count": len(snaps), "keep": undo_mod.DEFAULT_KEEP,
            "excluded": sorted(undo_mod.EXCLUDED),
            "covers": "the local store/ tree. NOT Stripe, NOT the live shelf, NOT config.yaml "
                      "(config has its own backups — see the config.restore action)."}


#: The shelf survey, loaded from the tool that already owns the question rather than
#: reimplemented here. `tools/verify_pass_shelf_coverage.py` reads the lint record the publish
#: path itself wrote, so it reports the engine's own finding; a second implementation here would
#: be a second opinion, and the two would drift the first time a lint check was renamed.
def _shelf_survey_module():
    import importlib.util

    path = _repo_root() / "tools" / "verify_pass_shelf_coverage.py"
    spec = importlib.util.spec_from_file_location("_shelf_survey", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"cannot load the shelf survey from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: Reasons a pack is stranded that are NOT lint checks. A pack can be blocked because it was
#: never published at all, which no rule in the content contract grades — that is a lifecycle
#: state, so it keeps its own small map here.
_SHELF_LIFECYCLE_REPAIR = {
    "never published": content_contract.PUBLISH_PENDING,
    "READY": content_contract.PUBLISH_PENDING,
}

#: Check names the stranded survey still prints under an older spelling than the linter emits
#: today. Kept so an archived receipt does not lose its button.
#: Check names the registry does not declare, mapped to the rule that covers them. Empty as of
#: 2026-08-17: `title_claim` was in here as a supposed alias of `title_new_word`, and it is not
#: an alias — `pack_linter.check_title_claims` is a live check with its own emission site. It is
#: declared in its own right now. `test_every_check_the_linters_emit_is_declared` is what keeps
#: this empty; an entry here means a real check went undeclared.
_LEGACY_CHECK_ALIASES: dict[str, str] = {}

#: Longest name first, so `title_new_word` cannot be shadowed by a bare `title` match.
_SUBSTRING_FALLBACK = tuple(sorted(
    ((r.check, content_contract.console_repair_for_check(r.check))
     for r in content_contract.RULES
     if content_contract.console_repair_for_check(r.check) != content_contract.MANUAL),
    key=lambda kv: -len(kv[0]),
))


def _shelf_repair_for(why: str, checks: list[str]) -> str:
    """The console action that repairs this stranded pack, or `manual`.

    The check-to-repair knowledge is read from `prospector.content_contract`, the same
    declaration the publish gate and the repair path read. Until 2026-08-17 this file held a
    private copy, so a new rule reached the console correct and the engine unaware — and the
    console could name a repair the engine had never heard of without anything failing.

    Checks are consulted before lifecycle phrases because a pack that is both unpublished and
    breaching a rule needs the rule fixed first: publishing it would only strand it again.
    """
    for check in checks:
        action = content_contract.console_repair_for_check(
            _LEGACY_CHECK_ALIASES.get(check, check)
        )
        if action != content_contract.MANUAL:
            return action
    for phrase, action in _SHELF_LIFECYCLE_REPAIR.items():
        if phrase in why:
            return action
    # Last resort, and only when nothing parsed. The previous version of this function matched
    # check names as substrings of the whole reason string; keeping that as a fallback means a
    # row whose `error(s): ...` line the survey did not print the usual way still gets its
    # button, instead of silently degrading to manual.
    if not checks:
        for name, action in _SUBSTRING_FALLBACK:
            if name in why:
                return action
    return content_contract.MANUAL


def _read_shelf(cfg, args: dict) -> dict:
    """Every PASS the engine produced that a buyer cannot buy, and what is holding each one back.

    This is the revenue gap stated as a number. A pack that passed every gate and is not on the
    shelf earned nothing, and until 2026-08-16 the only way to see the list was to run a script
    at a terminal.
    """
    mod = _shelf_survey_module()
    try:
        shelf = mod._shelf_ids()
    except Exception as exc:  # noqa: BLE001
        # The shelf being unreachable is UNKNOWN, not zero. Reporting 0 stranded because the
        # network failed is the same defect class as an empty default reading as "clean".
        return {"reachable": False,
                "reason": f"the live shelf could not be read: {type(exc).__name__}: {exc}",
                "shelf_packs": None, "stranded": None, "rows": []}

    root = str(_repo_root())
    rows, reasons = [], {}
    for cid, created in mod._passes(root):
        if cid in shelf:
            continue
        why = mod._why(root, cid)
        # Only the named lint checks, taken from the one place the tool prints them. A looser
        # word match reads "error(s)" and "(no lint record)" as check names and reports "s".
        checks = sorted({c.strip() for m in re.findall(r"error\(s\): ([^)]+)\)", why)
                         for c in m.split(",") if c.strip()})
        fix = _shelf_repair_for(why, checks)
        rows.append({"id": cid, "created": str(created)[:10], "why": why,
                     "checks": checks, "repair": fix})
        for c in checks or ["other"]:
            reasons[c] = reasons.get(c, 0) + 1

    by_repair: dict[str, int] = {}
    for r in rows:
        by_repair[r["repair"]] = by_repair.get(r["repair"], 0) + 1
    return {"reachable": True, "shelf_packs": len(shelf), "stranded": len(rows),
            "rows": rows, "by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            "by_repair": by_repair,
            "note": "Every row here is a pack that cleared every gate and earns nothing. "
                    "`repair` names the console action that fixes that class; `manual` means "
                    "no tool repairs it today."}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


#: How old the working-method scoreboard may be before the page says so. The nightly job
#: writes it; a page that renders a three-week-old number as if it were today's is the
#: same defect this whole view exists to fix.
_METHOD_STALE_H = 36


def _read_method(cfg: Any, args: dict) -> dict:
    """How the agents are working: founder stop rate, complaint clusters, live rules.

    The numbers come from `~/.claude/scripts/reflect.py --json`, which mines every session
    transcript on this machine. This reader only presents them, and refuses to present them
    silently when they are stale.
    """
    path = _repo_root() / "store" / "ops" / "method_metrics.json"
    if not path.exists():
        return {"present": False,
                "note": "No scoreboard yet. Run:  python3 ~/.claude/scripts/reflect.py --json",
                "generator": "python3 ~/.claude/scripts/reflect.py --json"}
    try:
        snap = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {"present": False, "note": f"unreadable scoreboard: {exc}"}

    age_h = (time.time() - path.stat().st_mtime) / 3600.0
    head = snap.get("headline", {})
    themes = snap.get("themes", [])
    untracked = [t["theme"] for t in themes if not t.get("tracked")]
    unenforced = [t["theme"] for t in themes if not t.get("enforced_live")]
    inert = [m["name"] for m in snap.get("mechanisms", []) if not m.get("live")]
    return {
        "present": True,
        "generated_at": snap.get("generated_at"),
        "age_hours": round(age_h, 1),
        "stale": age_h > _METHOD_STALE_H,
        "stale_note": (f"Scoreboard is {age_h:.0f}h old (limit {_METHOD_STALE_H}h). "
                       "Treat every number below as history, not state."
                       if age_h > _METHOD_STALE_H else ""),
        "headline": head,
        "stops": snap.get("stops", {}),
        "efficiency": snap.get("efficiency", {}),
        "predictions": snap.get("predictions", []),
        "themes": themes,
        "mechanisms": snap.get("mechanisms", []),
        "untracked": untracked,
        "unenforced": unenforced,
        "inert_mechanisms": inert,
        "generator": "python3 ~/.claude/scripts/reflect.py --json",
        "note": ("Each theme is a complaint the founder made more than once, clustered from "
                 "every session transcript. `check` is the command that reads its number; a "
                 "theme with no check is not being tracked by anything."),
    }


def _read_content_rules(cfg, args: dict) -> dict:
    """C2 of `docs/CONTENT_CONTRACT_PROGRAM.md`: how often each content rule is breached.

    `shelf` answers "which packs are stuck and what fixes them". This answers the question
    underneath it: which RULES are producing the breaches, how often, and which of them are
    already grading with nobody acting on the result.

    It reads the lint receipts the publish gate already writes. No new recorder, because a
    second count of one fact is how a dashboard ends up with two numbers for it.
    """
    from prospector.ops import content_breaches

    return content_breaches.breach_report(cfg)


READS: dict[str, Callable[[Any, dict], Any]] = {
    "method": _read_method,
    "shelf": _read_shelf,
    "content_rules": _read_content_rules,
    "status": _read_status,
    "queue": _read_queue,
    "providers": _read_providers,
    "routing": _read_routing,
    "spend": _read_spend,
    "money": _read_money,
    "data": _read_data,
    "metrics": _read_metrics,
    "runs": _read_runs,
    "run": _read_run,
    "candidate": _read_candidate,
    "config": _read_config,
    "intents": _read_intents,
    "tools": _read_tools,
    "undo": _read_undo,
    "catalogue": _read_catalogue,
    "pack": _read_pack,
}


# --------------------------------------------------------------------------- #
# The config keys the console may write
# --------------------------------------------------------------------------- #
#: Groups are named for what the knob DOES, not for its YAML path. An operator looking for "how
#: many ideas per batch" should not have to know it is called `batch_size` under `schedule`.
GROUP_ORDER = ["work", "evidence", "brains", "speed", "money"]
GROUP_BLURBS = {
    "work": "How much the engine takes on, and when it stops taking on more.",
    "evidence": "Where the engine looks for proof, and what counts as relevant.",
    "brains": "Which model rules a verdict. The highest blast radius in the portal.",
    "speed": "How many calls run at once. Throughput, not correctness.",
    "money": "The daily ceiling and where the warning fires.",
}

#: An allow-list, not a free-form path editor. `config.yaml` carries 1,362 comment lines and
#: several keys whose meaning is load-bearing in ways a form cannot express; a console that could
#: set any path would eventually set one of those from a phone at 2am.
#:
#: `high_blast` marks the three keys that decide which brain rules a verdict. They get a second,
#: explicit acknowledgement on top of the confirmation token — a casual dropdown is exactly what
#: they must not be.
KNOBS: list[dict] = [
    # ---- work ----
    {"path": ["generation", "candidates_per_signal"], "group": "work",
     "label": "Ideas invented per signal", "kind": "int", "min": 1, "max": 200,
     "help": "How many candidate ideas one signal turns into. More ideas means more verdicts to "
             "pay for, so this and the wave size together set the cost of a tick."},
    {"path": ["schedule", "batch_size"], "group": "work",
     "label": "Wave size — ideas per batch", "kind": "int", "min": 1, "max": 200,
     "help": "How many candidates one producer tick mints. Bigger waves risk the 3-hour tick "
             "deadline; scripts/gen_budget_guard.py is the check."},
    {"path": ["schedule", "lease_ttl_s"], "group": "work",
     "label": "How long a worker may hold a row (seconds)", "kind": "int",
     "min": 60, "max": 86400,
     "help": "After this the row returns to the queue. Sized off the WORST measured vet (4127s), "
             "not the median: a TTL near the average expires mid-vet and hands a live row to a "
             "second worker, which can reach the Stripe mint twice."},
    {"path": ["schedule", "backlog_cap"], "group": "work",
     "label": "Backlog brake (0 = off)", "kind": "int", "min": 0, "max": 100000,
     "help": "Above this many waiting rows a tick only drains. 0 disables it. The rate gate below "
             "is the primary brake; this is the floor of last resort, because a stock brake has "
             "unbounded memory — one outage can suppress generation indefinitely."},
    {"path": ["schedule", "gate_generation_on_grounding"], "group": "work",
     "label": "Stop inventing while search is broken", "kind": "bool",
     "help": "One bounded live search per tick. Generation is suppressed only while retrieval is "
             "ACTUALLY degraded, and it self-clears when the outage ends. Generation volume does "
             "not create backlog; failed retrieval does."},
    # ---- evidence ----
    {"path": ["retrieval", "provider"], "group": "evidence",
     "label": "Search engines, in order", "kind": "list",
     "choices": ["ddg", "exa", "claude_cli", "brave", "searxng", "fixture"],
     "help": "The grounding chain, tried in order. deepseek, minimax_search and openrouter are "
             "LLM synthesis, NOT real search — they invent URLs that get dropped, so every check "
             "comes back unverifiable. brave has no key on this machine and searxng is not "
             "running."},
    {"path": ["retrieval", "backstop_only_providers"], "group": "evidence",
     "label": "Held back for outages only", "kind": "list",
     "choices": ["ddg", "exa", "claude_cli", "brave", "searxng"],
     "help": "These answer a real outage and nothing else. They are skipped whenever an earlier "
             "provider answered at all, even off-topic, so a low-relevance escalation can never "
             "reach them. Empty restores the pre-2026-08-16 behaviour exactly."},
    {"path": ["retrieval", "min_relevance"], "group": "evidence",
     "label": "How relevant a passage must be to count", "kind": "float",
     "min": 0.0, "max": 1.0,
     "help": "Below this a passage is not evidence. Raising it escalates the search chain more "
             "often, which costs time; lowering it admits weaker passages."},
    # ---- brains (high blast) ----
    {"path": ["operator"], "group": "brains", "high_blast": True,
     "label": "Verdict chain — who is asked, in order", "kind": "list",
     "help": "The first entry that answers rules. Anything in this chain but NOT in the trusted "
             "roster below is stamped provisional, never publishes on PASS, and is re-vetted."},
    {"path": ["moat_primary"], "group": "brains", "high_blast": True,
     "label": "Trusted roster — who may rule FINALLY", "kind": "list",
     "help": "Only these may finalise a verdict and let a PASS reach the shelf. Blank falls back "
             "to operator.MOAT_PRIMARY_DEFAULT. Changing this changes what can be sold."},
    {"path": ["noncritical_operator"], "group": "brains", "high_blast": True,
     "label": "Cheap chain — generation, prescreen, scoring", "kind": "list",
     "help": "Never rules a verdict. claude_cli is BARRED here by founder directive and the "
             "builder strips it, so adding it back has no effect."},
    # ---- speed ----
    {"path": ["retrieval", "minimax_concurrency"], "group": "speed",
     "label": "MiniMax calls at once", "kind": "int", "min": 1, "max": 32,
     "help": "The ceiling on the primary brain, so this is the throughput knob. Measured clean "
             "at 16 concurrent with zero 429s."},
    {"path": ["retrieval", "claude_concurrency"], "group": "speed",
     "label": "Claude CLI calls at once", "kind": "int", "min": 1, "max": 16,
     "help": "Bounds the failover brain only, since MiniMax leads. At 2, a saturated queue once "
             "accounted for 1514s of a 1731s run."},
    # ---- money ----
    {"path": ["spend", "daily_cap_usd"], "group": "money",
     "label": "Daily spend ceiling (USD)", "kind": "float", "min": 0.0, "max": 1000.0,
     "help": "0.0 means NO CAP. The console renders 0.0 as disarmed, in red, because '£0.00 cap' "
             "reads as the tightest possible ceiling when it is the absence of one."},
    {"path": ["spend", "warn_at_usd"], "group": "money",
     "label": "Warn at (USD)", "kind": "float", "min": 0.0, "max": 1000.0,
     "help": "Where the alert rail fires, below the ceiling."},
]

KNOBS_BY_KEY: dict[str, dict] = {".".join(k["path"]): k for k in KNOBS}


def _normalise_key(key: Any) -> tuple:
    if isinstance(key, str):
        parts = tuple(p for p in key.split(".") if p)
    else:
        parts = tuple(str(p) for p in (key or ()))
    if not parts:
        raise ValueError("config.set needs a key")
    return parts


def _dig(mapping: Any, key: tuple) -> Any:
    cur = mapping
    for p in key:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _set_in(mapping: dict, key: tuple, value: Any) -> dict:
    out = dict(mapping)
    cur = out
    for p in key[:-1]:
        nxt = dict(cur.get(p) or {})
        cur[p] = nxt
        cur = nxt
    cur[key[-1]] = value
    return out


def _coerce(spec: dict, value: Any) -> Any:
    """Type and range are checked HERE, before `write_config` ever sees the value.

    A string where an int belongs would serialise as a quoted scalar and silently change the
    type the engine reads. The range bounds are a second fence: a wave size of 20000 is not a
    configuration, it is a typo on a phone keyboard.
    """
    kind = spec["kind"]
    if kind == "int":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a true/false")
        coerced: Any = int(value)
    elif kind == "float":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a true/false")
        coerced = float(value)
    elif kind == "bool":
        if isinstance(value, str):
            low = value.strip().lower()
            if low not in ("true", "false"):
                raise ValueError(f"expected true or false, got {value!r}")
            coerced = low == "true"
        else:
            coerced = bool(value)
    elif kind == "list":
        if isinstance(value, str):
            value = [v.strip() for v in value.replace(",", " ").split() if v.strip()]
        if not isinstance(value, list):
            raise ValueError("expected a list")
        coerced = [str(v) for v in value]
        choices = spec.get("choices")
        if choices:
            bad = [v for v in coerced if v not in choices]
            if bad:
                raise ValueError(f"not allowed here: {', '.join(bad)}. "
                                 f"Allowed: {', '.join(choices)}")
        if len(set(coerced)) != len(coerced):
            raise ValueError("the same entry appears twice")
        return coerced
    else:
        coerced = value
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None and coerced < lo:
        raise ValueError(f"{coerced} is below the allowed minimum {lo}")
    if hi is not None and coerced > hi:
        raise ValueError(f"{coerced} is above the allowed maximum {hi}")
    return coerced


# --------------------------------------------------------------------------- #
# The confirmation fence
# --------------------------------------------------------------------------- #
def _salt(cfg) -> str:
    path = _store_ops_dir(cfg) / SALT_FILENAME
    if path.exists():
        try:
            existing = path.read_text().strip()
            if existing:
                return existing
        except OSError:
            pass
    fresh = secrets.token_hex(16)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(fresh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return fresh


def _token(cfg, action: str, payload: dict, window: int) -> str:
    """A token binds the ACTION and its ARGUMENTS to a time window.

    Binding the arguments is the point: a token issued for "pause the consumer" cannot confirm
    "pause everything". Confirming a different action than the one previewed is exactly the
    mistake a confirmation step exists to catch.
    """
    body = json.dumps({"a": action, "p": _canonical(payload), "w": window},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((_salt(cfg) + "|" + body).encode()).hexdigest()[:20]


def _canonical(payload: dict) -> dict:
    """The parts of a payload a token commits to.

    `nonce` is excluded on purpose — the nonce makes the WRITE idempotent and is minted per
    attempt, while the token commits to what the operator was shown. Including it would force a
    fresh preview for every retry of the same decision.
    """
    return {k: v for k, v in sorted(payload.items())
            if k not in ("nonce", "confirm", "actor")}


def _valid_tokens(cfg, action: str, payload: dict) -> list[str]:
    """The current window's token and the previous one, so a preview read slowly still confirms."""
    window = int(time.time() // CONFIRM_TTL_S)
    return [_token(cfg, action, payload, window), _token(cfg, action, payload, window - 1)]


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def _act_pause_arm(cfg, payload: dict, preview: bool) -> dict:
    from .readmodel import PAUSE_SCOPES, pause_view

    scope = str(payload.get("scope") or "").strip()
    meta = PAUSE_SCOPES.get(scope)
    if meta is None:
        raise ValueError(f"unknown pause scope {scope!r}; expected one of "
                         f"{', '.join(sorted(PAUSE_SCOPES))}")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("a reason is required — an unexplained pause reads as a crash")
    if preview:
        current = {s["scope"]: s for s in pause_view(cfg)["scopes"]}
        already = bool(current.get(scope, {}).get("armed"))
        return {
            "action": "pause.arm", "scope": scope,
            "already_armed": already,
            "stops": meta["stops"], "keeps_running": meta["keeps_running"],
            "reader": meta["reader"], "note": meta["note"],
            "effect": ("already armed — arming again keeps the first armer's name and reason"
                       if already else meta["stops"]),
        }
    from .pause import arm

    return arm(cfg, scope, actor=str(payload.get("actor") or "console"),
               reason=reason, nonce=str(payload.get("nonce") or ""))


def _act_pause_disarm(cfg, payload: dict, preview: bool) -> dict:
    from .readmodel import PAUSE_SCOPES, pause_view

    scope = str(payload.get("scope") or "").strip()
    meta = PAUSE_SCOPES.get(scope)
    if meta is None:
        raise ValueError(f"unknown pause scope {scope!r}; expected one of "
                         f"{', '.join(sorted(PAUSE_SCOPES))}")
    if preview:
        current = {s["scope"]: s for s in pause_view(cfg)["scopes"]}
        rec = current.get(scope, {})
        return {
            "action": "pause.disarm", "scope": scope,
            "armed": bool(rec.get("armed")),
            "armed_by": rec.get("actor"), "armed_at": rec.get("armed_at"),
            "armed_reason": rec.get("reason"),
            "effect": (f"resumes: {meta['stops']}" if rec.get("armed")
                       else "not armed — nothing to clear"),
        }
    from .pause import disarm

    return disarm(cfg, scope, actor=str(payload.get("actor") or "console"),
                  nonce=str(payload.get("nonce") or ""))


def _act_routing_set(cfg, payload: dict, preview: bool) -> dict:
    from .routing import routing_problems, routing_view

    tiers = payload.get("tiers")
    if isinstance(tiers, str):
        tiers = [t.strip() for t in tiers.replace(",", " ").split() if t.strip()]
    tiers = [str(t) for t in (tiers or [])]
    if not tiers:
        raise ValueError("routing.set_moat_primary needs at least one tier")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("a reason is required — the roster is the publish gate")
    if preview:
        view = routing_view(cfg)
        problems = routing_problems(view.get("operator") or [], tiers)
        return {
            "action": "routing.set_moat_primary",
            "before": view.get("moat_primary_declared"),
            "after": tiers,
            "operator_chain": view.get("operator"),
            "would_be_refused": bool(problems),
            "problems": problems,
            "becomes_provisional": [t for t in (view.get("operator") or []) if t not in tiers],
            "high_blast": True,
            "requires_acknowledge_moat": True,
            "high_blast_note": "This decides which brain may rule a verdict FINALLY, and so what "
                               "can reach the shelf. It needs acknowledge_moat: true as well as "
                               "the confirmation token.",
            "takes_effect": "next scheduler tick (config.yaml is inside code_fingerprint)",
        }
    if payload.get("acknowledge_moat") is not True:
        raise ValueError("the trusted roster decides which brain may rule a verdict finally; "
                         "it needs acknowledge_moat: true as well as the confirmation token")
    from .routing import set_moat_primary

    return set_moat_primary(cfg, tiers, actor=str(payload.get("actor") or "console"),
                            reason=reason, nonce=str(payload.get("nonce") or ""))


def _act_config_set(cfg, payload: dict, preview: bool) -> dict:
    """Change ONE allow-listed knob in config.yaml.

    Goes through `config_editor.write_config`, which carries the fixes that cost real incidents:
    a line-surgical rewrite via `yaml_surgery` (a re-serialise destroyed 1,173 comment lines,
    including founder directives and calibration receipts), hard-gate validation, operator-chain
    validation against the builder, refusal BEFORE the write so a broken config never enters the
    daemon's code fingerprint and auto-deploys itself, JSON-lines history, and a
    `MOAT_AFFECTING_KEYS` set that names paths that exist.

    There is NO fallback writer here. If `yaml_surgery` cannot locate the line, the preview says
    so and the apply refuses. Falling back to a serialiser is the destruction the module exists
    to prevent.
    """
    from prospector.control_center import config_editor as ce
    from prospector.control_center import yaml_surgery as ys

    key = _normalise_key(payload.get("key"))
    label = ".".join(key)
    spec = KNOBS_BY_KEY.get(label)
    if spec is None:
        raise ValueError(f"{label!r} is not editable from the console. Editable: "
                         f"{', '.join(sorted(KNOBS_BY_KEY))}")
    if "value" not in payload:
        raise ValueError("config.set needs a value")
    value = _coerce(spec, payload["value"])
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("a reason is required — config history with no reason is a diff nobody "
                         "can explain six weeks later")

    raw, readable = ce._read_config_raw()
    if not readable or not raw:
        raise RuntimeError("config.yaml could not be parsed — refusing to write on top of a "
                           "failed read (that is what an empty config looks like)")
    path = ce._config_path()
    text = path.read_text(encoding="utf-8")
    before = _dig(raw, key)
    if before is None:
        raise ValueError(f"{label} is not present in config.yaml. The rewriter never adds a key; "
                         f"it edits lines that exist.")

    proposed = _set_in(raw, key, value)
    moat_affecting = ce.is_moat_affecting(raw, proposed)
    diff = ce.diff_configs(raw, proposed)
    valid, errors = ce.validate_config(proposed)
    high_blast = bool(spec.get("high_blast"))

    # The rewriter's own verdict, obtained by running it — not predicted.
    surgery_ok, surgery_reason = True, None
    try:
        after_text, unresolved = ys.rewrite(text, raw, proposed)
        if unresolved:
            surgery_ok, surgery_reason = False, unresolved[0]
        else:
            delta = len(after_text.splitlines()) - len(text.splitlines())
            if delta != 0:
                surgery_ok = False
                surgery_reason = (f"the edit would change the file length by {delta} lines; "
                                  f"refusing a write that is not line-for-line")
    except Exception as exc:  # noqa: BLE001
        surgery_ok, surgery_reason = False, f"rewriter raised: {exc}"

    stated_mtime = payload.get("mtime")
    conflict = bool(stated_mtime) and ce.mtime_conflict(float(stated_mtime))

    if preview:
        return {
            "action": "config.set", "key": label, "label": spec["label"],
            "before": before, "after": value, "unchanged": before == value,
            "kind": spec["kind"], "help": spec["help"], "group": spec["group"],
            "diff": diff,
            "valid": bool(valid), "validation_errors": errors,
            "writable": surgery_ok, "not_writable_reason": surgery_reason,
            "moat_affecting": bool(moat_affecting),
            "moat_note": ("This change affects the moat. Saving it drops certification to "
                          "certified: false until the golden set is re-run."
                          if moat_affecting else None),
            "high_blast": high_blast,
            "high_blast_note": ("This key decides which brain rules a verdict — the highest "
                                "blast radius in the portal. Saving it requires "
                                "acknowledge_moat: true on top of the confirmation token."
                                if high_blast else None),
            "requires_acknowledge_moat": high_blast,
            "conflict": conflict,
            "conflict_note": ("config.yaml changed on disk since you opened it. Re-read before "
                              "saving or you will overwrite someone else's edit."
                              if conflict else None),
            "certification": ce.load_certification(),
            "mtime": ce.get_config_mtime(),
            "config_path": str(path),
            "writer": "yaml_surgery via config_editor.write_config",
            "takes_effect": "next scheduler tick (config.yaml is inside code_fingerprint)",
        }

    if not surgery_ok:
        return _config_refusal(cfg, label, before, value, payload, reason,
                              f"the comment-preserving rewriter refuses this key: "
                              f"{surgery_reason}")
    if not valid:
        return _config_refusal(cfg, label, before, value, payload, reason,
                               "validation failed: " + "; ".join(errors))
    if conflict:
        return _config_refusal(cfg, label, before, value, payload, reason,
                               "config.yaml changed on disk since this edit was previewed")
    if high_blast and payload.get("acknowledge_moat") is not True:
        return _config_refusal(cfg, label, before, value, payload, reason,
                               "this key decides which brain rules a verdict; it needs "
                               "acknowledge_moat: true as well as the confirmation token")

    if before == value:
        receipt = {"ts": _now_iso(), "actuator": "engine.config.set", "key": label,
                   "actor": str(payload.get("actor") or "console"), "reason": reason,
                   "nonce": str(payload.get("nonce") or ""), "applied": True, "changed": False,
                   "before": before, "after": value,
                   "message": "already reads that; nothing written."}
        _record_intent(cfg, receipt)
        return receipt

    ok, message = ce.write_config(proposed, moat_affecting=bool(moat_affecting),
                                  orig_mtime=float(stated_mtime) if stated_mtime else 0.0)
    receipt = {"ts": _now_iso(), "actuator": "engine.config.set", "key": label,
               "actor": str(payload.get("actor") or "console"), "reason": reason,
               "nonce": str(payload.get("nonce") or ""),
               "applied": bool(ok), "changed": bool(ok),
               "before": before, "after": value if ok else before,
               "diff": diff, "moat_affecting": bool(moat_affecting), "message": message,
               "certification": ce.load_certification(),
               "takes_effect": "next scheduler tick (config.yaml is inside code_fingerprint)"}
    _record_intent(cfg, receipt)
    return receipt


def _config_refusal(cfg, label, before, value, payload, reason, why) -> dict:
    """A refusal is a receipt too. A control that logs only its successes cannot answer
    'why did nothing change when I pressed save'."""
    receipt = {"ts": _now_iso(), "actuator": "engine.config.set", "key": label,
               "actor": str(payload.get("actor") or "console"), "reason": reason,
               "nonce": str(payload.get("nonce") or ""),
               "applied": False, "changed": False,
               "before": before, "after": before, "requested": value,
               "message": f"Refused: {why}"}
    _record_intent(cfg, receipt)
    return receipt


def _act_config_restore(cfg, payload: dict, preview: bool) -> dict:
    """Roll config.yaml back to one of `config_editor`'s own backups.

    Every `write_config` takes a backup first, so the rollback path is the writer's own history
    rather than a second mechanism. A restore is moat-affecting by construction — the file it
    replaces may differ on any key — so certification drops.
    """
    from prospector.control_center import config_editor as ce

    filename = str(payload.get("filename") or "").strip()
    if not filename:
        raise ValueError("config.restore needs a backup filename")
    backups = {b.get("filename"): b for b in ce.list_backups()}
    rec = backups.get(filename)
    if rec is None:
        raise ValueError(f"no backup named {filename!r}. Available: "
                         f"{', '.join(sorted(backups)) or '(none)'}")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("a reason is required")

    if preview:
        return {"action": "config.restore", "filename": filename, "backup": rec,
                "effect": "replaces config.yaml wholesale with this backup",
                "moat_affecting": True,
                "moat_note": "A restore can change any key, so certification drops to "
                             "certified: false until the golden set is re-run.",
                "takes_effect": "next scheduler tick (config.yaml is inside code_fingerprint)"}

    ok, message = ce.restore_backup(filename)
    receipt = {"ts": _now_iso(), "actuator": "engine.config.restore", "filename": filename,
               "actor": str(payload.get("actor") or "console"), "reason": reason,
               "nonce": str(payload.get("nonce") or ""),
               "applied": bool(ok), "changed": bool(ok), "message": message,
               "certification": ce.load_certification()}
    _record_intent(cfg, receipt)
    return receipt


def _record_intent(cfg, receipt: dict) -> None:
    """Append one receipt. Never raises — an unwritable audit log must not leave the operator
    unable to act. Its absence is visible in the log; a refused control is a liability."""
    try:
        from prospector.jsonl_atomic import append_jsonl

        append_jsonl(_store_ops_dir(cfg) / "intents.jsonl", receipt)
    except Exception:  # noqa: BLE001
        pass


#: How long a shelf repair may run before the console gives up on it. The copy sweep calls a
#: model once per breaching line, so this is minutes, not seconds. A timeout is not a failure of
#: the repair — the tool writes each pack as it finishes — so the receipt says how far it got.
_SHELF_TIMEOUT_S = 1800


def _run_repair(cfg, name: str, argv: list[str], preview: bool, *, effect: str,
                payload: dict) -> dict:
    """Run one of the shelf repair tools and record what it did.

    The tools already exist and already re-grade their own output; the console's job is to make
    them reachable, not to reimplement them. Neither tool touches the money rail: the copy sweep
    rewrites one-liners and the publisher lists packs at the price the catalogue already holds.
    """
    root = _repo_root()
    python = os.environ.get("PROSPECTOR_PYTHON") or sys.executable
    cmd = [python, *argv]
    if preview:
        return {"action": name, "command": " ".join(cmd), "effect": effect,
                "moat_affecting": False,
                "takes_effect": "immediately, pack by pack, as each one is rewritten",
                "note": f"Runs for up to {_SHELF_TIMEOUT_S // 60} minutes. Nothing is priced "
                        f"or charged; this only unblocks packs the engine already passed."}

    # THE CONSOLE IS A LAUNCHD JOB, SO IT HAS NO SHELL AND NO KEYS.
    # launchd does not read ~/.zshrc, so a repair spawned from the web console starts with only
    # the handful of variables in the plist. Measured 2026-08-16: `shelf.repair_copy` returned
    # exit 1 and "no non-critical operator available — nothing rewritten", because every tier of
    # `noncritical_operator` raised `RuntimeError: MINIMAX_API_KEY not set`. The same command run
    # from a terminal worked, because the terminal already had the key exported — which is
    # exactly how this stayed invisible.
    #
    # `run._load_dotenv` is the mechanism the CLI already uses (`run.py:3742`) and it lets the
    # live environment win, so this fills gaps and never overrides the plist. It is done HERE,
    # once, rather than in each tool: the child inherits os.environ, so every repair — including
    # ones added later — gets the keys. `tools/publish_passes.py:175` already called it for
    # itself; `tools/sweep_shelf_copy.py` never did.
    try:
        from prospector.run import _load_dotenv

        _load_dotenv()
    except Exception:  # noqa: BLE001
        pass  # a missing .env is not a reason to refuse the repair; the tool will say what broke

    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                              timeout=_SHELF_TIMEOUT_S)
        out, code = (proc.stdout or "") + (proc.stderr or ""), proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = ((exc.stdout or b"").decode(errors="replace")
               + (exc.stderr or b"").decode(errors="replace")) if exc.stdout or exc.stderr else ""
        code = None

    tail = "\n".join(out.splitlines()[-40:])
    receipt = {"ts": _now_iso(), "actuator": f"engine.{name}", "command": " ".join(cmd),
               "actor": str(payload.get("actor") or "console"),
               "reason": str(payload.get("reason") or ""),
               "applied": code == 0, "changed": bool(tail), "timed_out": timed_out,
               "exit_code": code, "took_s": round(time.time() - started, 1),
               "message": tail or "(the tool printed nothing)"}
    _record_intent(cfg, receipt)
    return receipt


#: How long any catalogued tool may run from the console before it is killed. Same budget as a
#: shelf repair: these are batch tools, so minutes is normal and a timeout is not a failure.
_TOOL_TIMEOUT_S = _SHELF_TIMEOUT_S

#: `<name>` in a catalogued command is a value the operator must supply, e.g. `<idea>`.
_PLACEHOLDER_RE = re.compile(r"<([a-z0-9_]+)>")


def _tool_by_id(tool_id: str) -> dict:
    """Look a tool up in `TOOLS` by its id. The id is a hash of the catalogued command."""
    for tool in TOOLS:
        if tool["id"] == tool_id:
            return tool
    raise ValueError(f"no tool with id {tool_id!r}")


def _tool_argv(tool: dict, payload: dict) -> list[str]:
    """Turn a catalogued command into argv, filling `<placeholders>` from the payload.

    THE COMMAND COMES FROM `TOOLS`, NEVER FROM THE CALLER. The browser sends an id and values for
    named placeholders. It cannot send a command, a flag, or a path. Running a client-supplied
    string would be a web shell on the operator's machine — a different feature from "reach the
    admin tools", and not one anybody asked for.

    Values are substituted into single argv elements and the child runs without a shell, so a
    value containing `;` or `&&` is one argument, not a second command.
    """
    argv: list[str] = []
    for part in shlex.split(tool["command"]):
        missing: list[str] = []

        def _fill(match, _missing=missing):
            name = match.group(1)
            if payload.get(name) in (None, ""):
                _missing.append(name)
                return match.group(0)
            return str(payload[name])

        filled = _PLACEHOLDER_RE.sub(_fill, part)
        if missing:
            raise ValueError(f"{tool['purpose']!r} needs a value for "
                             f"{', '.join(sorted(set(missing)))}")
        argv.append(filled)

    # The catalogue writes `.venv/bin/python` because that is what an operator types. The console
    # is a launchd job whose interpreter is named in its plist, so resolve it rather than trusting
    # a relative path against whatever cwd the job happens to have.
    if argv and Path(argv[0]).name.startswith("python"):
        argv[0] = os.environ.get("PROSPECTOR_PYTHON") or sys.executable
    return argv


def _exec(cmd: list[str], cwd: Path, timeout: int) -> tuple[str, Optional[int], bool]:
    """Run a child and return (combined output, exit code, timed_out). Never raises on failure."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return (proc.stdout or "") + (proc.stderr or ""), proc.returncode, False
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"").decode(errors="replace")
               + (exc.stderr or b"").decode(errors="replace")) if exc.stdout or exc.stderr else ""
        return out, None, True


def _act_tools_run(cfg, payload: dict, preview: bool) -> dict:
    """Run any catalogued operator tool, and take a rollback snapshot first if it writes.

    This is the action that replaced the old `run=False` fence (founder directive, 2026-08-16:
    "we just need rollback to be safe not to hide actions"). A refused button did not stop a tool
    running; it moved the run to a terminal, where there is no preview, no receipt and no undo.

    What makes it safe is the same fence every other action goes through — a preview that names
    the exact command, a confirmation token bound to that payload, and a receipt — plus
    `prospector.ops.undo`. The preview states what the snapshot does NOT cover, because a tool
    that reaches Stripe or the live shelf cannot be rolled back from this machine.
    """
    from prospector.ops import undo as undo_mod

    tool = _tool_by_id(str(payload.get("id") or "").strip())
    root = _repo_root()
    if not tool["run"]:
        raise ValueError(f"{tool['path']} is not runnable from the console. {tool['danger']}")
    if not (root / tool["path"]).exists():
        raise ValueError(f"{tool['path']} is not on disk. The catalogue is hand-kept, so this "
                         f"means the tool was renamed or deleted and the table was not updated.")

    argv = _tool_argv(tool, payload)
    writes = bool(tool["writes"])

    if preview:
        return {
            "action": "tools.run", "id": tool["id"], "path": tool["path"],
            "purpose": tool["purpose"], "risk": tool["risk"], "danger": tool["danger"],
            "command": " ".join(shlex.quote(a) for a in argv),
            "effect": tool["purpose"],
            "snapshot": "a rollback snapshot of store/ is taken first" if writes
                        else "none — this tool writes nothing",
            "undo_covers": tool["undo_covers"],
            "moat_affecting": False,
            "takes_effect": "it starts immediately and keeps running if you close the page",
            "note": f"Runs in the background for up to {_TOOL_TIMEOUT_S // 60} minutes. You get a "
                    f"job id straight away and the receipt lands in the audit log when it ends." + (
                "" if tool["risk"] != "external" else
                " THIS REACHES OFF THIS MACHINE. Undo restores the local store/ tree and nothing "
                "else — a Stripe price, a published pack or an uploaded backup stays changed."),
        }

    # The snapshot is taken HERE, in the request, not in the background worker. The operator gets
    # the undo id in the same answer as the job id, so a tool that starts writing immediately can
    # already be rolled back — and a snapshot that failed refuses the run instead of being
    # discovered missing half an hour later.
    snap = None
    if writes:
        snap = undo_mod.snapshot(f"tools.run {tool['path']}", root=root,
                                 actor=str(payload.get("actor") or "console"),
                                 note=f"before: {' '.join(argv)}")

    # THE TOOL RUNS IN THE BACKGROUND, AND THE HTTP REQUEST DOES NOT WAIT FOR IT.
    #
    # `scripts/store_audit.py` measured 239.9s. Holding the request open for that (and up to 30
    # minutes for a repair) gives the operator a spinner with no progress, nothing to check from a
    # second device, and a run that dies with the tab. Every layer in between — the browser, the
    # Node gateway timeout, launchd restarting the console — is another way to lose a job that was
    # working. So the request starts the job and returns its id; the worker writes the finishing
    # receipt to the same audit log, and `read job` is how anyone asks how it went.
    #
    # `start_new_session=True` is what makes it survive: the worker gets its own process group, so
    # the console killing the gateway subprocess (ops.ts kills the GROUP on timeout) does not take
    # a running tool with it. That is the opposite of the synchronous path, where killing the
    # group is exactly right, and both are deliberate.
    job = secrets.token_hex(6)
    worker = [os.environ.get("PROSPECTOR_PYTHON") or sys.executable,
              "-m", "prospector.ops.console_api", "run-tool", tool["id"],
              "--job", job, "--payload", json.dumps({**payload, "undo_id": (snap or {}).get("id")},
                                                    default=str)]
    subprocess.Popen(worker, cwd=root, stdin=subprocess.DEVNULL,  # noqa: S603
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)

    receipt = {
        "ts": _now_iso(), "actuator": f"tools.run:{tool['path']}",
        "job": job, "state": "running",
        "command": " ".join(shlex.quote(a) for a in argv),
        "actor": str(payload.get("actor") or "console"),
        "reason": str(payload.get("reason") or ""),
        "nonce": str(payload.get("nonce") or ""),
        "risk": tool["risk"],
        "applied": True, "timed_out": False, "exit_code": None,
        "undo_id": (snap or {}).get("id"),
        "undo_covers": tool["undo_covers"],
        "message": f"started as job {job}; it runs for up to {_TOOL_TIMEOUT_S // 60} minutes and "
                   f"writes its own receipt when it ends",
    }
    _record_intent(cfg, receipt)
    return receipt


def _run_tool_job(cfg, tool_id: str, job: str, payload: dict) -> dict:
    """Run one catalogued tool to completion and write the finishing receipt. The background half.

    This is invoked ONLY by `_act_tools_run`, in a child process, AFTER the confirmation token was
    checked and the snapshot taken. It does not check a token itself and must not be treated as a
    second door: it takes a tool id from `TOOLS` exactly like the foreground path, so the worst a
    caller who can already run this module can do is run a tool they could have run by typing its
    command — which is what the catalogue is a list of.
    """
    tool = _tool_by_id(tool_id)
    argv = _tool_argv(tool, payload)

    # Same reason as `_run_repair`: launchd does not read a shell profile, so a tool spawned from
    # the console starts without the API keys a terminal already has.
    try:
        from prospector.run import _load_dotenv

        _load_dotenv()
    except Exception:  # noqa: BLE001
        pass

    started = time.time()
    out, code, timed_out = _exec(argv, _repo_root(), _TOOL_TIMEOUT_S)
    tail = "\n".join(out.splitlines()[-60:])
    receipt = {
        "ts": _now_iso(), "actuator": f"tools.run:{tool['path']}",
        "job": job, "state": "timed_out" if timed_out else "finished",
        "command": " ".join(shlex.quote(a) for a in argv),
        "actor": str(payload.get("actor") or "console"),
        "reason": str(payload.get("reason") or ""),
        "risk": tool["risk"],
        "applied": code == 0, "changed": bool(tail), "timed_out": timed_out,
        "exit_code": code, "took_s": round(time.time() - started, 1),
        "undo_id": payload.get("undo_id"),
        "undo_covers": tool["undo_covers"],
        "message": tail or "(the tool printed nothing)",
    }
    _record_intent(cfg, receipt)
    return receipt


#: A job whose worker died — a reboot, a SIGKILL, a crash before the finishing receipt — would
#: otherwise read as "running" forever. After the tool's own ceiling plus a minute of slack, an
#: unfinished job is reported LOST rather than in progress. "Still going" is a claim about a live
#: process, and nothing here can see one.
_JOB_LOST_AFTER_S = _TOOL_TIMEOUT_S + 60


def _read_job(cfg, args: dict) -> dict:
    """How one background tool run is going, read from the receipts it writes."""
    job = str(args.get("job") or "").strip()
    if not job:
        raise ValueError("a job id is required — `read job --arg job=<id>`")

    path = _store_ops_dir(cfg) / "intents.jsonl"
    rows: list[dict] = []
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("job") == job:
                rows.append(rec)

    if not rows:
        return {"job": job, "state": "unknown", "receipt": None, "rows": 0,
                "note": "no receipt carries this job id. Either it was never started or the audit "
                        "log was rotated."}

    latest = rows[-1]
    state = str(latest.get("state") or "finished")
    age_s = None
    try:
        started_ts = datetime.fromisoformat(str(rows[0].get("ts")).replace("Z", "+00:00"))
        age_s = round((datetime.now(timezone.utc) - started_ts).total_seconds(), 1)
    except (TypeError, ValueError):
        pass
    if state == "running" and age_s is not None and age_s > _JOB_LOST_AFTER_S:
        state = "lost"

    return {"job": job, "state": state, "receipt": latest, "rows": len(rows),
            "started_ts": rows[0].get("ts"), "age_s": age_s,
            "note": {"running": "still going; the receipt lands here when it ends",
                     "finished": "done — `exit_code` and `message` are the tool's own",
                     "timed_out": f"killed at {_TOOL_TIMEOUT_S // 60} minutes; whatever it wrote "
                                  f"before that is written",
                     "lost": "started but never finished, and it is past its own ceiling. The "
                             "worker died — check the tool by hand.",
                     }.get(state, "")}


#: Registered here rather than in the READS literal above because the tool-running machinery this
#: view reads is defined further down the file, and a dict literal evaluates its values at import.
READS["job"] = _read_job


def _act_tools_undo(cfg, payload: dict, preview: bool) -> dict:
    """Roll `store/` back to a snapshot taken before a tool ran.

    Rollback means the tree ends up as it was, so this deletes files written since as well as
    restoring the ones that changed. The preview counts both, because the deletion list is the
    part that can cost the operator work they wanted to keep.
    """
    from prospector.ops import undo as undo_mod

    snap_id = str(payload.get("snapshot") or "").strip()
    if not snap_id:
        snaps = undo_mod.list_snapshots()
        if not snaps:
            raise ValueError("there is no snapshot to roll back to")
        snap_id = snaps[0]["id"]

    plan = undo_mod.restore_plan(snap_id)
    if preview:
        return {"action": "tools.undo", **plan, "moat_affecting": False,
                "effect": f"puts store/ back to {snap_id}: restores {plan['restore']} file(s) "
                          f"and DELETES {plan['delete']} written since",
                "takes_effect": "immediately",
                "note": "Undo covers the local store/ tree only. It cannot take back a Stripe "
                        "price, a published pack, or an uploaded backup."}

    rec = undo_mod.restore(snap_id)
    receipt = {"ts": _now_iso(), "actuator": "engine.tools.undo", "snapshot": snap_id,
               "actor": str(payload.get("actor") or "console"),
               "reason": str(payload.get("reason") or ""),
               "nonce": str(payload.get("nonce") or ""),
               "changed": bool(rec["restored"] or rec["deleted"]), **rec}
    _record_intent(cfg, receipt)
    return receipt


def _act_shelf_repair_copy(cfg, payload: dict, preview: bool) -> dict:
    """Rewrite the shelf copy that fails the linter, so those packs can be listed."""
    argv = ["tools/sweep_shelf_copy.py", "--fix"]
    limit = payload.get("limit")
    if limit:
        argv += ["--limit", str(int(limit))]
    return _run_repair(cfg, "shelf.repair_copy", argv, preview, payload=payload,
                       effect="rewrites every shelf line that fails the copy check. A rewrite "
                              "is re-graded before it is accepted, and it may only re-word — "
                              "every figure and institution in the original must survive.")


def _pending_publish_paths(cfg) -> list[str]:
    """The dossier files for the stranded passes this action is allowed to publish.

    NAMED EXPLICITLY, never `--all`. `--all` walks every PASS in the store, including the 63
    already selling, and re-publishing a live pack re-runs the money rail on a row a buyer can
    already buy. The shelf reader already decides which rows need this repair
    (`_shelf_repair_for`), so the action publishes exactly those and nothing else.
    """
    shelf = _read_shelf(cfg, {})
    if not shelf.get("reachable"):
        # UNKNOWN is not zero. An empty list here would render as "nothing needs publishing",
        # which is the same defect class as a swallowed outage returning `[]`. Raise, so the
        # operator is told the shelf could not be read instead of being told there is no work.
        raise RuntimeError(
            f"the live shelf could not be read, so which packs are stranded is UNKNOWN, not "
            f"none: {shelf.get('reason')}")
    root = _repo_root()
    out = []
    for row in shelf.get("rows") or []:
        if row.get("repair") != "shelf.publish_pending":
            continue
        p = root / "store" / "dossiers" / f"{row['id']}.pass.json"
        if p.exists():
            out.append(f"store/dossiers/{row['id']}.pass.json")
    return sorted(out)


def _act_shelf_publish_pending(cfg, payload: dict, preview: bool) -> dict:
    """Publish the passes that were never published at all.

    Run as `-m tools.publish_passes`, NOT as a file path. `python tools/publish_passes.py` puts
    `tools/` on sys.path instead of the repo root, so the driver died on
    `ModuleNotFoundError: No module named 'prospector'` before it read a single dossier — and it
    was invoked with no arguments besides, which its own `main` answers by printing the usage and
    returning 2. Both were verified on 2026-08-16 by running the exact command this built.
    """
    paths = _pending_publish_paths(cfg)
    argv = ["-m", "tools.publish_passes", "--reuse-artifacts"]
    if payload.get("dry_run"):
        argv.append("--dry-run")
    if payload.get("cheap"):
        argv.append("--cheap")
    argv += paths
    if not paths:
        return {"action": "shelf.publish_pending", "applied": False, "changed": False,
                "message": "No stranded pass needs publishing — every pack the shelf reader "
                           "marks `shelf.publish_pending` is either already listed or its "
                           "dossier file is missing."}
    return _run_repair(cfg, "shelf.publish_pending", argv, preview, payload=payload,
                       effect=f"publishes the {len(paths)} PASS dossier(s) the shelf reader "
                              f"marks `shelf.publish_pending` — packs that cleared every gate "
                              f"and were never sent to the shelf. Named one by one; never "
                              f"`--all`, which would re-publish packs already selling.")


def _act_daemon_restart(cfg, payload: dict, preview: bool) -> dict:
    """Restart a launchd-supervised engine process from the console.

    The repair for the 2026-08-16 failure: `com.prospector.scheduler` was not loaded into launchd,
    so KeepAlive could not relaunch the daemon and it stayed dead until a human ran
    `launchctl bootstrap` at a terminal. That is a safe, mechanical repair with a known-good
    outcome, so it gets a control instead of a runbook (P10 — if it can change, the operator
    changes it from the console).

    Not destructive in the sense `index.reconcile` is: the worst case is a clean process replacing
    a running one, and the plists are the estate's own declaration of how these processes start.
    """
    from .supervisor import JOBS, PRODUCER, deploy_plist_path, job_state, restart

    label = str(payload.get("label") or PRODUCER).strip()
    if label not in JOBS:
        raise ValueError(f"unknown job {label!r}; expected one of {', '.join(sorted(JOBS))}")

    state = job_state(label)
    if preview:
        if state["loaded"] is None:
            effect = f"cannot ask launchctl ({state['reason']}) — this would do nothing"
        elif not state["loaded"]:
            if state["plist_exists"]:
                effect = (f"job is NOT loaded, so nothing can relaunch it — bootstraps "
                          f"{state['plist']}, which starts it (RunAtLoad) and keeps it up "
                          f"(KeepAlive)")
            else:
                deploy = deploy_plist_path(label)
                effect = (f"job has NEVER been installed — copies the tracked plist "
                          f"{deploy.name} from deploy/ to {state['plist']}, then bootstraps it"
                          if deploy.exists() else
                          f"job is NOT loaded, {state['plist']} does not exist and there is no "
                          f"tracked plist at {deploy} — nothing to do")
        else:
            effect = (f"SIGKILLs pid {state['pid'] or '—'} and lets launchd start a clean process "
                      f"(`launchctl kickstart -k`); in-flight work on this tick is lost")
        return {"action": "daemon.restart", **state, "effect": effect}

    return restart(cfg, label, actor=str(payload.get("actor") or "console"))


ACTIONS: dict[str, Callable[[Any, dict, bool], dict]] = {
    "shelf.repair_copy": _act_shelf_repair_copy,
    "shelf.publish_pending": _act_shelf_publish_pending,
    "daemon.restart": _act_daemon_restart,
    "pause.arm": _act_pause_arm,
    "pause.disarm": _act_pause_disarm,
    "routing.set_moat_primary": _act_routing_set,
    "config.set": _act_config_set,
    "config.restore": _act_config_restore,
    "catalogue.set_listing": _act_catalogue_listing,
    "tools.run": _act_tools_run,
    "tools.undo": _act_tools_undo,
}

#: Actions the console refuses by name rather than by absence, so the error says WHY.
#:
#: THIS LIST IS SHORT ON PURPOSE. It used to hold `index.reconcile` on the grounds that the tool
#: is destructive, and that was the wrong fence (founder directive 2026-08-16): refusing it did
#: not stop the deletion, it moved the deletion to a terminal where nothing recorded it. It now
#: runs through `tools.run`, behind a preview and a rollback snapshot.
#:
#: What is left is refused for a reason no snapshot fixes: these two would write the catalogue row
#: WITHOUT the Stripe side, so the two would disagree and a buyer would be charged the old price.
#: The fix is to run the money-rail tool, which writes both, and that is now reachable from the
#: console as well. `ADMIN_CONSOLE_PROGRAM.md` §7 carries the full design.
REFUSED_ACTIONS: dict[str, str] = {
    "catalogue.set_price": (
        "A direct catalogue price write is refused because it would drift from Stripe. "
        "prospector/bridge.py is the money rail: one PriceDecision mints the Stripe Price and "
        "writes the catalogue row together so they cannot disagree. Run the tool that does both "
        "— tools/set_live_pack_price.py, via the tools.run action."
    ),
    "catalogue.reprice": (
        "Same reason as catalogue.set_price: a bulk row write would leave Stripe holding the old "
        "prices. Run tools/reprice_live_packs.py via the tools.run action."
    ),
}


# --------------------------------------------------------------------------- #
# The operator CLI catalogue
# --------------------------------------------------------------------------- #
#: A hand-kept table, NOT a directory scan. A scan can list files; it cannot say whether a tool
#: reaches off this machine, and that is what decides which safety net applies. `exists` is filled
#: in at read time, so a tool that is renamed shows up as missing instead of silently vanishing
#: from the operator's map.
#:
#: `run` USED TO BE THE FENCE, AND THAT WAS WRONG (founder directive, 2026-08-16: "we just need
#: rollback to be safe not to hide actions"). A tool the console refused was not a tool that did
#: not run; it was a tool the operator ran at a terminal, with no preview, no receipt and no undo.
#: The fence is now the preview + confirmation token every action already goes through, plus
#: `prospector.ops.undo`. So `run` defaults to True and `risk` carries the honest part:
#:
#:   "read"     — writes nothing. No snapshot needed.
#:   "local"    — writes only the local store/ tree. `undo` rolls it back in full.
#:   "external" — reaches off this machine: Stripe, the live shelf, R2, public source files.
#:                A snapshot is still taken, but it CANNOT undo the external half. The preview
#:                says so, because an undo that covers half the blast radius is worse than none.
#:   "shell"    — not a tool. Not runnable, and the refusal names why.
RISKS = ("read", "local", "external", "shell")


def _t(path, purpose, writes, screen, run=True, danger=None, cmd=None, risk=None):
    if risk is None:
        risk = "local" if writes else "read"
    if risk not in RISKS:
        raise ValueError(f"{path}: risk={risk!r} is not one of {RISKS}")
    command = cmd or f".venv/bin/python {path}"
    # The id must be stable across restarts (a browser holds it between preview and confirm) and
    # unique. The command alone is neither: two rows share `launchctl list | grep com.prospector`.
    ident = hashlib.sha1(f"{path}|{purpose}|{command}".encode()).hexdigest()[:10]
    return {"id": ident,
            "path": path, "purpose": purpose, "writes": writes, "screen": screen,
            "run": bool(run) and risk != "shell", "danger": danger, "risk": risk,
            "undo_covers": {"read": "nothing is written",
                            "local": "everything this writes",
                            "external": "the local half only",
                            "shell": "n/a"}[risk],
            "command": command}


TOOLS: list[dict] = [
    # --- engine ---
    _t("prospector/run.py", "Vet one idea end to end", True, "/tools",
       cmd=".venv/bin/python -m prospector.run vet --idea '<idea>'"),
    _t("prospector/run.py", "Finish the waiting rows (re-vet)", True, "/queue",
       cmd=".venv/bin/python -m prospector.run vet --resume"),
    _t("prospector/run.py", "Generate candidates from a signal", True, "/tools",
       cmd=".venv/bin/python -m prospector.run signal --text '<signal>'"),
    _t("prospector/run.py", "Bounded generation batch", True, "/tools",
       cmd=".venv/bin/python -m prospector.run generate"),
    _t("prospector/run.py", "Drain the queue", True, "/tools",
       cmd=".venv/bin/python -m prospector.run consume"),
    _t("prospector/run.py", "Catalogue / metrics / cost report", False, "/metrics",
       cmd=".venv/bin/python -m prospector.run report"),
    _t("prospector/run.py", "System diagnostics", False, "/tools",
       cmd=".venv/bin/python -m prospector.run diagnose"),
    _t("prospector/run.py", "Operator state and quotas", False, "/engine",
       cmd=".venv/bin/python -m prospector.run operator"),
    _t("prospector/run.py", "Manage ambition lanes", True, "/tools",
       cmd=".venv/bin/python -m prospector.run lanes show"),
    _t("prospector/run.py", "Manage markets", True, "/tools",
       cmd=".venv/bin/python -m prospector.run markets show"),
    _t("prospector/scheduler/run_scheduled.py", "The producer loop (launchd owns it)", True,
       "/engine", risk="shell", cmd="launchctl list | grep com.prospector",
       danger="a daemon, not a tool — launchd starts it. Use daemon.restart."),
    _t("prospector/consumer.py", "The drain loop (launchd owns it)", True, "/engine",
       risk="shell", cmd="launchctl list | grep com.prospector",
       danger="a daemon, not a tool — launchd starts it. Use daemon.restart."),
    _t("prospector/ops/pause.py", "Arm or clear a pause scope", True, "/engine", run=True,
       cmd=".venv/bin/python -m prospector.ops.pause show"),
    _t("prospector/ops/routing.py", "Who may rule finally", True, "/engine", run=True,
       cmd=".venv/bin/python -m prospector.ops.routing show"),
    _t("prospector/ops/readmodel.py", "Queue, pause and provider state", False, "/", run=True,
       cmd=".venv/bin/python -m prospector.ops.readmodel"),
    _t("prospector/ops/metrics.py", "Outcome metrics", False, "/metrics", run=True,
       cmd=".venv/bin/python -m prospector.ops.metrics"),
    _t("prospector/ops/spend.py", "Spend split against the cap", False, "/spend", run=True,
       cmd=".venv/bin/python -m prospector.ops.spend"),
    _t("prospector/ops/runs.py", "Run and candidate internals", False, "/runs", run=True,
       cmd=".venv/bin/python -m prospector.ops.runs --runs"),
    _t("tools/spend_today.py", "Today's spend against the cap", False, "/spend"),
    # --- publish / republish ---
    _t("publish/publish.py", "The single publish entry point", True, "/catalogue",
       risk="external"),
    _t("tools/publish_offline.py", "Publish stored PASSes without regenerating", True,
       "/catalogue", risk="external"),
    _t("tools/publish_passes.py", "Generate content then publish", True, "/catalogue",
       risk="external", danger="costs model calls"),
    _t("tools/backfill_missing_listings.sh", "Mass publish stranded PASSes", True, "/catalogue",
       risk="external", danger="bulk publish — review the stranded list first",
       cmd="bash tools/backfill_missing_listings.sh"),
    _t("tools/unlist_killed.py", "Unlist packs re-vetted to KILL", True, "/catalogue",
       risk="external"),
    _t("tools/retire_rotted_passes.py", "Retire PASSes whose citations rotted", True,
       "/catalogue", risk="external"),
    _t("tools/verify_pass_shelf_coverage.py", "PASSes the shelf does not show", False,
       "/catalogue", run=True),
    # Read-only by default: it reports the route each stranded pack needs and what the ledger
    # already knows about it. `--apply` runs the repairs, `--publish` is the separate flag that
    # lets it reach the money rail, so the default row here writes nothing.
    _t("tools/recover_stranded_passes.py", "Repair PASSes the shelf does not show", False,
       "/catalogue", run=True),
    _t("tools/verify_selling_catalogue.py", "Every selling pack backed by a PASS", False,
       "/catalogue", run=True),
    _t("tools/preview_packs.py", "Read any pack in full without buying", False, "/catalogue"),
    _t("tools/pack_defect_census.py", "Live packs carrying each defect", False, "/catalogue"),
    _t("tools/floor_signature.py", "Deterministic-floor copy still on the shelf", False,
       "/catalogue"),
    _t("scripts/pack_banner_probe.py", "Live packs showing a retired banner", False, "/catalogue"),
    # --- backfill / repair ---
    _t("tools/backfill_facets.py", "Tag packs with discovery facets", True, "/tools",
       risk="external"),
    _t("tools/backfill_listing_copy.py", "Replace floor copy with generated copy", True,
       "/tools", risk="external"),
    _t("tools/backfill_bundle_html.py", "Re-render a listed pack's zip", True, "/tools",
       risk="external"),
    _t("tools/backfill_pack_currency.py", "Repair currency on pre-market packs", True, "/tools"),
    _t("tools/backfill_archived_url.py", "Backfill archived source urls", True, "/tools"),
    _t("tools/backfill_audience.py", "Copy audience tag into the index", True, "/tools",
       risk="external"),
    _t("tools/backfill_market.py", "Stamp legacy dossiers with market", True, "/tools",
       danger="no rehearsal flag — it writes on the first run"),
    _t("tools/sweep_shelf_copy.py", "Re-grade and rewrite shelf copy", True, "/tools"),
    _t("tools/retitle_catalogue.py", "Rewrite live pack titles", True, "/tools",
       risk="external"),
    _t("tools/site_wide_dash_cleanup.py", "Rewrite dashes in storefront source", True, "/tools",
       risk="external", danger="edits public source files, which undo does not cover — git does"),
    _t("scripts/backfill_tiers.py", "Fill ambition_tier on legacy dossiers", True, "/tools"),
    _t("scripts/backfill_price_anchors.py", "Backfill cited price anchors", True, "/tools"),
    _t("scripts/reconcile_orphan_index.py", "Delete index rows with no dossier", True, "/tools",
       risk="external",
       danger="DELETES index rows. Undo covers the local store, not the remote index — take the "
              "snapshot AND be ready to re-publish"),
    _t("tools/review_figures.py", "Human verification of untraceable figures", True, "/tools"),
    # --- money rail ---
    # These run from the console like everything else. What makes them safe is the preview, the
    # confirmation token and the receipt — NOT a hidden button. What undo cannot do is take back
    # a Stripe price, so `risk="external"` makes the preview say that in words.
    _t("tools/set_live_pack_price.py", "Set one pack to a named rung", True, "/catalogue",
       risk="external", danger="MONEY RAIL — mints a real Stripe Price. Undo cannot take it back; "
                               "correcting it means setting the rung again"),
    _t("tools/reprice_live_packs.py", "Re-price packs with unbillable stub ids", True, "/tools",
       risk="external", danger="MONEY RAIL — bulk Stripe writes. Undo cannot take them back"),
    _t("tools/reprice_to_charm_rungs.py", "Move packs onto charm rungs", True, "/tools",
       risk="external", danger="MONEY RAIL — bulk Stripe writes. Undo cannot take them back"),
    _t("scripts/backfill_ladder_prices.py", "Move the catalogue onto the L1 ladder", True,
       "/tools", risk="external",
       danger="MONEY RAIL — bulk Stripe writes. Undo cannot take them back"),
    _t("tools/depth_reprice_preview.py", "Before/after for the depth ladder", False, "/tools"),
    _t("tools/price_history.py", "Who moved a price and why", False, "/catalogue"),
    # --- integrity / probes ---
    _t("scripts/backup_store.py", "Back up dossiers and ledger to R2", True, "/tools",
       risk="external"),
    _t("scripts/restore_drill.py", "Prove the backup restores", False, "/tools"),
    _t("scripts/store_audit.py", "Audit the operator's store", False, "/tools"),
    _t("scripts/blocker_probe.py", "Which programme items are blocked", False, "/tools"),
    _t("scripts/load_gate.py", "Is the machine fit to trust a test result", False, "/tools"),
    _t("scripts/popdd_verify.py", "The lane-aware proof runner", False, "/tools"),
    _t("scripts/site_spec_probe.py", "Site spec ledger against the tree", False, "/tools"),
    _t("scripts/graphify_sweep.py", "Graph freshness scoreboard", True, "/tools",
       risk="external"),
    _t("scripts/gen_budget_guard.py", "Does generation fit its tick deadline", False, "/tools"),
    _t("scripts/guard_protected_deletions.py", "Guard silent deletion of protected files", False,
       "/tools"),
    _t("scripts/unit_economics.py", "Cost per pack", False, "/spend"),
    _t("tools/generation_survival.py", "Survival by generation axis", False, "/metrics"),
    _t("tools/citation_quality_by_provider.py", "Which provider gave the evidence", False,
       "/metrics"),
    _t("tools/meta_shape_monitor.py", "Are one-liners collapsing into one cluster", False,
       "/metrics"),
    _t("tools/audit_swallow_sites.py", "Rank swallowed failures by blast radius", False,
       "/tools"),
    _t("tools/prove_diversity.py", "Diversity proof harness", False, "/tools"),
    _t("tools/prove_reliability.py", "Reliability proof harness", False, "/tools"),
    _t("tools/make_kill_log.py", "Bake the public kill log", True, "/tools", risk="external"),
    _t("tools/make_sample_report.py", "Bake the public sample report", True, "/tools",
       risk="external"),
    _t("tools/govern.py", "Run a command under a concurrency ceiling", False, "/tools",
       danger="takes a command as an argument. The console only ever runs the command in this "
              "table, never one typed into the browser — that would be a web shell"),
    # --- registered 2026-08-17, when the drift test below first measured the gap ---
    _t("scripts/ops_status.py", "Launch-ops programme status, derived from the repo", False,
       "/audit"),
    _t("scripts/doc_lint.py", "Find docs that point at something no longer there", False,
       "/audit"),
    _t("scripts/copy_audit.sh", "Copy audit across the marketing and pack lanes", False, "/shelf",
       cmd="bash scripts/copy_audit.sh"),
    _t("scripts/backfill_packs_parallel.sh", "Backfill P5 pack artefacts into listed packs", True,
       "/catalogue", cmd="bash scripts/backfill_packs_parallel.sh",
       danger="runs N backfill processes in parallel — check the slot count first"),
    _t("scripts/live_checkout.py", "Which commit is production running?", False, "/tools"),
    _t("scripts/live_checkout.py", "Roll production forward to origin/main", True, "/tools",
       cmd=".venv/bin/python scripts/live_checkout.py --update", risk="external",
       danger="restarts the scheduler and consumer daemons; a tick in flight is killed"),
    _t("scripts/ops_state.py", "Live value of every fact the launch-ops programme asserts", False,
       "/audit", cmd="python3 scripts/ops_state.py"),
    _t("scripts/launchd_plists.py", "Has a scheduler's job definition drifted?", False, "/engine",
       cmd="python3 scripts/launchd_plists.py --check"),
    _t("scripts/launchd_plists.py", "Record the current job definitions", True, "/engine",
       cmd="python3 scripts/launchd_plists.py --snapshot",
       danger="overwrites the tracked copies with whatever is live, so run --check first "
              "or an unwanted change becomes the new baseline"),
]


#: Every file in `tools/` and `scripts/` is either in TOOLS above or named here with the reason
#: it is not an operator's button. Nothing may be in neither: `test_console_tool_registry_has_no_
#: drift` walks the disk and fails on anything unclassified.
#:
#: This exists because on 2026-08-17 twenty tools were on disk and invisible from the console,
#: and no test could tell. The registry was hand-written, so adding a tool and forgetting to
#: register it was silent — which is how an operator ends up unable to see what the system can do.
NOT_AN_OPS_TOOL: dict[str, str] = {
    # developer and CI tooling — it runs in a terminal or in GitHub Actions, never from an ops page
    "scripts/ci-gate.sh": "the POPDD CI gate; GitHub Actions runs it, not an operator",
    "scripts/setup_worktree.sh": "makes a git worktree usable; a developer's machine, not ops",
    "scripts/test_impacted.py": "picks the tests a diff can affect; a developer's and CI's shortcut",
    "scripts/verify_engine_change.sh": "the pre-commit proof that an engine change is safe",
    "scripts/seed_action_cache.sh": "seeds the CI runner's action archive cache; runs on the runner",
    "scripts/warm_ci_uv_cache.sh": "warms the CI runner's uv cache; runs on the runner",
    "tools/commit_mine.sh": "commits exactly the named paths; a developer's git helper",
    "scripts/prune_branches.py": "retires git branches already merged into main; git hygiene on a "
                                 "developer's machine, nothing an operator runs",
    # Claude Code hooks — the harness fires these, they have no operator-facing run
    "scripts/graphify_query_hook.py": "a UserPromptSubmit hook; the harness fires it",
    "scripts/graphify_session_hook.py": "a SessionStart hook; the harness fires it",
    "scripts/handoff.py": "writes an agent session handoff; not an operator action",
    # the console itself, and its predecessor
    "scripts/run_ops_console.sh": "launches this console; a button that starts the page you are already on",
    "tools/build_sample_fixture.py": "builds an offline retrieval fixture for the test suite, not a live action",
    # the legacy Streamlit console — superseded by this Next.js one
    "scripts/run_control_center.sh": "launches the older Streamlit console that this one replaces",
    "scripts/install_control_center_agent.sh": "installs that older console's launchd agent",
    # libraries and experiments, not commands
    "tools/_backfill_driver.py": "a library for backfill_missing_listings.sh, not a CLI",
    "tools/l8_ab.sh": "the COST_PROGRAM §L8 A/B experiment harness",
    "tools/l8_grade.py": "grades one L8 A/B run; the harness calls it",
    "tools/l8_summary.py": "summarises L8 A/B rows; the harness calls it",
    # wanted on the console, but not in this shape
    "scripts/watch_engine.py": "a terminal live view that never exits, so it cannot be a request; "
                               "the /engine screen is the console-native answer",
    "tools/queue_yield_batch.sh": "chains a wait, a publish and a batch launch into one script; "
                                  "split it before it becomes a single button",
    # on disk but unclassified until now. `run_ops_console.sh` and `build_sample_fixture.py`
    # are covered above; these two are the remainder.
    #
    # Two keys were written twice in this dict (`ci_local.py`, `test_impacted.py`), each with a
    # different reason. Python keeps the last one, so the first reason was dead text nobody could
    # see. Deduplicated 2026-08-17; the drift test counts keys, so it could not catch this.
    "scripts/ci_local.py": "replays a CI job's shell steps on this machine; a developer's loop",
    "tools/_audit_baseline_tmp.py": "a one-off inventory of failure-to-empty-answer sites, kept "
                                    "for its findings; the leading underscore says it is not a "
                                    "command",
}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def dispatch(argv: list[str]) -> tuple[dict, int]:
    """Parse argv and run one verb. Returns (document, exit_code).

    Separated from `main` so tests can call it without capturing stdout.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="prospector.ops.console_api",
                                 description="JSON gateway for the admin console")
    ap.add_argument("verb", choices=["read", "act", "views", "actions", "run-tool"])
    ap.add_argument("name", nargs="?", default="")
    ap.add_argument("--job", default="", help="job id; run-tool only")
    ap.add_argument("--arg", action="append", default=[],
                    help="k=v, repeatable; read verbs only")
    ap.add_argument("--payload", default="{}", help="JSON object; act verbs only")
    ap.add_argument("--confirm", default="", help="token issued by --preview")
    ap.add_argument("--preview", action="store_true",
                    help="describe the change and issue a confirmation token; writes nothing")
    ap.add_argument("--config", default=os.environ.get("PROSPECTOR_CONFIG") or None)
    args = ap.parse_args(argv)

    started = time.time()

    if args.verb == "views":
        return _envelope("verb", "views", started, data=sorted(READS)), 0
    if args.verb == "actions":
        return _envelope("verb", "actions", started,
                         data={"available": sorted(ACTIONS), "refused": REFUSED_ACTIONS}), 0

    if not args.name:
        return _envelope(args.verb, "", started,
                         error=f"{args.verb} needs a name", error_kind="ValueError"), 2

    if args.verb == "run-tool":
        # The background half of `tools.run`. `_act_tools_run` spawns this after the confirmation
        # token was checked and the snapshot taken; it is not a second door (see `_run_tool_job`).
        if not args.job:
            return _envelope("verb", "run-tool", started,
                             error="run-tool needs --job", error_kind="ValueError"), 2
        try:
            payload = json.loads(args.payload or "{}")
            if not isinstance(payload, dict):
                raise ValueError("--payload must be a JSON object")
            with _quiet_stdout():
                cfg = _cfg(args.config)
                data = _run_tool_job(cfg, args.name, args.job, payload)
            return _envelope("verb", "run-tool", started, data=data), 0
        except Exception as exc:  # noqa: BLE001
            return _fail("verb", "run-tool", started, exc), 1

    if args.verb == "read":
        fn = READS.get(args.name)
        if fn is None:
            return _envelope("view", args.name, started,
                             error=f"unknown view {args.name!r}; expected one of "
                                   f"{', '.join(sorted(READS))}",
                             error_kind="UnknownView"), 2
        kv: dict[str, str] = {}
        for pair in args.arg:
            k, _, v = pair.partition("=")
            kv[k.strip()] = v
        try:
            with _quiet_stdout():
                cfg = _cfg(args.config)
                data = fn(cfg, kv)
            return _envelope("view", args.name, started, data=data), 0
        except Exception as exc:  # noqa: BLE001
            return _fail("view", args.name, started, exc), 1

    # --- act ---
    name = args.name
    if name in REFUSED_ACTIONS:
        return _envelope("action", name, started, error=REFUSED_ACTIONS[name],
                         error_kind="RefusedByDesign"), 3
    fn = ACTIONS.get(name)
    if fn is None:
        return _envelope("action", name, started,
                         error=f"unknown action {name!r}; expected one of "
                               f"{', '.join(sorted(ACTIONS))}",
                         error_kind="UnknownAction"), 2
    try:
        payload = json.loads(args.payload or "{}")
        if not isinstance(payload, dict):
            raise ValueError("--payload must be a JSON object")
    except ValueError as exc:
        return _fail("action", name, started, exc), 2

    try:
        with _quiet_stdout():
            cfg = _cfg(args.config)
            if args.preview:
                data = fn(cfg, payload, True)
                data = {**data, "confirm": _valid_tokens(cfg, name, payload)[0],
                        "confirm_expires_in_s": CONFIRM_TTL_S,
                        "preview": True}
                return _envelope("action", name, started, data=data), 0

            # THE FENCE. Not in the button — here, where every caller lands.
            if args.confirm not in _valid_tokens(cfg, name, payload):
                preview = fn(cfg, payload, True)
                _record_intent(cfg, {
                    "ts": _now_iso(), "actuator": f"console.{name}", "applied": False,
                    "actor": str(payload.get("actor") or "console"),
                    "reason": str(payload.get("reason") or ""),
                    "refused": "missing or expired confirmation token"})
                return _envelope("action", name, started,
                                 data={**preview, "preview": True,
                                       "confirm": _valid_tokens(cfg, name, payload)[0],
                                       "confirm_expires_in_s": CONFIRM_TTL_S},
                                 error="missing or expired confirmation token — nothing was "
                                       "written; confirm the preview below",
                                 error_kind="ConfirmationRequired"), 4

            data = fn(cfg, payload, False)
        return _envelope("action", name, started, data=data), 0
    except Exception as exc:  # noqa: BLE001
        return _fail("action", name, started, exc), 1


def main(argv: Optional[list[str]] = None) -> int:
    doc, code = dispatch(list(argv) if argv is not None else sys.argv[1:])
    sys.stdout.write(json.dumps(doc, indent=2, default=str) + "\n")
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
