#!/usr/bin/env python3
"""Print the estate as it is right now: every part, where it runs, and whether it answered.

Why this exists. On 2026-08-18 the working trees vanished from ~/Documents in the middle of the
Fly migration, and nobody could say from memory what was still on the laptop, what had moved, and
what would stop if the laptop did. The docs could not answer it either: SYSTEM_SPECIFICATION.md
was 32 lines from June, and ESTATE_STATE.md predated the cutover. Prose about state goes stale in
hours. This command does not.

It is READ-ONLY. It starts nothing, stops nothing, deploys nothing and prints no secret VALUES --
only the NAMES of the secrets an app carries, which is what you need to know when you are asking
"could this app be rebuilt somewhere else".

Three answers per row, never two:
    ok       the thing answered and the answer was good
    FAIL     the thing answered and the answer was bad
    ?        could not ask -- CLI missing, no network, not this machine

"?" is not "fine" and it is not "broken". Collapsing it into either is how a dead component gets
reported healthy. See docs/ESTATE_MAP.md, "Probes that lie".

Usage:
    python3 scripts/estate_map.py              # the map, human readable
    python3 scripts/estate_map.py --json       # same facts, machine readable
    python3 scripts/estate_map.py --quick      # skip anything that shells into a machine
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# --- the estate, declared -------------------------------------------------------------------
# Everything below is a NAME plus how to prove it. Adding a component means adding a row here,
# not writing a paragraph somewhere.

FLY_APPS = {
    "prospector-engine": "makes the packs; the thing the business sells",
    "prospector-store-api": "the money rail: catalogue, checkout, entitlements, delivery",
    "prospector-store-web": "mumchimp.com, the storefront a buyer sees",
    "prospector-searxng": "private search the engine grounds against",
    "prospector-hermes": "the operator surface: Telegram, coordinator, Otto",
    "prospector-ci": "runs CI. Two Linux container runners, label 'heavy'. CI does NOT run "
                     "on the laptop; the actions.runner.* jobs there are off by founder "
                     "decision",
}

# tie-* are a separate, older product kept deliberately. Listed so nobody deletes them tidying up.
FLY_KEEP = ("tie-api", "tie-db", "tie-smoke", "tie-smoke-db", "tie-web")

# url -> (expected status, what a bad answer means)
ENDPOINTS = {
    "https://mumchimp.com/": (200, "the storefront is down; buyers see nothing"),
    "https://api.mumchimp.com/catalog": (200, "the money rail is down; nobody can buy"),
    "https://api.mumchimp.com/healthz/money-rail": (200, "the rail's own self-check is unhappy"),
    "https://prospector-store-web.fly.dev/": (200, "the storefront's Fly hostname is down"),
    "https://prospector-engine.fly.dev/": (200, "the ops console is down; the estate is unreadable"),
}

# The laptop jobs that are still load-bearing after the Fly cutover. Anything here is an answer to
# "what still stops if this laptop closes".
LAUNCHD_PREFIXES = ("actions.runner.", "ai.hermes.", "com.prospector")

TIMEOUT = 25


def run(cmd: list[str], timeout: int = TIMEOUT) -> tuple[int, str]:
    """Run a command, never raise. Returns (rc, combined output). rc 127 means "could not ask"."""
    if not shutil.which(cmd[0]):
        return 127, f"{cmd[0]} is not installed on this machine"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} did not answer within {timeout}s"
    except OSError as exc:
        return 127, str(exc)


def mark(state: str) -> str:
    return {"ok": "ok  ", "fail": "FAIL", "unknown": "?   "}[state]


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


# --- probes ---------------------------------------------------------------------------------

def probe_fly_apps() -> list[dict]:
    rc, out = run(["fly", "apps", "list", "--json"])
    if rc != 0:
        return [{"name": n, "state": "unknown", "note": out.splitlines()[0] if out else "no answer",
                 "why": w} for n, w in FLY_APPS.items()]
    try:
        live = {a["Name"]: a for a in json.loads(out)}
    except (json.JSONDecodeError, TypeError, KeyError):
        return [{"name": n, "state": "unknown", "note": "fly printed something we cannot parse",
                 "why": w} for n, w in FLY_APPS.items()]

    rows = []
    for name, why in FLY_APPS.items():
        app = live.get(name)
        if app is None:
            rows.append({"name": name, "state": "fail", "note": "declared here but not in this Fly org",
                         "why": why})
            continue
        status = (app.get("Status") or "").lower()
        # prospector-ci is SUPPOSED to be suspended -- R8 has not happened. Reporting that as a
        # failure would train the reader to ignore this line.
        expected_suspended = name == "prospector-ci"
        state = "ok" if status == "deployed" else ("ok" if expected_suspended else "fail")
        rows.append({"name": name, "state": state, "note": status or "no status", "why": why})

    for name in FLY_KEEP:
        if name in live:
            rows.append({"name": name, "state": "ok", "note": (live[name].get("Status") or "").lower(),
                         "why": "a separate older product, kept on purpose -- do not delete"})
    return rows


def probe_machines(app: str) -> dict:
    rc, out = run(["fly", "machines", "list", "-a", app, "--json"])
    if rc != 0:
        return {"state": "unknown", "note": out.splitlines()[0] if out else "no answer"}
    try:
        ms = json.loads(out)
    except json.JSONDecodeError:
        return {"state": "unknown", "note": "unparseable"}
    started = [m for m in ms if (m.get("state") or "") == "started"]
    vols = sorted({(m.get("config", {}).get("mounts") or [{}])[0].get("name")
                   for m in ms if m.get("config", {}).get("mounts")} - {None})
    return {
        "state": "ok" if started else ("unknown" if not ms else "fail"),
        "machines": len(ms),
        "started": len(started),
        "volumes": vols,
        "note": f"{len(started)}/{len(ms)} started" + (f", volume {', '.join(vols)}" if vols else ""),
    }


def probe_secret_names(app: str) -> list[str]:
    """The NAMES only. A name tells you what the app needs to run elsewhere. A value is a leak."""
    rc, out = run(["fly", "secrets", "list", "-a", app, "--json"])
    if rc != 0:
        return []
    try:
        # flyctl writes "name" lowercase here and "Name" capitalised in `apps list`. Take either.
        return sorted((s.get("name") or s["Name"]) for s in json.loads(out))
    except (json.JSONDecodeError, TypeError, KeyError):
        return []


def probe_endpoints() -> list[dict]:
    rows = []
    for url, (want, harm) in ENDPOINTS.items():
        rc, out = run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "12", url], 20)
        code = out.strip().splitlines()[-1] if out else ""
        if rc != 0 or not code.isdigit():
            rows.append({"url": url, "state": "unknown", "note": "no answer from curl", "harm": harm})
        else:
            got = int(code)
            rows.append({"url": url, "state": "ok" if got == want else "fail",
                         "note": f"HTTP {got}" + ("" if got == want else f", wanted {want}"),
                         "harm": harm})
    return rows


def probe_laptop_jobs() -> dict:
    """What still runs on this laptop. On Linux this is correctly 'could not ask', not 'none'."""
    rc, out = run(["launchctl", "list"])
    if rc != 0:
        return {"state": "unknown",
                "note": "launchctl is macOS only -- ask this on the laptop, not in a container",
                "jobs": []}
    jobs = []
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pid, _, label = parts[0], parts[1], parts[2]
        if label.startswith(LAUNCHD_PREFIXES):
            jobs.append({"label": label, "pid": pid, "running": pid not in ("-", "")})
    running = [j for j in jobs if j["running"]]
    return {"state": "ok", "jobs": sorted(jobs, key=lambda j: j["label"]),
            "note": f"{len(running)} of {len(jobs)} declared jobs have a pid"}


def probe_runners() -> dict:
    """Which runners can take a job, and WHERE they are.

    The where is the point. This row used to end "all on the laptop until R8 lands", which was
    true when it was written and false from #335 onward -- CI has run on the Fly app
    prospector-ci since then. On 2026-08-19 a pull request sat queued, an agent read the laptop's
    three offline runner jobs as the whole picture, and told the founder to start them. They are
    off by founder decision. So the label decides the location and nothing here asserts it.
    """
    rc, out = run(["gh", "api", "repos/chidionyema/prospector/actions/runners", "--jq",
                   ".runners[] | \"\\(.name) \\(.status) busy=\\(.busy) "
                   "labels=\\(.labels|map(.name)|join(\",\"))\""])
    if rc != 0:
        return {"state": "unknown", "note": out.splitlines()[0] if out else "gh did not answer",
                "runners": []}
    rs = [row for row in out.splitlines() if row.strip()]
    online = [r for r in rs if " online" in r]
    fly = [r for r in online if "fly" in r]
    busy = [r for r in online if "busy=true" in r]
    # No online runner anywhere is the only real failure: every workflow then queues forever.
    # An offline LAPTOP runner is a decision, not a fault.
    note = (f"{len(online)} of {len(rs)} online ({len(fly)} on the Fly app prospector-ci, "
            f"{len(online) - len(fly)} on the laptop), {len(busy)} busy. CI runs on "
            f"prospector-ci; the laptop's actions.runner.* jobs are off by founder decision "
            f"and a queued pull request is usually capacity, not a dead runner")
    return {"state": "ok" if online else "fail", "runners": rs, "note": note,
            "online": len(online), "on_fly": len(fly), "busy": len(busy)}


def probe_volume_usage(app: str, path: str = "/data") -> dict:
    rc, out = run(["fly", "ssh", "console", "-a", app, "-C",
                   f"sh -lc 'df -h {path} | tail -1'"], 40)
    if rc != 0:
        return {"state": "unknown", "note": out.splitlines()[-1] if out else "no answer"}
    line = [row for row in out.splitlines() if path in row or "%" in row]
    return {"state": "ok" if line else "unknown", "note": line[-1].strip() if line else out[-120:]}


# --- the map --------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine readable")
    ap.add_argument("--quick", action="store_true", help="skip anything that shells into a machine")
    ap.add_argument("--snapshot", action="store_true",
                    help="also write the JSON to <store>/ops/estate_map.json, which is what the "
                         "SessionStart probe renders")
    args = ap.parse_args()

    started = time.time()
    report: dict = {"as_of_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "probed_from": "fly machine " + os.environ["FLY_MACHINE_ID"]
                    if os.environ.get("FLY_MACHINE_ID") else "this laptop"}

    report["fly_apps"] = probe_fly_apps()
    report["machines"] = {a: probe_machines(a) for a in FLY_APPS}
    report["secrets"] = {a: probe_secret_names(a) for a in FLY_APPS}
    report["endpoints"] = probe_endpoints()
    report["laptop_jobs"] = probe_laptop_jobs()
    report["ci_runners"] = probe_runners()
    if not args.quick:
        report["storage"] = {a: probe_volume_usage(a)
                             for a in ("prospector-engine", "prospector-store-api", "prospector-hermes")}
    report["took_s"] = round(time.time() - started, 1)

    if args.snapshot:
        # store_root(), never a path derived from __file__: the store is pinned by
        # PROSPECTOR_STORE_DIR and does not move with the code. A snapshot written beside the
        # code is a snapshot the probe never reads.
        try:
            # Run as `scripts/estate_map.py`, sys.path[0] is scripts/, so the package is not
            # importable without this. Nothing else in the file needs it.
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from prospector.config import store_root
            out = Path(store_root()) / "ops" / "estate_map.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"snapshot -> {out}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 -- a failed snapshot must not fail the map
            print(f"snapshot FAILED: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    print(f"THE ESTATE at {report['as_of_utc']}, probed from {report['probed_from']}")
    print("ok = answered well   FAIL = answered badly   ? = could not ask (NOT the same as fine)")

    section("What runs, and what it is for")
    for r in report["fly_apps"]:
        m = report["machines"].get(r["name"], {})
        note = r["note"] + (f" | {m['note']}" if m.get("note") else "")
        print(f"  {mark(r['state'])} {r['name']:<22} {note}")
        print(f"       {r['why']}")

    section("What a customer touches")
    for e in report["endpoints"]:
        print(f"  {mark(e['state'])} {e['url']:<46} {e['note']}")
        if e["state"] != "ok":
            print(f"       if this stays bad: {e['harm']}")

    section("What still runs on the laptop")
    lj = report["laptop_jobs"]
    print(f"  {mark(lj['state'])} {lj['note']}")
    for j in lj["jobs"]:
        print(f"       {'running' if j['running'] else 'loaded '} {j['label']}")
    cr = report["ci_runners"]
    print(f"  {mark(cr['state'])} {cr['note']}")
    for r in cr["runners"]:
        print(f"       {r}")

    if "storage" in report:
        section("Where the state lives")
        for app, s in report["storage"].items():
            print(f"  {mark(s['state'])} {app:<22} {s['note']}")

    section("What each app needs to run somewhere else (secret NAMES, never values)")
    for app, names in report["secrets"].items():
        print(f"  {app}: {len(names)} secrets")
        if names:
            print(f"       {' '.join(names)}")

    print(f"\nRead docs/ESTATE_MAP.md for how these parts connect. Took {report['took_s']}s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
