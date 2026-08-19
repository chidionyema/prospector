#!/usr/bin/env python3
"""Refuse a push that RECREATES a branch whose pull request is already finished.

THE CLASS, not the one branch that taught it: any branch name a merged OR closed PR has already
used. GitHub deletes the head branch when it merges; people delete it when they abandon a PR.
Either way the name is spent, and pushing it again lands work on a branch nobody is watching. An
OPEN PR on the same name is never blocked — that push updates the PR, which is the whole point.

The failure this exists to stop, measured on 2026-08-19. A session pushed to
`process/incident-loop`, the branch its PR had been opened from. That PR had already auto-merged
on green, and GitHub deletes the head branch on merge, so the push did not update anything — it
created a brand new branch that looked exactly like the old one. Git said so, quietly, in a line
nobody reads:

    remote: Create a pull request for 'process/incident-loop' on GitHub by visiting:

The work then sat on a branch with no PR, which is the one state that looks like progress and is
not. Rebasing it onto main conflicted as well, because the merged commits came back as a squash
and the originals were still in the branch.

The fence is mechanical because the tell is not readable. A push either creates a remote branch or
it does not, and git tells the hook which on stdin.

  <local ref> <local sha> <remote ref> <remote sha>

A remote sha of all zeros means "this push creates the branch". That is the only case checked, so
the normal push — updating a branch that exists — costs nothing and makes no network call.

WHEN `gh` CANNOT ANSWER, THIS BLOCKS. A guard that waves the push through whenever it cannot check
is a warning, and a warning is not a fence. The escape hatch is named in the message and is one
environment variable, because a deliberate re-creation is a real thing to want.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ZERO = "0" * 40
OVERRIDE = "ALLOW_BRANCH_RECREATE"


def created_branches(stdin_text: str) -> list[str]:
    """The branch names this push would CREATE on the remote, from git's pre-push protocol.

    Deletions (local sha all zeros) and updates (remote sha set) are not our business. Tags are
    skipped: a tag is meant to be created, and there is no PR behind it.
    """
    out = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, remote_ref, remote_sha = parts
        if local_sha.strip("0") == "" or remote_sha.strip("0") != "":
            continue
        if not remote_ref.startswith("refs/heads/"):
            continue
        out.append(remote_ref[len("refs/heads/"):])
    return out


def finished_pr(branch: str) -> tuple[int, str] | None:
    """A PR that is DONE WITH this branch name — merged or closed — or None. Raises if gh cannot
    answer.

    Merged and closed are the same problem, which is why one query covers both. GitHub deletes the
    head branch on merge; a human deletes it when they close a PR they abandoned. Either way the
    name is spent, and pushing it again puts work on a branch nobody is watching. An OPEN PR is
    the normal case and is never blocked — that push updates the PR, which is the point.

    Raising rather than returning None is the point: "no finished PR" and "I could not look" are
    different answers, and collapsing them is how a fence becomes a suggestion.
    """
    proc = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "all", "--limit", "20",
         "--json", "number,state"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "gh exited non-zero")
    rows = json.loads(proc.stdout or "[]")
    # An OPEN PR on this name wins over any finished one: the branch was recreated and a PR is
    # already watching it, so the work is not stranded and there is nothing to refuse.
    if any(str(r.get("state", "")).upper() == "OPEN" for r in rows):
        return None
    for row in rows:
        state = str(row.get("state", "")).upper()
        if state in ("MERGED", "CLOSED"):
            return int(row["number"]), state.lower()
    return None


def main() -> int:
    if os.environ.get(OVERRIDE) == "1":
        return 0
    branches = created_branches(sys.stdin.read())
    if not branches:
        return 0

    # Every created branch is judged before anything is printed. Stopping at the first dead one
    # hides the others, so a `git push --all` gets fixed one refusal at a time.
    dead: list[tuple[str, int, str]] = []
    for branch in branches:
        try:
            found = finished_pr(branch)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            print(f"\ndead-branch guard BLOCKED: cannot ask GitHub about '{branch}' ({exc}).")
            print("This push would CREATE that branch. If the branch was deleted by a merge, the")
            print("push lands work on a branch with no PR and nobody notices.")
            print(f"Check it yourself, then: {OVERRIDE}=1 git push ...")
            return 1
        if found is not None:
            dead.append((branch, found[0], found[1]))

    if not dead:
        return 0

    print("")
    for branch, number, state in dead:
        verb = "merged" if state == "merged" else "closed without merging"
        print(f"dead-branch guard BLOCKED: '{branch}' belongs to PR #{number}, {verb}.")
    print("This push does not update those PRs. It creates new branches with the old names,")
    print("and the work sits there with no PR open on it.")
    print("")
    print("Do this instead:")
    print("    git fetch origin main")
    print("    git checkout -B <a-new-name> origin/main")
    print("    git cherry-pick <your commits>")
    print("    git push -u origin <a-new-name> && gh pr create")
    print("")
    print(f"If you really mean to recreate it: {OVERRIDE}=1 git push ...")
    return 1


if __name__ == "__main__":
    sys.exit(main())
