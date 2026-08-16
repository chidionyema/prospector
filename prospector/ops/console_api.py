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
import secrets
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

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
    out["pause"] = pause_view(cfg)
    out["providers"] = provider_view(cfg)
    out["queue"] = queue_view(cfg, lookback_h=float(args.get("lookback_h") or 24.0))
    try:
        out["routing"] = routing_view(cfg)
    except Exception as exc:  # StaleProcessGlobal and friends are information, not a crash
        out["routing"] = {"error": f"{exc}", "error_kind": type(exc).__name__}
    out["spend"] = _spend_headline(cfg)
    return out


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
                rec["unreadable"] = f"{exc}"
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
            "note": "Tools marked run=false are shown with their command and are not executable "
                    "from the web. Destructive tools are never runnable here."}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


READS: dict[str, Callable[[Any, dict], Any]] = {
    "status": _read_status,
    "queue": _read_queue,
    "providers": _read_providers,
    "routing": _read_routing,
    "spend": _read_spend,
    "metrics": _read_metrics,
    "runs": _read_runs,
    "run": _read_run,
    "candidate": _read_candidate,
    "config": _read_config,
    "intents": _read_intents,
    "tools": _read_tools,
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


ACTIONS: dict[str, Callable[[Any, dict, bool], dict]] = {
    "pause.arm": _act_pause_arm,
    "pause.disarm": _act_pause_disarm,
    "routing.set_moat_primary": _act_routing_set,
    "config.set": _act_config_set,
    "config.restore": _act_config_restore,
    "catalogue.set_listing": _act_catalogue_listing,
}

#: Actions the console refuses by name rather than by absence, so the error says WHY.
#: `ADMIN_CONSOLE_PROGRAM.md` §7 carries the full price-change design; nothing here implements it.
REFUSED_ACTIONS: dict[str, str] = {
    "catalogue.set_price": (
        "Price writes are not implemented, deliberately. prospector/bridge.py is the money rail: "
        "one PriceDecision mints the Stripe Price and writes the catalogue row together so they "
        "cannot drift. A console that PATCHed the catalogue price directly would write the row "
        "while Stripe still held the old price. Use tools/set_live_pack_price.py; the flow is "
        "specified in docs/ADMIN_CONSOLE_PROGRAM.md §7."
    ),
    "catalogue.reprice": (
        "Bulk repricing is not implemented from the web. See tools/reprice_live_packs.py and "
        "docs/ADMIN_CONSOLE_PROGRAM.md §7."
    ),
    "index.reconcile": (
        "scripts/reconcile_orphan_index.py deletes index rows. Destructive tools are never "
        "runnable from this surface; run it at a terminal."
    ),
}


# --------------------------------------------------------------------------- #
# The operator CLI catalogue
# --------------------------------------------------------------------------- #
#: A hand-kept table, NOT a directory scan. A scan can list files; it cannot say whether a tool
#: writes to the money rail, and that is the only property that decides whether the console may
#: run it. `exists` is filled in at read time, so a tool that is renamed shows up as missing
#: instead of silently vanishing from the operator's map.
def _t(path, purpose, writes, screen, run=False, danger=None, cmd=None):
    return {"path": path, "purpose": purpose, "writes": writes, "screen": screen,
            "run": run, "danger": danger,
            "command": cmd or f".venv/bin/python {path}"}


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
       "/engine", cmd="launchctl list | grep com.prospector"),
    _t("prospector/consumer.py", "The drain loop (launchd owns it)", True, "/engine",
       cmd="launchctl list | grep com.prospector"),
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
    _t("tools/govern.py", "Run a command under a concurrency ceiling", False, "/tools"),
    # --- publish / republish ---
    _t("publish/publish.py", "The single publish entry point", True, "/catalogue"),
    _t("tools/publish_offline.py", "Publish stored PASSes without regenerating", True,
       "/catalogue"),
    _t("tools/publish_passes.py", "Generate content then publish", True, "/catalogue",
       danger="costs model calls"),
    _t("tools/backfill_missing_listings.sh", "Mass publish stranded PASSes", True, "/catalogue",
       danger="bulk publish — review the stranded list first",
       cmd="bash tools/backfill_missing_listings.sh"),
    _t("tools/unlist_killed.py", "Unlist packs re-vetted to KILL", True, "/catalogue"),
    _t("tools/retire_rotted_passes.py", "Retire PASSes whose citations rotted", True,
       "/catalogue"),
    _t("tools/verify_pass_shelf_coverage.py", "PASSes the shelf does not show", False,
       "/catalogue", run=True),
    _t("tools/verify_selling_catalogue.py", "Every selling pack backed by a PASS", False,
       "/catalogue", run=True),
    _t("tools/preview_packs.py", "Read any pack in full without buying", False, "/catalogue"),
    _t("tools/pack_defect_census.py", "Live packs carrying each defect", False, "/catalogue"),
    _t("tools/floor_signature.py", "Deterministic-floor copy still on the shelf", False,
       "/catalogue"),
    _t("scripts/pack_banner_probe.py", "Live packs showing a retired banner", False, "/catalogue"),
    # --- backfill / repair ---
    _t("tools/backfill_facets.py", "Tag packs with discovery facets", True, "/tools"),
    _t("tools/backfill_listing_copy.py", "Replace floor copy with generated copy", True,
       "/tools"),
    _t("tools/backfill_bundle_html.py", "Re-render a listed pack's zip", True, "/tools"),
    _t("tools/backfill_pack_currency.py", "Repair currency on pre-market packs", True, "/tools"),
    _t("tools/backfill_archived_url.py", "Backfill archived source urls", True, "/tools"),
    _t("tools/backfill_audience.py", "Copy audience tag into the index", True, "/tools"),
    _t("tools/backfill_market.py", "Stamp legacy dossiers with market", True, "/tools",
       danger="no rehearsal flag — it writes on the first run"),
    _t("tools/sweep_shelf_copy.py", "Re-grade and rewrite shelf copy", True, "/tools"),
    _t("tools/retitle_catalogue.py", "Rewrite live pack titles", True, "/tools"),
    _t("tools/site_wide_dash_cleanup.py", "Rewrite dashes in storefront source", True, "/tools",
       danger="edits public source — never one-tap"),
    _t("scripts/backfill_tiers.py", "Fill ambition_tier on legacy dossiers", True, "/tools"),
    _t("scripts/backfill_price_anchors.py", "Backfill cited price anchors", True, "/tools"),
    _t("scripts/reconcile_orphan_index.py", "Delete index rows with no dossier", True, "/tools",
       danger="DESTRUCTIVE — never runnable from the web"),
    _t("tools/review_figures.py", "Human verification of untraceable figures", True, "/tools"),
    # --- money rail: shown, never run ---
    _t("tools/set_live_pack_price.py", "Set one pack to a named rung", True, "/catalogue",
       danger="MONEY RAIL — console shows the command only"),
    _t("tools/reprice_live_packs.py", "Re-price packs with unbillable stub ids", True, "/tools",
       danger="MONEY RAIL — console shows the command only"),
    _t("tools/reprice_to_charm_rungs.py", "Move packs onto charm rungs", True, "/tools",
       danger="MONEY RAIL — console shows the command only"),
    _t("scripts/backfill_ladder_prices.py", "Move the catalogue onto the L1 ladder", True,
       "/tools", danger="MONEY RAIL — console shows the command only"),
    _t("tools/depth_reprice_preview.py", "Before/after for the depth ladder", False, "/tools"),
    _t("tools/price_history.py", "Who moved a price and why", False, "/catalogue"),
    # --- integrity / probes ---
    _t("scripts/backup_store.py", "Back up dossiers and ledger to R2", True, "/tools"),
    _t("scripts/restore_drill.py", "Prove the backup restores", False, "/tools"),
    _t("scripts/store_audit.py", "Audit the operator's store", False, "/tools"),
    _t("scripts/blocker_probe.py", "Which programme items are blocked", False, "/tools"),
    _t("scripts/load_gate.py", "Is the machine fit to trust a test result", False, "/tools"),
    _t("scripts/popdd_verify.py", "The lane-aware proof runner", False, "/tools"),
    _t("scripts/site_spec_probe.py", "Site spec ledger against the tree", False, "/tools"),
    _t("scripts/graphify_sweep.py", "Graph freshness scoreboard", True, "/tools"),
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
    _t("tools/make_kill_log.py", "Bake the public kill log", True, "/tools"),
    _t("tools/make_sample_report.py", "Bake the public sample report", True, "/tools"),
]


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
    ap.add_argument("verb", choices=["read", "act", "views", "actions"])
    ap.add_argument("name", nargs="?", default="")
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
