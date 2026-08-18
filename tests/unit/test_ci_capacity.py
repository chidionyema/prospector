"""The CI capacity contract is checked, not commented.

`scripts/ci_capacity.py` is the check. These tests run it against the real repo, and against
mutated copies, so a green result here means the check can actually fail — a guard that cannot
fail is the defect it exists to prevent.
"""
from __future__ import annotations

import re
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
    # Append to whatever the light pool lists, rather than pinning one exact membership.
    # This wrote the literal "jobs: [changes, guard, ci-ok]". When nextjs and ops-console moved
    # into that pool the line stopped matching, so the replace did nothing, the config stayed
    # valid, the script exited 0, and the test failed asserting exit 1 — reading as a broken
    # capacity checker when the checker was fine and the fixture was stale. It cost a full CI
    # round trip to learn that, on 2026-08-18.
    head, sep, tail = cfg.read_text().partition("\n  light:")
    assert sep, "the light pool is gone from ci_capacity.yaml"
    tail, n = re.subn(r"(jobs: \[[^\]]*)\]", r"\1, no-such-job]", tail, count=1)
    assert n == 1, "the light pool has no jobs list"
    cfg.write_text(head + sep + tail)
    r = run(sandbox)
    assert r.returncode == 1
    assert "no such job" in r.stderr


def test_adding_a_runner_off_the_box_does_not_break_the_cpu_budget(sandbox: Path):
    """The failure that actually happened. Three Fly containers joined the heavy pool on
    2026-08-18. `pools.heavy.runners` was the count used BOTH to check the registered fleet and to
    sum the CPU worst case, so raising it to include machines that are not this Mac declared the
    contract broken for adding capacity that spends none of this box's CPUs."""
    cfg = sandbox / "ops/config/ci_capacity.yaml"
    cfg.write_text(cfg.read_text().replace("    runners: 3\n", "    runners: 30\n", 1))
    r = run(sandbox)
    assert r.returncode == 0, f"a bigger off-box pool must not touch the budget:\n{r.stderr}"
    assert "3 heavy jobs at once" in r.stdout, r.stdout


def test_shrinking_the_boxs_own_slots_is_what_moves_the_budget(sandbox: Path):
    """The other half: `box.heavy_slots` is the number the arithmetic reads, so it still fails."""
    cfg = sandbox / "ops/config/ci_capacity.yaml"
    cfg.write_text(cfg.read_text().replace("  heavy_slots: 3", "  heavy_slots: 5", 1))
    r = run(sandbox)
    assert r.returncode == 1
    assert "CPU budget" in r.stderr, r.stderr


# --------------------------------------------------------------------------- #
# An offline runner takes no work
# --------------------------------------------------------------------------- #
def _runner(name: str, label: str, status: str, busy: bool = False) -> dict:
    return {"name": name, "status": status, "busy": busy,
            "labels": [{"name": "self-hosted"}, {"name": label}]}


def _live_report(monkeypatch, capsys, runners: list[dict]) -> tuple[int, str]:
    """Run the --live check against a stubbed GitHub runner list."""
    import scripts.ci_capacity as cc
    monkeypatch.setattr(cc, "registered_runners", lambda: runners)
    monkeypatch.setattr(sys, "argv", ["ci_capacity.py", "--live"])
    rc = cc.main()
    out = capsys.readouterr()
    return rc, out.out + out.err


def test_a_registered_but_offline_runner_does_not_count_as_capacity(monkeypatch, capsys):
    """The whole point. On 2026-08-18 this script printed 'heavy pool: 5 registered ... contract:
    holds' while a CI run sat queued for 25 minutes. Three of the five were the laptop's Mac
    runners, offline since the estate moved to Fly. Counting registration measured GitHub's
    record; the queue measured the fleet."""
    runners = [_runner("mac-1", "heavy", "offline"),
               _runner("mac-2", "heavy", "offline"),
               _runner("mac-3", "heavy", "offline"),
               _runner("fly-1", "heavy", "online", busy=True)]
    rc, text = _live_report(monkeypatch, capsys, runners)
    assert rc == 1, "an all-but-one-offline fleet was reported as holding"
    assert "1 online" in text, text
    assert "mac-1" in text, "the offline runners must still be named — that is what explains the queue"


def test_an_online_fleet_that_meets_the_contract_holds(monkeypatch, capsys):
    """Guard the guard: if --live failed for any fleet, the test above would prove nothing."""
    import scripts.ci_capacity as cc
    pools = cc.read_contract(cc.CONTRACT)["pools"] if hasattr(cc, "CONTRACT") else None
    if pools is None:                                   # contract path named differently
        pytest.skip("contract constant not exposed")
    runners = []
    for name, p in pools.items():
        for i in range(p["runners"]):
            runners.append(_runner(f"{name}-{i}", p["label"], "online"))
    rc, text = _live_report(monkeypatch, capsys, runners)
    assert rc == 0, text
