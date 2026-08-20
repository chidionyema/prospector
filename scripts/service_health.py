#!/usr/bin/env python3
"""Ask every deployed service whether it is still serving, and alert when one stops.

WHY THIS EXISTS. `scripts/deploy_now.py` gave every service a Deploy button and
`scripts/rollback_now.py` gave every service a Roll back button. Both are controls with no
feedback: an operator could deploy a broken build from a web page and nothing on this estate
would ever say so. Measured 2026-08-20, before this file existed: `scripts/watch_engine.py`
makes no HTTP request at all (it tails local files), no launchd job or supervisord program
probed a public URL, and the only code that asked mumchimp.com anything was the rollback
drill, which runs when a human clicks it. Founder, 2026-08-20: "needs to be absolutely rock
solid and bulletproof, rollback also, verified with automated tests and a drill function in
ops and realtime notifying".

WHAT IT DOES NOT DUPLICATE. Fly already health-checks two of the four apps and refuses a
release that fails them: `api.fly.toml` checks `/catalog` every 30s, `web.fly.toml` checks
`/api/health` every 15s. This rail is different in two ways that matter. It covers the engine,
whose fly.toml declares NO checks block, so a deploy that boots a dead ops console is accepted
by Fly as a healthy release. And it reaches a PERSON: Fly's checks restart a machine quietly,
this one puts the failure in Telegram with the command that undoes it.

THE PROBE TABLE IS NOT DEFINED HERE. It is `rollback_now.SERVICES[*]["probe"]`, the same
checks the rollback drill runs. Two copies of "what healthy means" drift, and the copy nobody
runs is the one that goes stale.

    python scripts/service_health.py            # one pass, human-readable
    python scripts/service_health.py --json     # one pass, machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from rollback_now import SERVICES, find_fly, rollback_command  # noqa: E402

from prospector.config import load_config  # noqa: E402
from prospector.scheduler import paths  # noqa: E402
from prospector.scheduler.alerts import CRITICAL, emit_alert, resolve_alert  # noqa: E402

# Two consecutive failing passes before anyone is woken. One pass is not evidence of an
# outage: `_probe_one` already retries five times inside a single check, so a single failing
# pass means ~2.5 minutes of failure, and a Fly edge blip or a rolling restart can produce
# that without anything being wrong. Two passes at the supervisord interval is ~10 minutes of
# a service being down, which is an outage. Raising this number buys quiet at the cost of
# minutes of silence during a real one.
FAILURES_BEFORE_ALERT = 2

# One alert per service per hour while it stays down; `resolve_alert` clears it the moment it
# comes back, and clearing also clears the throttle, so a flapping service pages every time it
# falls over rather than once an hour.
THROTTLE_S = 3600

_STATE_NAME = "service_health.json"


def state_path(cfg) -> Path:
    return paths.scheduler_dir(cfg) / _STATE_NAME


def load_state(cfg) -> dict:
    try:
        data = json.loads(state_path(cfg).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(cfg, state: dict) -> None:
    path = state_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # The temp name carries the PID. Two passes CAN overlap: supervisord runs this
        # every 300s and the /deploys screen can run it by hand at the same moment. With
        # one shared temp name, the second process replaces a file the first is still
        # writing, and half a JSON document lands as the state. load_state survives that
        # (junk reads as {}), but the consecutive-failure count resets, which delays the
        # page by one whole pass during the outage it exists to report. `replace` is
        # atomic, so a per-process temp makes the overlap harmless instead of merely
        # survivable.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        tmp.replace(path)
    except OSError as exc:
        # A monitor that cannot remember yesterday still reports today correctly. It loses
        # only the consecutive-failure count, which makes it noisier, never blind.
        print(f"warning: could not write {path}: {exc}", file=sys.stderr)


def alert_key(name: str) -> str:
    return f"service_down:{name}"


def repair_hint(name: str) -> str:
    """The command that puts this service back, so the alert carries its own fix."""
    svc = SERVICES.get(name) or {}
    fly = find_fly() or "flyctl"
    app = svc.get("app", name)
    return (f"Roll it back from the ops console /deploys screen, or run:\n"
            f"  {' '.join(rollback_command(fly, app, svc.get('config', ''), '<previous ImageRef>'))}\n"
            f"  (python scripts/rollback_now.py {name} prints the exact image and asks first)")


def check_service(name: str, svc: dict) -> dict:
    """One pass over one service. Never raises: a monitor that dies is worse than a red one."""
    from rollback_now import _probe_all  # imported here so a test can monkeypatch it

    if shutil.which("curl") is None:
        # A monitor that cannot make a request has learned nothing about the service. Calling
        # that "down" would page the founder about production every interval because of a
        # missing package in the image the MONITOR runs in.
        return {"service": name, "status": "unproven", "lines": [
            f"{name}: no curl on this host, so nothing was measured; UNPROVEN"]}

    checks = svc.get("probe") or []
    if not checks:
        # searxng has no public route from anywhere this can run, so nothing it can do proves
        # the app is up. Reporting it healthy would be a lie; alerting forever would be noise
        # nobody reads. It is stated as unproven and left alone.
        return {"service": name, "status": "unproven", "lines": [
            f"{name}: no request this host can make proves it (private network); UNPROVEN"]}
    try:
        ok, lines = _probe_all(name, svc)
    except Exception as exc:  # noqa: BLE001 — a probe that blew up is a failed probe
        return {"service": name, "status": "down", "lines": [f"{name}: probe raised {exc!r}"]}
    return {"service": name, "status": "up" if ok else "down", "lines": lines}


def run_once(cfg=None) -> dict:
    cfg = cfg if cfg is not None else load_config(None)
    state = load_state(cfg)
    now = datetime.now(timezone.utc).isoformat()
    results, alerted, resolved = [], [], []

    for name, svc in SERVICES.items():
        result = check_service(name, svc)
        results.append(result)
        entry = state.get(name) if isinstance(state.get(name), dict) else {}

        if result["status"] == "unproven":
            entry["last_checked"] = now
            entry["status"] = "unproven"
            state[name] = entry
            continue

        if result["status"] == "up":
            if entry.get("alerted"):
                resolve_alert(cfg, key=alert_key(name),
                              reason=f"{name} answered its health checks again")
                resolved.append(name)
            state[name] = {"status": "up", "failures": 0, "last_ok": now, "last_checked": now}
            continue

        failures = int(entry.get("failures") or 0) + 1
        entry = {"status": "down", "failures": failures, "last_checked": now,
                 "last_ok": entry.get("last_ok"), "alerted": bool(entry.get("alerted"))}
        if failures >= FAILURES_BEFORE_ALERT:
            body = "\n".join(result["lines"]) + "\n\n" + repair_hint(name)
            emit_alert(cfg, severity=CRITICAL, key=alert_key(name),
                       title=f"{name} is failing its health checks",
                       message=body, throttle_s=THROTTLE_S,
                       service=name, consecutive_failures=failures)
            entry["alerted"] = True
            alerted.append(name)
        state[name] = entry

    # A service deleted from the table would otherwise leave its last alert active forever:
    # nothing checks it any more, so nothing can ever clear it, and ALERT.txt keeps showing an
    # outage in an app that no longer exists. This estate has shipped a write-only alert before.
    for gone in [name for name in state if name not in SERVICES]:
        if isinstance(state[gone], dict) and state[gone].get("alerted"):
            resolve_alert(cfg, key=alert_key(gone),
                          reason=f"{gone} is no longer a deployed service; nothing checks it")
            resolved.append(gone)
        del state[gone]

    save_state(cfg, state)
    return {"checked_at": now, "results": results, "alerted": alerted, "resolved": resolved,
            "down": [r["service"] for r in results if r["status"] == "down"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print the pass as JSON")
    args = ap.parse_args(argv)

    report = run_once()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for result in report["results"]:
            svc = SERVICES.get(result["service"]) or {}
            mark = {"up": "ok  ", "down": "DOWN", "unproven": "??  "}[result["status"]]
            print(f"{mark} {result['service']} ({svc.get('app', '')})")
            for line in result["lines"]:
                print("    " + line.strip())
        if report["alerted"]:
            print(f"\nALERTED: {', '.join(report['alerted'])}")
        if report["resolved"]:
            print(f"RECOVERED: {', '.join(report['resolved'])}")
        if not report["down"]:
            print("\nevery service with a public route answered its checks")

    # Exit 1 only when something is DOWN. An unproven service is not a failure, or this would
    # be permanently red because of searxng and nobody would read its exit code again.
    return 1 if report["down"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
