#!/usr/bin/env python3
"""Grade every GitHub workflow this repo declares: did it run, did it pass, is it still firing.

The question this answers is "are the enforcements themselves working?". A workflow is a fence,
and a fence you cannot see is a fence you find out about from a customer. On 2026-08-19 the ops
console was green while the live storefront smoke had been red for 30 hours, the escape-hatch
drill had never completed a run, and the autoscaler had failed at startup 19 times without ever
turning a single check red -- a startup failure attaches to no pull request, so nothing objected.

Three failure modes, all invisible to a dashboard that only shows a last result:

  FAILING    the last run was red. Visible in principle, but only if somebody looks.
  NEVER-RAN  no run at all. There is no red run to see, because there is no run.
  STOPPED    a scheduled workflow whose last run is older than its own cron interval. This is
             the live-smoke class: it does not go red, it goes quiet.

Why this exists as its own module rather than a section of `scripts/process_audit.py`: that
script's `grade_workflows` asked `gh run list --limit 200`, one global window across all
workflows. Measured 2026-08-19T14:11Z, those 200 runs covered 3h39m, because CI and auto-merge
alone produced 164 of them. Five of the ten workflows on disk had no run inside the window and
were graded NEVER-RAN; four of the five had in fact run that morning, and three of those four
were FAILING. So the one page that graded workflows was wrong about half of them, and it got
wronger the busier CI was -- exactly when it matters. The class of mistake is answering a
per-entity question with a global recent-N window. This asks GitHub per workflow instead
(`/actions/workflows/{id}/runs?per_page=1`), which is exact whatever the volume.

`process_audit.py` now consumes this module, so there is one count of one fact.

Read-only. No writes, no reruns, no dispatches, no money keys. Exits 1 when anything is BAD so
it can gate CI; `--json` is what the ops console reads.

    python3 scripts/workflow_health.py
    python3 scripts/workflow_health.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
REPO = os.environ.get("PROSPECTOR_GH_REPO", "chidionyema/prospector")

OK, WARN, BAD = "ok", "warn", "bad"

#: A run that ends in one of these is a failed fence, not a skipped one.
RED = ("failure", "timed_out", "startup_failure")
#: Neither red nor green. `skipped` is the normal resting state of auto-merge, and `cancelled`
#: is the normal state of a CI run superseded by a newer push, so neither is graded red.
AMBER = ("cancelled", "action_required", "stale")

#: How stale a scheduled workflow may get before it counts as STOPPED, in seconds, by how often
#: its cron says it should fire. Deliberately generous -- roughly two intervals -- because
#: GitHub delays scheduled runs under load and a jumpy alarm gets muted, which is worse than no
#: alarm. Anything past this has not been late, it has stopped.
STALE_AFTER = {"hourly": 3 * 3600, "daily": 2 * 86400, "weekly": 8 * 86400, "monthly": 32 * 86400}


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """Run a command, returning (exit code, stdout-or-stderr). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return p.returncode, (p.stdout if p.returncode == 0 else (p.stderr or p.stdout))


def cron_cadence(expr: str) -> str:
    """Classify a cron expression as hourly/daily/weekly/monthly.

    Coarse on purpose. The only decision this feeds is "has it been silent for longer than it
    could legitimately be", and for that the ORDER of magnitude is the whole answer. A precise
    next-fire calculation would need a timezone-aware cron parser in a file that must stay
    standard-library only, because the `guard` job in ci.yml runs without a virtualenv.
    """
    parts = expr.split()
    if len(parts) != 5:
        return "daily"
    _minute, hour, dom, _mon, dow = parts
    if dow != "*":
        return "weekly"
    if dom != "*":
        return "monthly"
    if hour == "*":
        return "hourly"
    return "daily"


def declared_crons(path: Path) -> list[str]:
    """Every cron expression in a workflow file.

    Read with a regex rather than a YAML parser for the same standard-library-only reason. The
    shape is fixed and machine-written (`- cron: "0 7 * * *"`), so there is nothing here a
    parser would get right that this gets wrong.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        m.group(1).strip() for m in re.finditer(r"^\s*-\s*cron:\s*[\"']?([^\"'#\n]+)", text, re.M)
    ]


def _iso_to_epoch(iso: str) -> float | None:
    """Parse GitHub's `2026-08-19T09:52:41Z` without pulling in a date library."""
    try:
        return time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (ValueError, TypeError):
        return None


