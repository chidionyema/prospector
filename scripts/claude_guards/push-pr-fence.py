#!/usr/bin/env python3
"""Refuse to push a branch that already exists on origin and has no pull request.

WHY THIS EXISTS AND WHY THE OLD GUARD WAS NOT ENOUGH.

`branch-pr-guard.py` is a Stop hook. It fires after the push has already happened, once per
commit, and the session answers "deliberately not for review" and carries on. On 2026-08-18 the
founder found remote branches two weeks old that had been pushed to repeatedly with no pull
request, while that guard was installed and firing. A hook that reports after the fact is a nag.
This one sits on the push itself.

THE RULE.

  first push of a branch      allowed. This is how a branch gets created, and the PR cannot be
                              opened before the branch exists on the remote.
  later pushes, PR open       allowed. The work is visible; that was the whole point.
  later pushes, no PR         REFUSED. Open the pull request, then push again.
  push while its CI is live   REFUSED. See below.

THE SECOND RULE: DO NOT CANCEL THE RUN THAT WOULD HAVE MERGED IT.

Measured 2026-08-19 across the last 60 CI runs: 7 success, 16 failure, 16 cancelled. Twenty-two
pull requests sat open and nothing merged. `.github/workflows/automerge.yml` merges a PR the
moment its CI run concludes `success`, so a CANCELLED run merges nothing, ever. At that time
`.github/workflows/ci.yml` set `cancel-in-progress` for every ref that was not main, so ANY push
to a PR branch killed that branch's in-flight run.

THAT CAUSE IS FIXED AND THE FENCE IS STILL RIGHT. Measured 2026-08-20 on main, ci.yml:123-125 is
now `group: ci-${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: false`, and
that is the only such setting in the file -- a push no longer kills anything. What it does
instead is QUEUE: GitHub holds at most one pending run per group, so the new run waits out the
full length of a run that is grading a sha which is no longer the branch head. The python job
takes about 25 minutes. A branch touched more often than that still never produces a completed
run at its current head; the waste simply moved from a cancellation to a queue.

Do not read this refusal as evidence that cancel-in-progress needs fixing. It was fixed. Check
before you act on it: `gh api "repos/OWNER/REPO/contents/.github/workflows/ci.yml?ref=main"`.

Several agents share this estate and cannot see each other. Each one independently found "CI is
red", pushed a fix, and cancelled the run that was about to go green -- often a run carrying
another agent's fix. The work was not wrong. It kept resetting the clock.

So a push is refused while a CI run for that branch is queued or in progress. Wait for it. If the
run is genuinely stuck, or the push must go now, set PUSH_ANYWAY=1 in the environment.

So a branch may exist without a PR for exactly as long as it takes to open one, and no longer.
Accumulating commits on an invisible branch is what stops being possible.

NEVER FENCED.

  main                        the shared trunk
  archive/ backup/ rescue/    safety copies whose entire purpose is to hold work that is NOT
  salvage/ parked/ capture/   proposed for review. Requiring a PR for them would be nonsense.
  --delete / :refs/heads/     deleting a remote branch is cleanup, not hidden work
  --dry-run                   changes nothing

FAILING OPEN.

If `gh` is missing, unauthenticated, or the network is down, the PR state cannot be established
and the push is ALLOWED. A fence that blocks work when it cannot see is worse than the problem
it solves; the Stop-hook nag still catches those cases afterwards.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

EXEMPT_PREFIXES = ("archive/", "backup/", "rescue/", "salvage/", "parked/", "capture/")
#: `git push` with no refspec pushes the current branch; these forms name it explicitly.
REFSPEC = re.compile(r"^(?:\+)?(?:HEAD|refs/heads/[^:]+|[^:]+)?:(?:refs/heads/)?(?P<dst>[^:]+)$")


def run(*cmd: str, cwd: str) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return p.returncode, (p.stdout or "").strip()


def follow_cd(cwd: str, target: str) -> str:
    """Where a `cd` earlier in the SAME command block leaves the shell.

    The hook is handed the SESSION's cwd. Agents on this estate write
    `cd <worktree> && git push`, so the push runs in a different repository than the one the hook
    was told about. Measured 2026-08-20: this fence read the iCloud checkout, 113 commits behind
    main, and refused a push from a worktree that was 0 behind. It printed a real number about the
    wrong tree, so the refusal read as correct and there was no tell from the outside.

    An unreadable directory leaves the cwd alone, which is what the fence did before this existed.
    """
    target = os.path.expanduser(target)
    path = target if os.path.isabs(target) else os.path.join(cwd, target)
    return os.path.normpath(path) if os.path.isdir(path) else cwd


def git_c_dir(argv: list[str], cwd: str) -> str:
    """`git -C <dir> push` runs in <dir> whatever the shell cwd is. Same trap as `cd`."""
    for i, a in enumerate(argv):
        if a == "-C" and i + 1 < len(argv):
            return follow_cd(cwd, argv[i + 1])
    return cwd


def graded_tree(cwd: str) -> str:
    """The repository this refusal was computed in. Printed in every BLOCKED message.

    THE TRAP THIS CLOSES. The hook is handed the SESSION's cwd, but the Bash tool's shell keeps
    its own cwd BETWEEN calls. `cd ~/.hermes` in one call and `git push` in the next leaves this
    fence grading the session's repository for a push to a different one. `follow_cd` and
    `git_c_dir` only see a `cd` inside the SAME command, so neither can catch it.

    Measured 2026-08-20: a peer session pushing in `~/.hermes` (on main, 0 behind) was refused
    with "`ci/deploy-after-automerge` is 23 commit(s) behind origin/main" -- prospector's branch
    and prospector's main. Reproduced exactly: `target_branch(["git", "push"], <prospector>)`
    returns that same branch name. The number was real and the tree was wrong, and the message
    gave no tell, so the refusal read as correct and was argued with instead of spotted.

    This fence cannot see the shell's real cwd, so it cannot stop grading the wrong tree. What it
    can do is SAY which tree it graded, so a wrong one is obvious on sight. Same class as estate
    memory `bash-cwd-persists-making-greps-vacuous.md`.
    """
    c, out = run("git", "rev-parse", "--show-toplevel", cwd=cwd)
    return out if c == 0 and out else cwd


def commits_behind_main(cwd: str, branch: str | None = None) -> int | None:
    """How many commits origin/main has that the branch BEING PUSHED does not.

    None when it cannot tell, which makes the fence fail OPEN.

    The REMOTE is asked, not the local `origin/main` ref. A local ref that has not been fetched
    today reports 0 while the branch is a day stale, which is the exact failure this check exists
    to catch.

    THE TRAP THIS CLOSES. This used to count `HEAD..FETCH_HEAD`, and HEAD is whatever the SESSION's
    cwd happens to be checked out at -- which is not the tree the push comes from. Measured
    2026-08-20: a push of `guard/agent-editable-guards` from a worktree that was 0 behind was
    refused with "`guard/agent-editable-guards` is 24 commit(s) behind origin/main", because the
    session's cwd was a shared checkout sitting on an unrelated CI branch 24 behind. The branch
    NAME came from argv and the COUNT came from another tree's HEAD, so the message paired a real
    number with the wrong ref and read as correct.

    Worktrees share one ref store, so naming the branch fixes it across all of them: the count is
    now about the thing being pushed. HEAD stays the fallback for a push that names no branch.
    """
    if run("git", "fetch", "origin", "main", "--quiet", cwd=cwd)[0] != 0:
        return None
    ref = "HEAD"
    if branch and run("git", "rev-parse", "--verify", "--quiet",
                      branch + "^{commit}", cwd=cwd)[0] == 0:
        ref = branch
    c, out = run("git", "rev-list", "--count", ref + "..FETCH_HEAD", cwd=cwd)
    if c != 0 or not out.isdigit():
        return None
    return int(out)


def target_branch(argv: list[str], cwd: str) -> str | None:
    """The branch name this push would write on the remote, or None if it cannot be determined.

    `git push [remote] [refspec]`. The first bare word after `push` is the REMOTE, not a branch --
    reading it as one made every push look like a push to a branch called `origin`, which has no
    pull request and does not exist on the remote, so the fence passed everything.
    """
    words = [a for a in argv[argv.index("push") + 1:] if not a.startswith("-")]
    if words and ":" not in words[0]:
        words = words[1:]                   # drop the remote
    for a in words:
        m = REFSPEC.match(a)
        if m:
            return m.group("dst")
        if ":" not in a:
            return a
    c, out = run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    return out if c == 0 and out and out != "HEAD" else None


#: (argv, expected branch) for `target_branch`. This is where the fence's one real bug lived:
#: the first bare word after `push` is the REMOTE, and reading it as a branch made every push
#: look like a push to a branch called `origin` -- which has no PR and is not on the remote, so
#: the fence silently passed everything. A parser that fails this way looks identical to one
#: that works, because the hook fails OPEN by design.
SELFTEST_CASES: list[tuple[list[str], str | None]] = [
    (["git", "push", "origin", "my-branch"], "my-branch"),
    (["git", "push", "origin", "HEAD:my-branch"], "my-branch"),
    (["git", "push", "origin", "HEAD:refs/heads/my-branch"], "my-branch"),
    (["git", "push", "origin", "local-name:remote-name"], "remote-name"),
    (["git", "push", "origin", "+feature:feature"], "feature"),
    (["git", "push", "-u", "origin", "my-branch"], "my-branch"),
    (["git", "push", "--force-with-lease", "origin", "my-branch"], "my-branch"),
    (["git", "push", "origin", "archive/old-work"], "archive/old-work"),
    # The remote must never be returned as the branch. `origin` alone falls through to the
    # HEAD lookup, which cannot run in a directory that is not a repository, so: None.
    (["git", "push", "origin"], None),
    (["git", "push"], None),
]


def selftest_staleness() -> tuple[list[str], int]:
    """Prove `commits_behind_main` reports the three answers that decide the LAW 7 block.

    Offline: `origin` is a local directory, so `git fetch` is a file copy and no network is
    touched. A check that only ever returns the allow answer is not a check, so the stale case
    is built on purpose and asserted to be non-zero.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    def git(*a: str, cwd: str) -> None:
        subprocess.run(("git",) + a, cwd=cwd, capture_output=True, check=True)

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        origin, clone = str(Path(tmp) / "origin"), str(Path(tmp) / "clone")
        Path(origin).mkdir()
        git("init", "--initial-branch", "main", "-q", cwd=origin)
        git("config", "user.email", "t@t", cwd=origin)
        git("config", "user.name", "t", cwd=origin)
        (Path(origin) / "a").write_text("1")
        git("add", "a", cwd=origin)
        git("commit", "-qm", "one", cwd=origin)
        subprocess.run(("git", "clone", "-q", origin, clone), capture_output=True, check=True)
        git("config", "user.email", "t@t", cwd=clone)
        git("config", "user.name", "t", cwd=clone)
        git("checkout", "-qb", "work", cwd=clone)

        if commits_behind_main(clone) != 0:
            failures.append("  fresh branch: want 0 behind, "
                            f"got {commits_behind_main(clone)!r}")

        # main moves twice while the branch sits still -- the case the block exists to refuse.
        for n in ("2", "3"):
            (Path(origin) / "a").write_text(n)
            git("commit", "-qam", n, cwd=origin)
        if commits_behind_main(clone) != 2:
            failures.append("  stale branch: want 2 behind, "
                            f"got {commits_behind_main(clone)!r}")

        # ...and merging main is what clears it. This is the escape the message tells you to use.
        git("fetch", "origin", "main", "-q", cwd=clone)
        git("merge", "FETCH_HEAD", "-q", "--no-edit", cwd=clone)
        if commits_behind_main(clone) != 0:
            failures.append("  after merging main: want 0 behind, "
                            f"got {commits_behind_main(clone)!r}")

        # The branch being pushed is what gets counted, NOT the cwd's HEAD. Here HEAD is parked
        # two commits behind on an unrelated branch while `ready` is level with main -- the exact
        # shape of a worktree push graded against a shared checkout. Counting HEAD says 2 and
        # refuses a branch that is perfectly fresh.
        git("branch", "ready", "FETCH_HEAD", cwd=clone)
        git("checkout", "-q", "HEAD~2", cwd=clone)
        if commits_behind_main(clone, "ready") != 0:
            failures.append("  named branch: want 0 behind, "
                            f"got {commits_behind_main(clone, 'ready')!r}")
        if not commits_behind_main(clone):
            failures.append("  the cwd HEAD really is stale here, so this case proves nothing")

        # A branch name that does not resolve falls back to HEAD rather than crashing or
        # waving the push through.
        if commits_behind_main(clone, "no/such/branch") != commits_behind_main(clone):
            failures.append("  unknown branch: want the HEAD answer, "
                            f"got {commits_behind_main(clone, 'no/such/branch')!r}")

    # The call site must actually pass the branch. Mutating it back to `commits_behind_main(cwd)`
    # leaves every case above green, because they call the function directly and never exercise
    # the wiring -- a guard whose fix can be undone without a single test failing is not guarded.
    import ast as _ast
    import inspect as _inspect
    # Match the LIVE call specifically -- the one whose first argument is `cwd`. An earlier
    # version accepted any two-argument call and stayed green, because the cases above call
    # commits_behind_main(clone, "ready") themselves.
    _sites = [n for n in _ast.walk(
                  _ast.parse(_inspect.getsource(_inspect.getmodule(commits_behind_main))))
              if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
              and n.func.id == "commits_behind_main"
              and n.args and isinstance(n.args[0], _ast.Name) and n.args[0].id == "cwd"]
    if not _sites or not all(len(n.args) >= 2 for n in _sites):
        failures.append("  the LAW 7 block calls commits_behind_main without a branch, so it "
                        "grades the session cwd's HEAD instead of the branch being pushed")

    with tempfile.TemporaryDirectory() as empty:
        if commits_behind_main(empty) is not None:
            failures.append("  not a git repo: want None so the fence fails OPEN, "
                            f"got {commits_behind_main(empty)!r}")

    return failures, 8


