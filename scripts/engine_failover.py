#!/usr/bin/env python3
"""Where is the engine, is it alive, and how do we move it - one command for all three.

    engine_failover.py status [--json] [--deep]   both sides, health and freshness
    engine_failover.py check                      one poll; what the watchdog job runs
    engine_failover.py arm  / disarm              turn automatic failover on and off
    engine_failover.py switch --to laptop|fly     move the engine, by hand
    engine_failover.py sync                       pull Fly's money files down to the standby

WHY THIS FILE EXISTS
--------------------
The engine moved to Fly on 2026-08-18. The laptop is kept as a cold standby. Two questions then
have to have a command behind them rather than a paragraph: "which side is carrying the load
right now", and "what happens at 4am when Fly's machine dies".

THE STATE LIVES OUTSIDE BOTH SIDES.
~/.prospector/ holds the active-side marker, the arm switch and the event log. It is deliberately
not in either engine's store directory: a marker that lives inside the thing it describes is gone
exactly when it is needed.

THE FIVE RULES OF AUTOMATIC FAILOVER
------------------------------------
Automatic failover can lose money two ways - by not firing, and by firing wrongly into two live
engines (EDGE-1: two engines keep two spend ledgers and can spend twice the $100 daily cap). So
it is deliberately hard to fire:

  1. It only fires when ARMED. Disarmed is the default and a successful failover disarms itself,
     so it can never flap.
  2. It only fires when the marker says Fly is the active side. It never "fails over" to the side
     that is already running.
  3. It only fires when the Fly API was REACHABLE and told us the machine is not started.
     An unreachable Fly API is far more likely to be this laptop's wifi than a Fly outage, and
     failing over on our own network glitch is how you get two engines. Unreachable means ALERT,
     never act.
  4. It only fires after N consecutive polls agree (default 5, i.e. 5 minutes). One bad poll is
     a blip.
  5. It fences the old side FIRST. `fly scale count 0` must succeed before the laptop is started.
     If the fence fails, the failover is abandoned, because the alternative is two writers.

WHAT IT COSTS WHEN IT FIRES
---------------------------
Whatever the Fly ledger gained since the last `sync`. That is why `sync` runs every 15 minutes
and why `status` prints the standby's staleness in minutes: the number is the exposure, and it
should be looked at, not assumed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TARGETS = REPO / "deploy" / "targets"

CTRL = Path(os.environ.get("PROSPECTOR_CTRL_DIR", Path.home() / ".prospector"))
ACTIVE_F = CTRL / "ACTIVE"
ARMED_F = CTRL / "AUTOFAILOVER"
FAILS_F = CTRL / "failcount"
EVENTS_F = CTRL / "events.jsonl"
STANDBY = CTRL / "standby"          # the pulled copy of Fly's money files

FLY_APP = os.environ.get("PROSPECTOR_FLY_APP", "prospector-engine")
LAPTOP_STORE = Path(os.environ.get("PROSPECTOR_STORE_DIR",
                                   "/Users/chidionyema/Documents/code/prospector/store"))
NEEDED_AGREEING_POLLS = int(os.environ.get("PROSPECTOR_FAILOVER_POLLS", "5"))

# The two files that carry money. The spend ledger decides whether the daily cap has been hit;
# the database carries the catalogue and the entitlements. Everything else - dossiers, logs,
# caches - is reproducible, so the standby copy does not carry it and the sync stays cheap
# enough to run every fifteen minutes.
MONEY_FILES = ("prospector.jsonl", "prospector.db")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def event(kind: str, **fields) -> None:
    CTRL.mkdir(parents=True, exist_ok=True)
    with EVENTS_F.open("a") as fh:
        fh.write(json.dumps({"at": now(), "event": kind, **fields}) + "\n")


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except OSError as exc:
        return 127, "", str(exc)


def active_side() -> str:
    try:
        return ACTIVE_F.read_text().strip() or "unknown"
    except OSError:
        return "unknown"


def set_active(side: str) -> None:
    CTRL.mkdir(parents=True, exist_ok=True)
    ACTIVE_F.write_text(side + "\n")


# --------------------------------------------------------------------------- probes

def probe_fly(deep: bool = False) -> dict:
    """Is the Fly machine started, and if asked, is it still ticking?

    `reachable` is a separate field from `healthy` on purpose - rule 3 above turns on the
    difference between "Fly says it is down" and "we could not ask Fly".
    """
    out: dict = {"side": "fly", "app": FLY_APP, "reachable": False, "healthy": False}
    if not shutil.which("fly"):
        out["error"] = "fly CLI not installed on this machine"
        return out
    rc, so, se = sh(["fly", "machines", "list", "-a", FLY_APP, "--json"], timeout=45)
    if rc != 0:
        out["error"] = (se or so).strip()[:200]
        return out
    try:
        machines = json.loads(so)
    except json.JSONDecodeError:
        out["error"] = "fly returned output that is not JSON"
        return out
    out["reachable"] = True          # we asked Fly and Fly answered
    out["machines"] = len(machines)
    out["state"] = machines[0].get("state") if machines else "none"
    out["machine_id"] = machines[0].get("id") if machines else None
    if len(machines) > 1:
        # Two machines on a single-writer app is EDGE-1 on the Fly side.
        out["error"] = f"{len(machines)} machines exist; exactly one is allowed"
        return out
    out["healthy"] = out["state"] == "started"
    if deep and out["healthy"]:
        rc, so, _ = sh(["fly", "ssh", "console", "-a", FLY_APP, "-C",
                        "/bin/sh -lc 'echo TICK=$(date -r /data/store/prospector.jsonl +%s) "
                        "LINES=$(wc -l < /data/store/prospector.jsonl)'"], timeout=90)
        for token in so.split():
            if token.startswith("TICK="):
                try:
                    out["ledger_age_min"] = round((time.time() - int(token[5:])) / 60, 1)
                except ValueError:
                    pass
            elif token.startswith("LINES="):
                try:
                    out["ledger_lines"] = int(token[6:])
                except ValueError:
                    pass
    return out


def probe_laptop(deep: bool = False) -> dict:
    """Is this machine running the engine? Always reachable - we are standing on it."""
    out: dict = {"side": "laptop", "reachable": True, "healthy": False}
    rc, so, _ = sh(["pgrep", "-f", "prospector.scheduler.run_scheduled"], timeout=15)
    out["scheduler_pids"] = [p for p in so.split() if p]
    rc2, so2, _ = sh(["launchctl", "print-disabled", f"gui/{os.getuid()}"], timeout=15)
    out["fenced"] = '"com.prospector.scheduler" => disabled' in so2 or \
                    '"com.prospector.scheduler" => true' in so2
    ledger = LAPTOP_STORE / "prospector.jsonl"
    if ledger.exists():
        out["ledger_age_min"] = round((time.time() - ledger.stat().st_mtime) / 60, 1)
        if deep:
            with ledger.open("rb") as fh:
                out["ledger_lines"] = sum(1 for _ in fh)
    else:
        out["error"] = f"no ledger at {ledger}"
    out["healthy"] = bool(out["scheduler_pids"]) and ledger.exists()
    return out


def probe_standby() -> dict:
    """How stale is the copy a failover would start from? This number IS the exposure."""
    out: dict = {"files": {}}
    oldest = None
    for name in MONEY_FILES:
        f = STANDBY / name
        if not f.exists():
            out["files"][name] = None
            oldest = -1
            continue
        age = round((time.time() - f.stat().st_mtime) / 60, 1)
        out["files"][name] = {"bytes": f.stat().st_size, "age_min": age}
        oldest = age if oldest is None else max(oldest, age)
    out["staleness_min"] = oldest
    out["usable"] = oldest is not None and oldest >= 0
    return out


# --------------------------------------------------------------------------- commands

def cmd_status(args) -> int:
    fly = probe_fly(deep=args.deep)
    lap = probe_laptop(deep=args.deep)
    report = {
        "at": now(),
        "active": active_side(),
        "autofailover": "armed" if ARMED_F.exists() else "disarmed",
        "consecutive_failed_polls": read_fails(),
        "sides": {"fly": fly, "laptop": lap},
        "standby": probe_standby(),
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    def line(p: dict) -> str:
        mark = "UP  " if p["healthy"] else ("DOWN" if p["reachable"] else "??? ")
        bits = [f"state={p.get('state')}" if "state" in p else "",
                f"pids={','.join(p.get('scheduler_pids', [])) or '-'}" if p["side"] == "laptop" else "",
                f"fenced={p.get('fenced')}" if p["side"] == "laptop" else "",
                f"ledger={p['ledger_age_min']}m old" if "ledger_age_min" in p else "",
                f"lines={p['ledger_lines']:,}" if "ledger_lines" in p else "",
                p.get("error", "")]
        return f"  {mark}  {p['side']:<7} " + "  ".join(b for b in bits if b)

    print(f"engine location: ACTIVE={report['active']}   autofailover={report['autofailover']}")
    print(line(fly))
    print(line(lap))
    sb = report["standby"]
    print(f"  standby copy: {'stale by %s min' % sb['staleness_min'] if sb['usable'] else 'MISSING - a failover would start from the laptop own store'}")
    if report["consecutive_failed_polls"]:
        print(f"  !! {report['consecutive_failed_polls']} consecutive failed polls of the active side")
    return 0 if report["sides"][report["active"]]["healthy"] else 1


def read_fails() -> int:
    try:
        return int(FAILS_F.read_text().strip())
    except (OSError, ValueError):
        return 0


def write_fails(n: int) -> None:
    CTRL.mkdir(parents=True, exist_ok=True)
    FAILS_F.write_text(str(n))


def cmd_check(args) -> int:
    """One poll. Returns 0 when the active side is healthy, 1 when it is not, 2 on a failover."""
    side = active_side()
    if side not in ("fly", "laptop"):
        print(f"active side is '{side}' - nothing to check. Set it with: switch --to <side>")
        return 0
    probe = probe_fly() if side == "fly" else probe_laptop()

    if probe["healthy"]:
        if read_fails():
            event("recovered", side=side, after_polls=read_fails())
        write_fails(0)
        return 0

    # Rule 3: could not ask, so do not act.
    if not probe["reachable"]:
        event("unreachable", side=side, error=probe.get("error"))
        print(f"{side} unreachable ({probe.get('error')}) - alerting, NOT failing over", file=sys.stderr)
        return 1

    n = read_fails() + 1
    write_fails(n)
    event("unhealthy", side=side, consecutive=n, state=probe.get("state"),
          error=probe.get("error"))
    print(f"{side} is DOWN (state={probe.get('state')}), {n}/{NEEDED_AGREEING_POLLS} polls agree",
          file=sys.stderr)

    if not ARMED_F.exists():            # rule 1
        print("automatic failover is disarmed - not acting", file=sys.stderr)
        return 1
    if side != "fly":                   # rule 2
        print("automatic failover only moves fly -> laptop", file=sys.stderr)
        return 1
    if n < NEEDED_AGREEING_POLLS:       # rule 4
        return 1

    print(f"FAILING OVER: fly has been down for {n} consecutive polls", file=sys.stderr)
    return do_failover()


def call_adapter(side: str, verb: str, timeout: int = 900) -> tuple[int, str, str]:
    script = TARGETS / f"{side}.sh"
    return sh(["/bin/bash", "-c", f'set -euo pipefail; . "{script}"; {verb}'], timeout=timeout)


def do_failover() -> int:
    event("failover_started", frm="fly", to="laptop")

    # Rule 5: fence the old side FIRST. Nothing else happens until Fly has zero machines.
    rc, so, se = sh(["fly", "scale", "count", "0", "-a", FLY_APP, "--yes"], timeout=180)
    if rc != 0:
        event("failover_abandoned", reason="could not fence fly", error=(se or so)[:300])
        print("could not scale fly to 0 - ABANDONING failover rather than run two engines",
              file=sys.stderr)
        return 1
    event("fenced", side="fly")

    # Restore the freshest money files we hold. If the standby copy is missing we still start,
    # on the laptop's own store, and say so loudly - a stale engine beats no engine, but the
    # operator has to be told which one they got.
    sb = probe_standby()
    if sb["usable"]:
        for name in MONEY_FILES:
            src = STANDBY / name
            if not src.exists():
                continue
            dst = LAPTOP_STORE / name
            if dst.exists():
                # Keep what the laptop had. A failover that turns out to have restored the wrong
                # thing must be undoable, and the laptop's own copy is the only other candidate.
                shutil.copy2(dst, dst.with_name(dst.name + ".pre-failover"))
            shutil.copy2(src, dst)
        event("restored", staleness_min=sb["staleness_min"], files=list(MONEY_FILES))
        print(f"restored standby copy (stale by {sb['staleness_min']} min)", file=sys.stderr)
    else:
        event("restore_skipped", reason="no standby copy")
        print("NO standby copy - starting the laptop on its own store, which may be old",
              file=sys.stderr)

    rc, so, se = call_adapter("laptop", "t_start")
    print(so, se, file=sys.stderr)
    if rc != 0:
        event("failover_failed", stage="t_start", error=(se or so)[:300])
        return 1

    set_active("laptop")
    ARMED_F.unlink(missing_ok=True)     # rule 1: a successful failover disarms itself
    write_fails(0)
    event("failover_done", frm="fly", to="laptop", staleness_min=sb.get("staleness_min"))
    print("FAILED OVER to laptop. Automatic failover is now disarmed.", file=sys.stderr)
    return 2


def cmd_sync(args) -> int:
    """Pull Fly's money files down to the standby copy. Bounds what a failover would lose."""
    if active_side() != "fly":
        print("active side is not fly - nothing to pull")
        return 0
    CTRL.mkdir(parents=True, exist_ok=True)
    STANDBY.mkdir(parents=True, exist_ok=True)
    ok = True
    for name in MONEY_FILES:
        tmp = STANDBY / (name + ".partial")
        rc, so, se = sh(["fly", "ssh", "sftp", "get", "-a", FLY_APP,
                         f"/data/store/{name}", str(tmp)], timeout=600)
        # `fly ssh sftp` has exited 0 on a failed transfer before (it cost cutover attempt 6),
        # so the size is what is trusted, never the exit status.
        if not tmp.exists() or tmp.stat().st_size == 0:
            print(f"sync: {name} did not arrive ({(se or so).strip()[:120]})", file=sys.stderr)
            tmp.unlink(missing_ok=True)
            ok = False
            continue
        tmp.replace(STANDBY / name)     # atomic: a half-pulled file is never the standby copy
        print(f"sync: {name} {(STANDBY / name).stat().st_size:,} bytes")
    event("sync", ok=ok, staleness_min=probe_standby()["staleness_min"])
    return 0 if ok else 1


