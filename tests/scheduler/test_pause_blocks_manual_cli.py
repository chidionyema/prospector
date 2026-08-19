"""The `PAUSE` kill switch must stop a HAND-RUN batch, not just the daemon.

WHY THIS FILE EXISTS (2026-08-13). `store/scheduler/PAUSE` is one of the two automated rails
that CLAUDE.md says replace human supervision for unattended generation. It was read only by
`prospector/scheduler/run_scheduled.py`: `rg -c PAUSE prospector/run.py` returned **0**. So the
documented stop procedure ("touch store/scheduler/PAUSE") halted the daemon and left every
manual `python -m prospector.run generate|vet|signal|discover|replicate` free to spend from the
same rails, call the same brains and append to the same store.

The gate is tested THROUGH THE CLI, not by calling `pause_block_reason` directly. A unit test on
the helper passes just as happily when the helper is wired into nothing — which is precisely the
state this file exists to make impossible. (Memory: `preflight-must-be-the-gates-own-command`,
`measure-the-violation-not-the-property`.)

`PROSPECTOR_STORE_DIR` redirects the store so the subprocess cannot touch the live one
(`prospector/config.py:531`, `scheduler/paths.py`).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Every command that calls a brain or writes a dossier, with the MINIMUM argv argparse will
#: accept. Kept explicit rather than derived from run.py, so ADDING a spending subcommand
#: without gating it fails here instead of shipping.
#:
#: The argv must be otherwise-valid on purpose: argparse rejects a missing required flag with
#: rc=2 long before main() reaches the gate, so a test built on bare subcommands would go green
#: on a usage error and prove nothing about PAUSE.
GATED = {
    "vet": ["vet", "--title", "x", "--one-liner", "y"],
    "signal": ["signal", "--text", "x"],
    "generate": ["generate"],
    "discover": ["discover"],
    "replicate": ["replicate", "--from", "uk"],
}


def _run(store: Path, argv: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PROSPECTOR_STORE_DIR"] = str(store)
    # Belt and braces: if the gate ever fails open, a mock operator keeps the escape cheap and
    # offline instead of spending real budget inside a test run.
    env["PROSPECTOR_OPERATOR"] = "mock"
    return subprocess.run([sys.executable, "-m", "prospector.run", *argv],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=180)


@pytest.fixture()
def paused_store(tmp_path: Path) -> Path:
    (tmp_path / "scheduler").mkdir(parents=True)
    (tmp_path / "scheduler" / "PAUSE").write_text("", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("command", sorted(GATED))
def test_pause_refuses_every_spending_command(paused_store: Path, command: str):
    """A paused engine refuses the manual entrypoints, with a non-zero, distinguishable code."""
    proc = _run(paused_store, GATED[command])
    assert proc.returncode == 3, (
        f"{command!r} ran under PAUSE (rc={proc.returncode}).\n"
        f"stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}")
    assert "PAUSE" in proc.stderr, proc.stderr[-2000:]


def test_pause_names_the_file_and_how_to_lift_it(paused_store: Path):
    """A stop switch you cannot find is a stop switch you power-cycle around."""
    proc = _run(paused_store, ["generate"])
    assert str(paused_store / "scheduler" / "PAUSE") in proc.stderr, proc.stderr[-2000:]
    assert "rm " in proc.stderr, proc.stderr[-2000:]


def test_pause_does_not_blind_the_operator(paused_store: Path):
    """Read-only commands still work while paused — that is how you learn WHY it is paused."""
    proc = _run(paused_store, ["lanes", "list"])
    assert proc.returncode != 3, (
        "a read-only command was blocked by the kill switch; an operator who cannot inspect "
        f"the engine will lift the switch to see it.\nstderr: {proc.stderr[-2000:]}")


def test_helper_is_silent_when_not_paused(tmp_path: Path, monkeypatch):
    """`None` means 'not paused' — the value callers branch on.

    `monkeypatch.setenv` rather than a raw `os.environ` write with a `finally`: the finally was
    correct, but the shape is the one that poisons a whole xdist worker the day someone adds an
    early `return` or a second assignment above it. PROSPECTOR_STORE_DIR beats `cfg.store["dir"]`
    in `Config.store_dir`, so a leak of it silently redirects every later test's store.
    """
    from prospector.config import load_config
    from prospector.scheduler.guard import pause_block_reason

    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path))
    cfg = load_config(str(REPO / "config.yaml"))
    assert pause_block_reason(cfg) is None
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scheduler" / "PAUSE").write_text("", encoding="utf-8")
    reason = pause_block_reason(cfg)
    assert reason and "PAUSED" in reason
