"""The Fly adapter must work when the CLI is installed as `flyctl` only.

The binary answers to two names and the environment decides which exists. Homebrew installs
`flyctl` plus a `fly` symlink, so a laptop has both. The `superfly/flyctl-actions/setup-flyctl`
action used by .github/workflows/escape-hatch-drill.yml and deploy-engine.yml installs only
`flyctl`. Every call in deploy/targets/fly.sh says `fly`.

On 2026-08-19 that killed the weekly escape hatch drill at its first step:
`deploy/targets/fly.sh: line 106: fly: command not found`, exit 127. The drill that proves we can
leave the platform could not run because of the name of a binary.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[2] / "deploy" / "targets" / "fly.sh"


def _sandbox(tmp_path: Path, *, name: str) -> Path:
    """A PATH holding the CLI under ONE name, plus the shell builtins the adapter needs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / name
    stub.write_text('#!/bin/sh\necho "stub $*"\n')
    stub.chmod(0o755)
    return bin_dir


def _probe(bin_dir: Path, script: str) -> subprocess.CompletedProcess:
    """Source the adapter with a restricted PATH and run `script` against it.

    Sourcing is deliberate: the adapter only dispatches a verb when it is EXECUTED
    (`[ "${BASH_SOURCE[0]}" = "${0}" ]`), so sourcing defines the functions and calls nothing.
    """
    return subprocess.run(
        ["bash", "-c", f'source "{ADAPTER}" >/dev/null 2>&1; {script}'],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(bin_dir.parent)},
        capture_output=True, text=True, timeout=60, check=False,
    )


def test_fly_is_reachable_when_only_flyctl_is_installed(tmp_path):
    bin_dir = _sandbox(tmp_path, name="flyctl")
    assert not (bin_dir / "fly").exists(), "the point of this test is that `fly` is absent"

    got = _probe(bin_dir, "fly version")

    assert got.returncode == 0, f"the adapter cannot reach the CLI: {got.stderr.strip()}"
    assert "stub version" in got.stdout, got.stdout


def test_the_preflight_accepts_a_flyctl_only_environment(tmp_path):
    """`command -v fly` is what the adapter's preflight asks. The shim must satisfy it."""
    bin_dir = _sandbox(tmp_path, name="flyctl")

    got = _probe(bin_dir, "command -v fly >/dev/null && echo reachable")

    assert got.stdout.strip() == "reachable", got.stderr.strip()


def test_a_real_fly_binary_is_left_alone(tmp_path):
    """Where `fly` exists the shim must not shadow it -- Homebrew laptops keep working."""
    bin_dir = _sandbox(tmp_path, name="fly")

    got = _probe(bin_dir, "type -t fly")

    assert got.stdout.strip() == "file", f"the shim shadowed the real binary: {got.stdout!r}"
