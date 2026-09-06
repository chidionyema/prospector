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

IT FIXES THE PUSH RATHER THAN JUST REFUSING IT. Founder, 2026-08-19: "the guard could auto fix
also". A refusal that hands back a four-line recipe is a chore, and a chore gets overridden. So the
guard pushes the same commits to a fresh name and opens a pull request on them, then refuses the
original push — the work is already safe under a name nobody has spent, and something is watching
it. Nothing is rewritten and nothing is deleted: the fix only ever ADDS a branch.

THE NEW PR IS A DRAFT, and that is the safety decision, not a hedge. This repo merges pull requests
by itself when CI goes green. A hook that opened an ordinary PR could therefore ship code straight
to main that no human asked to ship. Auto-merge does not fire on a draft, so the work is visible,
watched, and still waiting for a person. Marking it ready is one click.

The working tree is never touched. No checkout, no branch rename, no reset — the push is
`<sha>:refs/heads/<fresh-name>`, which needs no local branch at all. A hook that moved HEAD under a
running `git push` would be a worse bug than the one it fixes. `DEAD_BRANCH_NO_AUTOFIX=1` turns the
fix off and leaves the plain refusal.

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
NO_AUTOFIX = "DEAD_BRANCH_NO_AUTOFIX"
# The rescue push runs `git push` from inside a pre-push hook. `--no-verify` stops the hook
# re-entering itself; this variable is the belt to that brace, and it also lets the tests assert
# that the recursion fence is set rather than trusting a flag on a command line.
RECURSION = "_DEAD_BRANCH_AUTOFIX_RUNNING"


