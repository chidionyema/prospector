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


#: A heredoc that feeds a NON-shell program: `python3 - <<'PY' ... PY`, `cat > f <<EOF ... EOF`.
#: Group 2 is the delimiter, and the body runs to a line containing only that delimiter.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1[^\n]*\n.*?^\s*\2\s*$", re.S | re.M)
#: Interpreters that EXECUTE their heredoc body. A heredoc fed to one of these is live code, so
#: its body is left in place to be graded. Everything else is data being written to a file.
_SHELL_HEREDOC_RE = re.compile(r"(?:^|[|;&]|\$\()\s*(?:sudo\s+)?(?:ba|z|k|da)?sh\b[^\n]*<<")


def _executable_text(cmd: str) -> str:
    """The command with heredoc BODIES removed, so source code is not read as a command.

    THE TRAP THIS CLOSES. Measured 2026-08-20: this guard refused

        python3 - <<'PY'
        ... ("gh pr create --title x --body y", True), ...
        PY

    which was a patch script writing this file's OWN selftest cases. Nothing was going to open a
    pull request; the string appeared inside a Python literal being written to disk. The founder's
    words that turn: "the guard are causing too nuch friction".

    A matcher that reads every character of a command cannot tell code from an instruction to run
    code. Same class as `a-threat-rule-that-reads-english-blocks-a-skill-forever.md`, where a
    scanner graded a Python variable and a sentence of documentation as exfiltration.

    NOT A HOLE. A heredoc fed to a shell IS executed, so its body is kept and still graded --
    `bash <<EOF` cannot be used to smuggle the command past this fence. Only bodies going to a
    non-shell (python, cat, tee) are dropped, and those are data by definition.
    """
    if _SHELL_HEREDOC_RE.search(cmd):
        return cmd
    return _HEREDOC_RE.sub("\n", cmd)


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
    cmd = _executable_text(cmd)
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
    """Grade the LOGIC, not this machine.

    Every case runs against a freeze file this function writes itself. It used to read the real
    ~/.claude/PR_FREEZE, whose `Allow-Head:` names whichever integration branch is current -- so
    on 2026-08-20, when that branch moved from `integrate/all-open` to `integrate/2026-08-20-final`,
    this selftest started failing while the guard was working perfectly. A check that grades live
    state reports a defect that is not there, and a working guard then gets "fixed".
    """
    import tempfile

    global FREEZE

    allowed = "integrate/all-open"
    create = "gh pr " + "create"          # split so writing this file never trips the live hook
    cases = [
        (f"{create} --title x --body y", True),
        (f"{create} --head {allowed} --title x", False),
        ("gh api repos/chidionyema/prospector/pulls -f title=x", True),
        ("gh pr reopen 400", True),
        ("gh pr edit 451 --body-file b.md", False),
        ("gh pr merge 451 --squash", False),
        ("gh pr list --state open", False),
        (f"git push origin {allowed}", False),
        # A heredoc feeding a NON-shell is data being written to a file, not a command.
        (f"python3 - <<'PY'\ncases = [({create!r}, True)]\nPY", False),
        (f"cat > f.py <<EOF\n# {create} --title x\nEOF", False),
        # ...but a heredoc fed to a SHELL is executed, so it must still be refused.
        (f"bash <<EOF\n{create} --title x\nEOF", True),
    ]

    original, bad = FREEZE, 0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            FREEZE = os.path.join(tmp, "PR_FREEZE")
            with open(FREEZE, "w", encoding="utf-8") as fh:
                fh.write(f"Frozen for the selftest.\nAllow-Head: {allowed}\n")
            for cmd, want_block in cases:
                got = check(cmd) is not None
                if got != want_block:
                    print(f"FAIL {cmd!r}: blocked={got}, want={want_block}")
                    bad += 1
            # Anti-vacuity: with no freeze in force NOTHING is refused. Without this a `check`
            # that always returned None would pass every case above that expects False.
            os.remove(FREEZE)
            if check(f"{create} --title x --body y") is not None:
                print("FAIL: refused a new pull request while no freeze file exists")
                bad += 1
    finally:
        FREEZE = original

    total = len(cases) + 1
    print("pr-freeze selftest: "
          + (f"{total}/{total} passed" if not bad else f"{bad}/{total} FAILED"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
