"""No shell script may depend on a utility this project's host does not have.

Origin (2026-07-31): a single-instance lock was added to
`tools/backfill_missing_listings.sh` as `if ! flock -n 9; then echo already running; exit 3; fi`.
`flock(1)` does not exist on macOS, which is this project's only host. A missing command exits
**127**, and `if !` reads any non-zero as the true branch — so the guard reported "already
running" and refused to start the backfill on **every single run**, while looking like it was
working exactly as designed. The sibling trap, `setsid`, aborts the script under `set -e`.

That is the failure class this file guards: an absent utility whose exit code is
indistinguishable from a meaningful result. It is deliberately repo-wide rather than pinned to
the one script that had the bug — the bug was a habit, not a file.

Note that homebrew coreutils IS installed here (`timeout`, `realpath`, `nproc`, `md5sum`, `tac`
all resolve under /usr/local/bin), so the denylist is specifically util-linux binaries, which
homebrew keeps keg-only and therefore off PATH even when the formula is installed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Utilities that are NOT on macOS and are not made available by installing coreutils.
# Each maps to the portable replacement this repo uses, so a failure tells you what to do.
LINUX_ONLY = {
    "flock": "use fcntl.flock inside Python (see tools/_backfill_driver.py)",
    "setsid": "use bash `set -m` job control to get a new process group",
    "taskset": "no macOS equivalent; drop the affinity pin",
    "ionice": "no macOS equivalent; drop it",
    "pidof": "use `pgrep -f`",
    "free": "use `vm_stat`",
    "lsb_release": "use `sw_vers`",
}


# A utility is "used" only in COMMAND position: at the start of a line, after a separator, or
# after a keyword that introduces a command. The keyword arm is not optional decoration — the
# line that actually shipped was `if ! flock -n 9`, where the character before the utility is a
# plain space, so a separator-only matcher misses the one case this whole file exists for.
_KEYWORDS = "if|while|until|then|else|elif|do|!|time|exec|nohup|sudo|eval"


def command_position(util: str) -> re.Pattern[str]:
    return re.compile(rf"(?:^|[|&;(`{{]|\$\()\s*(?:(?:{_KEYWORDS})\s+)*{util}(?:\s|$)")


def _tracked_shell_scripts() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.sh"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / p for p in out.split("\0") if p]


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Numbered lines with comments and heredoc bodies stripped.

    Comments matter: every one of these scripts documents the trap in prose, and a naive grep
    would fire on the explanation rather than on real usage.
    """
    lines: list[tuple[int, str]] = []
    heredoc_terminator: str | None = None
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if heredoc_terminator is not None:
            if raw.strip() == heredoc_terminator:
                heredoc_terminator = None
            continue
        m = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z_0-9]*)'?", raw)
        if m:
            heredoc_terminator = m.group(1)
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((n, raw.split(" #")[0]))
    return lines


def test_there_are_shell_scripts_to_check():
    """A silent zero-file sweep would make every test below vacuously pass."""
    assert len(_tracked_shell_scripts()) >= 10


@pytest.mark.parametrize("util,replacement", sorted(LINUX_ONLY.items()))
def test_no_tracked_script_invokes_a_linux_only_utility(util, replacement):
    pattern = command_position(util)
    offenders = [
        f"{path.relative_to(ROOT)}:{n}: {text.strip()}"
        for path in _tracked_shell_scripts()
        for n, text in _code_lines(path)
        if pattern.search(text)
    ]
    assert not offenders, (
        f"{util}(1) does not exist on macOS, this project's host — "
        f"{replacement}.\n" + "\n".join(offenders)
    )


def test_the_guard_actually_catches_the_original_bug(tmp_path):
    """Meta-test: the sweep above is only worth anything if it fires on the real regression.

    Reproduces the exact line that shipped, and asserts the matcher flags it. The first version
    of this matcher did NOT — `if ! flock` puts a space, not a separator, before the utility —
    and this assertion is what caught that.
    """
    pattern = command_position("flock")
    for line in (
        "if ! flock -n 9; then",                 # verbatim, the line that shipped
        "flock -x /tmp/lock -c 'echo hi'",
        "mkdir -p x && flock -n 9",
        "while ! flock -w 5 9; do sleep 1; done",
        "exec flock -n 200 -- true",
    ):
        assert pattern.search(line), line

    # ...and does not fire on prose, on a capability probe, or on the Python API that IS the fix.
    for line in (
        "_lock_handle = fcntl.flock(fd, LOCK_EX)",
        'echo "the flock utility is absent on macOS"',
        "command -v flock >/dev/null || true",
    ):
        assert not pattern.search(line), line


# ---------------------------------------------------------------------------------------------
# A second member of the same class: a line that reads as documentation and executes as a command.

#: Characters a hand-drawn section rule is made of. A first word built only from these is never a
#: command anyone meant to run.
RULE_CHARS = set("-=*_~+.")


def _bare_rule_lines(path: Path) -> list[tuple[int, str]]:
    """Code lines whose command word is a punctuation rule that lost its `#`."""
    out = []
    for n, text in _code_lines(path):
        first = text.strip().split()[0] if text.strip() else ""
        if len(first) >= 3 and set(first) <= RULE_CHARS:
            out.append((n, text.strip()))
    return out


def test_no_tracked_script_has_a_section_rule_that_lost_its_comment_marker():
    """A separator missing its `#` is a command, and `bash -n` says the file is fine.

    Measured 2026-08-19: `scripts/setup_worktree.sh:185` was
    `---------------------------------------------------------------- 6. the warnings`, the only
    one of that file's eight section rules without a leading `# `. Every other check passed it:
    the syntax is valid, so `bash -n` returned 0, and the file ran correctly right up to that
    line. Then `set -euo pipefail` killed it with `command not found` and exit **127** — after
    all the setup work was done, but before `echo "==> worktree ready."`.

    So every agent following the documented worktree procedure in CLAUDE.md got a non-zero exit
    and concluded setup had failed, on a worktree that was in fact complete. The warnings block
    on the next 20 lines never printed either, so the three traps it exists to teach — never
    `git add -A` here, `npm run build | tail` reports tail's status, delete `.pyc` after a
    `worktree move` — were silently withheld from the person who most needed them.

    Same class as the `flock` bug above: an exit code that means "this line is not a command"
    is indistinguishable from an exit code that means something about the work.
    """
    offenders = [
        f"{path.relative_to(ROOT)}:{n}: {text}"
        for path in _tracked_shell_scripts()
        for n, text in _bare_rule_lines(path)
    ]
    assert not offenders, (
        "these lines are section rules that lost their leading `# `, so the shell will try to "
        "run them and the script dies with exit 127 under `set -e`:\n  " + "\n  ".join(offenders)
    )


def test_the_rule_guard_catches_the_line_that_shipped(tmp_path):
    """Meta-test: fire on the real regression, stay quiet on real commands."""
    script = tmp_path / "s.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# ------------------- 1. fine, this one is commented\n"
        "---------------------------------------------------------------- 6. the warnings\n"
        "echo done\n"
    )
    assert [n for n, _ in _bare_rule_lines(script)] == [3]

    # ...and does not fire on flags, case terminators, or a relative path.
    quiet = tmp_path / "q.sh"
    quiet.write_text(
        "#!/usr/bin/env bash\n"
        "--) shift ;;\n"
        "./scripts/thing.sh --flag\n"
        "-\n"
        "cmd -- --end-of-flags\n"
    )
    assert _bare_rule_lines(quiet) == [], _bare_rule_lines(quiet)
