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

from prospector import content_contract, pack_linter
from prospector.operator import BUILDABLE_TIERS

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
    out["supervisor"] = _supervisor_view()
    out["pause"] = pause_view(cfg)
    # A SHORT tail here on purpose. This view is polled every 30s by the Now page; the
    # Engine page asks `providers` directly and gets the full history.
    out["providers"] = provider_view(cfg, events_limit=8)
    out["queue"] = queue_view(cfg, lookback_h=float(args.get("lookback_h") or 24.0))
    try:
        out["routing"] = routing_view(cfg)
    except Exception as exc:  # StaleProcessGlobal and friends are information, not a crash
        out["routing"] = {"error": f"{exc}", "error_kind": type(exc).__name__}
    out["spend"] = _spend_headline(cfg)
    out["incidents"] = _incident_headline()
    return out


def _incident_headline() -> dict:
    """Counts only, for the Now page. The records themselves are the `incidents` view.

    Wrapped because this is the ONE view polled every 30 seconds by the front page: a malformed
    incident record, or a checkout with no `scripts/` at all, must cost a line on one card and
    never the whole screen. `load()` already treats a malformed file as a finding rather than an
    exception, so this only catches the case where the script itself cannot be reached.
    """
    try:
        from .incidents_view import incidents_view

        return incidents_view(_repo_root())["headline"]
    except Exception as exc:  # noqa: BLE001 — a broken record must not blank the Now page
        return {"error": f"{exc}", "error_kind": type(exc).__name__}


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


def _read_orders(cfg, args: dict) -> dict:
    """The order list. Filters are passed straight to `GET /internal/ops/orders`; the view module
    drops any the endpoint does not accept and says so in its warnings."""
    from .shop import ORDER_FILTERS, orders_view

    filters = {k: v for k, v in args.items() if k in ORDER_FILTERS and str(v).strip() != ""}
    return orders_view(cfg, _store_call, **filters)


def _read_order(cfg, args: dict) -> dict:
    """One order, with its entitlements, deliveries, siblings and sales audit."""
    from .shop import order_view

    order_id = str(args.get("order_id") or "").strip()
    if not order_id:
        raise ValueError("read order needs --arg order_id=<id>")
    return order_view(cfg, _store_call, order_id)


def _read_sales(cfg, args: dict) -> dict:
    """Revenue over a window, per currency. Nothing here adds two currencies together."""
    from .shop import sales_view

    return sales_view(cfg, _store_call, days=int(args.get("days") or 30))


def _read_deliveries(cfg, args: dict) -> dict:
    """The delivery outbox: what a paid buyer is still waiting for."""
    from .shop import deliveries_view

    limit = str(args.get("limit") or "").strip()
    return deliveries_view(cfg, _store_call,
                           state=str(args.get("state") or "all").strip() or "all",
                           limit=int(limit) if limit else None)


def _read_disputes(cfg, args: dict) -> dict:
    """Refunds and chargebacks, read from our own reversed orders rather than from Stripe."""
    from .shop import disputes_view

    return disputes_view(cfg, _store_call, days=int(args.get("days") or 90))


def _read_data(cfg, args: dict) -> dict:
    """DAT-1, DAT-2, DAT-4 and AST-1 on a screen, each read from the control that owns it."""
    from .data import data_view

    return data_view(cfg)


def _read_docs(cfg, args: dict) -> dict:
    """The repo's own documentation, in the console. Index by default, one doc with `name=`.

    Registered 2026-08-19: the founder asked twice whether docs were reachable from ops and the
    answer was no. Reads are confined to `docs/` by `docs_view._safe`, which resolves first and
    checks containment second so a `..` or a symlink cannot leave the tree.
    """
    from .docs_view import doc_view, docs_index

    name = str(args.get("name") or "").strip()
    if name:
        return doc_view(_repo_root(), name)
    return docs_index(_repo_root())


def _read_incidents(cfg, args: dict) -> dict:
    """What broke, what stops it repeating, and what is still unguarded.

    Registered 2026-08-19. The rollup existed only as terminal output from
    `scripts/incident.py check`, so an operator without a checkout could not see that a record
    had no mechanism or that a mechanism was past its grading window. The judgement stays in
    that script — this view calls it, so the page and the CI gate can never disagree.
    """
    from .incidents_view import incidents_view

    return incidents_view(_repo_root())


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
    from prospector.ops import config_editor as ce

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
        "writer": "prospector/ops/yaml_surgery.py via config_editor.write_config",
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
    from prospector.ops import yaml_surgery as ys

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


def _read_console_log(cfg, args: dict) -> dict:
    """What the CONSOLE itself did when it went wrong, newest first.

    WHY THIS EXISTS. On 2026-08-18 every tab in the portal rendered blank at once. The cause was
    an expired session — the reads 401ed and the page bounced to /login — but nothing recorded
    it, and `fly logs --no-tail` returns 100 lines, about four minutes on a generating daemon. By
    the time it was reported the evidence had scrolled away, so it was reasoned about instead of
    read. Founder: "we should log carefully next time this happens".

    The rows are written by the Next.js routes (`src/lib/oplog.ts`), not by the engine, and they
    only appear when something is worth a line: a refused read, a failed read, a slow read, a
    page crash, or a sign-in. A quiet file is the healthy state, which is why the panel says so
    in words rather than rendering an empty table.
    """
    path = _store_ops_dir(cfg) / "console_events.jsonl"
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
                # A torn write leaves half a line. Count it and carry on: one bad line must not
                # cost the operator the whole history.
                unreadable += 1
                continue
            if isinstance(rec, dict):
                rows.append(rec)
    rows.reverse()
    kinds: dict[str, int] = {}
    for r in rows:
        k = str(r.get("kind") or "unknown")
        kinds[k] = kinds.get(k, 0) + 1
    return {"path": str(path), "present": path.exists(), "total": len(rows),
            "unreadable_lines": unreadable, "kinds": kinds, "rows": rows[:limit]}


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


