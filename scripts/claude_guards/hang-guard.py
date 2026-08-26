#!/usr/bin/env python3
"""hang-guard.py — PreToolUse enforcement against commands that never terminate.

WHY THIS EXISTS. On 2026-08-10 a `pi` session sat wedged for 4h32m. It had shelled out to
`npx tsx scripts/verify-row-chip.ts 2>&1 | tail -30`; the script's selector wait threw, its
top-level `.catch` set `process.exitCode` without closing the browser, and a connected
Chromium keeps Node's event loop open forever. pi has no per-command timeout (261 internal
`timeoutMs` in its dist, no user-facing setting), so it blocked on that pipeline until the
process was killed by hand. Every task after it looked "stuck". The script itself is fixed,
but the CLASS is not: any browser/dev harness can hang, and nothing bounded it.

Found alongside it: three orphaned `grep -r TODO\\|FIXME\\|HACK` processes at PPID 1, one of
them 50 minutes old. Their parent shells had exited (tool call cancelled or timed out) and
the greps kept running, walking 169,226 files — 1.7 GB of `.claude/worktrees` (a full
node_modules per worktree), 387 MB `store/`, 120 MB `graphify-out/`. `/usr/bin/grep -r` does
not read `.gitignore`, and a downstream `| grep -v node_modules` is an OUTPUT FILTER: every
byte is still read. They accumulate, starve each other's I/O, and degrade the machine
cumulatively — which is why this got worse over time rather than all at once.

TWO RULES, both mechanical:

  1. UNBOUNDED RECURSIVE GREP. `grep -r/-R` with no `--exclude-dir` and no `timeout` wrapper.
     `rg` is installed and honours `.gitignore`, which already lists node_modules/ and
     graphify-out/, so the fix is usually one character.

  2. UNBOUNDED HANG-PRONE HARNESS. A foreground playwright / puppeteer / browser-driving
     script, or a dev server, with no `timeout` wrapper. These are the commands whose failure
     mode is "runs forever", not "exits non-zero".

DELIBERATELY NARROW. The pi-bridge fence taught this estate that a fence blocking work it was
never meant to block gets routed around by hand, and stops being a fence
(memory: `pi-bridge-fence-banned-a-directory-not-a-risk.md`). So: only these two shapes, both
with a one-token escape printed in the block message, and a kill switch.

  override: touch ~/.claude/state/hangguard/OFF
"""

from __future__ import annotations

import json
import os
import re
import sys

KILL_SWITCH = os.path.expanduser("~/.claude/state/hangguard/OFF")

# A `timeout`/`gtimeout` anywhere in the command bounds it. Cheap and sufficient: the point is
# that SOMETHING will reap it, not that we can prove which segment is wrapped.
BOUNDED_RE = re.compile(r"\b(timeout|gtimeout)\s+[\d.]+[smhd]?\b")

# `grep -r`, `-R`, or a combined cluster like `-rn` / `-rIl`. Matches the flag cluster, so
# `--include=` and friends do not accidentally satisfy it.
RECURSIVE_GREP_RE = re.compile(r"\bgrep\b[^|;&]*?\s-[A-Za-z]*[rR][A-Za-z]*\b")
PRUNED_RE = re.compile(r"--exclude-dir|--exclude=|\bfind\b.*-prune")

# Harnesses whose documented failure mode is a process that never exits.
HANG_PRONE_RE = re.compile(
    r"\b(playwright|puppeteer|chrome-headless-shell|chromium-headless)\b"
    r"|\bnpx\s+tsx\s+scripts/verify-"
    r"|\b(npm|pnpm|yarn)\s+run\s+dev\b"
    r"|\bnext\s+dev\b"
)
# Backgrounded work is the caller's explicit choice and is tracked by the harness; it is not
# the failure this guard exists for.
BACKGROUNDED_RE = re.compile(r"&\s*$|\bnohup\b|\bdisown\b")


def block(reason: str) -> int:
    sys.stderr.write(reason)
    return 2  # PreToolUse: exit 2 blocks the call and shows stderr to the model


def check(cmd: str) -> int:
    if not cmd or BOUNDED_RE.search(cmd) or BACKGROUNDED_RE.search(cmd):
        return 0

    if RECURSIVE_GREP_RE.search(cmd) and not PRUNED_RE.search(cmd):
        return block(
            "BLOCKED by hang-guard: unbounded recursive grep.\n"
            "`/usr/bin/grep -r` does not read .gitignore. In this estate it walks 169,226 "
            "files (1.7 GB .claude/worktrees, 387 MB store/, 120 MB graphify-out/) and takes "
            "tens of minutes. A downstream `| grep -v node_modules` filters the OUTPUT — every "
            "byte is still read. When the tool call is cancelled the grep is orphaned to PPID 1 "
            "and keeps running; three such orphans were found on 2026-08-10.\n"
            "Fix, cheapest first:\n"
            "  rg 'pattern' path/            # honours .gitignore, already excludes the bulk\n"
            "  grep -r --exclude-dir={node_modules,.git,.next,graphify-out,worktrees} ...\n"
            "  timeout 60 grep -r ...        # if you really want grep, bound it\n"
        )

    if HANG_PRONE_RE.search(cmd):
        return block(
            "BLOCKED by hang-guard: hang-prone harness with no timeout.\n"
            "Browser harnesses and dev servers fail by running forever, not by exiting "
            "non-zero. A `pi` session was wedged 4h32m on exactly this on 2026-08-10 — the "
            "verifier's browser was never closed, so Node's event loop never drained.\n"
            "Fix:\n"
            "  timeout 180 <your command>    # bound it, then read the exit code\n"
            "  <your command> &              # or background it, so the harness tracks it\n"
            "Note `cmd | tail` reports TAIL's exit status, so capture the real one first.\n"
        )

    return 0