def _age_words(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def collect(now: float | None = None) -> dict:
    """Every workflow on disk, its last run, and a grade. The whole report, as data."""
    now = time.time() if now is None else now
    code, out = sh(
        [
            "gh",
            "api",
            f"repos/{REPO}/actions/workflows",
            "--paginate",
            "--jq",
            ".workflows[] | {id, name, path, state} | tostring",
        ],
        timeout=90,
    )
    if code != 0:
        first = (out.strip().splitlines() or ["gh failed"])[0]
        return {
            "generated_at": now,
            "reachable": False,
            "error": first,
            "rows": [],
            "failing": 0,
            "warnings": 0,
            "ok": False,
            "note": "Could not ask GitHub. This is not evidence the workflows are healthy.",
        }

    known: dict[str, dict] = {}
    for line in out.splitlines():
        try:
            wf = json.loads(line)
        except ValueError:
            continue
        # Dependabot and the dependency-graph updater run "dynamic" workflows that live in no
        # file. They are GitHub's, not ours, and grading them would be grading someone else's
        # repo hygiene against our fences.
        if str(wf.get("path", "")).startswith(".github/workflows/"):
            known[wf["path"]] = wf

    rows: list[dict] = []
    on_disk = {f".github/workflows/{p.name}" for p in sorted(WORKFLOW_DIR.glob("*.y*ml"))}

    for path in sorted(on_disk | set(known)):
        f = ROOT / path
        wf = known.get(path)
        crons = declared_crons(f) if f.exists() else []
        cadence = cron_cadence(crons[0]) if crons else None
        row = {
            "file": path.split("/")[-1],
            "path": path,
            "name": (wf or {}).get("name") or path,
            "scheduled": cadence,
            "state": (wf or {}).get("state"),
            "conclusion": None,
            "status": None,
            "event": None,
            "at": None,
            "age_s": None,
            "url": None,
            "ever_ran": None,
        }

        if wf is None:
            row.update(
                grade=BAD,
                detail=(
                    "NOT REGISTERED -- this file is on disk but GitHub has no workflow for it. It has "
                    "never reached the default branch, so it has never protected anything."
                ),
            )
            rows.append(row)
            continue
        if not f.exists():
            row.update(
                grade=WARN,
                detail=(
                    "NOT ON THIS BRANCH -- GitHub has an active workflow at this path and this "
                    "checkout does not. Either it was deleted here, or it only ever existed on a "
                    "feature branch: GitHub registers a workflow the first time it runs, from any "
                    "branch. Both are worth knowing; a fence that lives on one branch guards one "
                    "branch."
                ),
            )
            rows.append(row)
            continue
        if wf.get("state") == "disabled_manually":
            row.update(
                grade=BAD,
                detail="DISABLED by hand in the GitHub UI. It is not protecting anything.",
            )
            rows.append(row)
            continue

        rc, runs_out = sh(
            [
                "gh",
                "api",
                f"repos/{REPO}/actions/workflows/{wf['id']}/runs?per_page=1",
                "--jq",
                ".workflow_runs[0] | {conclusion, status, event, created_at, html_url} | tostring",
            ],
            timeout=60,
        )
        run = None
        if rc == 0 and runs_out.strip():
            try:
                run = json.loads(runs_out.strip().splitlines()[0])
            except ValueError:
                run = None
        if rc != 0:
            row.update(
                grade=WARN, detail=f"could not ask GitHub for its runs ({runs_out.strip()[:120]})"
            )
            rows.append(row)
            continue

        row["ever_ran"] = run is not None
        if run is None:
            row.update(
                grade=BAD,
                detail=(
                    "NEVER-RAN -- not one run, ever. A workflow that never runs never goes red, so "
                    "this is the one failure no red badge anywhere can show you."
                ),
            )
            rows.append(row)
            continue

        concl = run.get("conclusion")
        status = run.get("status")
        at = run.get("created_at") or ""
        epoch = _iso_to_epoch(at)
        age = (now - epoch) if epoch else None
        row.update(
            conclusion=concl,
            status=status,
            event=run.get("event"),
            at=at,
            age_s=None if age is None else int(age),
            url=run.get("html_url"),
        )
        when = _age_words(age) if age is not None else at[:16]
        last = f"last {concl or status or '?'} ({run.get('event')}) {when}"

        if concl in RED:
            row.update(grade=BAD, detail=f"FAILING -- {last}")
        elif cadence and age is not None and age > STALE_AFTER[cadence]:
            row.update(
                grade=BAD,
                detail=(
                    f"STOPPED -- runs on a {cadence} schedule and its last run was {when}. It is not "
                    f"red, it is silent, which is the failure a dashboard of last-results cannot show. "
                    f"({last})"
                ),
            )
        elif concl in AMBER:
            row.update(grade=WARN, detail=last)
        else:
            row.update(grade=OK, detail=last)
        rows.append(row)

    failing = sum(1 for r in rows if r["grade"] == BAD)
    warnings = sum(1 for r in rows if r["grade"] == WARN)
    live = next((r for r in rows if r["file"] == "e2e-live-smoke.yml"), None)
    return {
        "generated_at": now,
        "reachable": True,
        "repo": REPO,
        "rows": rows,
        "failing": failing,
        "warnings": warnings,
        "ok": failing == 0,
        # The storefront's own answer to "is it broken right now", lifted out of the table so a
        # tile can show it without the reader having to know which file is the live smoke.
        "live_storefront": None
        if live is None
        else {"grade": live["grade"], "detail": live["detail"], "url": live["url"]},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable, for the ops console")
    ap.add_argument("--quiet", action="store_true", help="print only the problems")
    args = ap.parse_args(argv)

    report = collect()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if not report["reachable"]:
        print(f"WARN  could not ask GitHub: {report['error']}")
        print("      This is not evidence the workflows are healthy.")
        return 1

    mark = {OK: "ok  ", WARN: "WARN", BAD: "BAD "}
    for r in report["rows"]:
        if args.quiet and r["grade"] == OK:
            continue
        print(f"{mark[r['grade']]}  {r['file']:<28} {r['detail']}")
        if r["grade"] != OK and r.get("url"):
            print(f"        {r['url']}")
    print(
        f"\n{len(report['rows'])} workflows, {report['failing']} failing, "
        f"{report['warnings']} warning"
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
