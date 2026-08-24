#!/usr/bin/env python3
"""Refuse a pull request that duplicates another session's claim.

WHY THIS EXISTS. Founder, 2026-08-19: "too many agents fixing the same issues". Measured the
same day across the 21 open pull requests: only 3 of them declared which issue they close.
`gh issue list` showed 0 assignees on 16 of 17 open issues. So there was no machine-readable
record of what any session was working on, and a session that wanted to avoid duplicating work
had nothing to read. Sessions share this estate and cannot see each other, so "check first" is
not a mechanism.

THE CLASS. An agent starts work with no claim any other agent can see. Every fix for one
instance of it (a note, a handoff, a memory file) fails the same way: it reaches one session.

WHAT THIS REFUSES. Two things, at the one moment the intent is unambiguous and cheap to check:

  1. `gh pr create` whose title and body name no issue and no reason for naming none. The
     refusal is what MAKES the claim signal exist -- the guard bootstraps the data it reads.
     The escape hatch is honest and one line: `No-Issue: <why>` in the body.

  2. `gh pr create`, or `gh issue develop`, for an issue that an OPEN pull request already
     closes. That is the duplicate, caught before the second session opens it.

WHAT IT DOES NOT REFUSE, deliberately. Overlap in changed files. `prospector/ops/console_api.py`
is touched by 8 open pull requests right now, all legitimately. A fence on file overlap would be
a false-positive machine, and a fence that cries wolf is one somebody switches off.

FAILS OPEN, ALWAYS. No `gh`, no network, bad JSON, an unparseable command: exit 0. A guard that
blocks work when its own lookup breaks gets removed within the day.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import subprocess
import sys

CLAIM_RE = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b")
NO_ISSUE_RE = re.compile(r"(?im)^\s*No-Issue:\s*\S")
GH_TIMEOUT = 20


def _split_commands(cmd: str) -> list[list[str]]:
    parts: list[list[str]] = []
    # Deliberately NOT splitting on a single `|`: a pipe inside a quoted --body left an
    # unterminated quote, shlex raised, and the whole check was skipped -- a bypass wearing
    # a fail-open coat. `gh pr create ... | tee` still parses with argv[:3] intact.
    for part in re.split(r"&&|\|\||;|\n", cmd):
        try:
            argv = shlex.split(part)
        except ValueError:
            continue
        if argv:
            parts.append(argv)
    return parts


def _opt(argv: list[str], *names: str) -> str:
    """Value of the first of `names` present, supporting --x=v and --x v."""
    for i, tok in enumerate(argv):
        for name in names:
            if tok == name and i + 1 < len(argv):
                return argv[i + 1]
            if tok.startswith(name + "="):
                return tok.split("=", 1)[1]
    return ""


def _pr_text(argv: list[str], cwd: str) -> tuple[str, str]:
    """Everything the author wrote, and the body file that could not be read.

    Returns `(text, unreadable_body_file)`. The second value exists because swallowing the
    OSError produced a refusal with the WRONG REASON. On 2026-08-19 a session wrote the body
    file and created the pull request in ONE Bash command; this hook runs BEFORE that command,
    so the file did not exist yet, the read failed silently, and the fence said "names no
    issue" about a body whose first line was `Closes #454`. The author then re-ran the same
    command and was refused again, identically. A guard that reports a cause it did not
    measure sends the reader to fix the wrong thing.
    """
    # Joined with a NEWLINE, not a space: the No-Issue escape hatch is anchored to the start of
    # a line, and a space-joined title ran straight into the body so the hatch never matched.
    text = "\n".join([_opt(argv, "--title", "-t"), _opt(argv, "--body", "-b")])
    missing = ""
    body_file = _opt(argv, "--body-file", "-F")
    if body_file:
        path = body_file if os.path.isabs(body_file) else os.path.join(cwd, body_file)
        try:
            with open(path, encoding="utf-8") as fh:
                text += "\n" + fh.read()
        except OSError:
            missing = path
    return text, missing


def open_claims(cwd: str) -> dict[int, list[int]] | None:
    """issue number -> open PRs closing it. None when the lookup itself failed."""
    try:
        out = subprocess.run(
            [
                "gh", "pr", "list", "-L", "100", "--state", "open",
                "--json", "number,title,body,closingIssuesReferences",
            ],
            capture_output=True, text=True, timeout=GH_TIMEOUT, cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        prs = json.loads(out.stdout)
    except ValueError:
        return None

    claims: dict[int, list[int]] = {}
    for pr in prs:
        issues = {int(r["number"]) for r in (pr.get("closingIssuesReferences") or [])}
        issues |= {
            int(n)
            for n in CLAIM_RE.findall((pr.get("title") or "") + "\n" + (pr.get("body") or ""))
        }
        for issue in issues:
            claims.setdefault(issue, []).append(int(pr["number"]))
    return claims


def _refuse(message: str) -> int:
    print(f"BLOCKED by dupe-work-fence: {message}", file=sys.stderr)
    return 2


def check(argv: list[str], cwd: str, claims_fn=open_claims) -> int:
    is_pr_create = argv[:3] == ["gh", "pr", "create"]
    is_issue_develop = argv[:3] == ["gh", "issue", "develop"]
    if not (is_pr_create or is_issue_develop):
        return 0

    if is_pr_create:
        text, missing = _pr_text(argv, cwd)
        wanted = {int(n) for n in CLAIM_RE.findall(text)}
        if not wanted:
            if NO_ISSUE_RE.search(text):
                return 0
            if missing:
                return _refuse(
                    f"the body file {missing} does not exist, so this fence cannot read the "
                    "claim.\n"
                    "  This hook runs BEFORE your command. Writing the body file and running "
                    "`gh pr create`\n"
                    "  in the SAME call always fails here: at check time the file is not "
                    "written yet.\n"
                    "  Write the body file in one call, create the pull request in the next."
                )
            return _refuse(
                "this pull request names no issue, so no other session can see the work is "
                "taken.\n"
                "  Add 'Closes #N' to the body, or 'No-Issue: <why>' if it genuinely closes "
                "none.\n"
                "  Measured 2026-08-19: 18 of 21 open PRs named no issue, and five issues were "
                "worked twice."
            )
    else:
        positional = [a for a in argv[3:] if not a.startswith("-")]
        wanted = {int(a.lstrip("#")) for a in positional if a.lstrip("#").isdigit()}
        if not wanted:
            return 0

    claims = claims_fn(cwd)
    if claims is None:
        return 0  # lookup failed; never block on our own outage

    for issue in sorted(wanted):
        others = claims.get(issue) or []
        if others:
            listed = ", ".join(f"#{n}" for n in others)
            return _refuse(
                f"issue #{issue} is already claimed by open pull request(s) {listed}.\n"
                f"  Read it first: gh pr view {others[0]}\n"
                "  If that work is stalled, take it over there. Two pull requests on one issue "
                "is the thing this fence exists to stop."
            )
    return 0


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
    for argv in _split_commands(cmd):
        rc = check(argv, cwd)
        if rc:
            return rc
    return 0


def selftest() -> int:
    """Proves the fence REFUSES. A guard whose test only exercises the allow path is not tested."""
    cases: list[tuple[str, str, dict, int]] = [
        (
            "duplicate claim is refused",
            'gh pr create --title "fix: x" --body "Closes #404"',
            {404: [409]},
            2,
        ),
        (
            "unclaimed issue is allowed",
            'gh pr create --title "fix: x" --body "Closes #421"',
            {404: [409]},
            0,
        ),
        (
            "a PR naming no issue is refused",
            'gh pr create --title "fix: x" --body "some prose"',
            {},
            2,
        ),
        (
            "No-Issue is the escape hatch",
            'gh pr create --title "fix: x" --body "No-Issue: typo in a comment"',
            {},
            0,
        ),
        (
            "an unwritten body file is refused for THAT reason, not for naming no issue",
            'gh pr create --title "fix: x" --body-file /nonexistent/body-not-written-yet.md',
            {},
            2,
            "does not exist",
        ),
        (
            "gh issue develop on a claimed issue is refused",
            "gh issue develop 404 --checkout",
            {404: [409]},
            2,
        ),
        (
            "unrelated commands pass",
            "git status && gh pr view 398",
            {404: [409]},
            0,
        ),
        (
            "a failed lookup never blocks",
            'gh pr create --title "x" --body "Closes #404"',
            None,
            0,
        ),
        (
            "lowercase and past tense are caught",
            'gh pr create --body "resolved #404"',
            {404: [409]},
            2,
        ),
    ]
    failures = []
    for case in cases:
        name, cmd, claims, want = case[:4]
        want_msg = case[4] if len(case) > 4 else ""
        got = 0
        err = io.StringIO()
        for argv in _split_commands(cmd):
            with contextlib.redirect_stderr(err):
                got = check(argv, os.getcwd(), claims_fn=lambda _cwd, c=claims: c)
            if got:
                break
        why = ""
        if got != want:
            why = f"exit {got}, want {want}"
        elif want_msg and want_msg not in err.getvalue():
            why = f"refusal did not say {want_msg!r}: {err.getvalue().strip()[:80]}"
        mark = "ok" if not why else "FAIL"
        if why:
            failures.append(name)
        print(f"  [{mark}] {name}: exit {got} (want {want}){' -- ' + why if why else ''}")
    print(f"dupe-work-fence selftest: {len(cases) - len(failures)}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
