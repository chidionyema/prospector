"""A gate tested only on the case it refuses has not been shown safe to install.

INCIDENT. On 2026-08-23 two guards on this estate refused correct work in one evening: the LAW 32
documentation gate read the first word of a commit subject as the feature name, and the hook
router refused outright in any repository shipping no pre-push, which left four of six
repositories here unable to push at all. Both had been tested on the bad case only.

So this asserts the rule, not the implementation: the ratchet must ALLOW the repository exactly as
it stands, and must REFUSE a change that adds a reference to a vendor being left. Either half
failing alone is a defect.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "vendor_ratchet.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_it_allows_the_repository_as_it_stands():
    """The ALLOW half. A gate everyone has to bypass measures nothing."""
    result = _run("--check")
    assert result.returncode == 0, (
        "the ratchet refuses the repository as committed, so every honest change would have to "
        f"bypass it:\n{result.stdout}{result.stderr}"
    )


def _throwaway_repo(tmp_path: Path) -> Path:
    """A real git repository with a committed baseline, and nothing else.

    The REFUSE half used to run against THIS working tree: it wrote a probe file into `deploy/`
    and ran `git add -N` on it. Under pytest-xdist that is shared mutable state -- on 2026-08-24
    another worker's test read the tree during that window and failed naming a file it had never
    heard of. The counter takes `--root` now, so the probe happens somewhere nobody else is
    looking.
    """
    repo = tmp_path / "repo"
    (repo / "deploy").mkdir(parents=True)
    (repo / "ops" / "config").mkdir(parents=True)
    (repo / "deploy" / "already_here.sh").write_text("#!/bin/sh\nfly deploy -a the-one-that-exists\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    # One existing call-site, so the baseline is a real number rather than zero. A ratchet that has
    # only ever been proved against an empty repository has not been proved against this estate.
    baseline = {"fly": {"occurrences": 1, "files": {"deploy/already_here.sh": 1}}}
    (repo / "ops" / "config" / "vendor_ratchet.json").write_text(json.dumps(baseline, indent=2) + "\n")
    return repo


def test_it_allows_a_repository_that_has_not_grown(tmp_path):
    """The ALLOW half again, this time where the baseline is known exactly."""
    repo = _throwaway_repo(tmp_path)
    result = _run("--check", "--root", str(repo))
    assert result.returncode == 0, (
        f"it refused a repository sitting exactly on its baseline:\n{result.stdout}{result.stderr}"
    )


def test_it_refuses_a_new_reference_to_a_vendor_we_are_leaving(tmp_path):
    """The REFUSE half, driven through git so the counter sees the file the way CI would."""
    repo = _throwaway_repo(tmp_path)
    added = repo / "deploy" / "a_new_dependency.sh"
    added.write_text("#!/bin/sh\nfly deploy -a a-new-dependency\n")
    # The counter reads `git ls-files`, so an untracked file is invisible to it. --intent-to-add
    # makes it tracked without staging content, which is the state a real commit passes through.
    subprocess.run(["git", "add", "-N", str(added)], cwd=repo, check=True, capture_output=True)

    result = _run("--check", "--root", str(repo))
    assert result.returncode == 1, (
        f"the ratchet allowed a brand new `fly deploy` call-site:\n{result.stdout}{result.stderr}"
    )
    assert "a_new_dependency.sh" in result.stdout, (
        "it refused without naming the file that caused it, so the next agent has to derive the "
        f"diff by hand:\n{result.stdout}"
    )


def test_it_refuses_a_workflow_that_falls_back_to_the_vendors_runner_label(tmp_path):
    """Incident 2026-08-24. The counter could not see the one reference that mattered most.

    .github/workflows/e2e-live-smoke.yml:291 read `|| 'fly' }}` as its runs-on fallback. Measured:
    the repository counted 402 occurrences with that line present and 402 with it removed, so the
    gate would have let it stand forever. A job waiting for a runner label nobody carries queues
    rather than fails, which means it reports pending and nothing pages.

    This is the REFUSE half for that shape, and the ALLOW half is the test below it.
    """
    repo = _throwaway_repo(tmp_path)
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    added = wf / "smoke.yml"
    added.write_text(
        "jobs:\n"
        "  smoke:\n"
        "    runs-on: ${{ vars.CI_LIGHT_RUNS_ON || vars.CI_RUNS_ON || 'fly' }}\n"
    )
    subprocess.run(["git", "add", "-N", str(added)], cwd=repo, check=True, capture_output=True)

    result = _run("--check", "--root", str(repo))
    assert result.returncode == 1, (
        "the ratchet allowed a workflow that falls back to the departed vendor's runner label:\n"
        f"{result.stdout}{result.stderr}"
    )
    assert "smoke.yml" in result.stdout, (
        f"it refused without naming the workflow that caused it:\n{result.stdout}"
    )


def test_it_allows_a_workflow_whose_runner_fallback_is_hosted(tmp_path):
    """The ALLOW half of the same shape, and the reason it is a separate test.

    The narrow pattern must match the vendor's name on a runs-on line and nothing else on one. A
    guard that refused `ubuntu-latest` here would refuse every workflow in the estate, which is the
    outage LAW 38 names.
    """
    repo = _throwaway_repo(tmp_path)
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    added = wf / "smoke.yml"
    added.write_text(
        "jobs:\n"
        "  smoke:\n"
        "    runs-on: ${{ vars.CI_LIGHT_RUNS_ON || vars.CI_RUNS_ON || 'ubuntu-latest' }}\n"
    )
    subprocess.run(["git", "add", "-N", str(added)], cwd=repo, check=True, capture_output=True)

    result = _run("--check", "--root", str(repo))
    assert result.returncode == 0, (
        f"it refused a workflow that falls back to a GitHub-hosted runner:\n{result.stdout}{result.stderr}"
    )


def test_it_allows_again_once_the_new_reference_is_gone(tmp_path):
    """A gate that stays red after the cause is removed is an outage, not a guard."""
    repo = _throwaway_repo(tmp_path)
    added = repo / "deploy" / "a_new_dependency.sh"
    added.write_text("#!/bin/sh\nfly deploy -a a-new-dependency\n")
    subprocess.run(["git", "add", "-N", str(added)], cwd=repo, check=True, capture_output=True)
    assert _run("--check", "--root", str(repo)).returncode == 1

    subprocess.run(["git", "rm", "-q", "--cached", "--force", str(added)], cwd=repo, capture_output=True)
    added.unlink()
    result = _run("--check", "--root", str(repo))
    assert result.returncode == 0, (
        f"still refusing after the probe file was removed:\n{result.stdout}{result.stderr}"
    )
