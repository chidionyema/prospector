"""The CI capacity contract is checked, not commented.

`scripts/ci_capacity.py` is the check. These tests run it against the real repo, and against
mutated copies, so a green result here means the check can actually fail — a guard that cannot
fail is the defect it exists to prevent.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci_capacity.py"


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "scripts/ci_capacity.py")],
                          capture_output=True, text=True, timeout=120)


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """A copy of just the four paths the check reads, so a mutation cannot touch the real repo."""
    for rel in ("scripts/ci_capacity.py", "ops/config/ci_capacity.yaml",
                ".github/workflows/ci.yml"):
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    return tmp_path


def test_the_contract_holds_on_this_repo():
    r = run(ROOT)
    assert r.returncode == 0, f"the live contract is broken:\n{r.stdout}\n{r.stderr}"
    assert "holds" in r.stdout


def test_a_job_that_reads_the_shared_variable_fails(sandbox: Path):
    """The failure this exists for: someone adds a job, copies a `runs-on` from an older one, and
    it silently competes with the suites for the same slots."""
    ci = sandbox / ".github/workflows/ci.yml"
    ci.write_text(ci.read_text().replace(
        "runs-on: ${{ vars.CI_HEAVY_RUNS_ON || vars.CI_RUNS_ON || 'ubuntu-latest' }}",
        "runs-on: ${{ vars.CI_RUNS_ON || 'ubuntu-latest' }}", 1))
    r = run(sandbox)
    assert r.returncode == 1
    assert "not CI_HEAVY_RUNS_ON" in r.stderr


def test_widening_a_job_past_the_cpu_budget_fails(sandbox: Path):
    """The two numbers that were never compared: how many heavy jobs run at once, and how wide
    each one is. Twelve pytest workers alongside the other two heavy jobs is 16 on a 12-CPU box."""
    cfg = sandbox / "ops/config/ci_capacity.yaml"
    cfg.write_text(cfg.read_text().replace("  python: 6", "  python: 12", 1))
    r = run(sandbox)
    assert r.returncode == 1
    assert "CPU budget" in r.stderr


def test_a_declared_width_that_ci_yml_does_not_run_fails(sandbox: Path):
    """The contract may not describe a workflow that stopped agreeing with it."""
    ci = sandbox / ".github/workflows/ci.yml"
    ci.write_text(ci.read_text().replace("-n 6 --tb=short", "-n 2 --tb=short", 1))
    r = run(sandbox)
    assert r.returncode == 1
    assert "ci.yml runs 2" in r.stderr


def test_a_pool_naming_a_job_that_does_not_exist_fails(sandbox: Path):
    """A renamed or deleted job leaves the contract describing a workflow that is gone."""
    cfg = sandbox / "ops/config/ci_capacity.yaml"
    cfg.write_text(cfg.read_text().replace("jobs: [changes, guard, ci-ok]",
                                           "jobs: [changes, guard, ci-ok, no-such-job]", 1))
    r = run(sandbox)
    assert r.returncode == 1
    assert "no such job" in r.stderr
