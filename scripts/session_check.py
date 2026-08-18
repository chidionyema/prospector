#!/usr/bin/env python3
"""Did this session leave anything behind? Read only, run it before you stop.

WHY THIS EXISTS. Founder, 2026-08-18: "shipping without verifying, pushing branch without raising
pr, raising pr and not following through to shipped... everything here reoccurs across all agent
sessions dozens of times a day if not hundreds."

Rules that are broken hundreds of times a day are not being enforced by anything. docs/
WAYS_OF_WORKING.md Part 7 lists which rules had nothing behind them but words. This script is the
first of them made mechanical. It checks the five that a machine can see:

    W21  nothing left uncommitted
    W18  a pushed branch has a pull request
    W19  a pull request was followed to merged
    W23  branch and worktree hygiene
    W7   claimed work, so two sessions do not do the same thing

It does NOT check the two that need a human or a browser: W22 (close the browser tabs you opened)
and W20 (verify in production). It prints the commands for those instead, because a checklist that
silently skips items is worse than no checklist.

READ ONLY. There is no --fix. Every finding names the exact command that clears it, and running
that command is a decision, not an automatic consequence of asking a question.

EXIT CODES
    0   nothing outstanding
    1   something needs attention before this session ends

USAGE
    .venv/bin/python scripts/session_check.py            # everything
    .venv/bin/python scripts/session_check.py --local    # skip anything needing the network
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 25) -> tuple[int, str]:
    """Run a command and return (exit code, stdout). Never raises: a missing tool is a finding,
    not a crash, because this script must still be useful on a box without `gh`."""
    try:
        p = subprocess.run(
            cmd, cwd=cwd or ROOT, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


class Report:
    def __init__(self) -> None:
        self.findings: list[tuple[str, str, str]] = []   # (rule, what, the command that clears it)
        self.notes: list[str] = []

    def flag(self, rule: str, what: str, fix: str) -> None:
        self.findings.append((rule, what, fix))

    def note(self, text: str) -> None:
        self.notes.append(text)


def check_uncommitted(r: Report) -> None:
    """W21. Work in a worktree that is not committed is work that will be lost."""
    code, out = run(["git", "status", "--porcelain"])
    if code != 0:
        r.flag("W21", "git status failed, cannot tell if work is uncommitted", "git status")
        return
    # Never slice a fixed column off porcelain output. run() strips the whole payload, so the
    # FIRST line loses its leading status space and a [3:] slice eats a character of the path.
    # That printed "LAUDE.md" the very first time this script ran. Split on whitespace instead.
    paths = []
    for ln in out.splitlines():
        parts = ln.strip().split(maxsplit=1)
        if len(parts) == 2:
            paths.append(parts[1])
    # Runtime state is tracked and pytest writes to it. It is noise here, never a finding, and
    # staging it is its own documented mistake.
    real = [p for p in paths if not p.startswith(("store/", "storage/"))]
    if real:
        preview = ", ".join(real[:5])
        more = f" and {len(real) - 5} more" if len(real) > 5 else ""
        r.flag("W21", f"{len(real)} uncommitted file(s): {preview}{more}",
               "git add <paths explicitly, never -A> && git commit")


def check_unpushed(r: Report) -> None:
    """W21. A commit that exists only on this disk is one disk failure from gone.

    Scoped to THIS branch on purpose. `--branches --not --remotes` counts every branch in the
    shared checkout, so it reported 152 unpushed commits that belonged to other sessions' branches
    and were none of this session's business. A checker that cries wolf about someone else's work
    gets ignored, which costs more than the check is worth."""
    branch = current_branch()
    if branch in {"", "HEAD"}:
        return
    code, out = run(["git", "log", f"origin/{branch}..HEAD", "--pretty=%h %s"])
    if code != 0:
        # No upstream yet: everything on this branch that is not on origin/main is unpushed.
        code, out = run(["git", "log", "origin/main..HEAD", "--pretty=%h %s"])
    if code == 0 and out:
        n = len(out.splitlines())
        first = out.splitlines()[0]
        r.flag("W21", f"{n} commit(s) on {branch} exist only locally, first: {first}",
               f"git push origin HEAD:{branch}")


def current_branch() -> str:
    _, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return out


def check_branch_has_pr(r: Report, local_only: bool) -> None:
    """W18 and W19. A pushed branch with no pull request is invisible: not queued, not reviewed,
    not merged, and the next session will not find it."""
    branch = current_branch()
    if branch in {"", "HEAD", "main"}:
        return
    code, _ = run(["git", "rev-parse", "--verify", f"origin/{branch}"])
    if code != 0:
        return  # never pushed, so W18 has nothing to say yet
    if local_only:
        r.note(f"skipped the pull request check for {branch} (--local)")
        return
    code, out = run(["gh", "pr", "list", "--head", branch, "--state", "all",
                     "--json", "number,state,statusCheckRollup", "--limit", "5"])
    if code == 127:
        r.note("gh is not available, so the pull request checks were skipped")
        return
    try:
        prs = json.loads(out) if out else []
    except json.JSONDecodeError:
        prs = []
    if not prs:
        r.flag("W18", f"branch {branch} is pushed with no pull request",
               f"gh pr create --head {branch}")
        return
    for pr in prs:
        if pr.get("state") != "OPEN":
            continue
        rollup = pr.get("statusCheckRollup") or []
        failing = [c.get("name", "?") for c in rollup
                   if c.get("conclusion") in {"FAILURE", "TIMED_OUT", "CANCELLED"}]
        if failing:
            r.flag("W19", f"PR #{pr['number']} is open with failing checks: "
                          f"{', '.join(failing[:4])}",
                   f"gh pr checks {pr['number']}")
        else:
            r.note(f"PR #{pr['number']} is open and not failing. Follow it to merged.")


def check_worktrees(r: Report) -> None:
    """W23. Every stale worktree is another tree a session can edit by mistake."""
    code, out = run(["git", "worktree", "list", "--porcelain"])
    if code != 0:
        return
    paths = [ln.split(" ", 1)[1] for ln in out.splitlines() if ln.startswith("worktree ")]
    # Only this session's worktrees are this session's problem. scripts/worktree_gc.py owns the
    # same session fence; the two must agree or the checker demands work it will not let you do.
    here = Path.cwd().resolve()
    mine_id = next((p for p in here.parts if len(p) == 36 and p.count("-") == 4), "")
    ours = [p for p in paths if not mine_id or mine_id in p]
    if len(ours) > 1:
        r.flag("W23", f"{len(ours)} worktree(s) belong to this session ({len(paths)} in the "
                      f"checkout in total)",
               ".venv/bin/python scripts/worktree_gc.py  # report, then --fix")


def check_claims(r: Report, local_only: bool) -> None:
    """W7. Two sessions run in this checkout at once, routinely, and neither can see the other's
    intent unless somebody wrote it down."""
    if local_only:
        return
    code, out = run(["gh", "issue", "list", "--label", "claimed", "--state", "open",
                     "--json", "number,title", "--limit", "20"])
    if code == 127:
        return
    try:
        issues = json.loads(out) if out else []
    except json.JSONDecodeError:
        return
    if issues:
        r.note(f"{len(issues)} issue(s) claimed by someone right now: "
               + "; ".join(f"#{i['number']} {i['title'][:48]}" for i in issues[:5]))
    else:
        r.note("no issues are labelled `claimed`. If your work spans more than one turn, claim it.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--local", action="store_true",
                    help="skip everything that needs the network")
    args = ap.parse_args()

    r = Report()
    check_uncommitted(r)
    check_unpushed(r)
    check_branch_has_pr(r, args.local)
    check_worktrees(r)
    check_claims(r, args.local)

    print(f"session check — branch {current_branch() or '?'}")
    print()
    if r.findings:
        print(f"OUTSTANDING ({len(r.findings)}):")
        for rule, what, fix in r.findings:
            print(f"  [{rule}] {what}")
            print(f"         -> {fix}")
        print()
    else:
        print("OUTSTANDING: nothing.")
        print()

    if r.notes:
        print("NOTES:")
        for n in r.notes:
            print(f"  {n}")
        print()

    # The two a machine cannot see. Printed every time, deliberately, because a checklist that
    # silently drops its hardest items reads as "all clear" when it is not.
    print("NOT CHECKED HERE, do them yourself:")
    print("  [W22] close every browser tab this session opened")
    print("  [W20] .venv/bin/python scripts/live_checkout.py   # is production running your code")
    print()
    print("The rules: docs/WAYS_OF_WORKING.md")
    return 1 if r.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
