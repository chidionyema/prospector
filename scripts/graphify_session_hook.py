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


def main() -> None:
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

    name = row["name"]
    state = row["state"]
    if state == "SKIP":
        _fail_silent()

    query_hint = ('Ask the graph before grepping: `graphify query "<question>" --budget 2000` '
                  "— local BFS over graphify-out/graph.json, 0 tokens of inference. Treat its "
                  "output as LEADS with paths to verify, never as proof.")

    if state == "FRESH":
        line = f"[graphify] {name} — graph FRESH. {query_hint}"
    elif state == "ABSENT":
        line = (f"[graphify] {name} — NO GRAPH ({row['reason']}). Not auto-built: a first build "
                f"runs the community labeller, the one path that can spend tokens. Build it "
                f"deliberately with `python3 {SWEEP} --fix --bootstrap --only {repo}`.")
    else:
        pid = spawn_refresh(repo)
        if pid is None:
            line = (f"[graphify] {name} — graph STALE ({row['reason']}) and the refresh could "
                    f"NOT be started. Run `python3 {SWEEP} --fix --only {repo}` by hand.")
        else:
            line = (f"[graphify] {name} — graph was STALE ({row['reason']}). A detached, "
                    f"LLM-free `graphify update` is running now (pid {pid}, log "
                    f"{REFRESH_LOG}); it costs CPU, not tokens. Answers from the graph in the "
                    f"next few minutes may predate this refresh. {query_hint}")

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