#: (command, expected exit) — 0 allows, 2 blocks. Every case is a shape that was argued about
#: when the rules were written, so a regex "tidy-up" that changes behaviour fails here first.
#: A hook that nothing tests looks identical, from inside a session, to a hook that works: it
#: fails OPEN, the harness logs it, and the turn proceeds. That is why this exists.
SELFTEST_CASES: list[tuple[str, int]] = [
    # Rule 1: unbounded recursive grep.
    ("grep -r TODO .", 2),
    ("grep -R TODO .", 2),
    ("grep -rn 'foo' src/", 2),
    ("grep -rIl pattern .", 2),
    # ...and its three escapes.
    ("timeout 60 grep -r TODO .", 0),
    ("gtimeout 30s grep -r TODO .", 0),
    ("grep -r --exclude-dir=node_modules TODO .", 0),
    ("grep -r TODO . &", 0),
    ("nohup grep -r TODO .", 0),
    # An OUTPUT filter is not a prune. This is the exact command shape that orphaned three
    # greps on 2026-08-10; the downstream grep reads every byte anyway.
    ("grep -r TODO . | grep -v node_modules", 2),
    # Not recursive, so not this guard's business however slow it is.
    ("grep TODO src/app.py", 0),
    ("rg -n TODO src/", 0),
    # `--include=` narrows what is READ but still walks the tree, so it must not satisfy the
    # prune test on its own. Guarded because the flag looks like an exclusion at a glance.
    ("grep -r --include=*.py TODO .", 2),

    # Rule 2: harnesses whose failure mode is running forever.
    ("npx playwright test", 2),
    ("node puppeteer-check.js", 2),
    ("npm run dev", 2),
    ("pnpm run dev", 2),
    ("next dev", 2),
    ("npx tsx scripts/verify-row-chip.ts 2>&1 | tail -30", 2),  # the 4h32m wedge itself
    ("timeout 180 npx playwright test", 0),
    ("npm run dev &", 0),
    # Neither hang-prone nor recursive.
    ("npm run build", 0),
    ("npm test", 0),
    ("", 0),

    # Rule 3 is not a rule, it is a carve-out: a heredoc BODY is a file being written, not a
    # command. This exact shape was refused on 2026-08-19 while writing a subagent definition
    # whose text told the reader to prefer rg. Nothing recursive was going to run.
    ("cat > a.md <<'EOF'\nuse rg, never a recursive grep -r, it walks the estate\nEOF\n", 0),
    # ...but a shell READING the heredoc executes the body, so that still blocks.
    ("bash <<'EOF'\ngrep -r pattern /\nEOF\n", 2),
]


def _strip_heredocs(cmd: str) -> str:
    """Drop heredoc BODIES before judging, borrowing rule-guard's implementation.

    Found on 2026-08-19: writing a subagent definition whose text recommended rg over a recursive
    search was refused by this guard. Nothing recursive was going to run. The body of
    `cat > file <<'EOF'` is a FILE being written, and every pattern above matches the raw string.
    rule-guard hit the identical class an hour earlier, with a commit message that quoted the rule
    it was explaining. A guard that blocks writing down its own advice is one people learn to
    bypass, and after that it is not a guard.

    rule-guard.py solved this first, and its version carries the carve-out that matters: when a
    shell READS the heredoc (`bash <<EOF`) the body is executed and must still be judged. One
    implementation, imported by path because the module name has a hyphen in it. If the import
    fails the command is judged unstripped, which is the old behaviour -- a guard may be noisy,
    but it may not silently stop guarding.
    """
    try:
        import importlib.util
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rule-guard.py")
        spec = importlib.util.spec_from_file_location("_rule_guard", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.strip_heredocs(cmd)
    except Exception:
        return cmd


def selftest() -> int:
    """Run every case with stderr swallowed, print one line per failure, exit non-zero on any.

    Invoked by `scripts/process_audit.py`, which grades a hook carrying no selftest as WARN and
    a failing one as BAD, so this ends up on the ops console rather than in someone's head.
    """
    import io
    from contextlib import redirect_stderr

    failures = []
    for cmd, want in SELFTEST_CASES:
        with redirect_stderr(io.StringIO()):
            got = check(_strip_heredocs(cmd))
        if got != want:
            failures.append(f"  {cmd!r}\n    want exit {want}, got {got}")
    if failures:
        print(f"hang-guard selftest: {len(failures)}/{len(SELFTEST_CASES)} FAILED")
        print("\n".join(failures))
        return 1
    print(f"hang-guard selftest: {len(SELFTEST_CASES)}/{len(SELFTEST_CASES)} passed")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if os.path.exists(KILL_SWITCH):
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    return check(_strip_heredocs((payload.get("tool_input") or {}).get("command") or ""))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # a broken guard must never break a session
