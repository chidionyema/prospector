#!/usr/bin/env python3
"""Report GitHub Actions workflows that are DEAD — failing without ever producing a job.

WHY THIS EXISTS. A workflow GitHub cannot START fails with zero jobs, no log, no annotation
and no red check on any pull request. Nothing reports it, so it can be dead for its entire
life. Measured 2026-08-19: `.github/workflows/ci-autoscale.yml` had 30 runs, 30 failures and
`total_count: 0` jobs on every one, because `workflow_job` is a webhook event and not a
workflow trigger. The CI runner pool had never once been scaled automatically. The only tell
was a Fly machine stopped in the middle of PR #425's test suite.

`actionlint` in CI's `guard` job stops that defect being MERGED. This script is the other
half: it detects a workflow that is dead in the repository RIGHT NOW, whatever the cause —
a bad trigger, a YAML error, a deleted action, a permissions change. The rule is simple and
cause-agnostic: a run that CONCLUDED and produced zero jobs did no work at all.

Exit codes are deliberately three-valued, so an outage can never read as health:
  0  every workflow that ran recently produced jobs
  1  at least one workflow is dead, or is failing every run
  2  could not tell (no `gh`, not authenticated, API error) — never a green

Usage:
  python3 scripts/workflow_health.py                # human table
  python3 scripts/workflow_health.py --json         # for the ops console tile
  python3 scripts/workflow_health.py --runs 10      # how many recent runs to grade per workflow
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

# A run in one of these states has not concluded, so it cannot be evidence either way.
_UNCONCLUDED = {"queued", "in_progress", "waiting", "requested", "pending"}


def _gh(args: list[str]) -> object:
    """One `gh api` call returning parsed JSON. Raises RuntimeError with the real stderr."""
    proc = subprocess.run(
        ["gh", "api", *args], capture_output=True, text=True, timeout=60, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "gh api failed").strip()[:400])
    return json.loads(proc.stdout or "null")


def _repo(explicit: str | None) -> str:
    if explicit:
        return explicit
    proc = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "could not resolve the repository").strip()[:400])
    return proc.stdout.strip()


def grade(repo: str, runs_per_workflow: int) -> dict:
    """Grade every active workflow in `repo` on its most recent concluded runs."""
    wfs = _gh([f"repos/{repo}/actions/workflows", "--jq", ".workflows"]) or []
    rows: list[dict] = []
    for wf in wfs:
        if wf.get("state") != "active":
            continue
        wid = wf["id"]
        runs = (
            _gh(
                [
                    f"repos/{repo}/actions/workflows/{wid}/runs?per_page={runs_per_workflow}",
                    "--jq",
                    ".workflow_runs",
                ]
            )
            or []
        )
        concluded = [r for r in runs if r.get("status") not in _UNCONCLUDED]
        row = {
            "name": wf.get("name"),
            "path": wf.get("path"),
            "runs_graded": len(concluded),
            "jobless_runs": 0,
            "failed_runs": 0,
            "verdict": "no recent runs",
        }
        if concluded:
            for r in concluded:
                if r.get("conclusion") == "failure":
                    row["failed_runs"] += 1
                jobs = _gh([f"repos/{repo}/actions/runs/{r['id']}/jobs", "--jq", ".total_count"])
                if not jobs:
                    row["jobless_runs"] += 1
            if row["jobless_runs"] == len(concluded):
                # Every concluded run did no work. GitHub could not start this workflow.
                row["verdict"] = "DEAD — every run produced zero jobs"
            elif row["jobless_runs"]:
                row["verdict"] = f"{row['jobless_runs']}/{len(concluded)} runs produced zero jobs"
            elif row["failed_runs"] == len(concluded):
                row["verdict"] = "failing every run"
            else:
                row["verdict"] = "ok"
        rows.append(row)
    rows.sort(
        key=lambda r: (r["verdict"] == "ok", r["verdict"] == "no recent runs", r["name"] or "")
    )
    dead = [r["path"] for r in rows if r["verdict"].startswith("DEAD")]
    red = [r["path"] for r in rows if r["verdict"] == "failing every run"]
    degraded = [
        r["path"]
        for r in rows
        if "produced zero jobs" in r["verdict"] and not r["verdict"].startswith("DEAD")
    ]
    return {
        "repo": repo,
        "runs_per_workflow": runs_per_workflow,
        "workflows": rows,
        "dead": dead,
        "red": red,
        "degraded": degraded,
        "healthy": not dead and not red and not degraded,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--repo", help="owner/name; defaults to the checkout's own remote")
    ap.add_argument(
        "--runs", type=int, default=5, help="recent runs to grade per workflow (default 5)"
    )
    ap.add_argument("--json", action="store_true", help="machine-readable, for the ops console")
    args = ap.parse_args(argv)

    if shutil.which("gh") is None:
        payload = {"error": "gh CLI is not installed, so workflow health could not be measured"}
        print(json.dumps(payload) if args.json else payload["error"], file=sys.stderr)
        return 2
    try:
        report = grade(_repo(args.repo), max(1, args.runs))
    except Exception as exc:  # noqa: BLE001 — any failure here means "could not tell", never green
        payload = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(payload) if args.json else payload["error"], file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        width = max((len(r["path"] or "") for r in report["workflows"]), default=4)
        for r in report["workflows"]:
            print(f"{(r['path'] or ''):<{width}}  {r['runs_graded']:>2} graded  {r['verdict']}")
        if report["healthy"]:
            print("\nOK — every workflow that ran recently produced jobs.")
        else:
            for path in report["dead"]:
                print(f"\nDEAD: {path} — it runs, it fails, and it produces no jobs at all.")
            for path in report["degraded"]:
                print(f"\nDEGRADED: {path} — some runs produced no jobs at all.")
            for path in report["red"]:
                print(f"\nRED: {path} — it does real work and every recent run failed.")
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
