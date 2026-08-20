#!/usr/bin/env python3
"""PreToolUse guard: turn written rules into refusals.

WHY THIS EXISTS
---------------
On 2026-08-17 the founder asked whether the rules we enforce are working. Measured:

  13 hook scripts installed, and exactly ONE of them can block anything (hang-guard.py,
  about unbounded greps). Every other hook measures cost, accounts for context, or injects
  memory. There was no guard anywhere about commits, diffs, PRs or claims.

  333 memory files, two of which describe the exact diff-direction mistake made twice that
  same session, with the memory loaded in context both times.

So the conclusion is not "write the rule down more clearly". A rule that is READ does not
stop anything; a rule that RUNS does. This file is where a rule becomes a refusal.

HOW IT FAILS
------------
Open. Any exception, any unparseable payload, any git failure -> exit 0 and the command
proceeds. There are ~18 Claude processes against this estate, and a guard that wedges them
all is a worse outage than any rule it enforces.

EVERY RULE HAS AN ESCAPE
------------------------
Each rule names a marker you can add to the command to proceed anyway. That is deliberate:
the guard's job is to stop a mistake made by ACCIDENT, and to force the intent to be stated
out loud when it is not an accident. A rule with no escape gets disabled the first time it
is wrong, and then it protects nothing.

ADDING A RULE
-------------
Add a function to RULES. It takes the command string and returns a refusal message or None.
Then add a case to selftest(). `python3 rule-guard.py --selftest` must pass before wiring.
A rule with no selftest case is not a rule; it is a comment.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

REPO = "/Users/chidionyema/Documents/code/prospector"

#: The tree the command being judged will actually run in. A hardcoded REPO graded the shared
#: checkout's branch even when the work was in a worktree, so an 8-file PR could be refused for
#: a diff it had nothing to do with. The only way past was the override marker, which teaches
#: you to wave the guard through.
_ACTIVE_REPO = REPO

#: A command that starts by changing directory is telling you where it runs. Nothing else in the
#: payload does: `cwd` is the SESSION's directory, which for a worktree session is the wrong one.
_LEADING_CD = re.compile(r"""(?:^|[\n;&|]\s*)cd\s+(?P<path>'[^']+'|"[^"]+"|[^\s;&|]+)""")


def _worktree_root(path: str) -> str | None:
    """`path` resolved to the top of its git worktree, or None when it is not in one."""
    if not path or not os.path.isdir(path):
        return None
    rc, out = _git("rev-parse", "--show-toplevel", cwd=path)
    return out.strip() if rc == 0 and out.strip() else None


#: `SP=/long/path` then `cd "$SP/wt-prune"` is how a long scratchpad path gets used, and an
#: unexpanded `$SP` resolves to no directory at all -- so the cd was ignored and the SESSION's
#: repo was graded instead. On 2026-08-17 that refused a 1-file PR as "243 files", quoting the
#: shared checkout's branch, and the only way past was the override marker. Expanding the plain
#: assignments the command makes to itself is enough; no shell is invoked.
_ASSIGN = re.compile(r"""(?:^|[\n;&]\s*)(?P<name>[A-Za-z_]\w*)=(?P<val>'[^']*'|"[^"]*"|[^\s;&|]+)""")


def _expand(text: str, cmd: str) -> str:
    """`$VAR` and `${VAR}` in `text`, filled from assignments made earlier in `cmd`."""
    for m in _ASSIGN.finditer(cmd):
        val = m.group("val").strip("'\"")
        text = text.replace("${" + m.group("name") + "}", val).replace("$" + m.group("name"), val)
    return text


def _repo_for(cmd: str, session_cwd: str | None) -> str:
    """The worktree this command runs in. Falls back to REPO, so behaviour never gets worse."""
    for m in _LEADING_CD.finditer(cmd):
        root = _worktree_root(_expand(m.group("path").strip("'\""), cmd))
        if root:
            return root
    return _worktree_root(session_cwd or "") or REPO


def _sh(argv: list[str], timeout: int = 20) -> tuple[int, str]:
    """Run any CLI and return (rc, combined output). Never raises; rc != 0 means "cannot tell"."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    cwd = cwd or _ACTIVE_REPO
    try:
        p = subprocess.run(("git", *args), cwd=cwd, capture_output=True,
                           text=True, timeout=20)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _escape(marker: str) -> str:
    return (f"\n\nIf you mean it, append  # {marker}  to the command and say in your reply "
            f"why this case is different.")


# ---------------------------------------------------------------- rules

_ADD_ALL_RE = re.compile(r"\bgit\s+(?:-\S+\s+|--\S+(?:=\S+)?\s+)*add\s+(?:-A\b|--all\b|\.(?:\s|$))")


def rule_add_all(cmd: str) -> str | None:
    """`store/` and `storage/` are TRACKED runtime state that pytest writes to.

    `git add -A` here stages whatever the test suite happened to leave behind. The rule has
    been in CLAUDE.md for months and is restated in every handoff, which is how we know
    restating it does not work."""
    if "add-all-intended" in cmd:
        return None
    if _ADD_ALL_RE.search(cmd):
        return ("BLOCKED by rule-guard: `git add -A` / `git add .` in this estate.\n"
                "store/ and storage/ are tracked runtime state that pytest writes to, so this "
                "stages another process's test output.\n"
                "Stage explicit paths instead:  git add -- path/one path/two"
                + _escape("add-all-intended"))
    return None


# `[^|;&]*` also crosses NEWLINES, so in a multi-line script it scanned past the end of the
# commit and matched a `-n` on any later line — `rg -n`, `tail -n`, `sort -n`. Measured
# 2026-08-19: a `git commit` followed three lines later by `rg -n` was refused as
# `--no-verify`. A guard that blocks correct commands is a guard sessions learn to route
# around, so the line terminators are excluded too.
_NO_VERIFY_RE = re.compile(r"\bgit\s+commit\b[^|;&\n\r]*(?:--no-verify\b|\s-n\b)")


def rule_no_verify(cmd: str) -> str | None:
    """Skipping the gate is a decision, not a convenience."""
    if "no-verify-intended" in cmd:
        return None
    if _NO_VERIFY_RE.search(cmd):
        return ("BLOCKED by rule-guard: `git commit --no-verify`.\n"
                "The permission classifier has refused this twice already. Use the isolated "
                "worktree, or state why the gate must be skipped."
                + _escape("no-verify-intended"))
    return None


_LOCK_RE = re.compile(r"\brm\b[^|;&]*index\.lock")


def rule_index_lock(cmd: str) -> str | None:
    """That lock is another session's live commit, not litter."""
    if "lock-removal-intended" in cmd:
        return None
    if _LOCK_RE.search(cmd):
        return ("BLOCKED by rule-guard: removing .git/index.lock.\n"
                "Sessions share one index here. That lock is another session's commit in "
                "progress; deleting it corrupts their commit. Queue and wait."
                + _escape("lock-removal-intended"))
    return None


_DIFF_RE = re.compile(r"\bgit\s+diff\b([^|;&]*)")
#: A word that could be a ref. Naming specific branches here made the rule expire with them, so
#: the shape is checked first and git is asked second (`_is_ref`), which names nothing.
_REFISH = re.compile(r"^[\w.][\w.\-/+]*$")


