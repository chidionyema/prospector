#!/usr/bin/env python3
"""Refuse a push that lands directly on main.

WHY THIS EXISTS. Founder, 2026-08-19: "we need to protect main ourselves". Said on being told
that GitHub will not protect it for us -- this repo is private on a free plan, so both
protection endpoints answer 403:

    $ gh api repos/chidionyema/prospector/branches/main/protection
    {"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.",
     "status":"403"}

There is therefore NO server-side rule that main must be reviewed, or green, or reached through a
pull request. Every such rule in this estate is self-imposed, and until this file existed none of
them looked at a push:

    automerge.yml           merges only a run that concluded green -- but only on the paths it
                            drives. A push that goes straight to main never involves it.
    rule-guard.py           refuses `gh pr merge` and `PUT /pulls/N/merge` while checks are red.
                            A PreToolUse hook, so it reaches Claude sessions on this Mac and
                            nothing else.
    push-pr-fence.py        refuses a push while that branch's CI is still running, and skips
                            main by name: `if not branch or branch == "main": continue`.
    .githooks/pre-push      guarded protected-file deletion and dead branch names. It never
                            looked at where the push was going.

So a direct `git push origin main` passed every layer, and put code on main that no CI run had
ever tested. When main is red every open branch inherits the failure, which is the jam this
estate spent 2026-08-19 in: thirteen of seventeen open PRs red for three failures, none of them
in the PR that failed.

THE CLASS, not one command. Not "the string `git push origin main`" -- that is a spelling, and a
fence that names spellings loses to the next one. `HEAD:main`, `+main:main`, `main:refs/heads/main`
and a plain `git push` on a branch tracking main are four ways to type the same push, and there
are more. This guard never sees any of them. Git resolves every spelling BEFORE it calls the hook
and hands over the answer on stdin, one line per ref:

    <local ref> <local sha> <remote ref> <remote sha>

The third field is what the push actually writes. Matching it is exact and total: there is no
spelling of "push to main" that arrives with a different remote ref, so there is nothing to keep
up with.

IT CANNOT FAIL OPEN. The check is a string comparison on text git already handed us. No network
call, no `gh`, no subprocess -- so unlike the guards that ask GitHub a question, there is no state
in which it cannot see and has to choose between blocking honest work and waving a push through.
GitHub being down does not weaken it.

WHAT IS DELIBERATELY NOT COVERED. A merge made in the GitHub web interface, or from another
machine, or by a workflow. No local hook can see those. That half is server-side and is
`.github/workflows/main-green-guard.yml`, which reverts a main that goes red. Prevention here,
recovery there; neither is the whole answer alone.

THE HATCH IS REAL AND IS NAMED IN THE REFUSAL. `MAIN_PUSH_INTENDED=1` lets the push through.
It exists for the one case where the pull request path is genuinely shut: main is red, so
nothing can go green, so nothing can merge, and putting main back needs a direct push. A fence
with no hatch gets uninstalled, and an uninstalled fence guards nothing.
"""
from __future__ import annotations

import os
import sys

PROTECTED = "refs/heads/main"
OVERRIDE = "MAIN_PUSH_INTENDED"


def pushes_to_main(stdin_text: str) -> list[tuple[str, str, str]]:
    """(local_ref, local_sha, remote_sha) for every ref in this push that writes to main.

    Git's pre-push protocol gives four fields per line. Only the THIRD -- the remote ref -- says
    where the push lands, and it is compared for equality, never by prefix: `refs/heads/main` is
    protected and `refs/heads/maintenance` is an ordinary branch, and a `startswith` here would
    block the second while claiming to protect the first.

    A line that is not four fields is skipped rather than guessed at. Tags and every other ref
    namespace fall out of the same comparison, because a tag's remote ref is never this string.
    """
    out = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts
        if remote_ref != PROTECTED:
            continue
        out.append((local_ref, local_sha, remote_sha))
    return out


def is_deletion(local_sha: str) -> bool:
    """A local sha of all zeros means the push DELETES the remote ref."""
    return local_sha.strip("0") == ""


def main() -> int:
    if os.environ.get(OVERRIDE) == "1":
        return 0

    hits = pushes_to_main(sys.stdin.read())
    if not hits:
        return 0

    deleting = any(is_deletion(local_sha) for _lr, local_sha, _rs in hits)

    print("")
    if deleting:
        print("main-push guard BLOCKED: this push DELETES main.")
        print("Nothing in this estate needs that, and no plan restores it in one command.")
    else:
        print("main-push guard BLOCKED: this push writes straight to main.")
        print("It skips CI entirely. Code lands on main that no run has ever tested, and when")
        print("main is red every open branch inherits the failure -- so one bad push jams every")
        print("pull request in the repo, none of which caused it.")
    print("")
    print("GitHub is not going to catch this for us. Branch protection answers 403 on this plan:")
    print('    {"message":"Upgrade to GitHub Pro or make this repository public ...","status":"403"}')
    print("This hook is the protection.")
    print("")
    print("Do this instead:")
    print("    git checkout -B <a-branch-name>")
    print("    git push -u origin <a-branch-name>")
    print("    gh pr create --base main --fill")
    print("CI runs, and automerge.yml lands it once the run concludes green.")
    print("")
    print("If main is RED and the pull request path is genuinely shut, that is the one case this")
    print(f"hatch is for:   {OVERRIDE}=1 git push ...")
    return 1


if __name__ == "__main__":
    sys.exit(main())
