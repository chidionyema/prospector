#!/usr/bin/env python3
"""Where is the engine, is it alive, and how do we move it - one command for all three.

    engine_failover.py status [--json] [--deep]   both sides, health and freshness
    engine_failover.py check                      one poll; what the watchdog job runs
    engine_failover.py arm  / disarm              turn automatic failover on and off
    engine_failover.py switch --to laptop|fly     move the engine, by hand

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
import hashlib
import json
import os
import re
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
STANDBY = CTRL / "standby"          # where a failover restores the money files TO
#: The checkout a failback would start FROM. A different axis from the money files above:
#: those carry the DATA, this carries the CODE, and the two rot independently and for
#: unrelated reasons. Reporting one and calling it "the exposure" is what let the code axis
#: reach 81 commits behind unnoticed.
STANDBY_CHECKOUT = Path(os.environ.get(
    "PROSPECTOR_STANDBY_CHECKOUT", "/Users/chidionyema/Documents/code/prospector-live"))

FLY_APP = os.environ.get("PROSPECTOR_FLY_APP", "prospector-engine")
#: The ONE backup system. Until 2026-08-21 this file carried a second one: 220 lines that
#: pulled both money files off Fly over `fly ssh sftp` every 15 minutes, with its own
#: size check, partial-tail trimmer, shrink-refusal switch and stderr parser. It produced
#: four distinct failures in one day - out of disk, a 600s timeout, a flyctl metrics
#: WARNING parsed as "the file did not arrive", and a 1970 timestamp in its own log - while
#: scripts/backup_store.py was already putting the same two files in R2 and getting it
#: right. Measured the day it was deleted: R2's ledger snapshot was 2 minutes old and
#: 34,687,133 bytes; the last thing the sftp path landed was 9,240,576 bytes of a
#: 455,787,146-byte file, promoted as if it were complete.
BACKUP_PY = REPO / "scripts" / "backup_store.py"
VENV_PY = Path(os.environ.get("PROSPECTOR_VENV_PYTHON", str(REPO / ".venv" / "bin" / "python")))
LAPTOP_STORE = Path(os.environ.get("PROSPECTOR_STORE_DIR",
                                   "/Users/chidionyema/Documents/code/prospector/store"))
NEEDED_AGREEING_POLLS = int(os.environ.get("PROSPECTOR_FAILOVER_POLLS", "5"))
# How old the scheduler heartbeat may get before the side counts as down. Matches the
# `stale_after_s` the ops console status view reports, so one machine cannot be alive on one
# screen and dead on the other.
HEARTBEAT_STALE_S = int(os.environ.get("PROSPECTOR_HEARTBEAT_STALE_S", "300"))

# The two files that carry money. The spend ledger decides whether the daily cap has been hit;
# the database carries the catalogue and the entitlements. Everything else - dossiers, logs,
# caches - is reproducible. scripts/backup_store.py puts both in R2 continuously; this file
# no longer copies them itself, it restores them from there when a failover needs them.
MONEY_FILES = ("prospector.jsonl", "prospector.db")


def on_fly() -> bool:
    """Are we standing ON the Fly machine, rather than watching it from outside?

    Fly sets FLY_MACHINE_ID in every machine's environment, so this needs no API call and no
    credential. It matters because both probes below were written for one vantage point - the
    laptop, looking out at Fly - and the ops console now runs INSIDE the Fly machine, where both
    of them answered wrongly. See probe_fly and probe_laptop.
    """
    return bool(os.environ.get("FLY_MACHINE_ID"))


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
    if on_fly():
        # We ARE the Fly machine. Asking the Fly API whether we exist is both absurd and, from in
        # here, impossible: the container holds no FLY_API_TOKEN on purpose, so the call returned
        # `failed to list VMs: unauthorized` and the ops console reported the live side as
        # "unknown" from the 2026-08-18 cutover onward. Answer from the process table and the
        # ledger instead, which is the same evidence probe_laptop uses for its own side.
        out["reachable"] = True
        out["vantage"] = "self"
        out["machine_id"] = os.environ["FLY_MACHINE_ID"]
        out["state"] = "started"
        out["machines"] = 1
        store = Path(os.environ.get("PROSPECTOR_STORE_DIR", "/data/store"))
        # The HEARTBEAT, not pgrep. The engine image has no pgrep - `pgrep: not found`, measured
        # on prospector-engine 2026-08-18 - so a process probe here reports no scheduler and the
        # panel calls a running engine DOWN. The heartbeat is the engine's own liveness signal,
        # it is what the console's status view already grades, and it carries the pid anyway.
        beat_f = store / "scheduler" / "heartbeat.json"
        beat_age = None
        if beat_f.exists():
            beat_age = round(time.time() - beat_f.stat().st_mtime, 1)
            out["heartbeat_age_s"] = beat_age
            try:
                beat = json.loads(beat_f.read_text(errors="replace"))
                out["phase"] = beat.get("phase")
                out["scheduler_pids"] = [str(beat["pid"])] if beat.get("pid") else []
            except (OSError, json.JSONDecodeError, TypeError):
                out["scheduler_pids"] = []
        else:
            out["scheduler_pids"] = []
            out["error"] = f"no heartbeat at {beat_f}"
        ledger = store / "prospector.jsonl"
        if ledger.exists():
            out["ledger_age_min"] = round((time.time() - ledger.stat().st_mtime) / 60, 1)
            if deep:
                with ledger.open("rb") as fh:
                    out["ledger_lines"] = sum(1 for _ in fh)
        elif "error" not in out:
            out["error"] = f"no ledger at {ledger}"
        # Same 300s floor the console's status view uses, so the two cannot disagree about
        # whether the same heartbeat is stale.
        out["healthy"] = beat_age is not None and beat_age < HEARTBEAT_STALE_S and ledger.exists()
        return out
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
    if on_fly():
        # We are in a container, not on the laptop, so every probe below would answer about the
        # WRONG machine - and quietly. pgrep finds no scheduler and reports the laptop dead;
        # launchctl does not exist and reports it unfenced; worst of all, PROSPECTOR_STORE_DIR is
        # /data/store in here, so LAPTOP_STORE resolves to FLY's ledger and the laptop's copy
        # reads 0.3 minutes old when it may be hours stale. That number is the failover exposure,
        # so a wrong one is worse than no answer. Rule 3 in this file's header already says what
        # to do with a side we cannot ask: report unreachable, and never act on it.
        out["reachable"] = False
        out["error"] = "cannot see the laptop from inside the Fly machine"
        return out
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


def probe_standby_code() -> dict:
    """How many commits behind origin/main is the failback checkout?

    Deliberately does NOT fetch. This runs on every console status poll, and a probe that
    reaches the network is a probe that hangs when the network does.

    The cost of not fetching is the trap this estate already has a law about: `git rev-list
    --count HEAD..origin/main` reports 0 against an `origin/main` nobody has fetched today, so
    a 0 means EITHER "current" OR "nobody has looked in a week", and the two are the opposite
    of each other. So the age of the ref the count was taken against is reported beside it,
    and neither number means anything alone. A reader who sees behind=0 with ref_age_min=4300
    is looking at an instrument that has not been told anything for three days.
    """
    out: dict = {"checkout": str(STANDBY_CHECKOUT)}
    if not (STANDBY_CHECKOUT / ".git").exists():
        out["error"] = f"no checkout at {STANDBY_CHECKOUT}"
        return out
    git = ["git", "-C", str(STANDBY_CHECKOUT)]
    rc, head, err = sh(git + ["rev-parse", "--short", "HEAD"], timeout=20)
    if rc != 0:
        out["error"] = (err or "git rev-parse HEAD failed").strip()[:200]
        return out
    out["head"] = head.strip()
    rc, count, err = sh(git + ["rev-list", "--count", "HEAD..origin/main"], timeout=20)
    if rc != 0:
        out["error"] = (err or "git rev-list failed").strip()[:200]
        return out
    try:
        out["behind"] = int(count.strip())
    except ValueError:
        out["error"] = f"unreadable commit count: {count.strip()[:80]}"
        return out
    fetch_head = STANDBY_CHECKOUT / ".git" / "FETCH_HEAD"
    try:
        out["ref_age_min"] = round((time.time() - fetch_head.stat().st_mtime) / 60, 1)
    except OSError:
        # No FETCH_HEAD at all means nothing has ever fetched here, so `behind` was counted
        # against whatever the clone was born with. Say so rather than reporting a number.
        out["ref_age_min"] = None
    return out


def standby_code_line(code: dict) -> str:
    """One line an operator can act on: how far back a failover would start, CODE axis.

    Separate from probe_standby_code() so the wording is testable without a git repo, and so
    the number cannot be computed and then never printed - which is what happened for the
    whole of the period it was 81 commits behind.

    behind==0 is only good news when the ref it was counted against is fresh. A zero taken
    against a ref nobody has fetched in three days is the same reading as a zero taken one
    minute after a deploy, and they mean opposite things, so an old ref never prints OK.
    """
    if code.get("error"):
        return f"standby CODE: UNKNOWN - {code['error']}"
    behind = code.get("behind")
    head = code.get("head", "?")
    age = code.get("ref_age_min")
    age_txt = "ref NEVER fetched" if age is None else f"ref {age}m old"
    fresh = age is not None and age < 60
    mark = "OK" if behind == 0 and fresh else "!!"
    return (f"standby CODE: {mark} {behind} commits behind origin/main at {head} "
            f"({age_txt}) - a failover starts from THIS commit")


def probe_running_code() -> dict:
    """Is the file running RIGHT NOW the same bytes as the checkout's copy?

    A different axis again from `probe_standby_code`, and the one that was missing. That
    function grades the CHECKOUT a failback starts from. This one grades the copy of this
    script that launchd is actually executing, and the two are different files.

    Measured 2026-08-21. `~/.prospector/bin/engine_failover.frozen.py` was the 2026-08-18 copy,
    594 lines behind `scripts/engine_failover.py`. The launcher runs the frozen copy on purpose
    -- a disaster-recovery tool that reads out of a git worktree dies when someone deletes the
    worktree -- and it is refreshed only by `deploy/install_failover_watch.sh`, which nobody had
    run in three days. So commit 3f7550e5, which refuses a standby pull that did not reach the
    end of the source, was merged to main and never reached the job that does the pulling.
    Three short pulls were promoted over the good copy and the standby spend ledger fell to
    1,572,864 bytes against a source of 454,701,248. The checkout was 0 commits behind the
    whole time, and that line printed OK.
    """
    out: dict = {"running": None, "checkout_copy": None}
    try:
        running = Path(__file__).resolve()
        out["running"] = str(running)
        mirror = (STANDBY_CHECKOUT / "scripts" / "engine_failover.py").resolve()
        out["checkout_copy"] = str(mirror)
        if running == mirror:
            # Running straight out of the checkout. There is no second copy to drift, and
            # saying "matches" here would invent a comparison that did not happen.
            out["same_file"] = True
            return out
        out["same_file"] = False
        out["digest"] = hashlib.sha256(running.read_bytes()).hexdigest()[:12]
        out["checkout_digest"] = hashlib.sha256(mirror.read_bytes()).hexdigest()[:12]
    except OSError as exc:
        out["error"] = str(exc)[:200]
    return out


def running_code_line(run: dict) -> str:
    """One line an operator can act on: is the failover code that RUNS the code that was fixed?

    Split from the probe for the same reason `standby_code_line` is: so the wording is testable
    without two copies of the file on disk, and so the comparison cannot be computed and then
    never printed -- which is the shape of every defect this pair of lines exists to catch.
    """
    if run.get("error"):
        return f"failover CODE: UNKNOWN - {run['error']}"
    if run.get("same_file"):
        return f"failover CODE: OK running from the checkout ({run.get('running', '?')})"
    if run.get("digest") == run.get("checkout_digest"):
        return f"failover CODE: OK frozen copy matches the checkout at {run.get('digest', '?')}"
    return (f"failover CODE: !! the running copy is NOT the checkout copy "
            f"({run.get('digest', '?')} vs {run.get('checkout_digest', '?')}) - "
            f"re-run deploy/install_failover_watch.sh, or a merged fix is not what runs")


def probe_standby() -> dict:
    """How far back would a failover start? Two axes, and BOTH of them are the exposure.

    This docstring used to read "How stale is the copy a failover would start from? This
    number IS the exposure", and it was false in the way that matters most: it described only
    the money files. Measured 2026-08-21, the code axis it never looked at was 81 commits
    behind origin/main, on the day that checkout was the failover target - so a failover would
    have rolled production back 81 commits while `staleness_min` reported minutes and `usable`
    reported True. An instrument that reports green on one axis while the other one is the
    actual exposure is worse than no instrument, because it is the one the console prints.

    `usable` deliberately still grades the DATA only. Code drift must not block a failover:
    failing over to a checkout four commits behind beats staying down, and that is a decision
    for the operator reading `code`, not for this function. Anything that folds `code` into
    `usable` is changing what the estate does in an outage, which is not a refactor.
    """
    out: dict = {"files": {}, "code": probe_standby_code(),
                 "running_code": probe_running_code()}
    state = backup_state()
    out["backup"] = state
    if state.get("error"):
        out["staleness_min"] = -1
        out["usable"] = False
        return out
    for name, label in ((MONEY_FILES[0], "ledger"), (MONEY_FILES[1], "db")):
        rec = state.get(label)
        out["files"][name] = None if not rec else {
            "bytes": rec["bytes"], "age_min": round(rec["age_h"] * 60, 1), "key": rec["key"]}
    oldest = state.get("oldest_age_h")
    out["staleness_min"] = -1 if oldest is None else round(oldest * 60, 1)
    out["usable"] = bool(state.get("complete"))
    return out


def backup_state() -> dict:
    """What the ONE backup system holds, asked of it rather than reimplemented.

    Shelled out to the repo's venv on purpose. This file also runs as a frozen copy under
    /usr/bin/python3, which has no venv and no boto3 (deploy/install_failover_watch.sh) -- an
    `import boto3` at module scope would make the whole failover watchdog unimportable on the
    one machine it exists to protect.

    Only cmd_status and do_failover reach this. cmd_check, which runs every 60 seconds, does
    not, so the watchdog costs no network calls.
    """
    if not VENV_PY.exists():
        return {"error": f"no venv python at {VENV_PY}"}
    rc, so, se = sh([str(VENV_PY), str(BACKUP_PY), "--money-state"], timeout=120)
    if rc != 0:
        return {"error": (se or so or "no output").strip()[:300]}
    try:
        return json.loads(so)
    except ValueError as exc:
        return {"error": f"unreadable money-state: {exc}"}


def restore_money(dest: Path) -> tuple[bool, str]:
    """Bring both money files back from R2 into `dest`. Returns (ok, what happened).

    The whole restore lives in scripts/backup_store.py, which verifies the round trip against
    Content-Length and the gzip CRC written at compression time. Duplicating any of that here
    is what produced the 220 lines this function replaced.
    """
    if not VENV_PY.exists():
        return False, f"no venv python at {VENV_PY}"
    dest.mkdir(parents=True, exist_ok=True)
    rc, so, se = sh([str(VENV_PY), str(BACKUP_PY), "--restore-money", str(dest)], timeout=1800)
    tail = (so or se or "").strip().splitlines()
    return rc == 0, (tail[-1] if tail else f"rc={rc}")


# --------------------------------------------------------------------------- commands

def cmd_status(args) -> int:
    fly = probe_fly(deep=args.deep)
    lap = probe_laptop(deep=args.deep)
    active = active_side()
    active_from = "marker"
    if active == "unknown":
        # ~/.prospector/ACTIVE is deliberately outside both engines, which means a machine that
        # has never written it - every fresh Fly container, since the volume does not carry the
        # home directory - has no marker to read. The ops console then showed ACTIVE=unknown from
        # the 2026-08-18 cutover on, while standing on the machine that was doing the work.
        # A side we can SEE running is evidence; say so, and say where the answer came from,
        # because an observed answer must never be mistaken for the marker the switch writes.
        healthy = [p["side"] for p in (fly, lap) if p["healthy"]]
        if len(healthy) == 1:
            active, active_from = healthy[0], "observed"
    report = {
        "at": now(),
        "active": active,
        "active_from": active_from,
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
    print("  " + standby_code_line(sb.get("code", {})))
    print("  " + running_code_line(sb.get("running_code", {})))
    if report["consecutive_failed_polls"]:
        print(f"  !! {report['consecutive_failed_polls']} consecutive failed polls of the active side")
    # An unknown active side is not a side, so it cannot be indexed into `sides`. This used to
    # raise KeyError and take the whole status command down with a traceback, which is the worst
    # possible way to report "I do not know where the engine is".
    side = report["sides"].get(report["active"])
    return 0 if side and side["healthy"] else 1


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
    ok, detail = restore_money(STANDBY)
    if ok and sb["usable"]:
        for name in MONEY_FILES:
            pulled = STANDBY / name
            if not pulled.exists():
                continue
            dst = LAPTOP_STORE / name
            if dst.exists():
                # Keep what the laptop had. A failover that turns out to have restored the wrong
                # thing must be undoable, and the laptop's own copy is the only other candidate.
                shutil.copy2(dst, dst.with_name(dst.name + ".pre-failover"))
            shutil.copy2(pulled, dst)
        event("restored", staleness_min=sb["staleness_min"], files=list(MONEY_FILES),
              detail=detail)
        print(f"restored from R2 (snapshot {sb['staleness_min']} min old): {detail}",
              file=sys.stderr)
    else:
        # Never abandon the failover for this. A stale engine beats no engine; what must not
        # happen is the operator not being told which one they got.
        event("restore_skipped", reason=detail if not ok else "backup incomplete",
              backup=sb.get("backup"))
        print(f"COULD NOT RESTORE FROM R2 ({detail}) - starting the laptop on its own store, "
              f"which may be old", file=sys.stderr)

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

#: The file that decides which jobs the container runs, and therefore which receipts exist.
SUPERVISORD_CONF = REPO / "deploy" / "engine" / "supervisord.conf"

#: `receipt.sh <key> <command...>` - the key is the argument straight after the wrapper.
_RECEIPT_KEY_RE = re.compile(r"receipt\.sh\s+(\S+)")


def container_receipt_keys(conf: Path = SUPERVISORD_CONF) -> tuple[str, ...]:
    """Every receipt key the engine container writes, read from the file that writes them.

    This used to be a hand-written tuple of two, and that is what went wrong. supervisord wraps
    four jobs in receipt.sh; the tuple named `backup_store.py` and
    `prospector.scheduler.run_scheduled`. So `offsite_backup` and `restore_drill.py` wrote a
    receipt onto the volume on schedule and nothing ever collected it - the offsite backup and the
    restore drill, which are the two jobs that exist to prove the business can be recovered.

    Reading the list means a new receipt-wrapped job ships without a second edit. One list, in the
    file that already had to be right, instead of two that must agree and nothing compares.

    The key must still equal `observable.script` in ~/.hermes/capabilities.json, which is a
    different repository; `tests/unit/test_container_receipts_are_shipped_and_graded.py` is what
    fails when the two drift.

    Order follows the file and duplicates collapse, so a key wrapped twice is fetched once.
    """
    try:
        text = conf.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read {conf}: {exc}", file=sys.stderr)
        return ()
    keys: dict[str, None] = {}
    for line in text.splitlines():
        if line.lstrip().startswith(";"):
            # A commented-out program runs nothing and writes no receipt. This matters: the
            # comments in that file discuss the receipt keys by name.
            continue
        m = _RECEIPT_KEY_RE.search(line)
        if m:
            keys.setdefault(m.group(1), None)
    return tuple(keys)


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

    for key in container_receipt_keys():
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


# --------------------------------------------------------------------------- drain ledger

#: Where the drain's give-up counter lives, relative to a store root. One string, because the
#: laptop reads it with pathlib and Fly reads it over ssh, and a second copy of this path is how
#: the two silently start describing different files.
DRAIN_LEDGER_REL = "scheduler/drain_attempts.json"
FLY_STORE = "/data/store"


def _drain_grade(raw: str, cap: int) -> dict:
    """Turn a ledger's JSON text into counts. A missing or torn file is an EMPTY ledger, never an
    error, because that is exactly how `prospector.drain_state.load` reads it (drain_state.py:130)
    and the console must not disagree with the engine about what a row's budget is."""
    try:
        ledger = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        ledger = {}
    if not isinstance(ledger, dict):
        ledger = {}
    histogram: dict[str, int] = {}
    for n in ledger.values():
        histogram[str(n)] = histogram.get(str(n), 0) + 1
    retired = sorted(cid for cid, n in ledger.items()
                     if cap and isinstance(n, int) and n >= cap)
    return {"rows": len(ledger), "histogram": histogram,
            "retired": retired, "retired_count": len(retired)}