def selftest() -> int:
    """Check the refspec parser against the shapes that were argued about when it was written.

    Only `target_branch` is covered. The rest of the fence asks git and gh about the live
    remote, and a selftest that needed a network round trip would not be run. Graded by
    `scripts/process_audit.py`, so a failure shows on the ops console.
    """
    import tempfile

    failures = []
    with tempfile.TemporaryDirectory() as empty:  # not a git repo: the HEAD fallback returns None
        for argv, want in SELFTEST_CASES:
            got = target_branch(argv, empty)
            if got != want:
                failures.append(f"  {' '.join(argv)}\n    want {want!r}, got {got!r}")

    # The exemption list must stay prefixes, not substrings: a branch called
    # `feat/backup-restore` is ordinary work and must NOT be waved through.
    for name, exempt in (("archive/old", True), ("backup/x", True), ("capture/y", True),
                         ("feat/backup-restore", False), ("main", False), ("fix/archive", False)):
        if name.startswith(EXEMPT_PREFIXES) is not exempt:
            failures.append(f"  exemption {name!r}: want exempt={exempt}")

    staleness_failures, staleness_total = selftest_staleness()
    failures += staleness_failures

    total = len(SELFTEST_CASES) + 6 + staleness_total
    if failures:
        print(f"push-pr-fence selftest: {len(failures)}/{total} FAILED")
        print("\n".join(failures))
        return 1
    print(f"push-pr-fence selftest: {total}/{total} passed")
    return 0


