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
