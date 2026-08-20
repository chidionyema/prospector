#!/usr/bin/env python3
"""Start stopped CI runner machines back up, with no agent involved.

WHY THIS EXISTS. On 2026-08-19 ten of the twelve `prospector-ci` machines were `stopped`.
Not destroyed, not broken -- stopped. Capacity was 2/12 for hours and nothing anywhere said
so. `main`'s own CI run for 6054bf09 queued at 18:11:53Z and never got a machine. It passed
first time, in full, the moment the machines were started by hand.

Three separate things had to be true for that to stay invisible, and this file fixes the
third:

  1. THE FLOOR WAS THE COLLAPSE. `ops/config/ci_capacity.yaml` declared `runners: 2` and
     `autoscale_min: 2`, so `scripts/ci_capacity.py --live` graded a fleet of 2 online out of
     12 as CONTRACT HOLDS. A floor set to the minimum survivable number cannot detect a
     collapse to the minimum survivable number. `fleet.min_started` is a second, higher number
     whose only job is to notice.
  2. A KILLED RUNNER READS AS A FAILING TEST. A machine that dies mid-job cannot deregister,
     so GitHub keeps the registration `busy`, never schedules to it, and refuses to delete it
     (`422 ... currently running a job and cannot be deleted`). The job surfaces as
     `The self-hosted runner lost communication with the server`. Every such event burns a
     slot permanently, so capacity only ever ratchets DOWN.
  3. NOTHING PUT THE MACHINES BACK. `scripts/ci_fleet_probe.py` grades the fleet, but a report
     is only as good as the person reading it, and at 18:11 nobody was. This runs on a
     schedule and acts.

WHAT IT WILL AND WILL NOT DO. It STARTS machines. It never stops one, never destroys one, and
never creates one. That is the whole blast radius: the worst outcome of a bug here is a
machine running that did not need to be, which costs pennies and breaks nothing. Growing the
fleet is `deploy/runners.sh up <n>` and stays a human decision.

IT MUST NOT RUN ON THE FLEET IT HEALS. A self-hosted runner cannot start a dead self-hosted
fleet -- there is no runner left to pick the job up. `.github/workflows/ci-fleet-keeper.yml`
pins `runs-on: ubuntu-latest` for that reason and the reason is not obvious from the file.

THE REAP HALF IS REPORT-ONLY, AND NOT BY CHOICE. Deleting a phantom registration needs a
repo-admin PAT. This repository has none (secrets on 2026-08-19: FLY_API_TOKEN,
FLY_API_TOKEN_API, FLY_API_TOKEN_ENGINE), and `GITHUB_TOKEN` cannot list self-hosted runners
at all -- `administration` is not a grantable workflow permission. So with no PAT this names
the phantoms and exits non-zero; with one it deregisters them. Issue #436 tracks the PAT.

ORDER MATTERS IN THE REAP. Deregister on GitHub FIRST, then touch the Fly machine. Destroying
the machine first is exactly what leaves GitHub holding a `busy` registration it will not
release. And gate on GitHub's `busy` flag, never on Fly's machine state: Fly cannot see
whether a job is running.

    python3 scripts/ci_fleet_keeper.py                # report only, exit 1 if below floor
    python3 scripts/ci_fleet_keeper.py --start        # start machines up to the floor
    python3 scripts/ci_fleet_keeper.py --json         # for the ops console

Needs FLY_API_TOKEN to see or start machines. GITHUB_TOKEN/GH_TOKEN plus a repo-admin PAT in
RUNNER_ADMIN_PAT to grade registrations; without it the machine half still works.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "ops/config/ci_capacity.yaml"
FLY_TOML = ROOT / "deploy/runner/fly.toml"
FLY_API = "https://api.machines.dev/v1"
GH_API = "https://api.github.com"

# The floor when the contract does not declare one. Six is one CI run's peak fan-out on the
# `fly` pool, read off the `needs:` graph in .github/workflows/ci.yml: `changes` gates five
# jobs (python, engine, dotnet, nextjs, ops-console) and `guard` runs beside them, so six
# machines is the point at which one pull request stops queueing behind itself. It is not a
# tidy number and it is not a capacity target -- it is the smallest fleet that can serve one PR.
DEFAULT_MIN_STARTED = 6


# --------------------------------------------------------------------------- #
# Reading the declared contract
# --------------------------------------------------------------------------- #
def read_app(fly_toml: Path = FLY_TOML) -> str:
    """The Fly app that carries the runners, from the runner's own fly.toml.

    Read rather than hardcoded: the app name lives in exactly one place and a second copy here
    would be a copy that can go stale silently.
    """
    for line in fly_toml.read_text().splitlines():
        m = re.match(r'^\s*app\s*=\s*["\']([^"\']+)["\']', line)
        if m:
            return m.group(1)
    raise SystemExit(f"no `app =` line in {fly_toml}")


def read_floor(contract: Path = CONTRACT) -> int:
    """How many machines must be started, from `fleet.min_started`.

    Parsed with a regex rather than yaml so this file has no third-party import and can run on
    a bare GitHub-hosted runner without an install step. The contract is hand-written and two
    levels deep; anything more would deserve a real parser.
    """
    if not contract.exists():
        return DEFAULT_MIN_STARTED
    in_fleet = False
    for line in contract.read_text().splitlines():
        if re.match(r"^fleet:\s*$", line):
            in_fleet = True
            continue
        if in_fleet:
            if re.match(r"^\S", line):        # dedented back out of the block
                break
            m = re.match(r"^\s+min_started:\s*(\d+)", line)
            if m:
                return int(m.group(1))
    return DEFAULT_MIN_STARTED


# --------------------------------------------------------------------------- #
# The decisions, kept pure so they can be tested without a network
# --------------------------------------------------------------------------- #
def plan(machines: list[dict], floor: int) -> dict:
    """Which machines to start to reach the floor, and nothing else.

    Edge cases, each of which has a named answer rather than an accident:
      no machines at all  -> `impossible`. Starting cannot help; the fleet has to be created
                             with `deploy/runners.sh up <n>`, which is a human decision.
      already at floor    -> empty `start` list, `ok` true. Idempotent by construction, so two
                             overlapping runs cannot fight.
      more stopped than
      needed to reach it  -> start only up to the floor. This never grows a fleet to its full
                             size; a started machine bills and the floor is the number we can
                             justify.
      already started     -> never in the list. Fly's start is idempotent anyway, but sending
                             it would make the report lie about what was done.
    """
    started = [m for m in machines if m.get("state") == "started"]
    stopped = [m for m in machines if m.get("state") != "started"]
    short = max(0, floor - len(started))
    return {
        "floor": floor,
        "total": len(machines),
        "started": len(started),
        "short": short,
        "impossible": not machines,
        "ok": not machines or short == 0,
        # Stable order so a report diffs cleanly between runs.
        "start": sorted((m["id"] for m in stopped), key=str)[:short],
    }


def phantoms(runners: list[dict]) -> list[dict]:
    """Registrations holding a slot that no machine is behind.

    `offline AND busy` is the whole test, and both halves are load-bearing. An ONLINE busy
    runner is a runner doing its job. An OFFLINE idle runner is a machine that is merely
    stopped, which `plan()` fixes by starting it. Only the pair means GitHub believes a job is
    running on a runner that is not there -- the state a mid-job kill leaves behind, which
    GitHub will neither schedule to nor let anyone delete.
    """
    return [r for r in runners if r.get("status") != "online" and r.get("busy")]


# --------------------------------------------------------------------------- #
# The network edges
# --------------------------------------------------------------------------- #
def _api(url: str, token: str, method: str = "GET", accept: str | None = None) -> object:
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if accept:
        req.add_header("Accept", accept)
    with urllib.request.urlopen(req, timeout=45) as r:
        body = r.read().decode() or "{}"
    return json.loads(body) if body.strip() else {}


def fly_machines(app: str, token: str) -> list[dict]:
    return _api(f"{FLY_API}/apps/{app}/machines", token) or []


def fly_start(app: str, machine_id: str, token: str) -> None:
    _api(f"{FLY_API}/apps/{app}/machines/{machine_id}/start", token, method="POST")


def gh_runners(repo: str, token: str) -> list[dict]:
    got = _api(f"{GH_API}/repos/{repo}/actions/runners?per_page=100", token,
               accept="application/vnd.github+json")
    return got.get("runners", []) if isinstance(got, dict) else []


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", action="store_true",
                    help="actually start machines; without it this only reports")
    ap.add_argument("--json", action="store_true", help="machine-readable, for the ops console")
    ap.add_argument("--app", default=None, help="Fly app (default: deploy/runner/fly.toml)")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "chidionyema/prospector"))
    args = ap.parse_args()

    fly_token = os.environ.get("FLY_API_TOKEN", "")
    if not fly_token:
        print("BLOCKED: FLY_API_TOKEN is not set, so the fleet cannot be read or started.",
              file=sys.stderr)
        return 2

    app = args.app or read_app()
    floor = read_floor()
    try:
        machines = fly_machines(app, fly_token)
    except urllib.error.HTTPError as e:
        print(f"BLOCKED: Fly API {e.code} listing machines for {app}", file=sys.stderr)
        return 2

    p = plan(machines, floor)
    p["app"] = app
    p["started_now"], p["failed"] = [], []

    if args.start and p["start"]:
        for mid in p["start"]:
            try:
                fly_start(app, mid, fly_token)
                p["started_now"].append(mid)
            except urllib.error.HTTPError as e:
                # Keep going. One machine refusing to start is not a reason to leave the rest
                # of a starved fleet down; the exit status still reports the failure.
                p["failed"].append({"id": mid, "error": f"HTTP {e.code}"})

    # The registration half. Absent a PAT this is simply not graded, and says so, rather than
    # reporting a clean fleet it never looked at.
    pat = os.environ.get("RUNNER_ADMIN_PAT", "")
    p["phantoms"] = None
    if pat:
        try:
            p["phantoms"] = [{"id": r["id"], "name": r["name"]}
                             for r in phantoms(gh_runners(args.repo, pat))]
        except urllib.error.HTTPError as e:
            p["phantoms_error"] = f"HTTP {e.code}"

    if args.json:
        print(json.dumps(p, indent=2, sort_keys=True))
    else:
        print(f"fleet {app}: {p['started']}/{p['total']} started, floor {floor}")
        if p["impossible"]:
            print("  IMPOSSIBLE: the app has no machines. Create them with "
                  "`deploy/runners.sh up <n>` -- this tool only starts what exists.")
        for mid in p["started_now"]:
            print(f"  STARTED {mid}")
        for f in p["failed"]:
            print(f"  FAILED  {f['id']}: {f['error']}")
        if p["start"] and not args.start:
            print(f"  {len(p['start'])} stopped machine(s) would be started with --start: "
                  + " ".join(p["start"]))
        if p["phantoms"] is None:
            print("  registrations NOT graded: no RUNNER_ADMIN_PAT (issue #436)")
        elif p["phantoms"]:
            print(f"  {len(p['phantoms'])} phantom registration(s) holding a slot GitHub will "
                  "not schedule to and will not let us delete:")
            for r in p["phantoms"]:
                print(f"    {r['name']} (id {r['id']})")

    if p["impossible"] or p["failed"]:
        return 1
    # After a --start run, judge the fleet on what it is now, not on what it was.
    if p["short"] and not (args.start and len(p["started_now"]) == p["short"]):
        return 1
    return 1 if p["phantoms"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