def _is_ref(word: str) -> bool:
    """True when git resolves `word` to a commit. Cheap, and it cannot go stale."""
    if not _REFISH.match(word) or os.path.exists(os.path.join(_ACTIVE_REPO, word)):
        return False  # a path that looks like a ref is a path
    rc, _ = _git("rev-parse", "--verify", "--quiet", word + "^{commit}")
    return rc == 0


def rule_two_dot_diff(cmd: str) -> str | None:
    """A two-point diff against a branch that has MOVED is not a merge outcome.

    `git diff origin/main branch` answers "how do these two trees differ", and every line
    main gained since the fork shows up as a deletion. Read as "merging this deletes 23,000
    lines", which is what happened on 2026-08-17 — twice, with two memories about it already
    written."""
    if "raw-diff-intended" in cmd or "merge-base" in cmd or "..." in cmd:
        return None
    for tail in _DIFF_RE.findall(cmd):
        words = [w for w in tail.split() if not w.startswith("-")]
        if "--" in tail.split():
            words = tail.split()[:tail.split().index("--")]
            words = [w for w in words if not w.startswith("-")]
        refs = [w for w in words if _is_ref(w)]
        if len(refs) >= 2 and ".." not in tail:
            return (f"BLOCKED by rule-guard: two-point `git diff {' '.join(refs[:2])}`.\n"
                    "Against a branch that has moved, this is NOT what a merge would do — every "
                    "line the other side gained since the fork prints as a deletion.\n"
                    "For what a merge applies:  git diff $(git merge-base A B) B\n"
                    "For whether it conflicts:  git merge-tree --write-tree A B"
                    + _escape("raw-diff-intended"))
    return None


#: A PR bigger than this is not the small fix its title claims. #247 was 198 files.
PR_FILE_CEILING = 40


def rule_pr_size(cmd: str) -> str | None:
    """A PR whose diff is 40x its title is how a fix branch smuggles a whole integration in.

    PRs #247 and #248 were announced as a 5-file glossary change and an 18-file fix. Their
    merge base was 37 commits stale, so each actually carried 198 files and the entire
    integration branch. Nobody looked, because nothing made them look."""
    if "gh pr create" not in cmd or "large-pr-intended" in cmd:
        return None
    m = re.search(r"--base[= ]+(\S+)", cmd)
    base = m.group(1).strip("\"'") if m else "main"
    rc, head = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or not head:
        return None
    rc, mb = _git("merge-base", f"origin/{base}", "HEAD")
    if rc != 0 or not mb:
        return None
    rc, out = _git("diff", "--name-only", mb, "HEAD")
    if rc != 0:
        return None
    files = [ln for ln in out.splitlines() if ln.strip()]
    if len(files) <= PR_FILE_CEILING:
        return None
    rc, stat = _git("diff", "--shortstat", mb, "HEAD")
    return (f"BLOCKED by rule-guard: this PR is {len(files)} files, ceiling is "
            f"{PR_FILE_CEILING}.\n"
            f"  base            origin/{base}\n"
            f"  merge base      {mb[:12]}\n"
            f"  what it applies {stat}\n"
            "A branch this size is usually a stale base carrying somebody else's history, not "
            "the change in your title. Rebase onto the current base, or say what the size is "
            "for in the PR body."
            + _escape("large-pr-intended"))


#: Directories the ENGINE writes while it runs. Staging them puts a day of ledger churn in the
#: diff, which is how a branch reaches hundreds of files with only a handful of them code.
#: Stopping it at the `git add` is cheaper than stripping it out afterwards.
_RUNTIME_PREFIXES = ("store/", "storage/", "signals/", "corpora/", "graphify-out/",
                     ".popdd/", ".backfill-logs/", ".lux/receipts/", "scratchpad/")

#: Quoted text is a commit MESSAGE, not a path. `git commit -m "rotate store/prospector.jsonl"`
#: names the file in prose and stages nothing; firing on it would be the rule crying wolf on the
#: exact commit that fixes the problem.
_QUOTED = re.compile(r"""'[^']*'|"[^"]*\"""")
_GIT_STAGING = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)*(?:add|commit)\b")


def rule_runtime_state(cmd: str) -> str | None:
    if "runtime-state-intended" in cmd or not _GIT_STAGING.search(cmd):
        return None
    scan = _QUOTED.sub(" ", cmd)
    hits = sorted({p for p in _RUNTIME_PREFIXES
                   if re.search(rf"(?:^|[\s=]){re.escape(p)}\S", scan)})
    if not hits:
        return None
    return ("BLOCKED by rule-guard: this stages runtime state, not code.\n"
            f"  paths            {', '.join(hits)}\n"
            "  why              the engine rewrites these every tick, so this puts a day of\n"
            "                   ledger churn in your diff\n"
            "Name the code paths explicitly: git commit --only -m 'msg' -- path/one.py path/two.py"
            + _escape("runtime-state-intended"))


_GIT_COMMIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)*commit\b")


def _shared_checkout_refusal(active_repo: str, branch: str) -> str | None:
    """REFUSE a commit made in the shared checkout on a named branch.

    The invariant: only a task worktree sits on a task branch, and every long-lived checkout sits
    on main. Several sessions share this tree and its index, so a commit here lands on whatever
    branch the last session left behind, and that branch grows without anyone choosing it.

    This was a NOTE until 2026-08-17 and a note was worth nothing. `integrate/minimax-into-main`
    took 105 commits and 743 lines of uncommitted work in this checkout, on one disk, with no
    remote for part of that time. Sessions saw the note, appended `shared-checkout-intended`, and
    committed anyway -- so the branch kept growing and the founder had to be the one who noticed,
    twice. A fence every caller can wave past is not a fence. It refuses now.

    The branch name is read to SHOW it, never to decide. A rule that knows one branch's name is
    dead the day that branch is.
    """
    if os.path.realpath(active_repo) != os.path.realpath(REPO):
        return None  # already in a worktree, which is the point
    if branch in ("HEAD", ""):
        return None  # detached: nothing accumulates
    return (f"BLOCKED by rule-guard: commit into the SHARED checkout, on `{branch}`.\n"
            f"  {REPO}\n"
            "  invariant        work happens in a task worktree; this checkout tracks main\n"
            "  why              several sessions share this tree and its index, so the branch\n"
            "                   grows without anyone choosing it, on one disk, with no PR\n"
            "  instead          git worktree add --detach ../wt-<name> origin/main\n"
            "                   ./scripts/setup_worktree.sh ../wt-<name>\n"
            "                   then commit THERE and open a PR"
            + _escape("shared-checkout-intended"))


def rule_commit_in_shared_checkout(cmd: str) -> str | None:
    if "shared-checkout-intended" in cmd or not _GIT_COMMIT.search(cmd):
        return None
    rc, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return None  # fail open, always
    return _shared_checkout_refusal(_ACTIVE_REPO, branch.strip())


