#!/usr/bin/env python3
"""SessionStart hook — the "never stale" trigger (spec R5, R10).

Wired into ~/.claude/settings.json so it fires for EVERY session in EVERY repo. It is one
of three independent refresh triggers (spec §4.3), so no single failure leaves a graph stale.

RULES THIS HOOK OBEYS (each one is a failure this estate has already paid for):
  * It NEVER blocks. `graphify update` measured 46.5s on a small repo and minutes on a large
    one; a synchronous refresh would tax every single session start. The refresh is spawned
    detached (setsid-equivalent) and the hook returns immediately. R10 is a hard requirement,
    not a nicety.
  * It NEVER spends tokens. It triggers `graphify update` only, which the CLI documents as
    "no LLM needed" — measured 2026-08-06 with ANTHROPIC_API_KEY and OPENAI_API_KEY unset.
    An ABSENT graph is REPORTED, never auto-bootstrapped, because a first build runs the
    community labeller and that is the one path that can cost money. Reporting keeps the
    "enforcement is free" property absolute instead of nearly true.
  * It says what it did. A refresh nobody can see is indistinguishable from staleness — the
    exact prose-drift this estate's state-probe rule exists to kill.
  * It fails SILENT. A broken hook must never stop a session from starting, so every failure
    path exits 0 with no output.
  * It imports the freshness contract from graphify_sweep rather than restating it. Two
    definitions of FRESH would drift, and the one in the hook would be the one nobody checks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.join(HERE, "graphify_sweep.py")
REFRESH_LOG = os.path.expanduser("~/.claude/graphify-refresh.log")


def _fail_silent():
    sys.exit(0)


def repo_of(cwd: str) -> str | None:
    """Enclosing git repo of cwd, or None. Short timeout: this is on the session's path."""
    try:
        p = subprocess.run(("git", "-C", cwd, "rev-parse", "--show-toplevel"),
                           capture_output=True, text=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        return None
    if p.returncode != 0:
        return None
    top = p.stdout.strip()
    return top or None


def spawn_refresh(repo: str) -> int | None:
    """Start a detached refresh of one repo. Returns the pid, or None if it could not start.

    Deliberately re-enters graphify_sweep.py --fix --only rather than calling `graphify update`
    directly: the sweep holds the per-repo flock (R11), so a session opening while another
    refresh is already running no-ops instead of racing a second writer into the same
    graph.json. start_new_session=True detaches from the session's process group, so the
    refresh survives the session ending and can never hold it open.
    """
    try:
        log = open(REFRESH_LOG, "a")
    except OSError:
        log = subprocess.DEVNULL
    try:
        p = subprocess.Popen(
            [sys.executable, SWEEP, "--fix", "--only", repo],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=HERE,
        )
        return p.pid
    except (OSError, subprocess.SubprocessError):
        return None


def compose_line(row: dict, repo: str, spawn=None) -> str | None:
    """The session's one line about this graph, or None when there is nothing to say.

    Pulled out of main() on 2026-08-19 so it can be tested. This is the only thing the hook
    puts in front of an agent, and getting it wrong is expensive in a specific way: a STALE
    graph reported as FRESH means every session trusts leads built from code that has moved,
    and nothing downstream would catch it -- the hook fails silent, so a wrong line and no
    line are indistinguishable from the outside.

    `spawn` is injected so the selftest can exercise the STALE branches without starting a
    real refresh.
    """
    spawn = spawn or spawn_refresh
    name, state = row["name"], row["state"]
    if state == "SKIP":
        return None

    query_hint = ('Ask the graph before grepping: `graphify query "<question>" --budget 2000` '
                  "— local BFS over graphify-out/graph.json, 0 tokens of inference. Treat its "
                  "output as LEADS with paths to verify, never as proof.")

    if state == "FRESH":
        return f"[graphify] {name} — graph FRESH. {query_hint}"
    if state == "ABSENT":
        return (f"[graphify] {name} — NO GRAPH ({row['reason']}). Not auto-built: a first build "
                f"runs the community labeller, the one path that can spend tokens. Build it "
                f"deliberately with `python3 {SWEEP} --fix --bootstrap --only {repo}`.")

    pid = spawn(repo)
    if pid is None:
        return (f"[graphify] {name} — graph STALE ({row['reason']}) and the refresh could "
                f"NOT be started. Run `python3 {SWEEP} --fix --only {repo}` by hand.")
    return (f"[graphify] {name} — graph was STALE ({row['reason']}). A detached, "
            f"LLM-free `graphify update` is running now (pid {pid}, log "
            f"{REFRESH_LOG}); it costs CPU, not tokens. Answers from the graph in the "
            f"next few minutes may predate this refresh. {query_hint}")


def selftest() -> int:
    """Check what this hook tells a session. Graded by scripts/process_audit.py.

    Never spawns a refresh: `spawn` is a stub, so the STALE branches are exercised without
    touching a graph or starting a process.
    """
    failures: list[str] = []

    def check(name, got, want):
        if got != want:
            failures.append(f"  {name}: want {want!r}, got {got!r}")

    spawned: list[str] = []

    def fake_spawn(repo):
        spawned.append(repo)
        return 4242

    def dead_spawn(repo):
        return None

    repo = "/tmp/example-repo"

    # SKIP means say nothing at all. A hook that narrates a repo it does not manage is noise
    # on every session start in every unrelated checkout.
    check("SKIP is silent",
          compose_line({"name": "x", "state": "SKIP", "reason": "-"}, repo, fake_spawn), None)

    fresh = compose_line({"name": "prospector", "state": "FRESH", "reason": "-"}, repo, fake_spawn)
    check("FRESH says FRESH", "graph FRESH" in (fresh or ""), True)
    check("FRESH does not spawn a refresh", spawned, [])

    # ABSENT must be REPORTED, never built. A first build runs the community labeller, which is
    # the one path that can spend tokens, and "enforcement is free" has to stay absolute.
    absent = compose_line({"name": "p", "state": "ABSENT", "reason": "no graph.json"},
                          repo, fake_spawn)
    check("ABSENT is reported", "NO GRAPH" in (absent or ""), True)
    check("ABSENT says how to build it deliberately", "--bootstrap" in (absent or ""), True)
    check("ABSENT does not spawn anything", spawned, [])

    stale = compose_line({"name": "p", "state": "STALE", "reason": "12 commits behind"},
                         repo, fake_spawn)
    check("STALE spawns exactly one refresh", spawned, [repo])
    check("STALE reports the pid", "pid 4242" in (stale or ""), True)
    check("STALE says it costs CPU, not tokens", "not tokens" in (stale or ""), True)

    # A refresh that could not start must say so and hand over the manual command. Reporting it
    # as running would be the prose-drift this hook exists to kill.
    dead = compose_line({"name": "p", "state": "STALE", "reason": "old"}, repo, dead_spawn)
    check("failed spawn is admitted", "could NOT be started" in (dead or ""), True)
    check("failed spawn gives the manual command", "--fix --only" in (dead or ""), True)

    total = 11
    if failures:
        print(f"graphify session hook selftest: {len(failures)}/{total} FAILED")
        print("\n".join(failures))
        return 1
    print(f"graphify session hook selftest: {total}/{total} passed")
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    # Per-process off switch — see the note in graphify_query_hook.py. Disables this process
    # only; the wiring stays visible to --check-hooks and to the state probe.
    if os.environ.get("GRAPHIFY_HOOK_OFF") == "1":
        _fail_silent()

    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    cwd = data.get("cwd") or os.getcwd()

    repo = repo_of(cwd)
    if not repo:
        _fail_silent()

    sys.path.insert(0, HERE)
    try:
        import graphify_sweep  # noqa: E402  (path set above by design)
        row = graphify_sweep.assess(repo)
    except Exception:
        _fail_silent()

    line = compose_line(row, repo)
    if line is None:
        _fail_silent()

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": line,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _fail_silent()