def cmd_arm(args) -> int:
    CTRL.mkdir(parents=True, exist_ok=True)
    ARMED_F.write_text(now() + "\n")
    write_fails(0)
    event("armed")
    print(f"automatic failover ARMED: fly -> laptop after {NEEDED_AGREEING_POLLS} consecutive "
          f"failed polls, and only if Fly itself answers that the machine is down.")
    return 0


def cmd_disarm(args) -> int:
    ARMED_F.unlink(missing_ok=True)
    event("disarmed")
    print("automatic failover DISARMED")
    return 0


def cmd_switch(args) -> int:
    """A deliberate move, by hand or from the dashboard. This runs the real cutover."""
    to = args.to
    frm = active_side()
    if frm == to:
        print(f"already on {to}")
        return 0
    if frm not in ("fly", "laptop"):
        print(f"active side is '{frm}'; say which side to move from with --from", file=sys.stderr)
        if not args.frm:
            return 2
        frm = args.frm
    cutover = REPO / "deploy" / "cutover.sh"
    event("switch_started", frm=frm, to=to)
    print(f"running: {cutover} --from {frm} --to {to}", file=sys.stderr)
    p = subprocess.run(["/bin/bash", str(cutover), "--from", frm, "--to", to])
    if p.returncode == 0:
        set_active(to)
        event("switch_done", frm=frm, to=to)
    else:
        event("switch_failed", frm=frm, to=to, rc=p.returncode)
    return p.returncode


