"""One gate for "this test needs a binary", callable from a marker AND from a test's own helper.

It lives in its own module rather than in `tests/conftest.py` because `tests/unit/conftest.py`
exists: `from conftest import ...` inside a file under `tests/unit/` resolves to THAT file, so
the shared spelling fails at collection with `ImportError: cannot import name ... from conftest`.
A distinct module name has no such shadow.

WHAT PAID FOR IT. `pytest.mark.skipif(shutil.which("node") is None)` at module level, and the
same decision made inline inside a harness function, deleted 93 tests from CI without a word —
67 in `test_main_admission_guard.py` and `test_pr_keeper.py`, 26 more in the three modules that
gate node inside `_run`/`_decide`. `deploy/runner/Dockerfile` ships no language runtimes on
purpose, and `ci.yml`'s python job did not call setup-node, so `node` was not on PATH on any
runner. Every one of those tests skipped and every job stayed green.

THE CLASS is a test that answers "the tool is missing" with the same colour as "the code is
correct". A missing binary normally fails at exit 127, which is loud; wrapped in a skip it fails
as nothing at all. Same shape as pytest exiting 0 on a run that collected nothing.

So the skip survives where it is honest — a laptop without node should not be walled — and
becomes an ERROR on a CI runner, where a missing tool is never a fact about the world but a hole
in the gate that somebody has to close.
"""
from __future__ import annotations

import os
import shutil

import pytest


def in_ci() -> bool:
    """True on a CI runner. Both variables are set by GitHub Actions on every job."""
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def require_tool(tool: str) -> str:
    """Return the path to `tool`, or end the test the way this environment deserves."""
    found = shutil.which(tool)
    if found is not None:
        return found
    if in_ci():
        pytest.fail(
            f"`{tool}` is not on PATH on this CI runner, so this test cannot run. In CI that is "
            f"a hole in the gate, not a property of the box: skipping here would delete the test "
            f"from the only place anyone reads its result. Install `{tool}` in the job that runs "
            f"this file (see the setup-node step in ci.yml's python job) or in "
            f"deploy/runner/Dockerfile.",
            pytrace=False,
        )
    pytest.skip(f"`{tool}` is not installed on this machine")
    raise AssertionError("unreachable")  # pragma: no cover - pytest.skip raises
