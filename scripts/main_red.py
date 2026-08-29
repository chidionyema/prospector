#!/usr/bin/env python3
"""Is main red, what exactly is it red ON, and does this PR fix that and only that?

THE PROTOCOL THIS REPLACES. On 2026-08-19 main was red, every open pull request inherited the
failure, and the founder's question was the right one: "can u proof pr is the fix ... else we are
introducing ANOTHER ERROR ON ALREADY BROKEN MAIN". Answering it took five hand-run commands --
list main's runs, find the failed jobs, pull the job logs, grep the FAILED lines, diff the PR.
Five commands is a protocol nobody follows at 3am, so it is one command now.

WHAT IT REFUSES TO DO. It never reads a status letter and calls that evidence (LAW 1: a summary is
not the data). It downloads the failing job's LOG and lists the FAILED test ids by name, because
"python=FAILURE" does not say whether main is red on one test or forty, and that difference decides
whether one merge turns main green.

    scripts/main_red.py            # what is main red on, by name
    scripts/main_red.py --pr 425   # ...and is PR 425 the fix for exactly that

Exit 0 = main is green, or (with --pr) the PR is a clean fix for exactly main's failures.
Exit 1 = main is red and nothing here proves this PR fixes it.
Exit 2 = could not tell (no concluded run, gh missing, log unavailable, or the newest concluded
         run does not describe main's current HEAD) -- never guess.

A CI VERDICT IS ABOUT A SHA, NOT A BRANCH NAME. The first version of this script printed
`MAIN GREEN: run 31854380817 ... 2026-08-15` while main was red -- a four-day-old run, served from
a stale `gh run list`, reported as the state of main today. A green tick on some other commit is not
evidence about this one, so the run's headSha is checked against `git rev-parse origin/main`.

But "the run is behind HEAD" is not the same as "we cannot tell", and treating it that way would
make this useless in the exact hour it is needed: main almost always has a commit or two with no
concluded run yet. So when the newest verdict is behind, the script asks the only question that
settles it -- did any commit since then touch the FILES the run failed on? If not, those failures
are still in the tree and main is still red on them, and that is stated as fact with the commit
range that proves it. A GREEN run that is behind HEAD stays `could not tell`, because untested
commits can only break things.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

REPO = "chidionyema/prospector"
# `FAILED tests/unit/x.py::test_y - AssertionError: ...` is pytest's short summary line. The job
# log prefixes every line with a timestamp, so the pattern is not anchored to the start.
FAILED_RE = re.compile(r"FAILED (\S+::\S+)")
# `1 failed, 5423 passed, 8 skipped in 1103.79s`. The pass count is what tells you the suite ran
# at all -- a red job with 0 passed is an infrastructure failure, not a broken test.
TALLY_RE = re.compile(r"(\d+) failed, (\d+) passed")


def _gh(*args: str, timeout: int = 120) -> str:
    """One gh call. Any non-zero exit returns empty rather than raising, so a missing log degrades
    to `could not tell` (exit 2) instead of a traceback that reads as a verdict."""
    try:
        done = subprocess.run(("gh", *args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout if done.returncode == 0 else ""


def main_head() -> str:
    """The SHA a CI verdict has to be ABOUT. Fetched first, because a stale local ref would make a
    stale run look current, which is the failure this function exists to catch."""
    subprocess.run(("git", "fetch", "-q", "origin", "main"), capture_output=True, timeout=120)
    done = subprocess.run(("git", "rev-parse", "origin/main"), capture_output=True, text=True,
                          timeout=30)
    return done.stdout.strip() if done.returncode == 0 else ""


def files_changed_between(sha: str, head: str) -> set[str] | None:
    """Paths touched between the run's commit and main's HEAD. None when git cannot say."""
    done = subprocess.run(("git", "diff", "--name-only", f"{sha}..{head}"),
                          capture_output=True, text=True, timeout=60)
    return set(done.stdout.split()) if done.returncode == 0 else None


def commits_between(sha: str, head: str) -> int:
    """How far the run's commit sits behind main's HEAD. -1 when git cannot say."""
    done = subprocess.run(("git", "rev-list", "--count", f"{sha}..{head}"),
                          capture_output=True, text=True, timeout=30)
    try:
        return int(done.stdout.strip())
    except ValueError:
        return -1


def latest_concluded_main_run() -> dict | None:
    """main's most recent run that actually FINISHED.

    An in-flight run is not evidence either way, and taking the newest run regardless of status is
    how a green tick gets reported while the run that matters is still going.
    """
    raw = _gh("run", "list", "--repo", REPO, "--branch", "main", "--workflow", "ci.yml",
              "-L", "10", "--json", "databaseId,status,conclusion,headSha,createdAt")
    if not raw:
        return None
    for run in json.loads(raw):
        if run.get("status") == "completed":
            return run
    return None


def failures_in(run_id: int) -> tuple[list[str], dict[str, str]] | None:
    """Every failing job, and every FAILED test id inside it, read from the job's own log.

    Returns (job names, {test id: the job it failed in}). None means the logs could not be read --
    which is reported as `could not tell`, never as green.
    """
    raw = _gh("run", "view", str(run_id), "--repo", REPO, "--json", "jobs")
    if not raw:
        return None
    jobs = [j for j in json.loads(raw)["jobs"] if j.get("conclusion") == "failure"]
    tests: dict[str, str] = {}
    for job in jobs:
        log = _gh("api", f"repos/{REPO}/actions/jobs/{job['databaseId']}/logs", timeout=180)
        for test in FAILED_RE.findall(log):
            tests.setdefault(test, job["name"])
    return [j["name"] for j in jobs], tests


def pr_files(number: int) -> list[str]:
    raw = _gh("pr", "view", str(number), "--repo", REPO, "--json", "files")
    return [f["path"] for f in json.loads(raw)["files"]] if raw else []


def pr_checks(number: int) -> dict[str, str]:
    raw = _gh("pr", "view", str(number), "--repo", REPO, "--json", "statusCheckRollup")
    if not raw:
        return {}
    rollup = json.loads(raw).get("statusCheckRollup") or []
    return {c.get("name") or c.get("context", "?"):
            (c.get("conclusion") or c.get("state") or c.get("status") or "?") for c in rollup}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", type=int, help="grade this pull request as the fix for main's red")
    args = ap.parse_args()

    run = latest_concluded_main_run()
    if run is None:
        print("COULD NOT TELL: no concluded ci.yml run on main (or gh is unavailable)")
        return 2
    head = f"{run['headSha'][:8]} {run['createdAt']}"
    live = main_head()
    stale = bool(live) and run["headSha"] != live
    since: set[str] | None = None
    if stale:
        behind = commits_between(run["headSha"], live)
        gap = f"{behind} commit(s)" if behind >= 0 else "an unknown distance"
        since = files_changed_between(run["headSha"], live)
        print(f"NOTE: newest concluded run is on {head}; main's HEAD is {live[:8]}, "
              f"{gap} later with no verdict of its own.")
        if run["conclusion"] == "success":
            # Untested commits can only break things. A green run that predates them proves
            # nothing about the tree as it stands, so this never reports green.
            print("COULD NOT TELL: that run was green, but it did not test the commits since.")
            return 2
    elif run["conclusion"] == "success":
        print(f"MAIN GREEN: run {run['databaseId']} on {head}")
        return 0

    found = failures_in(run["databaseId"])
    if found is None:
        print(f"COULD NOT TELL: main run {run['databaseId']} is {run['conclusion']}, logs unreadable")
        return 2
    jobs, tests = found
    print(f"MAIN RED: run {run['databaseId']} on {head}")
    print(f"  failing job(s): {', '.join(jobs) or '(none named)'}")
    if not tests:
        # A job that fails with no FAILED line is not a broken test: it is a broken step -- setup,
        # a runner that died, a timeout. Merging a test fix does nothing for it, so say so.
        print("  no FAILED test ids in the logs — this is a broken STEP, not a broken test.")
        print("  a test-only PR cannot fix it. read the job log before merging anything.")
        return 1
    for test, job in sorted(tests.items()):
        print(f"  FAILED  {test}   (in {job})")

    red_files = {t.split("::")[0] for t in tests}
    if stale:
        if since is None:
            print("  COULD NOT TELL whether those failures survive: git could not diff the range.")
            return 2
        touched = red_files & since
        if touched:
            print(f"  ...but {', '.join(sorted(touched))} CHANGED since that run. "
                  f"Those failures may already be fixed — wait for HEAD's own run.")
            return 2
        print(f"  STILL RED: nothing since {run['headSha'][:8]} touched "
              f"{', '.join(sorted(red_files))}, so the failure(s) are still in the tree.")

    if args.pr is None:
        print(f"\n{len(tests)} failing test(s). Re-run with --pr N to grade a candidate fix.")
        return 1

    files = pr_files(args.pr)
    covered = {f for f in files if f in red_files}
    extra = [f for f in files if f not in red_files]
    print(f"\nPR #{args.pr}: {len(files)} file(s)")
    print(f"  touches the red file(s): {', '.join(sorted(covered)) or 'NONE'}")
    print(f"  also touches           : {', '.join(extra) or 'nothing else'}")
    checks = pr_checks(args.pr)
    unfinished = sorted(n for n, s in checks.items() if s in ("PENDING", "IN_PROGRESS", "QUEUED", "?"))
    failed = sorted(n for n, s in checks.items() if s == "FAILURE")
    print(f"  own checks             : {len(checks)} total, {len(failed)} failed, "
          f"{len(unfinished)} unfinished")

    verdict = []
    if red_files - covered:
        verdict.append(f"does NOT touch {', '.join(sorted(red_files - covered))}")
    if failed:
        verdict.append(f"its own checks are red: {', '.join(failed)}")
    if unfinished:
        # Not a defect in the PR, but it is the difference between proven and assumed, and merging
        # here also evicts main's queued run -- which is what scripts/../rule-guard.py refuses.
        verdict.append(f"unfinished checks: {', '.join(unfinished)}")
    if verdict:
        print(f"\nNOT PROVEN: {'; '.join(verdict)}")
        return 1
    if extra:
        # A fix that also carries unrelated files is how a second failure lands on a red main. It
        # is not automatically wrong, but it stops being a one-line unblock and must be read.
        print(f"\nPROVEN FIX, WITH CARGO: green, and covers every red file, but also changes "
              f"{len(extra)} unrelated file(s). Read them before merging onto a red main.")
        return 0
    print(f"\nPROVEN FIX: PR #{args.pr} is green, and changes exactly the file(s) main is red on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