# --------------------------------------------------------------------------- #
# Hermes receipts
# --------------------------------------------------------------------------- #

STORE_LEAF = LAPTOP_STORE.name

HERMES_RECEIPTS = Path.home() / ".hermes" / "state" / "capability_receipts.jsonl"

# The container writes one receipt file per job onto the volume. These are the two Hermes grades
# from them today; the key on the left is the file name, and it must equal `observable.script` in
# ~/.hermes/capabilities.json or the audit will not join them up.
CONTAINER_RECEIPTS = ("backup_store.py", "prospector.scheduler.run_scheduled")


def cmd_receipts(args) -> int:
    """Pull the container's job receipts down and sign them into the Hermes ledger.

    Hermes decides what is broken from ~/.hermes/state/capability_receipts.jsonl. Those receipts
    used to be written by a launchd wrapper on this laptop. The jobs run on Fly now, so without
    this the capabilities grade DARK while the jobs work perfectly.

    Nothing here invents a receipt. Every line written is a file the container wrote when the job
    actually ended, carrying that run's real exit code. If the container has no receipt for a job,
    this writes nothing and the capability goes DARK - which is the correct answer, because we do
    not know that it ran.
    """
    written = 0
    seen = set()
    if HERMES_RECEIPTS.exists():
        # `ended_at` is the run's identity. Re-signing the same run every 15 minutes would make a
        # stopped job look alive forever, which is the exact failure this is meant to catch.
        try:
            with HERMES_RECEIPTS.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"fly:prospector-engine"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    seen.add((r.get("script"), r.get("ended_at")))
        except OSError as exc:
            print(f"could not read the Hermes ledger: {exc}", file=sys.stderr)
            return 1

    for key in CONTAINER_RECEIPTS:
        rc, so, se = sh(["fly", "ssh", "console", "-a", FLY_APP, "-C",
                         f"cat /data/{STORE_LEAF}/ops/receipts/{key}.json"], timeout=120)
        if rc != 0:
            print(f"no receipt for {key} on the container: {(se or so).strip()[:160]}",
                  file=sys.stderr)
            continue
        body = so[so.find("{"):so.rfind("}") + 1]     # strip flyctl's connection banner
        try:
            rec = json.loads(body)
        except ValueError:
            print(f"receipt for {key} is not readable JSON", file=sys.stderr)
            continue
        if (rec.get("script"), rec.get("ended_at")) in seen:
            continue
        HERMES_RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
        with HERMES_RECEIPTS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        written += 1
        age = round((time.time() - float(rec.get("ended_at", 0))) / 60, 1)
        print(f"signed {key}: exit {rec.get('exit_code')}, ran {age} min ago")

    if not written:
        print("no new container receipts")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="both sides, health and freshness")
    s.add_argument("--json", action="store_true")
    s.add_argument("--deep", action="store_true", help="also read each side's ledger (slower)")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("check", help="one poll; what the watchdog job runs")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("sync", help="pull Fly's money files to the standby copy")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("receipts", help="sign the container's job receipts into Hermes")
    s.set_defaults(fn=cmd_receipts)

    s = sub.add_parser("arm", help="turn automatic failover on")
    s.set_defaults(fn=cmd_arm)

    s = sub.add_parser("disarm", help="turn automatic failover off")
    s.set_defaults(fn=cmd_disarm)

    s = sub.add_parser("switch", help="move the engine to the other side, deliberately")
    s.add_argument("--to", required=True, choices=["fly", "laptop", "sshdocker"])
    s.add_argument("--from", dest="frm", default=None)
    s.set_defaults(fn=cmd_switch)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
