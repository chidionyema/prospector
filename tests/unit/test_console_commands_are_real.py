"""Every console button must name something that actually runs.

WHY THIS EXISTS. The "Operator state and quotas" button on /engine shipped with
`cmd=".venv/bin/python -m prospector.run operator"`. There is no `operator` subcommand; the CLI
takes `operators`. Pressing the button printed:

    prospector.run: error: argument command: invalid choice: 'operator'
    (choose from 'vet', 'signal', 'generate', 'replicate', 'consume', 'discover', 'report',
     'diagnose', 'operators', 'lanes', 'markets')

Nothing caught it, because the registry's existing tests check the tool's `path`, its id, its risk
and its undo coverage. None of them read `cmd`, which is the only field a button actually executes.
A one-letter typo in a string is exactly the defect a test should own, so this file reads the verb.

It pins the CLASS rather than the line: it walks the whole registry, and for each command works out
what that command would have to find on disk to run at all.
"""
from __future__ import annotations

import ast
import shlex
from pathlib import Path

from prospector.ops import console_api as api

REPO = Path(__file__).resolve().parent.parent.parent


def _run_subcommands() -> set[str]:
    """The subcommands `python -m prospector.run` accepts, read from its own parser.

    Read by AST, not regex: three of the eleven `sub.add_parser(...)` calls put the name on the
    line after the paren, so a line-oriented grep silently misses `report`, `consume` and
    `markets` and the test passes while claiming they are invalid."""
    tree = ast.parse((REPO / "prospector" / "run.py").read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_parser"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "sub"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            names.add(node.args[0].value)
    return names


def _commands() -> list[tuple[str, str]]:
    """(tool id, command string) for every registry row.

    The field is `command`, not `cmd`. `_t(..., cmd=...)` is the CONSTRUCTOR argument; the dict it
    returns renames it, and defaults it to `.venv/bin/python <path>` when the caller passes none.
    The first draft of this file read `t["cmd"]`, matched nothing, and all four tests passed over an
    empty list while the broken button sat in the registry three lines away."""
    return [(t["id"], t["command"]) for t in api.TOOLS if t.get("command")]


def test_the_parser_scan_finds_the_real_subcommands():
    """Guard the guard. If this list ever comes back empty or short, every assertion below
    becomes vacuous and the console can ship a broken button again."""
    subs = _run_subcommands()
    assert {"vet", "generate", "operators", "report", "consume", "markets"} <= subs, subs
    assert len(subs) >= 10, subs


def test_the_registry_scan_actually_reads_commands():
    """The other half of the same guard. An empty command list makes every assertion below pass
    while proving nothing, which is exactly how the first draft of this file behaved."""
    cmds = _commands()
    assert len(cmds) >= 25, f"only {len(cmds)} commands read from the registry"
    runs = [c for _, c in cmds if "-m prospector.run " in c]
    assert len(runs) >= 8, runs


def test_every_run_subcommand_in_the_console_is_one_the_cli_accepts():
    subs = _run_subcommands()
    bad = []
    for tid, cmd in _commands():
        parts = shlex.split(cmd)
        if "-m" not in parts:
            continue
        mod = parts[parts.index("-m") + 1]
        if mod != "prospector.run":
            continue
        rest = parts[parts.index(mod) + 1:]
        verb = next((p for p in rest if not p.startswith("-")), "")
        if verb not in subs:
            bad.append(f"{tid}: `{cmd}` -> '{verb}' is not a subcommand")
    assert not bad, "console buttons that cannot run:\n  " + "\n  ".join(bad)


def test_every_module_a_console_button_runs_is_importable_on_disk():
    """`-m some.module` fails at import time, not at argparse time, so it fails the same way:
    the operator presses a button and reads a traceback."""
    missing = []
    for tid, cmd in _commands():
        parts = shlex.split(cmd)
        if "-m" not in parts:
            continue
        mod = parts[parts.index("-m") + 1]
        rel = Path(*mod.split("."))
        if not (REPO / rel).with_suffix(".py").exists() and not (REPO / rel / "__main__.py").exists():
            missing.append(f"{tid}: `{cmd}` -> no module {mod}")
    assert not missing, "console buttons naming a module that is not here:\n  " + "\n  ".join(missing)


def test_every_script_a_console_button_runs_exists():
    """The same check for the shell-script and plain-file rows, which never reach argparse.

    SCOPED TO THE REPO ON 2026-08-19. A command may name a script this checkout does not ship —
    `~/.hermes/scripts/hermes_selfcheck.py` is the first — and whether that file is present is a
    fact about one machine. Grading it here passed on the laptop and turned CI red, for a file
    no push had touched. EXISTENCE IS ONLY ASSERTABLE INSIDE THE REPO; the console measures the
    rest at runtime and reports the button unavailable, which is where a machine fact belongs.
    """
    missing = []
    for tid, cmd in _commands():
        for part in shlex.split(cmd):
            if not (part.endswith((".py", ".sh")) and "/" in part and not part.startswith("-")):
                continue
            if Path(part).expanduser().is_absolute():
                continue  # not this checkout's to grade
            if not (REPO / part).exists():
                missing.append(f"{tid}: `{cmd}` -> no file {part}")
    assert not missing, "console buttons naming a file that is not here:\n  " + "\n  ".join(missing)
