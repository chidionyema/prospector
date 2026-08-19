"""A workflow step may not throw away the only evidence of its own failure.

THE FAILURE. 2026-08-19, chidionyema/hermes-config run 32268561071, step "Fetch the pinned
hermes-agent": ``Process completed with exit code 127``, 13 milliseconds after the step started,
and not one other line of output. Exit 127 is "command not found", and the command was
``ssh-keyscan``, which the runner image did not carry. The message that says so went to stderr,
and the line was::

    ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null

GitHub runs ``run:`` under ``/usr/bin/bash -e``, so that command's exit status IS the step's exit
status. The redirect discarded the sentence that named the cause while keeping the failure. What
reached the operator was a bare number.

THE CLASS. **Discarding stderr on a command whose exit status is load-bearing.** Not "ssh-keyscan
was missing" — any command can be absent, wrong-versioned or unhappy about its arguments, and
every one of them explains itself on stderr and nowhere else. A step shaped like this is
undiagnosable by construction, and the diagnosis is what costs the hours.

WHAT IS STILL ALLOWED, and why each is not the trap:

* ``2>&1`` merges rather than discards. The evidence survives.
* ``cmd 2>/dev/null || fallback`` handles the failure itself, so the step does not die and there
  is nothing to diagnose.
* ``cmd 2>/dev/null | other`` — without ``pipefail`` a non-final command's status is discarded by
  the pipe, not by the redirect, so the step survives regardless. If the script sets ``pipefail``
  that stops being true, and this checks for it.
* An explicit ``# stderr-ok: <reason>`` on the line. An engineer who has thought about it can say
  so; the point is that it cannot happen by accident.

Companion guard: ``scripts/ci_fleet_probe.py::image_staleness``, which catches the OTHER half of
the same incident — the fleet was running an image older than the Dockerfile that declares
openssh-client. Neither guard is sufficient alone. This one makes the failure legible; that one
stops it happening.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# `2>&1` must NOT match: merging stderr into stdout keeps the evidence.
DISCARDS_STDERR = re.compile(r"2>\s*(?:/dev/null|&-)")
HANDLED = re.compile(r"\|\||#\s*stderr-ok:")


def _logical_lines(script: str) -> list[tuple[int, str]]:
    """Join backslash continuations, so a wrapped command is judged as one command."""
    out: list[tuple[int, str]] = []
    buf, start = "", 0
    for n, raw in enumerate(script.splitlines(), start=1):
        line = raw.rstrip()
        if not buf:
            start = n
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        out.append((start, buf + line))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def _run_steps() -> list[tuple[str, str]]:
    """Every `run:` script in every workflow, as (where, script)."""
    found: list[tuple[str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for job_id, job in (doc.get("jobs") or {}).items():
            for i, step in enumerate(((job or {}).get("steps") or [])):
                script = (step or {}).get("run")
                if isinstance(script, str):
                    name = (step or {}).get("name") or f"step {i}"
                    found.append((f"{path.name}:{job_id}:{name}", script))
    return found


def test_no_step_discards_the_stderr_that_would_explain_its_own_death():
    steps = _run_steps()

    # A guard that iterates an empty list passes and proves nothing. If the workflows move, or
    # the YAML stops parsing, this must fail rather than go quietly green.
    assert steps, f"no `run:` steps found under {WORKFLOWS} — this guard has stopped grading"

    offenders = []
    for where, script in steps:
        pipefail = "pipefail" in script
        for lineno, line in _logical_lines(script):
            if not DISCARDS_STDERR.search(line) or HANDLED.search(line):
                continue
            # Without pipefail, a pipe already discards a non-final command's status, so the
            # redirect is not what hides the failure and the step does not die here.
            if "|" in DISCARDS_STDERR.sub("", line) and not pipefail:
                continue
            offenders.append(f"  {where} (line {lineno} of the script): {line.strip()}")

    assert not offenders, (
        "these steps discard stderr on a command whose failure kills the step, so the step can "
        "only ever report a bare exit code (this is how hermes-config run 32268561071 reported "
        "`exit code 127` and nothing else). Merge with `2>&1`, handle it with `|| ...`, or say "
        "why with a trailing `# stderr-ok: <reason>`:\n" + "\n".join(offenders)
    )


def test_the_check_recognises_the_line_that_produced_it():
    """The real line must be caught, and the safe shapes must not be."""
    caught = "ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null"
    assert DISCARDS_STDERR.search(caught) and not HANDLED.search(caught)

    for safe in (
        "ssh-keyscan github.com >> ~/.ssh/known_hosts 2>&1",
        "sysctl -n vm.swapusage 2>/dev/null || echo n/a",
        "ssh-keyscan github.com 2>/dev/null  # stderr-ok: optional warm-up, checked below",
    ):
        assert not (DISCARDS_STDERR.search(safe) and not HANDLED.search(safe)), safe


def test_a_wrapped_command_is_judged_as_one_command():
    """`cmd \\` + `  || true` on the next line is handled, and must not be reported."""
    joined = dict(_logical_lines("ssh-keyscan github.com 2>/dev/null \\\n  || true\n"))
    assert HANDLED.search(joined[1]), joined