def created_pushes(stdin_text: str) -> list[tuple[str, str]]:
    """(branch, sha) for every branch this push would CREATE, from git's pre-push protocol.

    The sha is what the fix pushes. Deletions (local sha all zeros) and updates (remote sha set)
    are not our business. Tags are skipped: a tag is meant to be created, and there is no PR
    behind it.
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
        out.append((remote_ref[len("refs/heads/"):], local_sha))
    return out


def created_branches(stdin_text: str) -> list[str]:
    """Just the names. One parser behind both, so the two views cannot drift apart."""
    return [b for b, _sha in created_pushes(stdin_text)]


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


def _rescue_env() -> dict:
    env = dict(os.environ)
    env[RECURSION] = "1"
    return env


def fresh_name(branch: str, run=subprocess.run) -> str:
    """A name like the dead one but unspent: `feat/x` -> `feat/x-2`, then `-3`, and so on.

    A name is free only when BOTH answers agree: no branch on the remote, and no pull request that
    ever used it. Checking one of the two is how you land on a name a closed PR already burned,
    which is the failure being fixed.
    """
    for suffix in range(2, 20):
        candidate = f"{branch}-{suffix}"
        heads = run(["git", "ls-remote", "--heads", "origin", candidate],
                    capture_output=True, text=True, timeout=30, check=False)
        if heads.returncode != 0 or heads.stdout.strip():
            continue
        prs = run(["gh", "pr", "list", "--head", candidate, "--state", "all", "--limit", "1",
                   "--json", "number"], capture_output=True, text=True, timeout=30, check=False)
        if prs.returncode != 0 or json.loads(prs.stdout or "[]"):
            continue
        return candidate
    raise RuntimeError(f"no free name near '{branch}' after 18 tries")


def subject_of(sha: str, run=subprocess.run) -> str:
    """The commit subject, to title the PR. A generic title if git cannot say."""
    out = run(["git", "log", "-1", "--format=%s", sha], capture_output=True, text=True,
              timeout=30, check=False)
    subject = out.stdout.strip() if out.returncode == 0 else ""
    return subject or "work rescued from a spent branch name"


RESCUE_BODY = (
    "Opened by the dead-branch push guard.\n\n"
    "The original name `{branch}` belongs to a pull request that has already finished, so pushing "
    "it again would have put this work on a branch nobody is watching. These are the same "
    "commits, on a name that is free.\n\n"
    "It is a draft on purpose. This repo auto-merges on green, and a git hook must not be able to "
    "ship code. Mark it ready when you have looked at it.\n"
)


def open_pr_on_sha(sha: str, run=subprocess.run) -> tuple[str, str] | None:
    """An OPEN pull request whose head is exactly this sha: (branch, url). None when there is none.

    Measured 2026-08-26 on prospector: five families of identical draft PRs (#688 #693 #728 #739
    #744 were one set of commits) because every push of a dead name rescued the same sha again
    under the next free suffix. The suffix search asked "is this NAME free", never "are these
    COMMITS already open". Raises when gh cannot answer, for the reason finished_pr gives.
    """
    out = run(["gh", "pr", "list", "--state", "open", "--limit", "100",
               "--json", "headRefName,headRefOid,url"],
              capture_output=True, text=True, timeout=30, check=False)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gh pr list --state open exited non-zero")
    for row in json.loads(out.stdout or "[]"):
        if row.get("headRefOid") == sha:
            return str(row.get("headRefName", "")), str(row.get("url", ""))
    return None


def rescue(branch: str, sha: str, run=subprocess.run) -> tuple[str, str]:
    """Push these commits to a fresh name, open a DRAFT pull request. Returns (name, url).

    Additive only. It pushes a sha to a branch that does not exist, and never checks anything out,
    so a failure part way through leaves a branch with no PR rather than a damaged tree — and the
    caller then falls back to the plain refusal, which says what is where.

    Idempotent on the commits: when an open PR already carries this exact sha, that PR is the
    answer and nothing is pushed.
    """
    already = open_pr_on_sha(sha, run=run)
    if already is not None:
        return already
    name = fresh_name(branch, run=run)
    pushed = run(["git", "push", "--no-verify", "origin", f"{sha}:refs/heads/{name}"],
                 capture_output=True, text=True, timeout=180, check=False, env=_rescue_env())
    if pushed.returncode != 0:
        raise RuntimeError(pushed.stderr.strip() or "the rescue push failed")
    made = run(["gh", "pr", "create", "--draft", "--base", "main", "--head", name,
                "--title", subject_of(sha, run=run), "--body", RESCUE_BODY.format(branch=branch)],
               capture_output=True, text=True, timeout=120, check=False)
    if made.returncode != 0:
        raise RuntimeError(made.stderr.strip() or "gh pr create failed")
    lines = made.stdout.strip().splitlines()
    return name, lines[-1] if lines else ""


def main() -> int:
    if os.environ.get(OVERRIDE) == "1":
        return 0
    if os.environ.get(RECURSION) == "1":
        # The rescue push is itself a push. Without this the guard would inspect its own fix.
        return 0
    pushes = created_pushes(sys.stdin.read())
    if not pushes:
        return 0
    branches = [b for b, _sha in pushes]

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

    # The fix runs BEFORE anything is printed, so the message describes what actually happened
    # rather than what was about to be attempted. A partial rescue prints nothing but the manual
    # recipe: half a fix reported as a whole one is worse than no fix.
    shas = dict(pushes)
    fixed: list[tuple[str, str, str]] = []
    if os.environ.get(NO_AUTOFIX) != "1":
        for branch, _number, _state in dead:
            try:
                name, url = rescue(branch, shas[branch])
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                print(f"\ndead-branch guard: could not rescue '{branch}' automatically ({exc}).")
                fixed = []
                break
            fixed.append((branch, name, url))

    print("")
    for branch, number, state in dead:
        verb = "merged" if state == "merged" else "closed without merging"
        print(f"dead-branch guard BLOCKED: '{branch}' belongs to PR #{number}, {verb}.")
    print("This push does not update those PRs. It creates new branches with the old names,")
    print("and the work sits there with no PR open on it.")
    print("")

    if fixed:
        print("SO THE GUARD DID IT FOR YOU. The commits are pushed and a draft PR is open:")
        for branch, name, url in fixed:
            print(f"    {branch}  ->  {name}   {url}")
        print("")
        print("Nothing was rewritten and your working tree was not touched. The original push did")
        print("NOT happen, which is the point. To move your local branch onto the new name:")
        for branch, name, _url in fixed:
            print(f"    git branch -m {branch} {name} && git branch --set-upstream-to=origin/{name}")
        print("")
        print("The PR is a DRAFT because this repo auto-merges on green. Mark it ready yourself.")
        print("")
        # THE LAST LINE HAS TO BE THE ONE THAT SURVIVES A `tail`. git prints its own
        # "error: failed to push some refs" after this hook returns non-zero, and a caller that
        # pipes the push through `| tail -4` sees that error and the draft note and concludes the
        # push did nothing. It did: the commits are on GitHub and a PR is open. On 2026-08-21 that
        # misreading cost a duplicate PR (#603 and #604, same tip, two CI runs) because the agent
        # went and made a second branch by hand. So the summary is repeated last, with the URL.
        for _branch, name, url in fixed:
            print(f"ALREADY PUSHED AND OPEN, do not push again: {name}  {url}")
        return 1

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