def live_ci_run(branch: str, cwd: str) -> tuple[str, str] | None | bool:
    """The queued or in-progress CI run for `branch`, if there is one.

    Returns (run id, status) when one is live, False when none is, and None when the answer
    cannot be established -- the caller fails OPEN on None, same as every other unknown here.

    Only ci.yml is consulted. The deploy and drill workflows do not gate a merge, and blocking a
    push on one of those would fence work for a run nothing is waiting on.
    """
    if os.environ.get("PUSH_ANYWAY"):
        return False
    c, out = run("gh", "run", "list", "--workflow", "ci.yml", "--branch", branch,
                 "--limit", "5", "--json", "databaseId,status", cwd=cwd)
    if c != 0:
        return None
    try:
        runs = json.loads(out or "[]")
    except json.JSONDecodeError:
        return None
    for r in runs:
        if r.get("status") in ("queued", "in_progress", "waiting", "requested", "pending"):
            return str(r.get("databaseId")), str(r.get("status"))
    return False


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    cwd = payload.get("cwd") or os.getcwd()

    for part in re.split(r"&&|\|\||;|\n", cmd):
        try:
            argv = shlex.split(part)
        except ValueError:
            continue
        if argv[:1] == ["cd"] and len(argv) > 1:
            cwd = follow_cd(cwd, argv[1])
            continue
        if len(argv) < 2 or argv[0] != "git" or "push" not in argv[:4]:
            continue
        cwd = git_c_dir(argv, cwd)
        if any(a in ("--delete", "-d", "--dry-run", "--tags") for a in argv):
            continue
        if any(a.startswith(":") or ":refs/heads/" in a and a.startswith(":") for a in argv):
            continue

        branch = target_branch(argv, cwd)
        if not branch or branch == "main" or branch.startswith(EXEMPT_PREFIXES):
            continue

        # LAW 7 -- refresh on main before you ask for review. A branch behind main is graded
        # against a world that no longer exists, so its gate fails naming files and tests that
        # have nothing to do with the change. Measured 2026-08-20: five failures on one branch,
        # three of them in a test file main had already deleted.
        if not os.environ.get("PUSH_ANYWAY"):
            behind = commits_behind_main(cwd, branch)   # None => cannot tell => fail open
            if behind:
                print(f"BLOCKED by push-pr-fence: `{branch}` is {behind} commit(s) behind "
                      f"origin/main.\n"
                      f"  graded in: {graded_tree(cwd)}\n"
                      f"  If that is not the repository you are pushing, the shell cd'd in\n"
                      f"  an EARLIER call and this hook was handed the session's cwd. Re-run\n"
                      f"  as ONE command: `cd <repo> && git push ...` or `git -C <repo> push`.\n"
                      f"LAW 7 -- refresh on main before you ask for review. Its gate would grade "
                      f"your code against a main that has moved, and the red it prints would name "
                      f"files your change never touched.\n"
                      f"  git merge origin/main --no-edit\n"
                      f"Merge it. NEVER rebase and force push: the remote moves by itself here, "
                      f"so a force push destroys work you never saw arrive.\n"
                      f"If this genuinely cannot wait: PUSH_ANYWAY=1 git push ...",
                      file=sys.stderr)
                return 2

        # First push of a branch is how it comes into existence -- always allowed.
        c, out = run("git", "ls-remote", "--heads", "origin", branch, cwd=cwd)
        if c != 0:
            return 0                       # cannot reach the remote: fail open
        if not out:
            continue                        # branch is not on origin yet

        c, out = run("gh", "pr", "list", "--head", branch, "--state", "open",
                     "--json", "number", cwd=cwd)
        if c != 0:
            return 0                       # gh unavailable or unauthenticated: fail open
        try:
            if json.loads(out or "[]"):
                # A pull request is open, so the work is visible. One thing left to check:
                # pushing now would cancel this branch's in-flight CI, and automerge.yml only
                # merges on a run that COMPLETES green.
                live = live_ci_run(branch, cwd)
                if live is None:
                    continue                # cannot tell: fail open
                if not live:
                    continue                # nothing running: push away
                rid, status = live
                print(
                    f"BLOCKED by push-pr-fence: CI run {rid} for `{branch}` is {status}.\n"
                    f"  graded in: {graded_tree(cwd)}\n"
                    f"Pushing does not cancel it any more -- ci.yml is `cancel-in-progress: "
                    f"false` on main as of 2026-08-20, so do NOT go and 'fix' that. Your run "
                    f"would QUEUE instead: GitHub holds one pending run per group, so it waits "
                    f"out the whole of a run that is grading a sha you have already replaced. "
                    f"The python job is about 25 minutes.\n"
                    f"And automerge.yml only merges a PR whose CI run CONCLUDES green, at the "
                    f"branch's CURRENT head.\n\n"
                    f"Watch it, then push when it lands:\n"
                    f"  gh run watch {rid}\n"
                    f"  gh run list --branch {branch} --limit 1\n\n"
                    f"If the run is stuck or this genuinely cannot wait: PUSH_ANYWAY=1 git push ...",
                    file=sys.stderr,
                )
                return 2
        except json.JSONDecodeError:
            return 0

        print(
            f"BLOCKED by push-pr-fence: `{branch}` is already on origin and has no open pull "
            f"request.\n"
            f"  graded in: {graded_tree(cwd)}\n"
            f"A branch may sit on the remote without a PR only for as long as it takes to open "
            f"one. Pushing more commits onto it makes work no one can see, which is how the "
            f"remote reached two-week-old branches nobody could account for.\n\n"
            f"Open it, then push again:\n"
            f"  gh pr create --base main --head {branch} --title ... --body ...\n\n"
            f"If it is deliberately not for review, name it with one of: "
            f"{', '.join(EXEMPT_PREFIXES)}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
