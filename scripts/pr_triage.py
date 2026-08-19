#!/usr/bin/env python3
"""Why is every pull request red? Separate a broken TEST from a broken MACHINE.

WHY THIS EXISTS. On 2026-08-19 the founder said "look we have 27 open pr faiing". Twenty-seven
red pull requests. Measured with this file's logic: FOUR had a test failure. Nine were a machine
dying mid-build, seven were cancelled by someone else's push, three were already green, and two
had never run at all. Acting on "27 failing" would have meant twenty-seven investigations of
code that was fine.

Two traps produce that gap, and both cost real hours today -- one of them twice, in two
different sessions that could not see each other.

TRAP 1 -- THE GHOST RUN. A run whose conclusion is `action_required` has ZERO jobs. GitHub
refuses to build a push made with the default GITHUB_TOKEN, to stop workflows triggering
themselves. `.github/workflows/automerge.yml` updates each pull request branch with
`Merge branch 'main' into <branch>` using exactly that token, so every such update mints a
zero-job run. automerge compensates with a `workflow_dispatch`, and that dispatched run is the
REAL one -- but it is OLDER, so "the newest run at this head" returns the ghost and hides the
verdict underneath. Sorting by createdAt without discarding ghosts is wrong, quietly.

TRAP 2 -- THE KILLED RUNNER. A job that failed because its machine died has NO failed STEP:
the steps simply stop concluding. `jobs[] | select(.conclusion=="failure") | .steps[] |
select(.conclusion=="failure")` returns nothing, and the only place the truth is written is the
check-run ANNOTATION: "The self-hosted runner lost communication with the server". Read the step
list and it looks like a mysterious failure with no cause. Measured 2026-08-19: nine of the
twenty-seven, all caused by Fly standby machines that register as runners and are then stopped
by the platform (see scripts/ci_fleet_probe.py, which grades that).

THE CLASS both belong to is LAW 1's: acting on the SHAPE of the evidence instead of its CONTENT.
A red X is a pointer to a reason, never the reason. This script is the one command that reads
the content, so nobody has to remember either trap.

    .venv/bin/python scripts/pr_triage.py           # human table, exit 1 if any REAL failure
    .venv/bin/python scripts/pr_triage.py --json    # for the ops console
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import subprocess
import sys

RUNNER_LOSS = "lost communication with the server"

#: A run with this conclusion produced no jobs at all. See TRAP 1.
GHOST = "action_required"

#: Ordered worst-first, so the summary leads with what a person must actually fix.
SEVERITY = ["REAL FAIL", "CONFLICT", "NO RUN", "GHOST ONLY", "RUNNER KILLED", "CANCELLED",
            "IN PROGRESS", "GREEN"]

#: These need a person. REAL FAIL needs code read; CONFLICT needs a rebase, which no re-run and
#: no amount of waiting will produce. Leaving CONFLICT out was a real defect in this tool: on
#: 2026-08-19 it printed "0 of 6 need a person" while #458 and #426 both had merge conflicts and
#: could not have landed whatever CI said. A summary that cannot see a blocker reports all-clear.
NEEDS_A_PERSON = {"REAL FAIL", "CONFLICT"}

#: Not green and not still running: nothing is happening to it without an action.
STUCK = {"REAL FAIL", "CONFLICT", "NO RUN", "GHOST ONLY", "RUNNER KILLED", "CANCELLED"}


def _gh(args: list[str], timeout: int = 90) -> tuple[int, str]:
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    try:
        p = subprocess.run([gh, *args], capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def _json(args: list[str], timeout: int = 90):
    rc, out = _gh(args, timeout)
    if rc != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _repo() -> str | None:
    d = _json(["repo", "view", "--json", "nameWithOwner"])
    return d.get("nameWithOwner") if d else None


def classify(run: dict | None, jobs: list[dict] | None,
             annotations: dict[int, str] | None,
             mergeable: str | None = None) -> tuple[str, str]:
    """(verdict, detail) for one pull request. Pure, so the tests need no network."""
    # A conflicting branch cannot land on any CI verdict, so this outranks the run. GitHub
    # answers UNKNOWN while it computes the merge, and UNKNOWN is not a conflict -- treating it
    # as one would flag every freshly-opened PR.
    if mergeable == "CONFLICTING":
        return "CONFLICT", "merge conflict with main; needs a rebase, not a re-run"
    if run is None:
        return "NO RUN", "no CI run at this head"
    if run.get("conclusion") == GHOST:
        return "GHOST ONLY", "bot push; GitHub built nothing and no dispatched run exists"
    if run.get("status") != "completed":
        return "IN PROGRESS", str(run.get("databaseId", ""))
    if run.get("conclusion") == "success":
        return "GREEN", str(run.get("databaseId", ""))
    if run.get("conclusion") == "cancelled":
        # Do NOT name a mechanism here. This line used to read "cancel-in-progress killed
        # it", which ci.yml disproves -- it sets `cancel-in-progress: false`. A tool that
        # asserts a cause it did not measure sends the next reader to the wrong file.
        return "CANCELLED", "cancelled, and nothing has run since; re-run it"
    if run.get("conclusion") != "failure":
        return "REAL FAIL", f"conclusion={run.get('conclusion')}"

    real, killed = [], []
    for j in jobs or []:
        if j.get("conclusion") != "failure":
            continue
        # `ci-ok` is the aggregator: it fails BECAUSE something else did, so it never carries
        # the cause and counting it would make every failure look like two.
        if j.get("name") == "ci-ok":
            continue
        if RUNNER_LOSS in (annotations or {}).get(j.get("id"), ""):
            killed.append(j.get("name"))
            continue
        steps = [s.get("name") for s in (j.get("steps") or [])
                 if s.get("conclusion") == "failure"]
        real.append(f"{j.get('name')}>{'/'.join(str(s) for s in steps) or '?'}")

    if real:
        return "REAL FAIL", ", ".join(real)
    if killed:
        return "RUNNER KILLED", ", ".join(str(k) for k in killed)
    # Failed with no failed job we can name. Report it as real rather than inventing a cause.
    return "REAL FAIL", "the run failed but named no failing job — read it by hand"


def newest_real_run(runs: list[dict]) -> dict | None:
    """The newest CI run that actually built something. Ghosts are discarded first -- TRAP 1."""
    live = [r for r in runs if r.get("conclusion") != GHOST]
    if not live:
        return next(iter(sorted(runs, key=lambda r: r.get("createdAt", ""))[-1:]), None)
    return sorted(live, key=lambda r: r.get("createdAt", ""))[-1]


def triage(repo: str, workflow: str = "CI", limit: int = 250) -> list[dict]:
    prs = _json(["pr", "list", "--state", "open", "--limit", "60", "--json",
                 "number,headRefName,headRefOid,title,isDraft,mergeable"]) or []
    runs = _json(["run", "list", "--limit", str(limit), "--json",
                  "headSha,workflowName,status,conclusion,databaseId,createdAt"]) or []
    by_sha: dict[str, list[dict]] = collections.defaultdict(list)
    for r in runs:
        if r.get("workflowName") == workflow:
            by_sha[r.get("headSha")].append(r)

    out = []
    for p in sorted(prs, key=lambda x: -x["number"]):
        run = newest_real_run(by_sha.get(p["headRefOid"], []))
        jobs, anns = None, None
        if run and run.get("conclusion") == "failure":
            jd = _json(["api", f"repos/{repo}/actions/runs/{run['databaseId']}"
                                f"/jobs?per_page=100"])
            jobs = (jd or {}).get("jobs", [])
            anns = {}
            for j in jobs:
                if j.get("conclusion") != "failure":
                    continue
                a = _json(["api", f"repos/{repo}/check-runs/{j['id']}/annotations"]) or []
                anns[j["id"]] = " ".join(str(x.get("message", "")) for x in a)
        verdict, detail = classify(run, jobs, anns, p.get("mergeable"))
        out.append({"pr": p["number"], "branch": p["headRefName"], "draft": p["isDraft"],
                    "title": p["title"], "verdict": verdict, "detail": detail,
                    "run": run.get("databaseId") if run else None})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable, for the ops console")
    ap.add_argument("--workflow", default="CI", help="which workflow decides a PR (default: CI)")
    args = ap.parse_args()

    repo = _repo()
    if repo is None:
        print("could not read the repository from gh — cannot tell, which is not a green",
              file=sys.stderr)
        return 2

    rows = triage(repo, workflow=args.workflow)
    counts = collections.Counter(r["verdict"] for r in rows)
    need = sum(counts[v] for v in NEEDS_A_PERSON)

    if args.json:
        stuck = sum(counts[v] for v in STUCK)
        print(json.dumps({"ok": stuck == 0, "repo": repo, "needs_a_person": need,
                          "stuck": stuck, "counts": dict(counts), "prs": rows}, indent=2))
        return 1 if stuck else 0

    if not rows:
        print("no open pull requests")
        return 0

    print(f"{'PR':<6}{'VERDICT':<15}{'BRANCH':<38}WHY")
    for r in sorted(rows, key=lambda x: (SEVERITY.index(x["verdict"]), -x["pr"])):
        print(f"{('#' + str(r['pr'])):<6}{r['verdict']:<15}{r['branch'][:36]:<38}"
              f"{r['detail'][:64]}")
    print()
    for v in SEVERITY:
        if counts[v]:
            print(f"  {counts[v]:>3}  {v}")
    print()
    stuck = sum(counts[v] for v in STUCK)
    print(f"{need} of {len(rows)} open pull request(s) need a person "
          f"(REAL FAIL needs code read, CONFLICT needs a rebase).")
    print(f"{stuck} of {len(rows)} are not moving on their own — nothing changes without an "
          f"action. {counts['IN PROGRESS']} in progress, {counts['GREEN']} green.")
    return 1 if stuck else 0


if __name__ == "__main__":
    sys.exit(main())
