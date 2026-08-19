"""The runner image declares every tool our workflows call.

The failure this pins is a bare exit 127 in CI with no message: our runners are a container we
build, so a step written against GitHub's ubuntu-latest can be missing a command here and say
nothing about it. `scripts/ci_runner_tools.py` is the guard; these tests are the guard on the
guard, because a checker that cannot fail is not a checker.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci_runner_tools.py"
DOCKERFILE = REPO_ROOT / "deploy" / "runner" / "Dockerfile"


def _load():
    spec = importlib.util.spec_from_file_location("ci_runner_tools", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_real_dockerfile_declares_every_required_package():
    mod = _load()
    declared = mod.declared_packages(DOCKERFILE)
    missing = {package for _, (package, _) in mod.REQUIRED.items() if package not in declared}
    assert not missing, f"deploy/runner/Dockerfile does not install: {sorted(missing)}"


def test_openssh_client_specifically(tmp_path):
    """Named on its own because its absence is silent.

    `ssh-keyscan ... 2>/dev/null` sends the shell's own "command not found" to /dev/null, so
    the hermes-config gate failed in 17ms with an exit code and zero output (run 32267152679).
    A generic "some package is missing" assertion would have been satisfied by any other row.
    """
    mod = _load()
    assert "openssh-client" in mod.declared_packages(DOCKERFILE)


def test_a_dockerfile_missing_a_package_fails_the_parse_based_check(tmp_path, monkeypatch):
    mod = _load()
    stripped = DOCKERFILE.read_text().replace("openssh-client", "")
    fake = tmp_path / "Dockerfile"
    fake.write_text(stripped)
    declared = mod.declared_packages(fake)
    assert "openssh-client" not in declared
    assert "git" in declared, "the parser must still see the packages that ARE there"


def test_the_parser_stops_at_the_first_ampersand():
    """`locale-gen` and `rm` follow the install on the same continued line.

    Read naively they look like package names, which would make the checker report success for
    a package called `locale-gen` that no apt repository has ever carried.
    """
    mod = _load()
    declared = mod.declared_packages(DOCKERFILE)
    for word in ("locale-gen", "rm", "en_GB.UTF-8", "/var/lib/apt/lists/*"):
        assert word not in declared, f"the parser read `{word}` as a package"


def test_the_script_exits_zero_on_the_repository_as_it_stands():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_present_check_is_skipped_on_a_github_hosted_runner(monkeypatch, capsys):
    """A pass on ubuntu-latest must not read as a pass for our image.

    ubuntu-latest carries all twelve binaries, so grading PATH there is a guaranteed green
    that says nothing about the container we ship. The check reports NOT APPLICABLE instead.
    """
    mod = _load()
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    assert mod.hosted_runner() is True
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    assert mod.hosted_runner() is False


def _run(*args: str, path: str | None = None) -> subprocess.CompletedProcess:
    """Run the guard as a subprocess with a chosen PATH.

    Emptying PATH is how "the fleet is running an older image" is reproduced without a fleet:
    every declared binary becomes un-findable, which is exactly the state the guard must
    classify as an operator action rather than a code defect.
    """
    env = {"RUNNER_ENVIRONMENT": "self-hosted"}
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_a_stale_fleet_does_not_wall_the_pull_request_gate():
    """The first version of this guard failed the pull request that fixed the image.

    A binary that is DECLARED in deploy/runner/Dockerfile but absent from PATH means the
    running machines predate the Dockerfile. No pull request can change that; only an operator
    running `deploy/runners.sh up` can. If the gate failed here it would block every pull
    request in the repository, including the deploy that clears it, so it must not.
    """
    result = _run(path="")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning title=Runner fleet is stale::" in result.stdout
    assert "ssh: not on PATH" in result.stdout
    assert "deploy/runners.sh up" in result.stdout
    assert "PASSING ANYWAY" in result.stdout


def test_strict_makes_a_stale_fleet_fatal():
    """--strict is what the fleet probe runs, where an operator reads the answer."""
    result = _run("--strict", path="")
    assert result.returncode == 1
    assert "THE RUNNING FLEET IS OLDER THAN THE RUNNER DOCKERFILE" in result.stderr
    assert "ssh: not on PATH" in result.stderr


def test_an_undeclared_package_is_fatal_even_without_strict(monkeypatch, capsys):
    """The one failure a pull request CAN fix stays fatal in the gate.

    Proved by injecting a row for a package no Dockerfile line installs, which is the same
    defect as deleting a package from the image. PATH is left alone, so a non-zero exit here
    can only have come from the declaration lane.
    """
    mod = _load()
    mod.REQUIRED["notarealbinary"] = ("definitely-not-a-real-package", "injected by a test")
    monkeypatch.setattr(sys, "argv", ["ci_runner_tools.py"])
    monkeypatch.delenv("RUNNER_ENVIRONMENT", raising=False)
    assert mod.main() == 1
    captured = capsys.readouterr()
    assert "definitely-not-a-real-package" in captured.err
    assert "deploy/runner/Dockerfile" in captured.err


def test_the_declaration_lane_runs_on_a_hosted_runner_too(monkeypatch):
    """An undeclared package must fail on ubuntu-latest as well.

    Otherwise the guard only speaks on our own fleet, and the fleet is exactly what is stale
    when it matters. RUNNER_ENVIRONMENT is set to github-hosted here, which switches the PATH
    lane off, and the exit code must still be 1.
    """
    mod = _load()
    mod.REQUIRED["notarealbinary"] = ("definitely-not-a-real-package", "injected by a test")
    monkeypatch.setattr(sys, "argv", ["ci_runner_tools.py"])
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    assert mod.main() == 1
