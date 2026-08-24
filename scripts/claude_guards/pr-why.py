#!/usr/bin/env python3
"""Print WHY each open pull request is red, not that it is red.

LAW 1, PROOF BEFORE ACTION. On 2026-08-19 an agent read `gh pr checks` output showing `python=F`
on twelve pull requests, took `F` for congestion, and bought six Fly machines. `F` means FAILED,
not QUEUED. One log read showed seven of them failing on the SAME assertion: a single red test on
main that every branch inherits.

`gh pr checks` tells you WHICH job failed and nothing about WHY. The reason is one API call away.
This script makes that call so nobody has to choose between guessing and typing twelve commands.

Usage:
    pr-why.py                 # every open PR with a failing check
    pr-why.py 410 407         # only these
    pr-why.py --repo owner/name
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter

# Lines worth showing. A pytest assertion, a summary count, a runner-level abort.
SIGNAL = re.compile(
    r"(^E\s+\S|assert |short test summary|\d+ failed,|Error: |error: |"
    r"npm ERR!|FAIL |Process completed with exit code)",
)
# The named cause, for grouping PRs. A pytest node id is specific; "assert None" is not.
ASSERT_LINE = re.compile(r"^\s*(?:FAILED|ERROR)\s+(\S+::\S+)|^##\[error\](Process completed.*)$")
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s*")


def gh(args: list[str]) -> str:
    """Run gh and return stdout. Empty string on any failure, so one dead PR never stops the sweep."""
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    return proc.stdout if proc.returncode == 0 else ""


def repo_slug(explicit: str | None) -> str:
    if explicit:
        return explicit
    out = gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).strip()
    if not out:
        sys.exit("cannot determine the repo; pass --repo owner/name")
    return out


def open_prs(repo: str, only: list[int]) -> list[int]:
    if only:
        return only
    raw = gh(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100",
              "--json", "number", "--jq", ".[].number"])
    return [int(n) for n in raw.split()]


def failing_jobs(repo: str, pr: int) -> list[tuple[str, str]]:
    """(check name, job id) for every FAILED check on this PR. Pending and passing are skipped."""
    raw = gh(["pr", "view", str(pr), "--repo", repo, "--json", "statusCheckRollup"])
    if not raw:
        return []
    try:
        rollup = json.loads(raw).get("statusCheckRollup") or []
    except json.JSONDecodeError:
        return []
    out = []
    for check in rollup:
        if check.get("conclusion") != "FAILURE":
            continue
        url = check.get("detailsUrl") or ""
        m = re.search(r"/job/(\d+)", url)
        if m:
            out.append((check.get("name") or "?", m.group(1)))
    return out


def why(repo: str, job_id: str, keep: int) -> tuple[list[str], list[str]]:
    """The signal lines from a job log, and every named cause in it.

    Two return values, because they must not share a cut-off. The printed lines are the TAIL of the
    log, so a run with many failures pushes the `FAILED <file>::<test>` lines off the top — and on
    2026-08-19 that emptied the grouping table on a sweep of 26 PRs, which is the exact number the
    tool exists to explain. Causes are counted over the WHOLE log; only the display is trimmed.
    """
    log = gh(["api", f"repos/{repo}/actions/jobs/{job_id}/logs"])
    if not log:
        return ["(no log: the run was cancelled, or the log has expired)"], []
    lines = [TIMESTAMP.sub("", ln).rstrip() for ln in log.splitlines()]
    hits = [ln for ln in lines if ln.strip() and SIGNAL.search(ln)]
    # Deduplicate while preserving order; a parallel suite repeats the same line many times.
    seen, uniq = set(), []
    for ln in hits:
        if ln not in seen:
            seen.add(ln)
            uniq.append(ln)
    causes = []
    for ln in uniq:
        m = ASSERT_LINE.match(ln)
        if m and m.group(1):
            causes.append(m.group(1).strip()[:110])
    shown = uniq[-keep:] if uniq else ["(log read, no recognised failure line — open it by hand)"]
    return shown, causes


def main() -> int:
    ap = argparse.ArgumentParser(description="Print why each open PR is red.")
    ap.add_argument("prs", nargs="*", type=int, help="PR numbers (default: every open PR)")
    ap.add_argument("--repo", help="owner/name (default: the repo in cwd)")
    ap.add_argument("--lines", type=int, default=6, help="signal lines per job (default 6)")
    args = ap.parse_args()

    repo = repo_slug(args.repo)
    prs = open_prs(repo, args.prs)
    if not prs:
        print("no open pull requests")
        return 0

    causes: Counter[str] = Counter()
    red = 0

    for pr in prs:
        jobs = failing_jobs(repo, pr)
        if not jobs:
            continue
        red += 1
        print(f"\n=== PR #{pr} ===")
        for name, job_id in jobs:
            print(f"  [{name}]")
            shown, found = why(repo, job_id, args.lines)
            for ln in shown:
                print(f"    {ln}")
            causes.update(found)

    print(f"\n{'=' * 60}")
    print(f"{red} of {len(prs)} open pull request(s) have a FAILED check.")
    if causes:
        print("\nShared causes, most common first — one fix here moves every PR that shares it:")
        for cause, n in causes.most_common(10):
            print(f"  {n:>3} x  {cause}")
    print("\nA failed check is not a queued check. Adding CI capacity moves none of these.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