def _drain_cap() -> int:
    """The give-up cap, from config. 5 when config cannot be read — the shipped default, and the
    same fallback `drain_state.DEFAULT_MAX_ATTEMPTS` carries."""
    try:
        sys.path.insert(0, str(REPO))
        from prospector import drain_state
        from prospector.config import load_config
        return drain_state.max_attempts(load_config())
    except Exception:  # noqa: BLE001 — this script must run on a box with no venv
        return 5


def drain_ledger(side: str, *, reset: bool = False) -> dict:
    """Read (or clear) the drain attempt ledger on ONE named side.

    This lives here rather than in the console because the console is not the only caller that
    needs it, and because the console reads the LAPTOP store while the engine has been on Fly
    since 2026-08-17. A drain panel that quietly reported the laptop's empty ledger while Fly
    carried 251 retired rows would be a confident lie, which is worse than no panel.
    """
    cap = _drain_cap()
    out: dict = {"side": side, "max_attempts": cap, "ok": False, "error": None,
                 "ledger_path": None, "removed": False, "backup": None}

    if side == "laptop":
        path = LAPTOP_STORE / DRAIN_LEDGER_REL
        out["store_dir"] = str(LAPTOP_STORE)
        out["ledger_path"] = str(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        out.update(_drain_grade(raw, cap))
        out["ledger_exists"] = path.exists()
        out["ok"] = True
        if reset and path.exists():
            backup = path.with_name(path.name + ".bak-" + time.strftime("%Y%m%dT%H%M%SZ",
                                                                       time.gmtime()))
            backup.write_bytes(path.read_bytes())
            path.unlink()
            out["removed"] = True
            out["backup"] = str(backup)
        return out

    if side != "fly":
        out["error"] = f"unknown side {side!r}; expected fly or laptop"
        return out

    remote = f"{FLY_STORE}/{DRAIN_LEDGER_REL}"
    out["store_dir"] = FLY_STORE
    out["ledger_path"] = remote
    if not shutil.which("fly"):
        out["error"] = "fly CLI not installed on this machine"
        return out
    # `cat || true` so a missing ledger comes back as empty rather than as a failed command:
    # absent means "nothing has been tried", which is a real answer, not an outage.
    rc, so, se = sh(["fly", "ssh", "console", "-a", FLY_APP, "-C",
                     f"/bin/sh -lc 'cat {remote} 2>/dev/null || true'"], timeout=90)
    if rc != 0:
        out["error"] = (se or so).strip()[:200] or f"fly ssh exited {rc}"
        return out
    body = so[so.index("{"):so.rindex("}") + 1] if "{" in so and "}" in so else ""
    out.update(_drain_grade(body, cap))
    out["ledger_exists"] = bool(body)
    out["ok"] = True

    if reset and body:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        rc, so2, se2 = sh(["fly", "ssh", "console", "-a", FLY_APP, "-C",
                           f"/bin/sh -lc 'cp {remote} {remote}.bak-{stamp} && rm -f {remote} "
                           f"&& echo RESET_OK'"], timeout=90)
        if rc != 0 or "RESET_OK" not in so2:
            out["error"] = (se2 or so2).strip()[:200] or f"reset exited {rc}"
            return out
        out["removed"] = True
        out["backup"] = f"{remote}.bak-{stamp}"
    return out


def cmd_drain(args) -> int:
    side = args.side if args.side != "active" else active_side()
    if side not in ("fly", "laptop"):
        side = "laptop"
    data = drain_ledger(side, reset=bool(args.reset))
    data["active_side"] = active_side()
    data["asked_for"] = args.side
    if args.reset:
        event("drain_reset", side=side, removed=data.get("removed"),
              rows=data.get("rows"), retired=data.get("retired_count"))
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"{side}: {data.get('rows')} row(s), {data.get('retired_count')} retired "
              f"(cap {data['max_attempts']}) at {data.get('ledger_path')}")
        if data["error"]:
            print(f"  error: {data['error']}")
        if data["removed"]:
            print(f"  cleared; backup {data['backup']}")
    return 0 if data["ok"] else 1