def _act_delivery_resend(cfg, payload: dict, preview: bool) -> dict:
    """Put one delivery back in front of the drain.

    This action sends nothing. `DeliveryDrain` stays the only sender, so a redelivery is a retry
    of the one code path that has ever emailed a buyer, not a second one. That matters more than
    it sounds: a console that sent its own mail would be a second template, a second failure mode
    and a second thing to keep in step with the entitlement.

    There is only ever one outbox row per entitlement. `PendingDeliveries.EntitlementId` is UNIQUE
    (`StoreDbContext.cs:61`) and that index is what makes enqueueing idempotent against a duplicate
    webhook, so a resend cannot add a second row. It resets the row it has.

    That has a cost on a delivery that already went out: clearing `SentAt` destroys the row-level
    receipt that a link was emailed, and "we already emailed them once" is the fact a support
    conversation turns on. So the API returns `previousSentAt`, and this function writes it into
    the intent receipt before the row loses it. The receipt trail is where that timestamp lives
    from then on.

    Refused by the API with 409 when the entitlement is revoked, i.e. refunded or disputed.
    """
    raw = str(payload.get("id") or "").strip()
    if not raw:
        raise ValueError("deliveries.resend needs a delivery id (the delivery row, not the order)")
    try:
        delivery_id = int(raw)
    except ValueError as exc:
        raise ValueError(f"deliveries.resend needs a numeric delivery id, got {raw!r}") from exc

    if preview:
        seen = _store_call("GET", "/internal/ops/deliveries?state=all&limit=200", internal=True)
        rows = []
        body = seen.get("body")
        if isinstance(body, dict) and isinstance(body.get("deliveries"), list):
            rows = [r for r in body["deliveries"]
                    if isinstance(r, dict) and r.get("id") == delivery_id]
        row = rows[0] if rows else None
        sent = bool(row and row.get("sentAtUtc"))
        return {
            "action": "deliveries.resend", "id": delivery_id,
            # Not "does not exist". The window is the most recent 200 rows, and saying an older id
            # is missing would be a claim the read cannot support.
            "found": bool(row),
            "found_note": (None if row else
                           "This delivery was not in the most recent 200 rows. That is a limit of "
                           "the preview window, not proof the id is wrong. The resend will still "
                           "be attempted and the API answers 404 if there is no such delivery."),
            "buyer_email": (row or {}).get("buyerEmail"),
            "pack_id": (row or {}).get("packId"),
            "state": (row or {}).get("state"),
            "attempts": (row or {}).get("attempts"),
            "last_error": (row or {}).get("lastError"),
            "will": "requeued",
            "effect": ("this link was ALREADY SENT. The one outbox row is reset, so its SentAt "
                       "receipt is cleared; the send time is returned as previousSentAt and "
                       "written to the receipt trail. The buyer gets a second email."
                       if sent else
                       "attempts reset to 0; the delivery drain picks it up on its next pass"),
            "endpoint": f"POST /internal/ops/deliveries/{delivery_id}/resend",
            "sends_email_directly": False,
        }

    resp = _store_call("POST", f"/internal/ops/deliveries/{delivery_id}/resend", internal=True)
    ok = 200 <= int(resp["status"]) < 300
    answer = resp.get("body") if isinstance(resp.get("body"), dict) else {}
    receipt = {"ts": _now_iso(), "actuator": "store.deliveries.resend", "id": delivery_id,
               "actor": str(payload.get("actor") or "console"),
               "reason": str(payload.get("reason") or ""),
               "nonce": str(payload.get("nonce") or ""),
               "applied": ok, "changed": ok,
               "outcome": answer.get("action"),
               # The row is about to lose this. The receipt is the only place it survives.
               "previous_sent_at": answer.get("previousSentAt"),
               "delivery_id": answer.get("deliveryId"),
               "buyer_email": answer.get("buyerEmail"),
               "pack_id": answer.get("packId"),
               "status": resp["status"], "response": resp.get("body"),
               "endpoint": f"POST /internal/ops/deliveries/{delivery_id}/resend"}
    _record_intent(cfg, receipt)
    return receipt


def _tool_on_disk(root: Path, rel: str) -> Path:
    """Where a catalogued tool actually lives.

    `root / rel` is wrong for the estate tools, and wrong SILENTLY. Most rows are repo-relative,
    but some name a tool outside this checkout — `~/.hermes/scripts/hermes_selfcheck.py`. Joined
    to the repo root that becomes `<repo>/~/.hermes/...`, which never exists, so the console
    reported the tool missing and the run action refused it. The Hermes self-check button was
    registered on 2026-08-19 and could not have run on any day since.

    Same shape as the store resolver incident: a path built from the wrong base answers a
    different question and says nothing about it. Expand first, then join only what is still
    relative.
    """
    expanded = Path(rel).expanduser()
    return expanded if expanded.is_absolute() else root / expanded


def _read_tools(cfg, args: dict) -> dict:
    """The operator CLI catalogue. See `TOOLS` for why it is a table and not a directory scan."""
    root = _repo_root()
    out = []
    for tool in TOOLS:
        rel = tool["path"]
        out.append({**tool, "exists": _tool_on_disk(root, rel).exists()})
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


