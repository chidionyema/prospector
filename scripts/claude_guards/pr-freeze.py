#!/usr/bin/env python3
"""Refuse to open a NEW pull request while a PR freeze is in force.

Founder directive 2026-08-19, during the queue emergency: "can we lock new prs until this is
resolved". Thirty-one open PRs against an eleven-runner fleet whose python job takes ~26 minutes.
Every merge to main invalidates the other thirty, so each costs a fresh full run: the work grows
pairwise while the pipe stays fixed, and the queue cannot drain. One more PR makes it worse.

Sessions share this estate and cannot see each other, so a note in a doc reaches nobody. This is a
PreToolUse hook, which every session on this machine passes through.

The freeze is a FILE, so the founder turns it off with `rm`, not by editing a script:

    ~/.claude/PR_FREEZE      exists => frozen. Its text is shown to whoever is refused.

What is still allowed while frozen, because none of it adds a branch to the queue:
  - pushing commits, including to the integration branch
  - `gh pr edit`, `gh pr merge`, `gh pr view`, `gh pr list`, `gh pr comment`
  - opening a PR whose head IS the integration branch named in the freeze file
"""
import json
import os
import re
import sys

FREEZE = os.path.expanduser("~/.claude/PR_FREEZE")

# `gh pr create` in any spelling, and the REST call that does the same thing.
CREATE_RE = re.compile(r"\bgh\s+pr\s+create\b")
API_RE = re.compile(r"\bgh\s+api\b.*?\brepos/[^\s]+/pulls\b")
REOPEN_RE = re.compile(r"\bgh\s+pr\s+reopen\b")


def _head_branch(cmd: str) -> str:
    m = re.search(r"--head[= ]+([^\s'\"]+)", cmd)
    return m.group(1) if m else ""


def _allowed_head(text: str) -> str:
    """The branch the freeze file names as the one PR that is still allowed."""
    m = re.search(r"(?im)^\s*Allow-Head:\s*(\S+)", text)
    return m.group(1) if m else ""


def check(cmd: str) -> str | None:
    if not os.path.exists(FREEZE):
        return None
    if not (CREATE_RE.search(cmd) or API_RE.search(cmd) or REOPEN_RE.search(cmd)):
        return None
    try:
        with open(FREEZE, encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError:
        text = ""
    allowed = _allowed_head(text)
    if allowed and _head_branch(cmd) == allowed:
        return None
    return (
        "BLOCKED by pr-freeze: new pull requests are frozen.\n"
        + (text or "No reason recorded in ~/.claude/PR_FREEZE.")
        + "\n\nStill allowed: pushing commits, gh pr edit/merge/view/list/comment, and opening a PR"
        + (f" whose --head is {allowed}." if allowed else ".")
        + "\nPut your change on the open integration branch instead of a new PR."
        + f"\nThe founder lifts this with: rm {FREEZE}"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "")
    message = check(cmd)
    if message is None:
        return 0
    print(message, file=sys.stderr)
    return 2


def selftest() -> int:
    cases = [
        ("gh pr create --title x --body y", True),
        ("gh pr create --head integrate/all-open --title x", False),
        ("gh api repos/chidionyema/prospector/pulls -f title=x", True),
        ("gh pr reopen 400", True),
        ("gh pr edit 451 --body-file b.md", False),
        ("gh pr merge 451 --squash", False),
        ("gh pr list --state open", False),
        ("git push origin integrate/all-open", False),
    ]
    bad = 0
    for cmd, want_block in cases:
        got = check(cmd) is not None
        if got != want_block:
            print(f"FAIL {cmd!r}: blocked={got}, want={want_block}")
            bad += 1
    print("selftest: " + ("OK" if not bad else f"{bad} failed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
