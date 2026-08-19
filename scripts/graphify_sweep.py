#!/usr/bin/env python3
"""Graphify estate scoreboard and refresher.

READ-ONLY by default. It writes ONLY when explicitly asked with --fix/--bootstrap, and
then only by invoking `graphify`, never by editing a repo itself.

Implements the freshness contract in docs/GRAPHIFY_ENFORCEMENT_SPEC.md §4.1 and reports
R2 (universal), R3 (never stale) and R8 (not tracked in git) for every git repo under the
estate root.

    FRESH  := graph.json exists AND mtime >= HEAD committer time
              AND no tracked source file is newer than it
    STALE  := graph exists but fails that
    ABSENT := no graph at all

RULES THIS SCRIPT OBEYS (each is a rule the estate learned the hard way):
  * Without --fix it never writes. A probe that mutates is worse than none.
  * It reports the number it measured, never a judgement about it.
  * Exit 0 only when ABSENT, STALE and TRACKED are all zero. Anything else exits 1, so it
    can gate a hook without a human reading the table.
  * Refresh uses `graphify update`, which the CLI documents as "no LLM needed" — so keeping
    the estate fresh costs CPU, not tokens. Bootstrapping an ABSENT graph is a SEPARATE flag
    because a first build runs clustering and may invoke the LLM community-labeller.

Usage:
    graphify_sweep.py                 # full table (read-only)
    graphify_sweep.py --brief         # one line, for injection into a session
    graphify_sweep.py --fix           # refresh every STALE graph, then re-assess
    graphify_sweep.py --fix --bootstrap   # also build graphs for ABSENT repos (may use LLM)
    graphify_sweep.py --root DIR      # override the estate root
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ESTATE_ROOT = os.path.expanduser("~/Documents/code")
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")

# The two session-level triggers, and the marker that proves each is wired. Checked by
# --check-hooks (spec R7): enforcement that cannot detect its own removal is not enforcement.
REQUIRED_SESSION_HOOKS = (
    ("SessionStart", "graphify_session_hook.py"),
    ("UserPromptSubmit", "graphify_query_hook.py"),
)

# Extensions graphify extracts from. Deliberately excludes .json: store/ and storage/ are
# tracked *runtime state* that the daemon rewrites constantly, and counting them would make
# every graph permanently stale for reasons that have nothing to do with the code.
SOURCE_EXT = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cs", ".go", ".rs", ".java", ".rb",
    ".sh", ".md", ".yaml", ".yml", ".sql", ".html", ".css", ".scss",
}
EXCLUDE_PREFIX = ("graphify-out/", "node_modules/", "store/", "storage/", ".venv/", "venv/")

SKIP_MARKER = ".graphify-skip"  # opt-out file, per spec decision S1


def git(repo: str, *args: str) -> str | None:
    """Run a git command in repo; None if it fails. Never raises."""
    try:
        out = subprocess.run(
            ("git", "-C", repo) + args,
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout if out.returncode == 0 else None


def main_checkout(repo: str) -> str | None:
    """The main working tree behind `repo`, or None if repo IS the main one.

    In a linked worktree `.git` is a file containing `gitdir:`, and the common dir points
    at the main checkout's `.git`. Asking git is the only safe way — reading `.git` as a
    directory is the bug this estate has already hit twice.
    """
    if os.path.isdir(os.path.join(repo, ".git")):
        return None  # a real clone, not a linked worktree
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return None
    parent = os.path.dirname(common.strip().rstrip("/"))
    return parent or None


def discover(root: str) -> list[str]:
    """Every git repo one level under root. Enumerated at run time — never a hardcoded
    list — so a repo created tomorrow is covered without editing this file (spec G-DISCOVER)."""
    repos = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return repos
    for name in entries:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        # In a worktree .git is a FILE containing `gitdir:`, so test existence, not isdir.
        if os.path.exists(os.path.join(path, ".git")):
            repos.append(path)
    return repos


def newest_source_mtime(repo: str) -> tuple[float, str | None]:
    """(mtime, path) of the newest tracked source file. (0.0, None) if none found."""
    listing = git(repo, "ls-files", "-z")
    if listing is None:
        return 0.0, None
    best, best_path = 0.0, None
    for rel in listing.split("\0"):
        if not rel or rel.startswith(EXCLUDE_PREFIX):
            continue
        if os.path.splitext(rel)[1] not in SOURCE_EXT:
            continue
        try:
            m = os.stat(os.path.join(repo, rel)).st_mtime
        except OSError:
            continue  # deleted-but-tracked; not evidence of anything
        if m > best:
            best, best_path = m, rel
    return best, best_path


def head_time(repo: str) -> float:
    out = git(repo, "log", "-1", "--format=%ct")
    if not out or not out.strip().isdigit():
        return 0.0
    return float(out.strip())


def assess(repo: str) -> dict:
    name = os.path.basename(repo)
    row = {"name": name, "repo": repo, "state": "ABSENT", "age_days": None,
           "reason": "", "tracked": 0, "ignored": False, "skipped": False}

    if os.path.exists(os.path.join(repo, SKIP_MARKER)):
        row["state"] = "SKIP"
        row["skipped"] = True
        return row

    # A linked worktree is covered by its main checkout's graph. Measured 2026-08-17:
    # all 12 ABSENT and both STALE rows were linked worktrees of repos that were
    # themselves FRESH, so the sweep's verdict was permanently red on transient
    # checkouts that get created and deleted several times a day. Building a graph in
    # each one costs ~120 MB and is stale the moment the worktree is removed. Skip only
    # when the MAIN checkout actually carries a graph — if the main repo is uncovered,
    # the worktree still reports, so this can never hide a real gap.
    main = main_checkout(repo)
    if main and main != repo and os.path.exists(
            os.path.join(main, "graphify-out", "graph.json")):
        row["state"] = "SKIP"
        row["skipped"] = True
        row["reason"] = f"linked worktree of {os.path.basename(main)}"
        return row

    tracked = git(repo, "ls-files", "graphify-out")
    row["tracked"] = len([x for x in (tracked or "").splitlines() if x])
    try:
        with open(os.path.join(repo, ".gitignore")) as fh:
            row["ignored"] = any("graphify" in line for line in fh)
    except OSError:
        row["ignored"] = False

    graph = os.path.join(repo, "graphify-out", "graph.json")
    try:
        gm = os.stat(graph).st_mtime
    except OSError:
        row["reason"] = "no graphify-out/graph.json"
        return row

    row["age_days"] = (time.time() - gm) / 86400.0
    ht = head_time(repo)
    nm, np_ = newest_source_mtime(repo)

    if ht and gm < ht:
        row["state"] = "STALE"
        row["reason"] = f"older than HEAD by {(ht - gm) / 86400:.1f}d"
    elif nm and gm < nm:
        row["state"] = "STALE"
        row["reason"] = f"older than {np_}"
    else:
        row["state"] = "FRESH"
    return row


def repo_lock(repo: str):
    """Exclusive non-blocking lock for one repo (spec R11). Returns the open handle, or
    None if another sweep already holds it — in which case this caller no-ops rather than
    racing a second `graphify update` into the same graph.json.

    macOS has no flock(1), so this uses fcntl.flock. The lock file lives in the temp dir,
    not in the repo, so a lock never shows up as a repo change and can never be committed.
    """
    key = hashlib.sha1(repo.encode()).hexdigest()[:16]
    path = os.path.join(tempfile.gettempdir(), f"graphify-sweep-{key}.lock")
    fh = open(path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def refresh(repo: str, timeout: int, force: bool) -> tuple[bool, str, float]:
    """Run `graphify update` on one repo. Returns (ok, detail, seconds)."""
    exe = shutil.which("graphify")
    if not exe:
        return False, "graphify not on PATH", 0.0
    cmd = [exe, "update", repo] + (["--force"] if force else [])
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s", time.time() - t0
    except OSError as e:
        return False, f"exec failed: {e}", time.time() - t0
    dt = time.time() - t0
    if p.returncode == 0:
        return True, "updated", dt
    tail = (p.stderr or p.stdout or "").strip().splitlines()
    return False, (tail[-1][:100] if tail else f"exit {p.returncode}"), dt


def do_fix(rows: list[dict], bootstrap: bool, timeout: int, force: bool) -> list[dict]:
    """Refresh STALE repos (and ABSENT ones when bootstrap is set). Re-assesses after."""
    targets = [r for r in rows if r["state"] == "STALE"]
    if bootstrap:
        targets += [r for r in rows if r["state"] == "ABSENT"]
    if not targets:
        print("nothing to fix — no STALE repos"
              + ("" if bootstrap else " (ABSENT repos need --bootstrap)"))
        return rows

    print(f"── REFRESHING {len(targets)} repo(s) with `graphify update` (LLM-free path) ──")
    for r in targets:
        lock = repo_lock(r["repo"])
        if lock is None:
            print(f"  {r['name']:<24} SKIPPED — another sweep holds the lock")
            continue
        try:
            ok, detail, dt = refresh(r["repo"], timeout, force)
        finally:
            lock.close()
        mark = "✅" if ok else "❌"
        print(f"  {mark} {r['name']:<24} {dt:6.1f}s  {detail}")
    print("── re-assessing ──")
    return [assess(r["repo"]) for r in rows]


# ── Trigger wiring (R4, R5, R6) and its self-check (R7) ────────────────────────────────
#
# Three independent triggers keep a graph fresh, so no single failure causes staleness:
#   post-commit git hook  (R4) — the repo changed, refresh it
#   SessionStart hook     (R5) — an agent arrived, refresh before it reads anything
#   UserPromptSubmit hook (R6) — a codebase question, answer it from the graph
# This section installs the first and verifies all three. It verifies by READING what git and
# Claude Code actually load, never by asserting that an install ran: a hook written where git
# is not looking is the failure mode this estate has already hit (core.hooksPath, and a
# worktree whose .git is a FILE, not a directory).


def hooks_dir(repo: str) -> str | None:
    """Where git ACTUALLY looks for this repo's hooks — honours core.hooksPath, and works in
    a worktree where .git is a file. Never construct `<repo>/.git/hooks` by hand."""
    out = git(repo, "rev-parse", "--git-path", "hooks")
    if not out:
        return None
    path = out.strip()
    path = path if os.path.isabs(path) else os.path.join(repo, path)
    # An ORPHANED worktree still looks like a repo: the directory is there and `.git` is there,
    # but it is a file whose `gitdir:` points at metadata that has been pruned. git then answers
    # `rev-parse --git-path` with the literal `.git/hooks`, and joining that gives a path whose
    # first component is a FILE. Measured 2026-08-19 on wt-cardsub and wt-site-pr: the sweep died
    # with NotADirectoryError and reported the hooks as broken estate-wide, every 30 minutes.
    # Resolving the answer against the disk is the check that distinguishes the two cases.
    return path if os.path.isdir(os.path.dirname(path)) or os.path.isdir(path) else None


def post_commit_state(repo: str) -> tuple[str, str | None]:
    """('ok'|'missing'|'foreign', path) for this repo's post-commit hook.

    'foreign' means a post-commit hook exists that is not ours — we report it and refuse to
    overwrite, because silently clobbering another tool's hook is a worse bug than a stale
    graph."""
    hd = hooks_dir(repo)
    if not hd:
        return "missing", None
    path = os.path.join(hd, "post-commit")
    if not os.path.exists(path):
        return "missing", path
    try:
        with open(path) as fh:
            body = fh.read()
    except OSError:
        return "foreign", path
    return ("ok" if "graphify" in body else "foreign"), path


def install_git_hooks(rows: list[dict]) -> int:
    """R4: a commit makes its repo's graph fresh again with no human action."""
    exe = shutil.which("graphify")
    if not exe:
        print("❌ graphify not on PATH — cannot install git hooks")
        return 1
    print("── INSTALLING post-commit refresh hooks ──")
    failed = 0
    for r in rows:
        if r["skipped"]:
            continue
        state, path = post_commit_state(r["repo"])
        if state == "ok":
            print(f"  ✓  {r['name']:<24} already installed")
            continue
        if state == "foreign":
            print(f"  ⚠️  {r['name']:<24} NOT touched — a non-graphify post-commit hook "
                  f"exists at {path}")
            failed += 1
            continue
        try:
            p = subprocess.run((exe, "hook", "install"), cwd=r["repo"],
                               capture_output=True, text=True, timeout=120)
        except (subprocess.SubprocessError, OSError) as e:
            print(f"  ❌ {r['name']:<24} {e}")
            failed += 1
            continue
        # Verify by reading git's own hook path, not by trusting the installer's exit code.
        state, _ = post_commit_state(r["repo"])
        mark = "✅" if state == "ok" else "❌"
        if state != "ok":
            failed += 1
        detail = "installed" if state == "ok" else (
            (p.stderr or p.stdout or "").strip().splitlines() or ["no hook written"])[-1][:80]
        print(f"  {mark} {r['name']:<24} {detail}")
    return failed