def _lint_receipt(root: str, cid: str) -> Any:
    """The pack's stored gate verdict, or None if there is not one this reader can parse."""
    try:
        return json.loads(
            (Path(root) / "store" / "dossiers" / f"{cid}.lint.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
        # WHETHER TO BELIEVE `why` AT ALL. It is read from the pack's stored `<id>.lint.json`,
        # and a receipt outlives the rules that wrote it: editing the linter touches no dossier,
        # so every receipt stays byte-identical and reads as current forever. On 2026-08-17 five
        # rules stopped blocking and seven stranded packs became sellable while every receipt on
        # disk still said "blocked" — this page would have printed that, confidently, with no
        # way for the operator to tell. `verdict` is the honest label, and `shelf.regate` is the
        # button that resolves it. Same function the tool and the tick use.
        # `receipt` first, because a MISSING receipt is not a STALE one. `receipt_is_current`
        # answers False for both, so a pack with no `<id>.lint.json` at all had its real repair
        # replaced by `shelf.regate` - the button that re-grades a receipt that does not exist.
        # A pack that was never published has no receipt by definition, so this hit exactly the
        # rows `shelf.publish_pending` was written for.
        receipt = _lint_receipt(root, cid)
        current = pack_linter.receipt_is_current(receipt)
        if receipt is not None and not current:
            fix = "shelf.regate"
        rows.append({"id": cid, "created": str(created)[:10], "why": why,
                     "checks": checks, "repair": fix,
                     "verdict": "current" if current else "stale — rules changed since"})
        for c in checks or ["other"]:
            reasons[c] = reasons.get(c, 0) + 1

    by_repair: dict[str, int] = {}
    for r in rows:
        by_repair[r["repair"]] = by_repair.get(r["repair"], 0) + 1
    stale = sum(1 for r in rows if r["verdict"] != "current")
    return {"reachable": True, "shelf_packs": len(shelf), "stranded": len(rows),
            "stale_verdicts": stale,
            "rows": rows, "by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            "by_repair": by_repair,
            "note": "Every row here is a pack that cleared every gate and earns nothing. "
                    "`repair` names the console action that fixes that class; `manual` means "
                    "no tool repairs it today."
                    + (f" {stale} of {len(rows)} carry a verdict from rules that have since "
                       f"changed — the reason shown for those is the OLD answer. Run "
                       f"`shelf.regate` (a rehearsal: no Stripe object, nothing"
                       f"listed) to find out what today's rules say." if stale else "")}


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
        # Per session, because a monthly average cannot say whether a change helped.
        # Only the most recent rows travel: the console is a dashboard, not an export.
        "compliance": snap.get("compliance", {}),
        "sessions": (snap.get("sessions") or [])[:12],
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


# --------------------------------------------------------------------------- #
# Where the engine is running, and whether the other side could take over
# --------------------------------------------------------------------------- #

_FAILOVER_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "engine_failover.py"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUDIT_SCRIPT = _REPO_ROOT / "scripts" / "process_audit.py"


def _failover(*argv: str, timeout: int = 120) -> str:
    """Run scripts/engine_failover.py and hand back its stdout.

    The console asks a script rather than reimplementing the probes, because the same answer has
    to be available to a launchd job at 4am with no browser open. One implementation, three
    callers: this console, the failover watchdog, and an operator at a terminal.
    """
    proc = subprocess.run([sys.executable, str(_FAILOVER_SCRIPT), *argv],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode not in (0, 1):   # 1 only means "the active side is unhealthy"
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:400] or
                           f"engine_failover.py {' '.join(argv)} exited {proc.returncode}")
    return proc.stdout


def _read_engine_location(cfg, args: dict) -> dict:
    """Both platforms at once, so the console can never show one side and imply the other.

    `deep` also reads each side's ledger, which costs an SSH round trip to Fly. The page polls
    without it and asks for it on demand.
    """
    argv = ["status", "--json"]
    if str(args.get("deep") or "").lower() in ("1", "true", "yes"):
        argv.append("--deep")
    return json.loads(_failover(*argv, timeout=180))


#: The sides the drain ledger can be read from. "active" resolves through the same marker the
#: failover watchdog uses, so the console and the watchdog can never disagree about which box is
#: production.
DRAIN_SIDES = ("active", "fly", "laptop")


def _drain_ledger(cfg, *, side: str = "active", reset: bool = False) -> dict:
    """The drain's give-up ledger, read from the side the engine is ACTUALLY running on.

    This goes through `scripts/engine_failover.py drain` instead of reading the local store, and
    that indirection is the whole point of the view. Production moved to Fly on 2026-08-17, so
    `config.store_root()` in this process resolves to the LAPTOP store, which is idle. On
    2026-08-19 that store held an empty ledger while the Fly engine carried 253 rows, 251 of them
    permanently retired, and said so in its log once a minute
    (`docs/incidents/INC-2026-08-19-drain-retired-on-our-own-outages.json`). A console pointed at
    the wrong box does not show less than the truth. It shows a confident zero, which is worse.
    """
    if side not in DRAIN_SIDES:
        raise ValueError(f"unknown side {side!r}; expected one of {', '.join(DRAIN_SIDES)}")
    argv = ["drain", "--side", side, "--json"]
    if reset:
        argv.append("--reset")
    data = json.loads(_failover(*argv, timeout=180))

    warnings: list[str] = []
    if data.get("error"):
        warnings.append(f"Could not read the {data.get('side')} ledger: {data['error']}")
    if data.get("side") != data.get("active_side"):
        warnings.append(
            f"These numbers come from the {data.get('side')} side, but the engine is running on "
            f"{data.get('active_side')}. Nothing here describes production.")
    if not data.get("max_attempts"):
        warnings.append(
            "schedule.max_resume_attempts is 0, so the give-up cap is off and no row can be "
            "retired. `retired` stays empty while that holds, however stuck the queue is.")
    if data.get("retired_count"):
        warnings.append(
            f"{data['retired_count']} candidate(s) have spent their whole re-vet budget and have "
            "left the drainable population for good. The drain will log them as excluded and "
            "never touch them again. Read the incident record before assuming they are genuinely "
            "unrulable — until PR #356 an outage spent that budget like a real attempt.")
    data["warnings"] = warnings
    data["incident"] = "docs/incidents/INC-2026-08-19-drain-retired-on-our-own-outages.json"
    return data


def _read_drain(cfg, args: dict) -> dict:
    """How much work the drain has permanently given up on, and on which box.

    A row leaves the drainable population after `schedule.max_resume_attempts` completed re-vets
    that did not resolve it. Until PR #356 an infrastructure DEFER — a MiniMax quota outage, a
    retrieval failure — spent that budget like a real attempt, so 251 candidates were retired for
    our own downtime. The counter is blind to infrastructure defers now, but nothing hands back a
    budget already spent. That is what `drain.reset` is for.
    """
    return _drain_ledger(cfg, side=str(args.get("side") or "active"))


def _act_engine_arm(cfg, payload: dict, preview: bool) -> dict:
    if preview:
        st = json.loads(_failover("status", "--json"))
        return {
            "action": "engine.arm",
            "effect": "Automatic failover will move the engine from fly to laptop, unattended.",
            "fires_when": ("Fly's own API answers that the machine is not started, on 5 "
                           "consecutive one-minute polls. An unreachable Fly API does NOT fire "
                           "it — that is far more likely to be this machine's network, and "
                           "acting on it would leave two engines running."),
            "standby_staleness_min": st["standby"].get("staleness_min"),
            "would_lose": "whatever the Fly ledger gained since the last sync, in minutes above",
            "already_armed": st["autofailover"] == "armed",
        }
    _failover("arm")
    return json.loads(_failover("status", "--json"))


def _act_engine_disarm(cfg, payload: dict, preview: bool) -> dict:
    if preview:
        st = json.loads(_failover("status", "--json"))
        return {"action": "engine.disarm", "already_disarmed": st["autofailover"] != "armed",
                "effect": "Nothing will move the engine on its own. Switching stays manual."}
    _failover("disarm")
    return json.loads(_failover("status", "--json"))


def _act_engine_switch(cfg, payload: dict, preview: bool) -> dict:
    """Move the engine deliberately, from the dashboard.

    The cutover takes minutes and opens a downtime window, so this does NOT block the request.
    It starts the real `deploy/cutover.sh` detached, writes its log where the console can read it
    back, and returns the path. A console that waits six minutes for an HTTP response is a
    console that times out halfway through a migration and leaves nobody able to say what state
    the engine is in.
    """
    to = str(payload.get("to") or "").strip()
    if to not in ("fly", "laptop", "sshdocker"):
        raise ValueError(f"unknown side {to!r}; expected fly, laptop or sshdocker")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("a reason is required — an unexplained engine move reads as an outage")

    st = json.loads(_failover("status", "--json"))
    frm = st["active"]
    if frm == to:
        raise ValueError(f"the engine is already on {to}")

    if preview:
        return {
            "action": "engine.switch", "from": frm, "to": to, "reason": reason,
            "downtime": ("Yes. The engine stops on the source before its state is packed, and "
                         "starts on the target only after the copy is proved. The last measured "
                         "window was 5 minutes 40 seconds."),
            "target_state": st["sides"].get(to, {}),
            "source_state": st["sides"].get(frm, {}),
            "single_writer": ("The source is stopped and fenced before the target starts. Two "
                              "engines would keep two spend ledgers and could spend twice the "
                              "daily cap."),
            "effect": f"runs deploy/cutover.sh --from {frm} --to {to}",
        }

    root = _FAILOVER_SCRIPT.parent.parent
    log = root / "store" / "ops" / f"engine-switch-{time.strftime('%Y%m%dT%H%M%S')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "wb") as fh:
        subprocess.Popen(
            [sys.executable, str(_FAILOVER_SCRIPT), "switch", "--to", to],
            stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            cwd=str(root), start_new_session=True)
    return {"action": "engine.switch", "from": frm, "to": to, "reason": reason,
            "started": True, "log": str(log),
            "note": "Poll the engine_location view; `active` flips when the cutover finishes."}

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


def _read_processes(cfg, args: dict) -> dict:
    """Every automated process on this estate, graded -- see scripts/process_audit.py.

    Exit 1 is the NORMAL answer here, not a failure to read. The script exits non-zero whenever
    something is failing, which is exactly the state this page exists to show; treating that as an
    error would blank the page at the only moment it matters.
    """
    proc = subprocess.run(
        [sys.executable, str(_AUDIT_SCRIPT), "--json"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=240)
    if not proc.stdout.strip():
        raise RuntimeError(f"process_audit.py produced nothing: {proc.stderr[-400:]}")
    return json.loads(proc.stdout)


READS: dict[str, Callable[[Any, dict], Any]] = {
    "processes": _read_processes,
    "engine_location": _read_engine_location,
    "method": _read_method,
    "shelf": _read_shelf,
    "content_rules": _read_content_rules,
    "status": _read_status,
    "queue": _read_queue,
    "drain": _read_drain,
    "providers": _read_providers,
    "routing": _read_routing,
    "spend": _read_spend,
    "money": _read_money,
    "data": _read_data,
    "metrics": _read_metrics,
    "docs": _read_docs,
    "incidents": _read_incidents,
    "runs": _read_runs,
    "run": _read_run,
    "candidate": _read_candidate,
    "config": _read_config,
    "intents": _read_intents,
    "console_log": _read_console_log,
    "tools": _read_tools,
    "undo": _read_undo,
    "catalogue": _read_catalogue,
    "pack": _read_pack,
    "orders": _read_orders,
    "order": _read_order,
    "sales": _read_sales,
    "deliveries": _read_deliveries,
    "disputes": _read_disputes,
}


# --------------------------------------------------------------------------- #
# The config keys the console may write
# --------------------------------------------------------------------------- #
#: Groups are named for what the knob DOES, not for its YAML path. An operator looking for "how
#: many ideas per batch" should not have to know it is called `batch_size` under `schedule`.
GROUP_ORDER = ["work", "evidence", "brains", "speed", "money", "content"]
GROUP_BLURBS = {
    "content": ("Which content rules may REFUSE a pack. Every rule grades either way; these "
                "switches decide whether a breach blocks the sale or only lands on the receipt. "
                "Read `views content_rules` first — a rule breaching most packs will strand most "
                "of the catalogue the moment it is promoted."),
    "work": "How much the engine takes on, and when it stops taking on more.",
    "evidence": "Where the engine looks for proof, and what counts as relevant.",
    "brains": ("Which brain does which job, and which model each one runs. Every role the "
               "engine has is here: the verdict chain and its trusted roster, the cheap chain, "
               "the pack writer, the marketing writer, and the model pin for each provider. "
               "The highest blast radius in the portal."),
    "speed": "How many calls run at once. Throughput, not correctness.",
    "money": "The daily ceiling and where the warning fires.",
}

#: An allow-list, not a free-form path editor. `config.yaml` carries 1,362 comment lines and
#: several keys whose meaning is load-bearing in ways a form cannot express; a console that could
#: set any path would eventually set one of those from a phone at 2am.
#:
#: `high_blast` marks the keys that can stop the engine producing anything sellable: the three
#: that decide which brain rules a verdict, and `producer_mode`, which decides whether this daemon
#: vets at all. They get a second, explicit acknowledgement on top of the confirmation token — a
#: casual dropdown is exactly what they must not be.
KNOBS: list[dict] = [
    # ---- work ----
    {"path": ["generation", "candidates_per_signal"], "group": "work",
     "label": "Ideas invented per signal", "kind": "int", "min": 1, "max": 200,
     "help": "How many candidate ideas one signal turns into. More ideas means more verdicts to "
             "pay for, so this and the wave size together set the cost of a tick."},
    {"path": ["schedule", "batch_size"], "group": "work",
     "label": "Wave size — ideas per batch", "kind": "int", "min": 1, "max": 200,
     "help": "How many candidates one producer tick mints. Bigger waves risk the tick "
             "deadline; scripts/gen_budget_guard.py is the check."},
    {"path": ["schedule", "interval_s"], "group": "work",
     "label": "How often a wave starts (seconds)", "kind": "int", "min": 60, "max": 604800,
     "help": "The production cadence. With the wave size above, this is the whole answer to how "
             "much the engine invents and how often — 3600 is hourly, 300 is near-continuous. It "
             "lived in a launchd plist argument until 2026-08-17, which is why it read as fixed. "
             "Floored at 60s: the daemon takes no cross-cycle lock, so a shorter cadence starts a "
             "second batch beside the first."},
    {"path": ["schedule", "queue_target_depth"], "group": "work",
     "label": "Hold the queue at N rows (0 = off)", "kind": "int", "min": 0, "max": 100000,
     "help": "OPTIONAL and off by default. On, a tick mints only the shortfall below N and skips "
             "generation entirely when the queue is full. Off, the wave size above is exactly what "
             "gets minted every cadence. Off is the default on purpose: following the queue makes "
             "the production rate a consequence of how fast the consumer happens to be draining, "
             "instead of a number you set."},
    {"path": ["schedule", "tick_deadline_s"], "group": "work",
     "label": "Hard deadline for one tick (seconds)", "kind": "int", "min": 60, "max": 86400,
     "help": "A tick running longer than this force-exits the daemon and launchd relaunches it. "
             "Every time budget below is a fraction of this number. Sized for the old world where "
             "one tick generated, vetted and published; a producer tick only generates. "
             "PROSPECTOR_TICK_DEADLINE_S still overrides it for one manual run."},
    {"path": ["schedule", "producer_mode"], "group": "work", "high_blast": True,
     "label": "Producer/consumer split", "kind": "bool",
     "help": "On, this daemon only invents and parks rows; a separate consumer vets and publishes. "
             "Off, one tick does all of it inside the deadline. Turning it ON without a running "
             "consumer fills the queue and nothing drains it, and that failure is QUIET by design "
             "— a producer tick is all-DEFER, so the usual alert is suppressed."},
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
     "choices": list(BUILDABLE_TIERS),
     "help": "The first entry that answers rules. Anything in this chain but NOT in the trusted "
             "roster below is stamped provisional, never publishes on PASS, and is re-vetted."},
    {"path": ["moat_primary"], "group": "brains", "high_blast": True,
     "label": "Trusted roster — who may rule FINALLY", "kind": "list",
     "choices": list(BUILDABLE_TIERS),
     "help": "Only these may finalise a verdict and let a PASS reach the shelf. Blank falls back "
             "to operator.MOAT_PRIMARY_DEFAULT. Changing this changes what can be sold."},
    {"path": ["noncritical_operator"], "group": "brains", "high_blast": True,
     "label": "Cheap chain — generation, prescreen, scoring", "kind": "list",
     "choices": list(BUILDABLE_TIERS),
     "help": "Never rules a verdict. claude_cli is BARRED here by founder directive and the "
             "builder strips it, so adding it back has no effect."},
    # The two chains below were unreachable from this page until 2026-08-18. They are real roles
    # with their own config keys, so changing the brain that writes what a buyer reads meant
    # editing config.yaml on the box — the one thing this page exists to remove.
    {"path": ["artifact_operator"], "group": "brains", "high_blast": True,
     "label": "Pack writer — who writes what the buyer reads", "kind": "list",
     "choices": list(BUILDABLE_TIERS),
     "help": "Runs the model-written parts of a pack. It never rules a verdict, so a change here "
             "moves prose quality and cost, never what is allowed to publish."},
    {"path": ["marketing_operator"], "group": "brains", "high_blast": True,
     "label": "Marketing writer — shelf copy and launch text", "kind": "list",
     "choices": list(BUILDABLE_TIERS),
     "help": "Writes titles, one-liners and marketing copy. The publish gate still grades every "
             "line it produces, so a weaker brain here strands packs rather than shipping bad ones."},
    # ---- the model each brain runs ----
    # A tier name says WHICH adapter; these say which model that adapter asks for. Swapping
    # MiniMax M3 for another version is a change of THIS value, not of the chain above.
    {"path": ["model"], "group": "brains", "kind": "str",
     "label": "Verdict model pin (blank = each provider default)",
     "help": "Applied only to the provider it names, by prefix match in `_build_operator`. Blank "
             "means every brain uses its own default from the pins below. Wrong here is not a "
             "typo you see — it is a provider erroring on an unknown model on every call."},
    {"path": ["model_fast"], "group": "brains", "kind": "str",
     "label": "Cheap-call model pin (query-gen, prescreen)",
     "help": "Same rule as the pin above, for the mechanical calls. Blank falls back to the "
             "main pin, then to the provider default."},
    {"path": ["model_defaults", "minimax"], "group": "brains", "kind": "str",
     "label": "MiniMax model", "help": "The model the `minimax` tier asks for. This is where a "
     "different MiniMax version goes — the tier name stays `minimax`."},
    {"path": ["model_defaults", "minimax_fast"], "group": "brains", "kind": "str",
     "label": "MiniMax model for cheap calls",
     "help": "M3 by standing order: MiniMax has no non-reasoning model, so a `_fast` pin here "
             "buys nothing unless it names a genuinely different model."},
    {"path": ["model_defaults", "minimax_m27"], "group": "brains", "kind": "str",
     "label": "Second MiniMax tier model",
     "help": "The whole point of the `minimax_m27` tier is being a DIFFERENT model from the one "
             "above, so an M3 stall does not imply this one stalls too. Setting both the same "
             "makes the second tier inert depth."},
    {"path": ["model_defaults", "deepseek"], "group": "brains", "kind": "str",
     "label": "DeepSeek model",
     "help": "Read only when `deepseek` appears in a chain above. Naming a model here does not "
             "put DeepSeek to work; adding it to a chain does."},
    {"path": ["model_defaults", "ollama"], "group": "brains", "kind": "str",
     "label": "Ollama model (local)",
     "help": "Fully local, zero token cost, CPU-only on this box. Same rule: this pin is inert "
             "until `ollama` is in a chain."},
    # ---- speed ----
    {"path": ["retrieval", "minimax_concurrency"], "group": "speed",
     "label": "MiniMax calls at once", "kind": "int", "min": 1, "max": 32,
     "help": "The ceiling on the primary brain, so this is the throughput knob. Measured clean "
             "at 16 concurrent with zero 429s."},
    {"path": ["retrieval", "claude_concurrency"], "group": "speed",
     "label": "Claude CLI calls at once", "kind": "int", "min": 1, "max": 16,
     "help": "Bounds the failover brain only, since MiniMax leads. At 2, a saturated queue once "
             "accounted for 1514s of a 1731s run."},
    # The four fractions below divide ONE tick deadline between its phases. They are fractions,
    # not seconds, so changing the deadline rescales all of them together rather than silently
    # leaving a phase budgeted for a tick length that no longer exists.
    {"path": ["schedule", "gen_budget_frac"], "group": "speed",
     "label": "Share of a tick for inventing", "kind": "float", "min": 0.0, "max": 1.0,
     "help": "Fraction of the tick deadline generation may spend before it stops and hands the "
             "rest of the tick on. 0 removes the bound."},
    {"path": ["schedule", "vet_budget_frac"], "group": "speed",
     "label": "Share of a tick for vetting", "kind": "float", "min": 0.0, "max": 1.0,
     "help": "Fraction of the tick deadline the vetting phase may spend. Only bites when the "
             "producer/consumer split is OFF — a producer tick does not vet."},
    {"path": ["schedule", "drain_budget_frac"], "group": "speed",
     "label": "Share of a tick for draining", "kind": "float", "min": 0.0, "max": 1.0,
     "help": "Fraction of the tick deadline for re-vetting parked rows. Also inert under the "
             "split, where a separate consumer owns the drain."},
    {"path": ["schedule", "artifact_budget_frac"], "group": "speed",
     "label": "Share of a tick for writing packs", "kind": "float", "min": 0.0, "max": 1.0,
     "help": "Fraction of the tick deadline for building the buyer-facing pack of a PASS."},
    {"path": ["schedule", "artifact_budget_floor_s"], "group": "speed",
     "label": "Minimum pack-writing time (seconds)", "kind": "int", "min": 0, "max": 86400,
     "help": "A floor under the fraction above, so a short deadline cannot leave a PASS with too "
             "little time to render the artifact a buyer actually reads."},
    # ---- money ----
    {"path": ["spend", "daily_cap_usd"], "group": "money",
     "label": "Daily spend ceiling (USD)", "kind": "float", "min": 0.0, "max": 1000.0,
     "help": "0.0 means NO CAP. The console renders 0.0 as disarmed, in red, because '£0.00 cap' "
             "reads as the tightest possible ceiling when it is the absence of one."},
    {"path": ["spend", "warn_at_usd"], "group": "money",
     "label": "Warn at (USD)", "kind": "float", "min": 0.0, "max": 1000.0,
     "help": "Where the alert rail fires, below the ceiling."},
]


def _content_rule_knobs() -> list[dict]:
    """P5's actuator: the switch that promotes a content rule from shadow to blocking.

    GENERATED from `content_contract.RULES`, not typed out. There are 24 rules and a third of
    them share an actuator, so hand-writing the entries is how the console ends up offering a
    switch the gate no longer reads, or missing one it does. The registry is already the single
    declaration of which config key drives which check; this reads it.

    One entry per CONFIG KEY, not per rule, because `title`, `title_new_word` and `title_claim`
    are three rules on one switch. The label names every rule the switch moves, so an operator
    turning it on can see it is promoting three checks at once rather than the one they came for.
    """
    from prospector import content_contract

    by_key: dict[str, list] = {}
    for rule in content_contract.RULES:
        if rule.config_key:
            by_key.setdefault(rule.config_key, []).append(rule)

    out: list[dict] = []
    for key in sorted(by_key):
        rules = by_key[key]
        checks = ", ".join(sorted(r.check for r in rules))
        default_on = any(r.enforced_by_default for r in rules)
        out.append({
            "path": ["listing", key], "group": "content", "kind": "bool",
            "label": f"Enforce: {checks}",
            "help": (
                f"When on, the publish gate REFUSES a pack breaching {checks}. When off the "
                f"finding is still recorded on the pack's lint receipt, so the breach rate "
                f"accrues while the switch is down — that history is what `views content_rules` "
                f"reports, and what makes promoting this an evidence-based decision instead of a "
                f"guess. Check the rate before switching it on: on 2026-08-17 two shadow rules "
                f"were breaching 98% of packs, so promoting either would have stranded almost "
                f"the whole catalogue. "
                f"{'On by default.' if default_on else 'Off by default (shadow).'}"
            ),
        })
    return out


# Appended rather than written inline so the generation stays one obvious block. `extend`, not a
# second list, because `KNOBS_BY_KEY` below and every consumer of `KNOBS` must see one list.
KNOBS.extend(_content_rule_knobs())

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
    elif kind == "str":
        # Explicit, not the fall-through below: model pins are free text, and the fall-through
        # would have written back whatever JSON type arrived — a number, a list, a dict — into a
        # key the engine reads as a string.
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("expected text")
        coerced = str(value).strip()
        choices = spec.get("choices")
        if choices and coerced not in choices:
            raise ValueError(f"not allowed here: {coerced!r}. Allowed: {', '.join(choices)}")
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


def _act_drain_reset(cfg, payload: dict, preview: bool) -> dict:
    """Hand every retired row its re-vet budget back by clearing the attempt ledger.

    `drain_state.load` returns `{}` for a missing file and calls that "a real value"
    (`prospector/drain_state.py:130-131`), so deleting the ledger IS the reset. There is no
    separate un-retire path to write, and writing one would be a second definition of the same
    fact.

    It runs against the ACTIVE side, not this laptop. Resetting the laptop ledger while Fly's
    stayed full would be the same lie the read view exists to remove.

    The ledger is copied beside itself first. The counts are the only record of which rows had
    been worked and how often, and losing them costs re-vet money rather than correctness.

    This is deliberately not scoped to "only the retired rows". A row sitting at 4 of 5 got there
    the same way the retired ones did, and leaving it one outage short of retirement would keep
    exactly the bug this reset undoes.
    """
    side = str(payload.get("side") or "active").strip()
    if side not in DRAIN_SIDES:
        raise ValueError(f"unknown side {side!r}; expected one of {', '.join(DRAIN_SIDES)}")

    before = _drain_ledger(cfg, side=side)
    if before.get("error"):
        raise RuntimeError(f"cannot read the {before.get('side')} ledger, so it will not be "
                           f"cleared: {before['error']}")

    if preview:
        rows, retired = before.get("rows", 0), before.get("retired_count", 0)
        return {
            "action": "drain.reset",
            "side": before.get("side"),
            "active_side": before.get("active_side"),
            "ledger_path": before.get("ledger_path"),
            "store_dir": before.get("store_dir"),
            "rows": rows,
            "retired_count": retired,
            "histogram": before.get("histogram"),
            "max_attempts": before.get("max_attempts"),
            "warnings": before.get("warnings"),
            "effect": (
                f"Deletes {before.get('ledger_path')} on {before.get('side')}. {retired} retired "
                f"row(s) become drainable again and all {rows} row(s) go back to zero attempts. "
                "The next tick starts working them, which costs re-vet money."
                if rows else
                f"Nothing to do: {before.get('ledger_path')} holds no rows on "
                f"{before.get('side')}."),
            "cost": ("Roughly one re-vet per released row. MiniMax was measured at about "
                     "$0.0004 per check on 2026-08-19."),
            "backup": "<ledger>.bak-<UTC timestamp>, beside the ledger",
            "reversible": "Yes — copy the backup back over the ledger.",
        }

    after = _drain_ledger(cfg, side=side, reset=True)
    if after.get("error"):
        raise RuntimeError(f"the reset failed on {after.get('side')}: {after['error']}")
    return {
        "action": "drain.reset",
        "side": after.get("side"),
        "ledger_path": after.get("ledger_path"),
        "removed": after.get("removed"),
        "rows_released": before.get("rows", 0),
        "retired_released": before.get("retired_count", 0),
        "backup": after.get("backup"),
        "note": ("every row now reads as untried; the next tick picks them up"
                 if after.get("removed") else
                 "there was no ledger on disk, so every row already read as untried"),
    }


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
    from prospector.ops import config_editor as ce
    from prospector.ops import yaml_surgery as ys

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
    from prospector.ops import config_editor as ce

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
        # THE CHILD RUNS WITHOUT A SHELL, so nothing expands `~` on the way in. Expanded here,
        # before substitution, so it applies to the catalogued command only and never to a value
        # the browser sent.
        if part.startswith("~"):
            part = str(Path(part).expanduser())
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
    if not _tool_on_disk(root, tool["path"]).exists():
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


def _repair_copy_ids(cfg) -> list[str]:
    """The packs the shelf reader marks `shelf.repair_copy`, named one by one.

    Named, because the tool's own default selection cannot see them. `sweep_shelf_copy` picks
    rows by whether a `store/listings/*.json` file exists, and its comment records what that
    costs: 26 of the 29 copy-blocked packs on 2026-08-17 had a listing file and were still
    absent from the shelf. So the button this action backs ran over packs that were already
    fine and never touched the ones on the page the operator was looking at.
    """
    shelf = _read_shelf(cfg, {})
    if not shelf.get("reachable"):
        raise RuntimeError(
            f"the live shelf could not be read, so which packs need their copy repaired is "
            f"UNKNOWN, not none: {shelf.get('reason')}")
    return sorted(str(r["id"]) for r in (shelf.get("rows") or [])
                  if r.get("repair") == "shelf.repair_copy")


def _act_shelf_repair_copy(cfg, payload: dict, preview: bool) -> dict:
    """Rewrite the shelf copy that fails the linter, so those packs can be listed.

    Runs `repair_stranded_shelf_lines.py`, not `sweep_shelf_copy.py`. The sweep rewrites the
    one-liner only — a title over the 60-character limit made it print `defective: 0` and exit
    clean, which is why 14 of the 34 stranded packs sat behind a button that could not move
    them. The replacement repairs the title and the one-liner through `field_write`, graded by
    the publish gate's own `check_title` and `check_shelf_copy`.
    """
    ids = _repair_copy_ids(cfg)
    if not ids:
        return {"action": "shelf.repair_copy", "applied": False, "changed": False,
                "moat_affecting": False,
                "message": "No pack needs its shelf copy repaired — nothing on the shelf "
                           "reader is marked `shelf.repair_copy`."}
    limit = payload.get("limit")
    if limit:
        ids = ids[:int(limit)]
    argv = ["tools/repair_stranded_shelf_lines.py", "--fix", "--only", ",".join(ids)]
    return _run_repair(cfg, "shelf.repair_copy", argv, preview, payload=payload,
                       effect=f"rewrites the title and one-liner of the {len(ids)} pack(s) the "
                              f"shelf reader marks `shelf.repair_copy`. A rewrite is re-graded "
                              f"against the publish gate's own rules before it is accepted, and "
                              f"it may only re-word — every figure and institution in the "
                              f"original must survive. It does not list anything: publishing "
                              f"stays a separate, explicit action.")


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
                # Every act result carries this key, including the ones that do nothing. A
                # console reading `doc["data"]["moat_affecting"]` to decide how loudly to warn
                # got a KeyError on the do-nothing branch instead of a False.
                "moat_affecting": False,
                "message": "No stranded pass needs publishing — every pack the shelf reader "
                           "marks `shelf.publish_pending` is either already listed or its "
                           "dossier file is missing."}
    return _run_repair(cfg, "shelf.publish_pending", argv, preview, payload=payload,
                       effect=f"publishes the {len(paths)} PASS dossier(s) the shelf reader "
                              f"marks `shelf.publish_pending` — packs that cleared every gate "
                              f"and were never sent to the shelf. Named one by one; never "
                              f"`--all`, which would re-publish packs already selling.")