#: Every way a merge is actually typed here. The REST endpoint was added on 2026-08-18: the fence
#: matched only `gh pr merge`, so `gh api -X PUT .../pulls/324/merge` walked straight past it.
#: PR #324 was merged that way at 07:01:13 with `python` still running; the merge then cancelled
#: that run at 07:01:58 and `ci-ok` concluded failure at 07:02:13 -- the same shape as #315, an
#: hour after #315 was cleaned up. A fence that names one spelling of the command is not a fence.
_GH_MERGE = re.compile(r"\bgh\s+pr\s+merge\b|/pulls/\d+/merge\b")
_GH_MERGE_NUM = re.compile(r"\bgh\s+pr\s+merge\s+(?:--?\S+(?:=\S+)?\s+)*?(\d+)\b"
                           r"|/pulls/(\d+)/merge\b")

#: States meaning the job has not finished. Merging on one of these is how three of main's four
#: runs on 2026-08-17 were cancelled: each merge landed while the previous run was still queued,
#: and GitHub keeps at most ONE run pending per concurrency group, so the next one evicted it.
_PENDING_STATES = {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED"}

#: States that count as green. SKIPPED and NEUTRAL belong here: a path filter deciding the web
#: lane is not needed for a Python-only diff is a real answer, not a missing one.
_OK_STATES = {"SUCCESS", "SKIPPED", "NEUTRAL"}


def _merge_refusal(pr: str, states: list[tuple[str, str]] | None) -> str | None:
    """Refuse `gh pr merge <pr>`? Pure, given the checks, so the decision is testable offline.

    `states` is (check name, state) pairs, or None when they could not be read at all.
    """
    if states is None:
        return (f"BLOCKED by rule-guard: could not read the CI checks for PR #{pr}.\n"
                "  why              a merge is the one irreversible step here, so an unknown\n"
                "                   verdict is treated as a red one, not waved through\n"
                "  instead          gh pr checks " + pr + _escape("merge-red-intended"))
    if not states:
        return (f"BLOCKED by rule-guard: PR #{pr} has NO checks at all.\n"
                "  why              main ran commit 5b8d010 in production on 2026-08-17 with\n"
                "                   zero finished runs; 'no checks' looked identical to green\n"
                "  instead          push a commit that triggers CI, or wait for the run to\n"
                "                   register, then re-read: gh pr checks " + pr
                + _escape("merge-red-intended"))

    waiting = [n for n, s in states if s.upper() in _PENDING_STATES]
    red = [f"{n}={s.lower()}" for n, s in states
           if s.upper() not in _OK_STATES and s.upper() not in _PENDING_STATES]
    if red:
        return (f"BLOCKED by rule-guard: PR #{pr} is not green — {', '.join(red[:6])}.\n"
                "  why              nothing on GitHub stops this: branch protection needs a\n"
                "                   paid plan or a public repo, so this hook is the only fence\n"
                "  instead          fix the failure, or merge the fix for it first\n"
                "  note             `gh pr checks --watch` exits 0 even when jobs failed, so\n"
                "                   read the states, never the exit code\n"
                "  no override      `merge-red-intended` does not open this one. A check that\n"
                "                   finished and did not pass is an answer, not an outage.")
    if waiting:
        return (f"BLOCKED by rule-guard: PR #{pr} still has {len(waiting)} check(s) running — "
                f"{', '.join(waiting[:6])}.\n"
                "  why              merging now cancels main's queued run: GitHub keeps one\n"
                "                   run pending per concurrency group and evicts the waiter\n"
                "  instead          wait for it, then re-read: gh pr checks " + pr
                + "\n  no override      `merge-red-intended` does not open this one.")
    return None


def _failed_jobs(run_id: str) -> list[str]:
    """Names of the jobs in `run_id` that concluded FAILURE. Empty when none, or unreadable.

    `ci-ok` is excluded because it is an aggregator, not a measurement. It reads its needs\'
    results and fails when any of them is not `success` or `skipped`, so a CANCELLED job makes
    it fail. Counting it here would re-create the exact false red this function exists to
    remove: run 32109476818 was cancelled with zero lane failures, and ci-ok alone still
    reported failure. A real breakage always shows up as a failed LANE job.

    Read through the REST API deliberately. `gh run view` and `gh pr` go through GraphQL, which
    this repo's token cannot use (`Resource not accessible by integration`, HTTP 403), while the
    same token reads REST fine. Measured 2026-08-18 inside one run: eleven REST calls succeeded
    and the single GraphQL call 403ed.
    """
    try:
        p = subprocess.run(
            ("gh", "api", f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs?per_page=100",
             "--jq", '.jobs[] | select(.conclusion == "failure") | select(.name != "ci-ok") | .name'),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _main_red_refusal() -> str | None:
    """Is main's own last finished CI run red? Returns the refusal text, or None.

    Fails OPEN, unlike the PR check above. The PR's own verdict already fails closed, so a second
    closed fence on an unreadable answer would wedge every merge on a GitHub hiccup. This one only
    ever adds a refusal it can prove.
    """
    try:
        p = subprocess.run(
            ("gh", "run", "list", "--branch", "main", "--workflow", "ci.yml",
             "--status", "completed", "--limit", "1",
             "--json", "conclusion,databaseId,headSha",
             "--jq", '.[] | "\\(.conclusion)\\t\\(.databaseId)\\t\\(.headSha)"'),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    row = p.stdout.strip().split("\t")
    if p.returncode != 0 or len(row) != 3 or row[0].upper() in ("SUCCESS", "SKIPPED", "NEUTRAL"):
        return None
    conclusion, run_id, sha = row

    # A run-level conclusion is not a verdict on the code. `cancelled` in particular measures
    # NOTHING: until 2026-08-18 ci.yml carried `cancel-in-progress: true` unconditionally, and
    # `github.ref` is `refs/heads/main` on every push to main, so every merge cancelled main's own
    # in-flight verification. 38 of main's last 94 CI runs are cancelled for that one reason. This
    # fence read the newest of them as "main is red" and refused every merge -- including the
    # merge that fixes it. A fence that cannot be satisfied is an outage, not a fence.
    #
    # Grade the JOBS instead. A job that concluded `failure` is a measurement and still blocks,
    # even inside a cancelled run. A cancelled run with no failed job is an absence of evidence.
    failed = _failed_jobs(run_id)
    if not failed:
        return None
    conclusion = f"{conclusion.lower()}, with {', '.join(failed)} failed"
    return (f"BLOCKED by rule-guard: main's own last CI run is {conclusion} "
            f"(run {run_id}, {sha[:7]}).\n"
            "  why              a merge onto a red main inherits the breakage and hides it\n"
            "                   behind its own red. On 2026-08-18 that turned one bad squash\n"
            "                   into 23 failures on every open pull request for five hours\n"
            "  instead          merge the fix for main FIRST, then come back to this one\n"
            "  override         append `# main-is-red` when THIS merge is that fix")


def _merge_verdict(pr: str, states: list[tuple[str, str]] | None,
                   escaped: bool, main_red: str | None, fixing_main: bool) -> str | None:
    """The whole merge decision, pure, so every branch of it is tested offline.

    Two fences, in order. The PR's own checks decide first, and `merge-red-intended` opens
    exactly one of those outcomes: `states is None`, which is GitHub not answering. A check that
    finished and did not pass is an answer.

    Then main's own last CI run. Merging onto a red main is how one bad commit became twenty-three
    failures on every open pull request: each merge inherits the breakage and hides it behind its
    own red, so nobody can tell whose fault it is. `main-is-red` is the marker for the merge that
    fixes it, and it says out loud what is being done.
    """
    refusal = _merge_refusal(pr, states)
    if refusal is not None:
        if escaped and states is None:
            return None    # the outage case, deliberately overridden
        return refusal
    if main_red and not fixing_main:
        return main_red
    return None


def _pr_check_states(pr: str) -> list[tuple[str, str]] | None:
    """(name, state) for every check on `pr`, or None if the query itself failed."""
    try:
        p = subprocess.run(
            ("gh", "pr", "checks", pr, "--json", "name,state",
             "--jq", '.[] | "\\(.name)\\t\\(.state)"'),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    # `gh pr checks` exits 8 when checks are still pending and 1 when some failed, so the exit
    # code alone cannot separate "query worked, PR is red" from "query broke". Trust stdout:
    # rows parsed means the query worked.
    rows = [ln.split("\t", 1) for ln in p.stdout.splitlines() if "\t" in ln]
    if rows:
        return [(a, b) for a, b in rows]
    # No rows and a clean exit means a PR with no checks registered — a real, dangerous answer.
    return [] if p.returncode == 0 else None


def rule_merge_red_pr(cmd: str) -> str | None:
    """The merge is the irreversible step, so it is the one worth fencing.

    On 2026-08-17 four merges landed on main in 25 minutes. Three cancelled each other's CI and
    the fourth concluded failure, and the follower shipped the result to production inside 60
    seconds. Every control that should have stopped that is unavailable on this plan: both
    `/branches/main/protection` and `/rulesets` return 403 "Upgrade to GitHub Pro or make this
    repository public". So the fence has to live where the command is typed.

    Fails CLOSED. An unreadable verdict blocks, because failing open is precisely what let an
    untested commit reach production; the escape marker is there for a real GitHub outage.
    """
    if not _GH_MERGE.search(cmd):
        return None
    # The marker is read AFTER the checks now, and it no longer covers a check that finished
    # and did not pass. On 2026-08-18 PR #315 was merged with `python` cancelled and `ci-ok`
    # failed, on the argument that those checks were structurally impossible rather than red.
    # Its branch carried a stale copy of scripts/live_checkout.py, so the squash deleted 115
    # lines that #286 had added an hour earlier. main was red for 23 tests for the next five
    # hours and every open pull request inherited them. The hatch exists for a GitHub outage,
    # which is the `states is None` case. A concluded FAILURE or CANCELLED is not an outage.
    escaped = "merge-red-intended" in cmd
    m = _GH_MERGE_NUM.search(cmd)
    if m:
        pr = m.group(1) or m.group(2)    # `gh pr merge N` or `/pulls/N/merge`
    else:
        rc, out = _git("rev-parse", "--abbrev-ref", "HEAD")
        if rc != 0:
            return None  # no branch to resolve a PR from; not our call to block
        try:
            p = subprocess.run(("gh", "pr", "view", "--json", "number", "--jq", ".number"),
                               cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        pr = p.stdout.strip()
        if not pr.isdigit():
            return None
    return _merge_verdict(pr, _pr_check_states(pr), escaped,
                          _main_red_refusal(), "main-is-red" in cmd)


#: Rules that REFUSE the command. Each one matches on what the command does — a flag, a path — so
#: it stays true whatever the repo's branches are called.
# --- CI autoscale: switched OFF on 2026-08-19 by founder decision, and kept off ------------
#
# WHY. `.github/workflows/ci-autoscale.yml` landed on main as dad8cb7c (#396) at 13:15Z. It
# calls `deploy/runners.sh autoscale`, whose scale-down loop reads the GitHub busy-runner list
# with `|| true`. secrets.GITHUB_TOKEN cannot read that endpoint (it needs repo ADMIN), so the
# list came back EMPTY, every started machine read as idle, and the loop stopped machines that
# were mid-build. Measured: machine 8ee06eb7701628 got `stop stopping` at 14:50:51Z and
# `crash stopped requested_stop=True` at 14:51:58Z while it was 15 minutes into PR #425's python
# job. Nine PRs died the same way (#383 #387 #390 #391 #407 #414 #424 #427 #431), each with
# step 6 concluding `null` and the annotation "The self-hosted runner lost communication with
# the server" — which is indistinguishable from a failing test unless you read the annotation.
# #396's OWN merge commit was one of the casualties, so main went red on the commit that
# introduced the autoscaler and stayed red.
#
# Founder, 2026-08-19: "we cant have autoscaling until we are confident that machines that are
# spun up are reliable" and "ensure it cant be reenabled by accident".
#
# The workflow is disabled at GitHub (`gh workflow disable 337731742`) and deleted from the
# repo. This rule is the third layer: a machine refusal that reaches every agent on this box,
# because the first two live in places a single command can undo.
_AUTOSCALE_ENABLE_RE = re.compile(
    r"\bgh\s+workflow\s+enable\b[^|;&\n]*(?:337731742|ci-autoscale|CI\s+autoscale)")
_AUTOSCALE_RUN_RE = re.compile(r"runners\.sh\s+autoscale\b")
_FLY_STOP_CI_RE = re.compile(r"\bfly\s+machine[s]?\s+stop\b[^|;&\n]*prospector-ci")


def rule_ci_autoscale(cmd: str) -> str | None:
    """CI autoscaling killed nine builds mid-run. It stays off until the fleet is proven."""
    if "autoscale-intended" in cmd:
        return None
    if _AUTOSCALE_ENABLE_RE.search(cmd):
        return ("BLOCKED by rule-guard: re-enabling the CI autoscale workflow.\n"
                "It was turned off on 2026-08-19 by founder decision after it stopped Fly "
                "machines mid-build and killed nine PRs, including its own merge commit.\n"
                "It may only come back when the busy-runner read is proven (needs a repo-admin "
                "PAT secret) AND the founder says the fleet is reliable."
                + _escape("autoscale-intended"))
    if _AUTOSCALE_RUN_RE.search(cmd):
        return ("BLOCKED by rule-guard: `deploy/runners.sh autoscale`.\n"
                "Its scale-down reads the busy-runner list with `|| true`; when that read fails "
                "the list is empty, every machine reads as idle, and it stops runners that are "
                "mid-build. That is what killed PRs #383 #387 #390 #391 #407 #414 #424 #427 "
                "#431 on 2026-08-19.\n"
                "Scale by hand with `fly machine start`, or fix the fail-open read first."
                + _escape("autoscale-intended"))
    if _FLY_STOP_CI_RE.search(cmd):
        return ("BLOCKED by rule-guard: stopping a machine in the CI fleet `prospector-ci`.\n"
                "A stopped runner mid-job fails as \"The self-hosted runner lost communication "
                "with the server\", which reads as a failing test and costs a session to "
                "diagnose. Check the GitHub busy list first, then re-run with the marker."
                + _escape("autoscale-intended"))
    return None


# --- a CLONED runner machine is a spare tyre, not a worker ----------------------------------
#
# WHY. `fly machine clone` on an app with no services makes the clone a STANDBY of its source:
# `config.standbys = ["<source id>"]`. A standby is meant to sit stopped and take over only if
# its source's host fails, so Fly stops it again whenever something starts it -- through the
# Machines API, which the machine event log records as `stop | user`, indistinguishable from a
# person or a script.
#
# Measured 2026-08-19: 10 of prospector-ci's 12 machines were standbys cloned from
# 8e4530a7712248. `fly machine list` said 12 machines, `fly status` said 12, and GitHub said 11
# registered runners. The number that could actually hold a build was 2. The standbys DID
# register as runners and DID take jobs, then Fly stopped them mid-build, which surfaces as
# "The self-hosted runner lost communication with the server" and reads as a failing test.
#
# THE CLASS: an action whose result looks like capacity on every instrument and is not. Grow a
# runner fleet with `fly scale count`, which makes real machines.
_FLY_CLONE_RE = re.compile(r"\bfly\s+m(?:achine)?s?\s+clone\b")


def rule_clone_makes_a_standby(cmd: str) -> str | None:
    """A cloned machine in a service-less app is a standby and can never hold a CI job."""
    if "clone-standby-intended" in cmd:
        return None
    if _FLY_CLONE_RE.search(cmd):
        return ("BLOCKED by rule-guard: `fly machine clone`.\n"
                "On an app with no services -- prospector-ci and hermes-ci are both service-less "
                "by design -- a clone is created as a STANDBY of its source (`config.standbys`). "
                "Fly stops a started standby on purpose, so it registers as a GitHub runner, "
                "takes a job, and dies mid-build as \"The self-hosted runner lost communication "
                "with the server\".\n"
                "Measured 2026-08-19: 10 of 12 prospector-ci machines were clones. Real capacity "
                "was 2 while every count on every screen said 12.\n"
                "Grow the fleet with `fly scale count <n> -a <app>`, which makes real machines. "
                "Repair an existing clone with "
                "`fly machine update <id> -a <app> --standby-for \"\" --yes`."
                + _escape("clone-standby-intended"))
    return None


# --- a machine repair restarts the machine, and a build was on it ---------------------------
#
# WHY. On 2026-08-19 at 20:26–20:32Z I repaired 10 standby machines with
# `fly machine update <id> -a prospector-ci --standby-for "" --yes`. That command RESTARTS the
# machine. A peer session's test suite was running on one of them. Their job died, and they
# spent the next stretch hunting "a rolling restart of 10 of 12 runners, 15s apart, with no new
# release" -- which was me, invisible to them, because sessions cannot see each other.
#
# THE CLASS is the one LAW 0's own worked example names: an agent action that silently destroys
# another agent's in-flight work. `push-pr-fence.py` already guards the CI-cancel version of it.
# This is the machine version. The fix is not "remember to check"; it is that the check runs
# whether or not anyone remembers.
#
# `start` is deliberately NOT matched: starting a stopped machine cannot interrupt a build.
# The check FAILS OPEN -- if gh is missing or GitHub is unreachable it allows the command --
# because a fleet repair is most needed exactly when GitHub is unhappy, and a guard that walls
# the box whenever it cannot see is a worse failure than the one it prevents.
_FLY_DISRUPT_RE = re.compile(
    r"\bfly\s+m(?:achine)?s?\s+(update|restart|stop|destroy)\b[^|;&\n]*?-a\s+(\S+)")

# Which repository's runners live on which Fly app. An app that is not a runner fleet is not
# this rule's business, so an unknown app is allowed through.
_RUNNER_APP_REPOS = {
    "prospector-ci": "chidionyema/prospector",
    "hermes-ci": "chidionyema/hermes",
}


def _busy_runners(repo: str) -> list[str]:
    """Names of `repo`'s runners that are mid-job. Empty when busy is zero OR unknowable.

    Separate from the rule so the selftest can stub it: the rule must be provable without
    depending on whatever CI happens to be doing when the selftest runs.
    """
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    rc, out = _sh([gh, "api", f"repos/{repo}/actions/runners",
                   "--jq", ".runners[] | select(.busy) | .name"])
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def rule_restart_kills_a_live_build(cmd: str) -> str | None:
    """Refuse a machine restart while that fleet has a runner mid-job."""
    if "runner-busy-intended" in cmd:
        return None
    m = _FLY_DISRUPT_RE.search(cmd)
    if not m:
        return None
    verb, app = m.group(1), m.group(2).strip("'\"")
    repo = _RUNNER_APP_REPOS.get(app)
    if repo is None:
        return None

    busy = _busy_runners(repo)
    if not busy:
        return None  # empty OR unknowable; failing open is the deliberate choice above

    return (f"BLOCKED by rule-guard: `fly machine {verb}` on {app} while "
            f"{len(busy)} runner(s) are MID-JOB.\n"
            f"Busy now: {', '.join(busy)}\n"
            f"`fly machine {verb}` restarts or removes the machine. If the job you kill belongs "
            f"to another session, they see a build that died as \"The self-hosted runner lost "
            f"communication with the server\" -- which reads as a failing test, from a cause "
            f"they cannot see. That is exactly what happened on 2026-08-19 at 20:26Z.\n"
            f"Wait for the fleet to go idle:\n"
            f"  gh api repos/{repo}/actions/runners --jq "
            f"'[.runners[]|select(.busy)]|length'\n"
            f"If the repair genuinely cannot wait, MESSAGE THE PEER SESSIONS FIRST "
            f"(ListAgents, then SendMessage) so the dead build is explained before they hunt it."
            + _escape("runner-busy-intended"))


# --- the stash stack is SHARED, and it is not yours -----------------------------------------
#
# WHY. `git stash` writes to `refs/stash` in the COMMON git dir. Every worktree of this repo
# shares it, so `git stash pop` in one session takes the top entry off another session's stack.
# Measured 2026-08-19: a `git stash -u` on an already-clean tree created nothing, and the
# matching `git stash pop` popped `stash@{0}: WIP on fix/home-row-us-rules-chip-overflow` --
# a different branch, a different session -- and conflicted in
# store_platform/src/Store.Web/src/pages/index.tsx.
#
# It has happened before. `stash@{2}` in this repo is literally labelled
# "On main: unrelated edits (restored by Claude 2026-08-07 after an accidental drop)".
# Twice is a class, so this is a refusal rather than a third note.
#
# `git stash list` and `git stash show` are reads and stay allowed. `git stash push` is allowed
# too: pushing only ever ADDS an entry, and the damage is in taking one off.
_STASH_TAKE_RE = re.compile(r"\bgit\s+stash\s+(pop|apply|drop|clear)\b")


def rule_shared_stash(cmd: str) -> str | None:
    """Popping a stash in a shared checkout takes another session's work."""
    if "stash-intended" in cmd:
        return None
    mm = _STASH_TAKE_RE.search(cmd)
    if mm:
        return (f"BLOCKED by rule-guard: `git stash {mm.group(1)}`.\n"
                "refs/stash lives in the COMMON git dir, so every worktree and every concurrent "
                "session shares one stack. The top entry is very likely not yours.\n"
                "On 2026-08-19 this popped another branch's WIP into a detached worktree and "
                "conflicted; on 2026-08-07 it dropped an entry that had to be recovered.\n"
                "Read it first:  git stash list && git stash show -p stash@{0}\n"
                "To save your own work, commit on a branch instead of stashing."
                + _escape("stash-intended"))
    return None


# A bare force-push destroys whatever the remote gained since you last looked, and on this repo
# the remote gains things by itself. `.github/workflows/automerge.yml` on main says so in its own
# header: "this workflow now refuses to merge a PR that sits behind main. It updates the branch
# instead and dispatches CI on it". So every time main moves, that workflow pushes a
# `Merge branch 'main' into <branch>` commit onto every open PR branch, mine included.
#
# Measured 2026-08-19: two of my branches gained such a commit while I worked --
# `fix/ci-autoscale-trigger` gained c2a85a4c and `ci/runner-carries-its-tools` gained 6534d51c.
# Both of my pushes were rejected as non-fast-forward. That rejection is the ONLY thing that
# stopped the branch being reset to a behind-main state, which would have restarted the whole
# update-and-retest cycle and thrown away a CI run nobody would have known was lost.
#
# The class is: an agent action that silently destroys work the agent did not know existed.
# git's own non-fast-forward rejection guards it, and `--force` is exactly the flag that turns
# that guard off. So the bare flag is refused and the safe form is named.
#
# `--force-with-lease` stays ALLOWED: it compares against the remote-tracking ref and refuses
# when the remote moved, which is the same protection by a different route. `--force-if-includes`
# likewise. A leading `+` on a refspec is the same force, spelled differently, so it is caught.
_FORCE_PUSH_RE = re.compile(
    r"\bgit\s+(?:-\S+\s+|--\S+(?:=\S+)?\s+)*push\b[^|;&\n]*?"
    r"(?:(?P<flag>--force(?!-with-lease|-if-includes)\b|-f\b)"
    r"|\s(?P<plus>\+(?:refs/)?[\w.][\w./\-]*:))")


def rule_force_push(cmd: str) -> str | None:
    """A bare force-push overwrites commits the remote gained while you were not looking."""
    if "force-push-intended" in cmd:
        return None
    mm = _FORCE_PUSH_RE.search(cmd)
    if mm:
        what = mm.group("flag") or ("refspec " + (mm.group("plus") or "").strip())
        return (f"BLOCKED by rule-guard: force-push ({what}).\n"
                "The remote moves on its own here. automerge.yml updates every open PR branch "
                "whenever main moves, so your branch very likely has a commit you have not "
                "fetched -- measured twice on 2026-08-19 (c2a85a4c, 6534d51c).\n"
                "git's non-fast-forward rejection is what catches that, and --force is the flag "
                "that switches it off.\n"
                "Do this instead:  git fetch origin && git merge origin/<branch>\n"
                "If you truly must rewrite, use the form that still refuses a moved remote:\n"
                "  git push --force-with-lease origin <branch>"
                + _escape("force-push-intended"))
    return None


RULES = (rule_add_all, rule_runtime_state, rule_no_verify, rule_index_lock, rule_two_dot_diff,
         rule_pr_size, rule_commit_in_shared_checkout, rule_merge_red_pr,
         rule_ci_autoscale, rule_clone_makes_a_standby,
         rule_restart_kills_a_live_build, rule_shared_stash,
         rule_force_push)

#: Rules that let the command through and say something. Empty since 2026-08-17: the one warning
#: that lived here, the shared-checkout commit, was ignored for 105 commits and is a refusal now.
WARN_RULES: tuple = ()


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    cases = [
        # (command, rule that must fire or None)
        ("gh workflow enable 337731742", "rule_ci_autoscale"),
        ("gh workflow enable ci-autoscale.yml", "rule_ci_autoscale"),
        ("gh workflow enable 337731742  # autoscale-intended", None),
        ("gh workflow disable 337731742", None),
        ("bash deploy/runners.sh autoscale", "rule_ci_autoscale"),
        ("./deploy/runners.sh autoscale --dry-run", "rule_ci_autoscale"),
        ("bash deploy/runners.sh scale 12", None),
        ("fly machine stop 8ee06eb7701628 -a prospector-ci", "rule_ci_autoscale"),
        ("fly machines stop abc -a prospector-ci", "rule_ci_autoscale"),
        ("fly machine stop abc -a prospector-engine", None),
        ("fly machine start 8ee06eb7701628 -a prospector-ci", None),
        ("fly machine clone 8e4530a7712248 -a prospector-ci", "rule_clone_makes_a_standby"),
        # rule_restart_kills_a_live_build reads GitHub, so the harness skips it above and it is
        # proved against a stubbed busy list further down.
        ("fly machines clone abc --region lhr", "rule_clone_makes_a_standby"),
        ("fly m clone abc -a hermes-ci", "rule_clone_makes_a_standby"),
        ("fly machine clone abc  # clone-standby-intended", None),
        ("fly scale count 12 -a prospector-ci", None),
        ("fly machine update abc -a prospector-ci --standby-for \"\" --yes", None),
        ("git push --force origin my-branch", "rule_force_push"),
        ("git push -f origin my-branch", "rule_force_push"),
        ("git push origin +main:main", "rule_force_push"),
        ("git push origin +refs/heads/x:refs/heads/x", "rule_force_push"),
        ("git push --force origin b  # force-push-intended", None),
        ("git push --force-with-lease origin my-branch", None),
        ("git push --force-if-includes origin my-branch", None),
        ("git push origin my-branch", None),
        ("git push --follow-tags origin main", None),
        ("git push", None),
        ("grep -f patterns.txt file.txt", None),
        ("git stash pop", "rule_shared_stash"),
        ("git stash pop  # stash-intended", None),
        ("git stash drop stash@{0}", "rule_shared_stash"),
        ("git stash clear", "rule_shared_stash"),
        ("git stash apply stash@{1}", "rule_shared_stash"),
        ("git stash list", None),
        ("git stash show -p stash@{0}", None),
        ("git stash -u", None),
        ("git stash push -m wip", None),
        ("git add -A", "rule_add_all"),
        ("git add --all", "rule_add_all"),
        ("git add .", "rule_add_all"),
        ("git add -A  # add-all-intended", None),
        ("git add -- scripts/ops_status.py", None),
        ("git add -p", None),
        ("git commit --no-verify -m x", "rule_no_verify"),
        ("git commit -n -m x", "rule_no_verify"),
        ("git commit -m 'no-verify is bad'", None),
        ("git commit -m x\nrg -n PATTERN docs/", None),          # -n on a LATER line
        ("git commit -m x && tail -n 5 log", None),               # -n after a separator
        ("git add -- x\ngit commit -n -m x", "rule_no_verify"),   # still caught

        ("rm -f .git/index.lock", "rule_index_lock"),
        ("rm /Users/x/.git/worktrees/w/index.lock", "rule_index_lock"),
        ("git diff --stat origin/main HEAD", "rule_two_dot_diff"),
        # Two BRANCH-shaped refs, not a branch-and-HEAD. This used to name
        # `origin/pr/shelf-copy-glossary`, which has since been deleted from origin — so
        # `_is_ref` stopped resolving it, only one ref was found, and the case failed for a
        # reason that had nothing to do with the rule. A selftest must not depend on a ref
        # somebody can delete. `origin/main` twice is still two refs and cannot go stale.
        ("git diff origin/main origin/main", "rule_two_dot_diff"),
        ("git diff --shortstat $(git merge-base origin/main HEAD) HEAD", None),
        ("git diff origin/main...HEAD", None),
        ("git diff --stat origin/main HEAD  # raw-diff-intended", None),
        ("git diff -- prospector/config.py", None),
        ("git diff HEAD~1", None),
        ("echo git add -A is banned", "rule_add_all"),  # substring match is acceptable here
        ("git add store/catalog.sqlite3", "rule_runtime_state"),
        ("git commit --only -m x -- prospector/run.py store/index.json", "rule_runtime_state"),
        ("git add .popdd/last_verify.json", "rule_runtime_state"),
        # A message that NAMES the file stages nothing. The rule must not fire on the commit
        # that fixes the problem it is about.
        ('git commit -m "rotate store/prospector.jsonl"', None),
        ("git add -- prospector/inflight.py", None),
        ("git add store/catalog.sqlite3  # runtime-state-intended", None),
        ("ls store/inflight", None),  # not a staging command at all
        # A heredoc BODY is text, not a command. Writing a doc that quotes the rule,
        # or a commit message that explains it, must not trip the rule it quotes.
        ("git commit -F - -- docs/A.md <<MSG\nnever git add -A in a worktree\nMSG\n", None),
        # A commit message quoting the rule is prose, not a command. This exact shape was
        # refused on 2026-08-19 while staging three explicit paths.
        ('git add -- CLAUDE.md docs/X.md && git commit -m "what stays: never git add -A here"',
         None),
        ("git commit -m 'the rule is: git add -A is banned'", None),
        ('git commit --message="never git add -A"', None),
        # The quotes end where they end. A real violation chained after a commit still blocks.
        ('git commit -m "docs" && git add -A', "rule_add_all"),
        ("python3 - <<'PY'\nprint('the git add -A rule')\nPY\n", None),
        # ...unless a shell is reading it, because then the body executes.
        ("bash <<EOF\ngit add -A\nEOF\n", "rule_add_all"),
    ]
    bad = 0
    for cmd, want in cases:
        got = None
        cmd = strip_commit_messages(strip_heredocs(cmd))
        for rule in RULES:
            if rule.__name__ in ("rule_pr_size", "rule_commit_in_shared_checkout",
                                 "rule_merge_red_pr", "rule_restart_kills_a_live_build"):
                # These read live state -- the branch this process is standing on, or GitHub --
                # so their answer here depends on where the selftest was launched, not on `cmd`.
                # Covered separately below, against explicit inputs.
                continue
            if rule(cmd):
                got = rule.__name__
                break
        if got != want:
            bad += 1
            print(f"  FAIL  {cmd!r}\n        wanted {want}, got {got}")

    # Which tree a rule measures is itself a rule, and it is the one that was wrong.
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ~/.claude, not a repo
    for cmd, session_cwd, want in [
        (f"cd {REPO} && gh pr create", "/nonexistent", REPO),
        (f"cd '{REPO}'\ngh pr create", "/nonexistent", REPO),
        ("gh pr create", REPO, REPO),          # no cd: the session's own tree
        ("cd /nonexistent/nope && gh pr create", None, REPO),   # unusable cd -> fall back
        ("gh pr create", here, REPO),          # cwd outside any worktree -> fall back
        # The 2026-08-17 false refusal: the cd path was a shell variable, so it resolved to no
        # directory and the SESSION's repo got graded instead.
        (f"P={REPO}\ncd \"$P\"\ngh pr create", "/nonexistent", REPO),
        (f"P={os.path.dirname(REPO)}\ncd \"$P/{os.path.basename(REPO)}\"\ngh pr create",
         "/nonexistent", REPO),
    ]:
        got_repo = _repo_for(cmd, session_cwd)
        if got_repo != want:
            bad += 1
            print(f"  FAIL  _repo_for({cmd!r}, {session_cwd!r})\n"
                  f"        wanted {want}, got {got_repo}")
        else:
            cases.append((cmd, want))

    # The shared-checkout note, tested on its decision rather than on the repo's mood.
    for repo, branch, want_note in [
        (REPO, "some/long-lived-branch", True),
        (REPO, "main", True),          # the shared tree is shared whatever the branch is called
        (REPO, "HEAD", False),         # detached: nothing accumulates
        ("/Users/chidionyema/Documents/code/wt-recover", "fix/anything", False),
    ]:
        note = _shared_checkout_refusal(repo, branch)
        noted = note is not None
        if noted != want_note:
            bad += 1
            print(f"  FAIL  _shared_checkout_refusal({repo!r}, {branch!r})\n"
                  f"        wanted noted={want_note}, got {noted}")
        else:
            cases.append((f"{repo}@{branch}", want_note))

    # The merge fence, tested on its decision rather than against a live GitHub.
    for states, want_blocked, label in [
        ([("python", "SUCCESS"), ("nextjs", "SKIPPED"), ("guard", "NEUTRAL")], False, "all green"),
        # Tonight's PR #290 exactly: five green, two red. `gh pr checks --watch` exited 0 on it.
        ([("engine", "SUCCESS"), ("python", "FAILURE"), ("ci-ok", "FAILURE")], True, "red"),
        ([("python", "SUCCESS"), ("dotnet", "IN_PROGRESS")], True, "still running"),
        ([("python", "SUCCESS"), ("dotnet", "QUEUED")], True, "queued"),
        # A cancelled run is not a pass. Three of main's four runs ended this way.
        ([("python", "CANCELLED")], True, "cancelled"),
        ([], True, "no checks at all"),        # what 5b8d010 looked like
        (None, True, "checks unreadable"),     # fails CLOSED
    ]:
        blocked = _merge_refusal("290", states) is not None
        if blocked != want_blocked:
            bad += 1
            print(f"  FAIL  _merge_refusal({label})\n"
                  f"        wanted blocked={want_blocked}, got {blocked}")
        else:
            cases.append((f"merge/{label}", want_blocked))

    # What the escape marker may and may not open. It was unconditional until 2026-08-18, when
    # PR #315 was merged with `python` cancelled and `ci-ok` failed on the argument that those
    # checks could not have run; the squash deleted 115 lines #286 had added an hour earlier and
    # main was red for 23 tests for five hours. The marker now opens ONE outcome: GitHub did not
    # answer. A concluded failure, a cancelled job, no checks at all, and a run still going are
    # all answers.
    GREEN = [("python", "SUCCESS")]
    RED = [("python", "FAILURE")]
    for label, states, escaped, main_red, fixing, want_blocked in [
            ("outage + marker", None, True, None, False, False),
            ("outage, no marker", None, False, None, False, True),
            ("red + marker", RED, True, None, False, True),
            ("cancelled + marker", [("python", "CANCELLED")], True, None, False, True),
            ("no checks + marker", [], True, None, False, True),
            ("pending + marker", [("python", "IN_PROGRESS")], True, None, False, True),
            ("green, main green", GREEN, False, None, False, False),
            ("green, main red", GREEN, False, "main is red", False, True),
            ("green, main red, fixing", GREEN, False, "main is red", True, False),
            ("red, main red", RED, False, "main is red", True, True),
    ]:
        blocked = _merge_verdict("1", states, escaped, main_red, fixing) is not None
        if blocked != want_blocked:
            bad += 1
            print(f"  FAIL  _merge_verdict({label})\n"
                  f"        wanted blocked={want_blocked}, got {blocked}")
        else:
            cases.append((f"verdict/{label}", want_blocked))

    # Every spelling of a merge must reach the fence, and the PR number must come out of each.
    # `gh api .../pulls/N/merge` did not match until 2026-08-18, which is how #324 was merged
    # with its `python` job still running.
    for cmd, want_pr in [
            ("gh pr merge 324 --squash", "324"),
            ("gh pr merge --squash --delete-branch 324", "324"),
            ("gh api -X PUT repos/chidionyema/prospector/pulls/324/merge", "324"),
            ("gh api --method PUT /repos/o/r/pulls/9/merge -f merge_method=squash", "9")]:
        m = _GH_MERGE_NUM.search(cmd)
        got = (m.group(1) or m.group(2)) if m else None
        if not _GH_MERGE.search(cmd) or got != want_pr:
            bad += 1
            print(f"  FAIL  {cmd!r}\n        wanted pr={want_pr}, matched={bool(_GH_MERGE.search(cmd))} got={got}")
        else:
            cases.append((f"merge-spelling/{want_pr}", cmd))

    # The rule must ignore commands that are not a merge.
    for cmd, want in [("gh pr list --state open", None),
                      ("gh pr create --base main", None)]:
        got = "rule_merge_red_pr" if rule_merge_red_pr(cmd) else None
        if got != want:
            bad += 1
            print(f"  FAIL  {cmd!r}\n        wanted {want}, got {got}")
        else:
            cases.append((cmd, want))

    # A warning must not be able to become a refusal by accident. The two tuples decide different
    # exit codes, so a rule appearing in both would block on a path meant only to inform.
    for name, ok, why in [
        ("warn_rules_are_not_also_refusals",
         not (set(RULES) & set(WARN_RULES)), "a rule is in RULES and WARN_RULES"),
        # Pin the 2026-08-17 promotion. This was a WARN_RULE for months; sessions read the note,
        # appended the marker and committed anyway, and `integrate/minimax-into-main` reached 105
        # commits in the shared checkout. Demoting it back is how that happens again.
        ("shared_checkout_commit_is_a_refusal",
         rule_commit_in_shared_checkout in RULES
         and rule_commit_in_shared_checkout not in WARN_RULES
         and (_shared_checkout_refusal(REPO, "some/branch") or "").startswith("BLOCKED"),
         "the shared-checkout commit rule is not a refusal"),
        ("a_warning_does_not_say_blocked",
         all(not (r(c) or "").startswith("BLOCKED")
             for r in WARN_RULES
             for c in (f"cd {REPO} && git commit -m x",)), "a WARN_RULES message says BLOCKED"),
    ]:
        if ok:
            cases.append((name, True))
        else:
            bad += 1
            print(f"  FAIL  {name}: {why}")
    # A machine repair while a runner is mid-job. The busy lookup is stubbed, because a rule
    # that can only be proved when CI happens to be busy is a rule that is never proved.
    _real_busy = _busy_runners
    for name, busy, cmd, want_block in [
        ("busy_fleet_blocks_update", ["runner-7819644f116928"],
         'fly machine update abc -a prospector-ci --standby-for "" --yes', True),
        ("busy_fleet_blocks_restart", ["r1"], "fly machine restart abc -a prospector-ci", True),
        ("busy_fleet_blocks_destroy", ["r1"], "fly machine destroy abc -a hermes-ci", True),
        ("idle_fleet_allows_update", [],
         'fly machine update abc -a prospector-ci --standby-for "" --yes', False),
        # Starting a stopped machine cannot interrupt a build, so it is never this rule's business.
        ("start_is_never_blocked", ["r1"], "fly machine start abc -a prospector-ci", False),
        # An app that is not a runner fleet has no jobs to destroy.
        ("non_runner_app_allowed", ["r1"], "fly machine restart abc -a prospector-engine", False),
        ("escape_hatch_allows", ["r1"],
         "fly machine restart abc -a prospector-ci  # runner-busy-intended", False),
    ]:
        globals()["_busy_runners"] = lambda _repo, _b=busy: list(_b)
        got = bool(rule_restart_kills_a_live_build(cmd))
        if got != want_block:
            bad += 1
            print(f"  FAIL  {name}: wanted block={want_block}, got {got}")
        else:
            cases.append((name, True))
    globals()["_busy_runners"] = _real_busy

    print(f"selftest: {len(cases) - bad}/{len(cases)} passed")
    return 1 if bad else 0


# ---------------------------------------------------------------- entry

_HEREDOC_START = re.compile(r"""<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")
_SHELL_HEREDOC = re.compile(r"\b(?:ba|z|k|da)?sh\b[^\n|;]*<<")


def strip_heredocs(cmd: str) -> str:
    """Drop heredoc BODIES before the rules judge a command.

    Why this exists. On 2026-08-19 this guard refused a commit whose only match was the
    add-all rule quoted inside the commit message. The command staged two explicit paths.
    Every rule below matches on the raw command string, so any heredoc carrying prose about
    a forbidden command -- a doc being written, a commit message, a python patch script --
    trips a fence it never went near. A guard that refuses correct commands trains people to
    reach for the escape marker, and after that it is not a guard.

    The carve-out is deliberate. `bash <<EOF` and friends EXECUTE the body, so those lines
    are commands and must still be judged. When a shell is reading the heredoc, nothing is
    stripped and the old behaviour stands.
    """
    if _SHELL_HEREDOC.search(cmd):
        return cmd
    lines = cmd.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        m = _HEREDOC_START.search(line)
        if not m:
            continue
        term = m.group(2)
        # Skip the body. An unterminated heredoc runs to the end of the command, so
        # everything after it is body, not command.
        while i < len(lines) and lines[i].strip() != term:
            i += 1
        if i < len(lines):
            out.append(lines[i])
            i += 1
    return "".join(out)


_COMMIT_MSG = re.compile(r"""(-m|--message)(=|\s+)(?P<q>['"])(?P<body>.*?)(?<!\\)(?P=q)""",
                         re.DOTALL)


def strip_commit_messages(cmd: str) -> str:
    """Drop `-m "..."` bodies before the rules judge a command.

    Same reason as strip_heredocs, and found the same way: on 2026-08-19 this guard refused
    `git add -- CLAUDE.md .claude/skills docs/... && git commit -m "... never git add -A ..."`.
    The staged paths were explicit. The only match was the rule being QUOTED in the message that
    explains it.

    A commit message is text. It cannot execute, so nothing is lost by not judging it, and a
    guard that blocks writing down its own rule is a guard people learn to bypass.

    Only the quoted body goes. `git commit -m` with an unquoted word is left alone, and so is
    everything outside the quotes -- including anything chained after the commit with && or ;.
    """
    return _COMMIT_MSG.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group('q')}{m.group('q')}", cmd)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = str(payload.get("tool_input", {}).get("command", ""))
    if not cmd:
        return 0
    global _ACTIVE_REPO
    _ACTIVE_REPO = _repo_for(cmd, payload.get("cwd"))
    cmd = strip_heredocs(cmd)
    for rule in RULES:
        try:
            reason = rule(cmd)
        except Exception:
            continue  # fail open, always
        if reason:
            sys.stderr.write(reason + "\n")
            return 2
    for rule in WARN_RULES:
        try:
            note = rule(cmd)
        except Exception:
            continue  # fail open, always
        if note:
            # Exit 0 with a systemMessage: the command runs, and the note is shown once.
            json.dump({"systemMessage": note}, sys.stdout)
            sys.stdout.write("\n")
            break
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)  # fail open
