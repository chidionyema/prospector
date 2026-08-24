#!/usr/bin/env python3
"""UserPromptSubmit hook — inject graph EVIDENCE, not instructions (spec R6, G-USE/S2).

A rule that says "use the graph" is a rule an agent can forget, skip, or rationalise past —
which is exactly what happened: graphify's enforcement was three prose lines in CLAUDE.md and
the measured result was an estate with 3 stale and 5 absent graphs. This hook removes the
choice. On a codebase-shaped prompt it runs the query itself and puts the ANSWER in context
before the model acts, so the cheap path is the default path rather than the disciplined one.

RULES THIS HOOK OBEYS:
  * Bounded cost, every time. `graphify query` is local BFS over graph.json — 0 tokens of
    inference — and its output is capped with --budget. The only cost is the injected text
    itself, which is why the budget is a constant here and not a per-call judgement.
  * Conservative trigger. Injecting on EVERY prompt would add the budget to every turn, which
    is a cost regression dressed up as a feature. It fires only on prompts that look like
    questions about this codebase, and never on slash commands.
  * Leads, not proof. The injected banner says so explicitly. A graph edge is a lead to verify
    at a file:line, and the estate's proof-of-claim rule outranks anything this hook injects.
  * Fails SILENT and FAST. Any error, any timeout, any missing graph: print nothing, exit 0.
    A prompt hook that can hang is a prompt hook that will hang.
  * It measures itself. Every injection appends one line to the log below, so R12 (enforcement
    cost is known and capped) is answerable from data instead of from this docstring.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

# 700, not graphify's default 2000. Measured 2026-08-06: a depth-2 BFS on a real prompt
# returned 337 nodes and spent the whole budget on a flat node list whose useful rows were in
# the first ~25. Paying 2000 tok per codebase prompt for that is a cost regression wearing a
# feature's clothes. 700 keeps the head of the list; §L8's A/B is what may raise it again.
BUDGET_TOKENS = 700
QUERY_TIMEOUT_S = 12
MIN_PROMPT_CHARS = 12
MAX_PROMPT_CHARS = 400        # longer prompts are usually pasted content, not a graph question
INJECT_LOG = os.path.expanduser("~/.claude/graphify-inject.log")

# Prompts that are ABOUT a codebase. Two independent signals; either one is enough.
_INTENT = re.compile(
    r"\b(where\s+is|where\s+does|how\s+does|how\s+is|what\s+calls|who\s+calls|what\s+uses|"
    r"why\s+does|which\s+file|find\s+the|trace|call\s?graph|depend(s|ency|encies)?|"
    r"architecture|wired|entry\s?point|refactor|impact|affected|flow)\b", re.I)
_CODE_NOUN = re.compile(
    r"\b(function|method|class|module|file|import|hook|endpoint|route|handler|schema|"
    r"migration|adapter|provider|component|daemon|scheduler|pipeline|config|codebase|repo)\b",
    re.I)
# Identifier-shaped tokens: a path, a dotted filename, snake_case, CamelCase, or a call.
_IDENT = re.compile(
    r"(\b[\w./-]+\.(py|ts|tsx|js|jsx|mjs|cs|go|rs|java|rb|sh|sql|ya?ml)\b|"
    r"\b\w+_\w+\b|\b[a-z]+[A-Z]\w*\b|\b\w+\(\))")


def is_codebase_shaped(prompt: str) -> bool:
    p = prompt.strip()
    if not (MIN_PROMPT_CHARS <= len(p) <= MAX_PROMPT_CHARS):
        return False
    if p.startswith("/") or p.startswith("!"):      # slash command / shell passthrough
        return False
    if _INTENT.search(p) and (_CODE_NOUN.search(p) or _IDENT.search(p)):
        return True
    return bool(_CODE_NOUN.search(p) and _IDENT.search(p))


def repo_of(cwd: str) -> str | None:
    try:
        p = subprocess.run(("git", "-C", cwd, "rev-parse", "--show-toplevel"),
                           capture_output=True, text=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        return None
    return p.stdout.strip() or None if p.returncode == 0 else None


def run_query(repo: str, prompt: str) -> str | None:
    graph = os.path.join(repo, "graphify-out", "graph.json")
    if not os.path.exists(graph):
        return None
    exe = os.path.expanduser("~/.local/bin/graphify")
    if not os.path.exists(exe):
        return None
    try:
        p = subprocess.run(
            [exe, "query", prompt, "--budget", str(BUDGET_TOKENS), "--graph", graph],
            capture_output=True, text=True, timeout=QUERY_TIMEOUT_S, cwd=repo,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if p.returncode != 0:
        return None
    out = (p.stdout or "").strip()
    return out or None


def log_injection(repo: str, chars: int, seconds: float) -> None:
    """R12: enforcement cost is known and capped. ~4 chars/token is the usual rule of thumb."""
    try:
        with open(INJECT_LOG, "a") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "repo": os.path.basename(repo),
                "chars": chars,
                "est_tokens": round(chars / 4),
                "query_seconds": round(seconds, 2),
            }) + "\n")
    except OSError:
        pass


def selftest() -> int:
    """Check the trigger. Graded by scripts/process_audit.py.

    `is_codebase_shaped` IS this hook's cost control. Every prompt it accepts pays up to
    BUDGET_TOKENS of injected text, and every prompt it rejects gets nothing. The hook fails
    silent by design, so a trigger that broke -- widened by a regex edit, or narrowed to never
    fire -- looks exactly like a quiet turn. Nothing else can tell the difference, so these
    cases do.

    No graph, no subprocess, no network: the trigger is a pure function of the prompt string.
    """
    cases: list[tuple[str, bool]] = [
        # -- must fire: a real question about this codebase --------------------------------
        ("where is the scheduler wired up in run.py", True),
        ("how does prospector/ops/console_api.py build the method payload", True),
        ("what calls _read_rework()", True),
        ("which file owns the retrieval provider chain", True),
        ("trace the money rail from bridge.py to the endpoint", True),
        ("what is the impact of changing the config schema", True),
        ("show me the verify_moat module and its dependencies", True),
        # -- must NOT fire -----------------------------------------------------------------
        ("/graphify", False),                       # slash command
        ("!ls -la", False),                         # shell passthrough
        ("ok", False),                              # under MIN_PROMPT_CHARS
        ("thanks, that works", False),              # conversational, no code noun or identifier
        ("what do you think about the pricing strategy for the packs", False),
        ("architecture", False),                    # intent word alone, no noun and no identifier
        ("x" * (MAX_PROMPT_CHARS + 1), False),      # pasted content, not a question
    ]
    failures = [f"  {p[:60]!r}: want {want}, got {is_codebase_shaped(p)}"
                for p, want in cases if is_codebase_shaped(p) is not want]

    # The budget is the cost cap. If it is ever raised past graphify's own default the comment
    # above it is wrong and the A/B in COST_PROGRAM §L8 is measuring something else.
    if not 0 < BUDGET_TOKENS <= 2000:
        failures.append(f"  BUDGET_TOKENS={BUDGET_TOKENS} is outside the measured 1..2000 range")

    total = len(cases) + 1
    if failures:
        print(f"graphify query hook selftest: {len(failures)}/{total} FAILED")
        print("\n".join(failures))
        return 1
    print(f"graphify query hook selftest: {total}/{total} passed")
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Per-process off switch. It exists because measuring this hook's value requires a control
    # arm WITHOUT it, and the hook is global in settings.json — without a switch, the A/B in
    # COST_PROGRAM §L8 would inject into its own control and measure nothing. It disables one
    # process only: `--check-hooks` and the state probe still see the wiring, so it cannot be
    # used to quietly turn enforcement off estate-wide.
    if os.environ.get("GRAPHIFY_HOOK_OFF") == "1":
        sys.exit(0)

    prompt = data.get("prompt") or ""
    cwd = data.get("cwd") or os.getcwd()
    if not is_codebase_shaped(prompt):
        sys.exit(0)

    repo = repo_of(cwd)
    if not repo:
        sys.exit(0)

    t0 = time.time()
    out = run_query(repo, prompt)
    if not out:
        sys.exit(0)
    dt = time.time() - t0
    log_injection(repo, len(out), dt)

    banner = (f"[graphify] Graph evidence retrieved automatically for this prompt "
              f"(local BFS over {os.path.basename(repo)}/graphify-out/graph.json, "
              f"0 tokens of inference, capped at {BUDGET_TOKENS} tok, {dt:.1f}s). "
              f"These are LEADS: nodes and edges to verify at a file:line before you claim "
              f"anything. Prefer following these paths over a fresh grep sweep; if the graph "
              f"does not contain the answer, say so and search normally.")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": banner + "\n\n" + out,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