def _act_shelf_regate(cfg, payload: dict, preview: bool) -> dict:
    """Re-ask the gate about packs whose stored verdict predates the current rules.

    THE SAFEST ACTION ON THIS PAGE, and the one to run first. `--dry-run` returns at
    `bridge.py:1261`, before `price_for` — no Stripe Price, no R2 upload, no catalogue row, and
    nothing goes on sale.

    It is also the cheapest: no model call either, because the generation loop under `--dry-run`
    is `range(1, 1)`. The only thing it writes is `store/dossiers/<id>.lint.json`, which undo
    covers in full. The cost is network — the linter probes the URLs each pack cites, ~124s a
    pack measured 2026-08-17 — and `publish_passes` gates ~10 at a time, so 40 packs is minutes
    rather than the hour and a quarter it was while the gate ran one at a time.

    Why it exists: a receipt outlives the rules that wrote it. Editing the linter touches no
    dossier, so every receipt stays byte-identical and the shelf page goes on printing an
    answer nobody has re-asked. On 2026-08-17 five rules stopped blocking and seven stranded
    packs became sellable while every receipt on disk still said "blocked".

    It lists nothing. It replaces an out-of-date reason with a current one; putting a pack back
    on sale stays a separate, deliberate act.
    """
    shelf = _read_shelf(cfg, {})
    if not shelf.get("reachable"):
        raise RuntimeError(
            f"the live shelf could not be read, so which verdicts are stale is UNKNOWN, not "
            f"none: {shelf.get('reason')}")
    root = _repo_root()
    paths = sorted(f"store/dossiers/{r['id']}.pass.json" for r in (shelf.get("rows") or [])
                   if r.get("repair") == "shelf.regate"
                   and (root / "store" / "dossiers" / f"{r['id']}.pass.json").exists())
    if not paths:
        return {"action": "shelf.regate", "applied": False, "changed": False,
                "message": "Every stranded pack's verdict was produced by the rules running "
                           "now, so re-gating would ask a question that is already answered."}
    return _run_repair(cfg, "shelf.regate", ["-m", "tools.publish_passes", "--dry-run", *paths],
                       preview, payload=payload,
                       effect=f"re-runs the gate on the {len(paths)} stranded pack(s) whose "
                              f"stored verdict came from rules that have since changed, and "
                              f"rewrites each `.lint.json`. Mints nothing, publishes nothing, "
                              f"lists nothing — it only replaces an out-of-date reason with a "
                              f"current one.")


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
    "shelf.regate": _act_shelf_regate,
    "daemon.restart": _act_daemon_restart,
    "pause.arm": _act_pause_arm,
    "pause.disarm": _act_pause_disarm,
    "routing.set_moat_primary": _act_routing_set,
    "drain.reset": _act_drain_reset,
    "config.set": _act_config_set,
    "config.restore": _act_config_restore,
    "catalogue.set_listing": _act_catalogue_listing,
    "deliveries.resend": _act_delivery_resend,
    "tools.run": _act_tools_run,
    "tools.undo": _act_tools_undo,
    "engine.switch": _act_engine_switch,
    "engine.arm": _act_engine_arm,
    "engine.disarm": _act_engine_disarm,
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
    _t("scripts/process_audit.py", "Grade every automated job on this estate", False,
       "/processes", cmd=".venv/bin/python scripts/process_audit.py"),
    _t("prospector/run.py", "Operator state and quotas", False, "/engine",
       cmd=".venv/bin/python -m prospector.run operators"),
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
    _t("scripts/ops_state.py", "Live value of every fact the ops programme asserts", False, "/",
       run=True, cmd=".venv/bin/python scripts/ops_state.py"),
    _t("scripts/launchd_plists.py", "Launchd job definitions, and drift against them", False,
       "/engine", run=True, cmd=".venv/bin/python scripts/launchd_plists.py --check"),
    _t("scripts/estate_map.py", "The whole estate, probed live: Fly apps, customer URLs, laptop "
       "jobs, volumes, secret names", False, "/engine", run=True,
       cmd=".venv/bin/python scripts/estate_map.py"),
    _t("tools/spend_today.py", "Today's spend against the cap", False, "/spend"),
    # --- publish / republish ---
    _t("publish/publish.py", "The single publish entry point", True, "/catalogue",
       risk="external"),
    _t("tools/publish_offline.py", "Publish stored PASSes without regenerating", True,
       "/catalogue", risk="external"),
    _t("tools/publish_passes.py", "Generate content then publish", True, "/catalogue",
       risk="external", danger="costs model calls"),
    # The same tool with the money rail switched off. `--dry-run` returns at bridge.py:1261,
    # before `price_for`, so no Stripe Price, no R2 upload and no catalogue row — it reuses the
    # stored artifacts, runs every deterministic gate, and rewrites store/dossiers/<id>.lint.json.
    # risk="local" is therefore exact, and undo covers all of it.
    #
    # It only re-gates packs whose stored verdict is stale, so running it after a linter change
    # is how the catalogue's own answer to "why is this pack not on sale?" catches up with the
    # rules. Before this row the operator's only route to that was a terminal.
    _t("tools/publish_passes.py", "Re-gate stale verdicts (mints nothing)", True, "/catalogue",
       risk="local", cmd=".venv/bin/python tools/publish_passes.py --dry-run --all"),
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
    _t("tools/repair_stranded_shelf_lines.py", "Repair a pack's title and one-liner", True,
       "/tools"),
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
    # --- registered 2026-08-18 with the incident loop; docs/INCIDENT_PROCESS.md ---
    # Moved from /audit to /incidents on 2026-08-19, when that page was built. `screen` is not
    # part of the tool id, so the ids these rows have always had are unchanged and a browser
    # holding one between preview and confirm still resolves it.
    _t("scripts/incident.py", "Incidents: what broke, what class it belongs to, was the fix graded",
       False, "/incidents", cmd=".venv/bin/python scripts/incident.py check"),
    _t("scripts/incident.py", "What takes longest and what repeats, with recommendations", False,
       "/incidents", cmd=".venv/bin/python scripts/incident.py friction"),
    # `external` because it creates GitHub issues, which no local snapshot can roll back.
    _t("scripts/incident.py", "Open a ticket for every incident with no mechanism behind it",
       True, "/incidents", risk="external",
       cmd=".venv/bin/python scripts/incident.py ticket",
       danger="opens real GitHub issues; run the dry run first"),
    _t("scripts/incident.py", "Show what a ticket run would open, without opening anything",
       False, "/incidents", cmd=".venv/bin/python scripts/incident.py ticket --dry-run"),
    # --- registered 2026-08-19. Hermes lives in ~/.hermes, a different repo, but the operator
    # should not have to know that: the founder's ask was "make this visible in ops".
    _t("~/.hermes/scripts/hermes_selfcheck.py", "Is Hermes actually healthy? six invariants, "
       "not liveness", False, "/audit",
       cmd="/usr/local/bin/python3 ~/.hermes/scripts/hermes_selfcheck.py"),
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
    # --live also asks GitHub which runners are registered, which is the half CI cannot check
    # itself: the workflow can only see the workflow.
    _t("scripts/ci_capacity.py", "Does CI still fit on this machine alongside the daemons?",
       False, "/engine", cmd="python3 scripts/ci_capacity.py --live", risk="external"),
    _t("scripts/launchd_plists.py", "Record the current job definitions", True, "/engine",
       cmd="python3 scripts/launchd_plists.py --snapshot",
       danger="overwrites the tracked copies with whatever is live, so run --check first "
              "or an unwanted change becomes the new baseline"),
    # --- registered 2026-08-18 ---
    # An operator button, not a developer's script, because the number it reports is a business
    # number: work that is finished and not shipped. On 2026-08-17 the repo held 61 local
    # branches and 49 worktrees, and nobody could say how much of that was unlanded work without
    # running three probes by hand and getting three different answers.
    _t("scripts/branch_backlog.py", "How much finished work is sitting unmerged on a branch?",
       False, "/audit"),
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
    "scripts/seed_action_cache.sh": "fills the self-hosted runners' action cache; CI plumbing, "
                                    "run once on the runner box, not from an ops page",
    "scripts/setup_worktree.sh": "makes a git worktree usable; a developer's machine, not ops",
    "scripts/prove_test_fails.py": "edits source files to prove a test goes red, then puts them "
                                  "back; it belongs to whoever is writing the test, and "
                                  "pointing it at a running estate would mutate live code",
    "scripts/session_check.py": "asks whether an agent session left work behind — uncommitted, "
                               "unpushed, a branch with no PR; a session's own hygiene, and there "
                               "is no session to check from an ops page",
    "scripts/worktree_gc.py": "reports and removes merged git worktrees; a developer's disk, and "
                              "it refuses to touch another session's tree, so it has no meaning "
                              "off the machine that made them",
    "scripts/estate_census.py": "counts tracked files that nothing else refers to; a repo-health "
                                "reading for whoever is deleting dead code, not an action on the "
                                "running platform",
    "scripts/test_impacted.py": "picks the tests a local edit can affect; a developer's loop",
    "scripts/verify_engine_change.sh": "the pre-commit proof that an engine change is safe",
    "tools/commit_mine.sh": "commits exactly the named paths; a developer's git helper",
    "tools/backfill_human_register.py": "a one-off repair that back-filled the human register after a schema change; kept for the record, not for re-running",
    "tools/register_repair_probe.py": "reports rows the human register cannot resolve; a developer's diagnostic, and it names local paths an operator has no access to",
    # Claude Code hooks — the harness fires these, they have no operator-facing run
    "scripts/graphify_query_hook.py": "a UserPromptSubmit hook; the harness fires it",
    "scripts/graphify_session_hook.py": "a SessionStart hook; the harness fires it",
    "scripts/handoff.py": "writes an agent session handoff; not an operator action",
    # the console itself, and its predecessor
    "scripts/run_ops_console.sh": "launches this console; a button that starts the page you are already on",
    "tools/build_sample_fixture.py": "builds an offline retrieval fixture for the test suite, not a live action",
    "scripts/build_docs_bundle.py": "bundles docs/ into one shareable HTML file and writes it "
                                    "into the repo checkout, to be committed. The engine runs "
                                    "from a detached mirror of main, so a button here would "
                                    "write a file nothing ever reads and no one can commit",
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
    "scripts/ci_local.py": "replays a CI job's shell steps on this machine; a developer's loop",
    "scripts/prune_branches.py": "retires merged git branches and dead worktrees; a developer's "
                                 "housekeeping, not an estate action",
    "scripts/warm_ci_uv_cache.sh": "prebuilds wheels into the runners' shared uv cache; CI "
                                   "plumbing, run on the runner box",
    "tools/_audit_baseline_tmp.py": "a one-off inventory of failure-swallowing call sites; the "
                                    "audit it fed is done, it is kept as the baseline",
    # the migration control plane. Both are reachable from the console already, as actions rather
    # than as tool buttons, so listing them again would give the operator two ways to do one thing.
    "scripts/engine_failover.py": "the engine failover control plane; the console drives it through "
                                  "the engine.switch, engine.arm and engine.disarm actions and the "
                                  "engine_location view, not as a tool button",
    "scripts/store_migrate.py": "packs and verifies the engine store during a cutover; "
                                "deploy/cutover.sh calls it, never an operator",
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