def settings_commands(event: str) -> list[str]:
    try:
        with open(SETTINGS_PATH) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    cmds = []
    for entry in (data.get("hooks", {}) or {}).get(event) or []:
        for h in entry.get("hooks") or []:
            if h.get("command"):
                cmds.append(h["command"])
    return cmds


def check_hooks(rows: list[dict]) -> list[str]:
    """R7: report every way the enforcement could have been removed or broken. Empty list
    means every trigger is wired where the tool that runs it will actually find it."""
    problems = []
    for event, marker in REQUIRED_SESSION_HOOKS:
        cmds = settings_commands(event)
        if not any(marker in c for c in cmds):
            problems.append(f"{SETTINGS_PATH}: no {event} hook running {marker}")
            continue
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), marker)
        if not os.path.exists(script):
            problems.append(f"{event} hook is configured but {script} does not exist")

    # A directory whose git metadata was pruned is not a repo with a missing hook. It is a
    # leftover, and no hook can be installed into a git dir that no longer exists. Counting it
    # here made a check that could never go green, and a check that can never go green is one
    # nobody reads: `--check-hooks` reported BROKEN on wt-cardsub and wt-site-pr indefinitely
    # while every real trigger was wired. Orphans are estate hygiene, reported by
    # scripts/process_audit.py under "orphaned directories", so they are noted here and not
    # counted as an enforcement failure.
    orphaned, missing = [], []
    for r in rows:
        if r["skipped"] or post_commit_state(r["repo"])[0] == "ok":
            continue
        (orphaned if hooks_dir(r["repo"]) is None else missing).append(r["name"])
    if missing:
        problems.append(f"post-commit refresh hook missing in {len(missing)} repo(s): "
                        + ", ".join(sorted(missing)[:8])
                        + (" …" if len(missing) > 8 else ""))
    if orphaned:
        print("[graphify] note: %d orphaned worktree dir(s) skipped, git metadata pruned: %s"
              % (len(orphaned), ", ".join(sorted(orphaned)[:8])))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ESTATE_ROOT)
    ap.add_argument("--brief", action="store_true",
                    help="one line, for injection into a session")
    ap.add_argument("--fix", action="store_true",
                    help="refresh every STALE graph via `graphify update`, then re-assess")
    ap.add_argument("--bootstrap", action="store_true",
                    help="with --fix, also build graphs for ABSENT repos (may invoke the LLM labeller)")
    ap.add_argument("--timeout", type=int, default=900,
                    help="per-repo seconds before giving up (default 900)")
    ap.add_argument("--force", action="store_true",
                    help="pass --force to graphify update (accepts a rebuild with fewer nodes)")
    ap.add_argument("--only", metavar="PATH",
                    help="restrict to a single repo (used by the SessionStart hook)")
    ap.add_argument("--install-git-hooks", action="store_true",
                    help="install the post-commit refresh hook in every repo (R4)")
    ap.add_argument("--check-hooks", action="store_true",
                    help="verify every trigger is wired; exit 1 if any is missing (R7)")
    args = ap.parse_args()

    rows = [assess(r) for r in discover(args.root)]

    if args.only:
        target = os.path.realpath(os.path.expanduser(args.only))
        rows = [r for r in rows if os.path.realpath(r["repo"]) == target]
        if not rows:
            print(f"--only: {target} is not a git repo under {args.root}")
            return 1

    if args.install_git_hooks:
        return 1 if install_git_hooks(rows) else 0

    if args.check_hooks:
        problems = check_hooks(rows)
        for p in problems:
            print(f"❌ {p}")
        print("[graphify] hooks " + ("WIRED — all triggers present" if not problems
                                     else f"BROKEN — {len(problems)} problem(s)"))
        return 1 if problems else 0

    if args.fix:
        rows = do_fix(rows, args.bootstrap, args.timeout, args.force)
    absent = sum(1 for r in rows if r["state"] == "ABSENT")
    stale = sum(1 for r in rows if r["state"] == "STALE")
    fresh = sum(1 for r in rows if r["state"] == "FRESH")
    tracked = sum(r["tracked"] for r in rows)
    hook_problems = check_hooks(rows)
    ok = absent == 0 and stale == 0 and tracked == 0 and not hook_problems

    if args.brief:
        mark = "OK" if ok else "ACTION NEEDED"
        print(f"[graphify] {mark} — fresh {fresh} / stale {stale} / absent {absent} "
              f"/ git-tracked graph files {tracked} / hook problems {len(hook_problems)} "
              f"(of {len(rows)} repos)")
        return 0 if ok else 1

    print(f"── GRAPHIFY ESTATE SWEEP ── {time.strftime('%Y-%m-%d %H:%M')} — root {args.root}")
    print(f"{'REPO':<24}{'STATE':<8}{'AGE(d)':>8}  {'TRACKED':>7} {'IGN':>4}  REASON")
    for r in sorted(rows, key=lambda x: (x["state"] != "STALE", x["state"] != "ABSENT", x["name"])):
        age = f"{r['age_days']:.1f}" if r["age_days"] is not None else "-"
        ign = "yes" if r["ignored"] else "NO"
        print(f"{r['name'][:23]:<24}{r['state']:<8}{age:>8}  {r['tracked']:>7} {ign:>4}  {r['reason']}")
    print("──")
    print(f"repos {len(rows)}   FRESH {fresh}   STALE {stale}   ABSENT {absent}   "
          f"graph files tracked in git {tracked}")
    if hook_problems:
        for p in hook_problems:
            print(f"HOOKS ❌ {p}")
    else:
        print("HOOKS ✅ post-commit + SessionStart + UserPromptSubmit all wired")
    print(f"VERDICT: {'✅ spec R2/R3/R4/R7/R8 satisfied' if ok else '❌ see docs/GRAPHIFY_ENFORCEMENT_SPEC.md'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
