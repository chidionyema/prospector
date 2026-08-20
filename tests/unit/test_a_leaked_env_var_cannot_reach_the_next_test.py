"""A test may not leave an environment variable set for the tests that follow it.

WHY THIS FILE EXISTS. On 2026-08-19 nine tests failed on the CI runner and passed on every
developer box, in two files (`test_exemplar_eligibility.py`, `test_lint_receipt_survives_revet.py`)
that had not changed. The cause was PROSPECTOR_STORE_DIR left set in the worker process.
`Config.store_dir` gives that variable precedence over `cfg.store["dir"]`, and `cfg.store["dir"]`
is the exact redirect those tests use to point the store at `tmp_path` — so the redirect was
silently ignored and the tests read a store belonging to something else. Setting the variable by
hand reproduced six of the nine failures on the same assertions.

It could only be seen in CI because `pytest.ini` runs `-n auto --dist loadfile`: the worker count
follows the CPU count, so which files share a process differs between the runner and a laptop. A
defect that is invisible locally is exactly the kind that needs a machine rather than a rule.

The guard is the `pytest_runtest_setup` / `pytest_runtest_teardown` pair in `tests/conftest.py`.
This file proves it FIRES, because a guard nobody has watched fail is not a guard.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from prospector.adaptive import get_exemplars
from prospector.config import load_config
from prospector.models import Candidate, Decision, Dossier
from prospector.store import Store

REPO = Path(__file__).resolve().parents[2]


def _run_pytest_on(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """Run one generated test file against the REAL conftest, in its own process and directory.

    Its own PROCESS because the thing under test is process-global state, and this suite's workers
    must not inherit whatever the generated test does. Its own DIRECTORY because writing a test
    file into the repo tree is collected by any other suite run in flight — a shared checkout runs
    concurrent sessions, and a generated file that appears mid-collection fails somebody else's
    run. The conftest is COPIED rather than imported, so the guard under test is the real file
    byte for byte; PYTHONPATH points back at the repo so `prospector` still imports.
    """
    (tmp_path / "conftest.py").write_text(
        (REPO / "tests" / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_generated.py").write_text(body, encoding="utf-8")
    env = dict(os.environ)
    # `tests/` as well as the repo root: the real conftest imports its own siblings
    # (`from tool_gate import require_tool`), which pytest resolves because it puts the
    # conftest's directory on sys.path. A copy in a bare tmp directory gets no such help, and
    # the whole file then fails to import -- which reads as "the env guard is broken" rather
    # than "a module is missing", in a test about something else entirely.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO), str(REPO / "tests"), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n0",
         "test_generated.py"],
        cwd=tmp_path, capture_output=True, text=True, timeout=300, env=env,
    )


def test_the_guard_fails_the_test_that_leaked(tmp_path):
    """The leaking test is named, and it is the one that fails."""
    proc = _run_pytest_on(tmp_path, '"""Generated."""\nimport os\n\n\n'
                                    'def test_leaks():\n'
                                    '    os.environ["PROSPECTOR_STORE_DIR"] = "/tmp/somewhere"\n')
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"the guard did not fire:\n{out}"
    assert "leaked the environment" in out, out
    assert "PROSPECTOR_STORE_DIR" in out, out
    assert "monkeypatch" in out, "the failure must say what to use instead:\n" + out


def test_the_guard_restores_the_variable_for_the_next_test(tmp_path):
    """The victim is protected even though the culprit is not fixed yet.

    Two tests, alphabetically ordered by pytest's file order: the first leaks, the second asserts
    the variable is gone. Exactly one failure means the leak was contained.
    """
    proc = _run_pytest_on(tmp_path, '"""Generated."""\nimport os\n\n\n'
                                    'def test_a_leaks():\n'
                                    '    os.environ["PROSPECTOR_STORE_DIR"] = "/tmp/somewhere"\n\n\n'
                                    'def test_b_sees_a_clean_environment():\n'
                                    '    assert "PROSPECTOR_STORE_DIR" not in os.environ\n')
    out = proc.stdout + proc.stderr
    # A fixture that fails in TEARDOWN is reported as an ERROR against that test, not a failure —
    # the body already ran and passed. Exactly one, and it names the leaker; the test after it
    # sees a clean environment, which is the whole point of restoring before raising.
    assert "1 error" in out and "2 errors" not in out, out
    assert "test_a_leaks" in out, out
    assert "2 passed" in out, out


def test_a_pass_row_with_no_score_does_not_crash_generation(tmp_path):
    """A NULL composite must read as 0.0, not raise.

    `store.py:372` writes NULL when a dossier is saved without a score, and the exemplar builder
    sorted such a row happily (`or 0.0`) and then formatted it with `float(w.get("composite", 0))`
    — which raises, because a dict default only applies to a MISSING key, never to a key present
    with value None. One such row took down every generation call that reached it.
    """
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    store = Store(cfg)
    d = Dossier(candidate=Candidate(title="unscored", one_liner="no score was ever computed"),
                decision=Decision.PASS, model_version="t", created_at="t")
    d.candidate.candidate_id = "unscored"
    store.save(d)

    out = get_exemplars(store)
    assert "unscored" in out
    assert "Score 0.0" in out, out
