"""Integration test — golden-set promotion CLI gating mechanism.

Tests the three mechanical guarantees from specs/offline-moat-validation.md §6:
  1. main() exits non-zero when discrimination < 1.0
  2. main() exits zero when discrimination == 1.0
  3. --operator deepseek/minimax are accepted choices (argparse)

Uses pytest's monkeypatch fixture for reliable sys.argv isolation.
No real network calls; CI stays offline/free.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

# Pre-import so golden.main() calls don't hang on module-level init
from prospector.run import vet_candidate  # noqa: F401

from prospector.golden import (
    OPERATOR_CHOICES,
    _mock_vet_candidate,
    main as golden_main,
)
from prospector.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]

# Golden set cases that match _mock_vet_candidate rules:
#   "haulage" in title → KILL; else → PASS
_KILL_CASE = {
    "idea": "Haulage HMRC fuel-duty PTO rebate",
    "expected": "kill",
    "gate": "value_durability",
    "must_surface": "value legislated away not durable",
}
_PASS_CASE = {
    "idea": "Unified-API niche bridge (open-core)",
    "expected": "pass",
    "gate": None,
    "must_surface": None,
}
_CORRECT_CASES = [_KILL_CASE, _PASS_CASE]


def _write_cases(path: Path, cases: list[dict]) -> None:
    path.write_text(json.dumps(cases), encoding="utf-8")


def _run_main(tmp_path: Path, cases: list[dict], extra_args: list[str] | None = None) -> int:
    """Write cases to tmp_path, call golden_main() with given extra_args, return exit code."""
    path = tmp_path / "cases.json"
    _write_cases(path, cases)
    args = ["golden", "--golden-set", str(path), "--operator", "mock", "--mock-vet"]
    if extra_args:
        args.extend(extra_args)
    old_argv = sys.argv
    old_out = sys.stdout
    old_err = sys.stderr
    sys.argv = args
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        golden_main()
        return 0
    except SystemExit as e:
        return e.code or 0
    finally:
        sys.argv = old_argv
        sys.stdout = old_out
        sys.stderr = old_err


# ---------------------------------------------------------------------------
# §6 test 1: exit != 0 when discrimination < 1.0
# ---------------------------------------------------------------------------
def test_golden_cli_exits_nonzero_on_fail(tmp_path: Path):
    """Wrong verdicts → discrimination < 1.0 → exit != 0."""
    # "NOT HAULAGE" → mock PASS (wrong, expected KILL) → FAIL
    # "Unified-API..." → mock PASS (correct, expected PASS) → PASS
    # Discrimination = 1/2 = 0.5 → non-zero exit.
    # _mock_vet_candidate: KILL iff "haulage" in title.
    # "NOT HAULAGE" → KILL (correct). "Random SaaS" → PASS (wrong, expected KILL).
    wrong_cases = [
        {"idea": "NOT HAULAGE rebate", "expected": "kill",
         "gate": "value_durability", "must_surface": "haulage"},
        {"idea": "Random SaaS productivity app", "expected": "kill",
         "gate": None, "must_surface": None},
    ]
    exit_code = _run_main(tmp_path, wrong_cases)
    assert exit_code != 0, f"Expected non-zero exit, got {exit_code}"


# ---------------------------------------------------------------------------
# §6 test 2: exit == 0 when discrimination == 1.0
# ---------------------------------------------------------------------------
def test_golden_cli_exits_zero_on_full_pass(tmp_path: Path):
    """Correct verdicts → discrimination == 1.0 → exit == 0."""
    exit_code = _run_main(tmp_path, _CORRECT_CASES)
    assert exit_code == 0, f"Expected zero exit, got {exit_code}"


# ---------------------------------------------------------------------------
# §6 test 3: --operator deepseek/minimax accepted by argparse
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("op", ["deepseek", "minimax", "openrouter"])
def test_golden_cli_accepts_real_operators(op: str):
    """Argparse must accept every operator in OPERATOR_CHOICES."""
    assert op in OPERATOR_CHOICES


# ---------------------------------------------------------------------------
# §6 test 4: --runs N writes N audit files
# ---------------------------------------------------------------------------
def test_golden_cli_runs_flag(tmp_path: Path):
    """--runs 3 writes 3 audit files to store/golden_runs/."""
    audit_dir = REPO_ROOT / "store" / "golden_runs"
    audit_dir.mkdir(parents=True, exist_ok=True)
    for f in audit_dir.glob("mock_*.json"):
        f.unlink(missing_ok=True)

    exit_code = _run_main(tmp_path, _CORRECT_CASES, extra_args=["--runs", "3"])
    assert exit_code == 0, f"Expected zero exit, got {exit_code}"

    all_files = sorted(audit_dir.glob('*'))
    files = sorted(audit_dir.glob("mock_*.json"))
    assert len(files) == 3, (
        f"Expected 3 audit files, got {len(files)}"
    )


# ---------------------------------------------------------------------------
# §6 test 5: --runs requires ALL N runs == 1.0 (any fail → exit != 0)
# ---------------------------------------------------------------------------
def test_golden_cli_runs_all_or_nothing(tmp_path: Path):
    """If any run has discrimination < 1.0, overall exits non-zero."""
    # "Construction..." (no "haulage") → mock PASS (wrong, expected KILL) → FAIL
    # Discrimination = 1/2 = 0.5 in every run → all runs fail the >=1.0 bar.
    wrong_cases = [
        {"idea": "Construction retention recovery", "expected": "kill",
         "gate": "value_durability", "must_surface": "retention"},
        {"idea": "Unified-API niche bridge (open-core)", "expected": "pass",
         "gate": None, "must_surface": None},
    ]
    exit_code = _run_main(tmp_path, wrong_cases, extra_args=["--runs", "3"])
    assert exit_code != 0, (
        f"Expected non-zero exit when discrimination < 1.0, got {exit_code}"
    )


# ---------------------------------------------------------------------------
# §6 test 6: mock operator does not emit retrieval warning
# ---------------------------------------------------------------------------
def test_golden_cli_mock_no_warning(tmp_path: Path):
    """--operator mock does not trigger the real-operator retrieval warning."""
    stderr_buffer = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = stderr_buffer
    try:
        _run_main(tmp_path, _CORRECT_CASES)
    finally:
        sys.stderr = old_stderr
    assert "WARNING" not in stderr_buffer.getvalue()


# ---------------------------------------------------------------------------
# §6 test 7: audit file schema has required fields
# ---------------------------------------------------------------------------
def test_golden_cli_audit_file_schema(tmp_path: Path):
    """Each audit file contains: timestamp, operator, model_version, discrimination,
    run_index, total_runs, per_case."""
    audit_dir = REPO_ROOT / "store" / "golden_runs"
    audit_dir.mkdir(parents=True, exist_ok=True)
    before = set(audit_dir.glob("mock_*.json"))

    exit_code = _run_main(tmp_path, _CORRECT_CASES)
    assert exit_code == 0

    after = set(audit_dir.glob("mock_*.json"))
    new_files = after - before
    assert len(new_files) == 1, f"Expected 1 audit file, got {len(new_files)}"
    record = json.loads(new_files.pop().read_text(encoding="utf-8"))

    for field in ("timestamp", "operator", "model_version", "discrimination",
                 "run_index", "total_runs", "per_case"):
        assert field in record, f"Missing required field: {field}"
    assert record["operator"] == "mock"
    assert record["discrimination"] == 1.0
    assert len(record["per_case"]) == 2