def deploy_targets() -> list[str]:
    """Every platform the engine can be moved to, DISCOVERED from deploy/targets/*.sh.

    Not a list typed out here. deploy/cutover.sh already answers this question by looking for the
    file — `[ -f "$HERE/targets/$side.sh" ]` — so a second list is a second answer that drifts the
    moment an adapter lands. Measured 2026-08-20: `deploy/targets/k8s.sh` was written, and both
    this script and the ops console would still have refused `--to k8s` with the adapter sitting
    on disk beside the three names they had memorised. Same rule as the estate inventory: read the
    running world, never the declaration.

    `tests/unit/test_every_deploy_target_implements_the_contract.py` fails if either caller starts
    keeping its own list again.
    """
    here = Path(__file__).resolve().parents[1] / "deploy" / "targets"
    return sorted(f.stem for f in here.glob("*.sh"))


def cmd_targets(args) -> int:
    """The console asks this rather than globbing the directory itself: one implementation, three
    callers, exactly as _failover() in prospector/ops/console_api.py already assumes."""
    names = deploy_targets()
    if getattr(args, "json", False):
        print(json.dumps(names))
    else:
        for n in names:
            print(n)
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

    s = sub.add_parser("receipts", help="sign the container's job receipts into Hermes")
    s.set_defaults(fn=cmd_receipts)

    s = sub.add_parser("arm", help="turn automatic failover on")
    s.set_defaults(fn=cmd_arm)

    s = sub.add_parser("disarm", help="turn automatic failover off")
    s.set_defaults(fn=cmd_disarm)

    s = sub.add_parser("drain", help="the drain's give-up ledger on the ACTIVE side")
    s.add_argument("--side", default="active", choices=["active", "fly", "laptop"])
    s.add_argument("--reset", action="store_true",
                   help="clear it, handing every retired row its budget back (keeps a backup)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_drain)

    s = sub.add_parser("targets", help="every platform the engine can be moved to")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_targets)

    s = sub.add_parser("switch", help="move the engine to the other side, deliberately")
    s.add_argument("--to", required=True, choices=deploy_targets())
    s.add_argument("--from", dest="frm", default=None)
    s.set_defaults(fn=cmd_switch)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
