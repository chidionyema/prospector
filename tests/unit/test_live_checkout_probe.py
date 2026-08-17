"""The live-checkout probe must not report runtime state as a code change.

Production runs from a dedicated checkout pinned to origin/main. `store/` and `storage/`
are tracked but written by every run, so `git status` there is never empty. The probe
refuses to update a checkout with local CODE modifications, and that refusal is only
useful if it can tell code from runtime state.

Measured 2026-08-17: it could not. The live checkout sat 14 commits behind origin/main
and `--update` refused, naming one "local modification" that was
` T store/provider_health.json` -- runtime state the function is written to ignore. The
cause is in this file's `run()`: it strips the whole command output, so the FIRST
porcelain line loses its leading space whenever the index column is blank. Slicing the
path at a fixed offset 3 then read "ore/provider_health.json".
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "live_checkout.py"


def _load():
    spec = importlib.util.spec_from_file_location("live_checkout", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lc():
    if not SCRIPT.exists():
        pytest.skip("scripts/live_checkout.py is not in this checkout")
    return _load()


class TestRuntimeStateIsNotACodeChange:
    def test_a_normal_porcelain_line_for_store_is_ignored(self, lc):
        assert lc._code_changes(" M store/prospector.jsonl") == []

    def test_the_STRIPPED_first_line_is_still_recognised_as_store(self, lc):
        """This is the real input: run() strips, so line 1 loses its leading space."""
        assert lc._code_changes("T store/provider_health.json") == []

    def test_a_whole_stripped_report_of_runtime_state_is_clean(self, lc):
        porcelain = (
            "T store/provider_health.json\n"
            " T store/provider_health_noncritical.json\n"
            " D store/scheduler/audit/1970-01-01.jsonl\n"
            " M storage/catalog.json\n"
        )
        assert lc._code_changes(porcelain) == []

    def test_untracked_files_are_ignored_stripped_or_not(self, lc):
        assert lc._code_changes("?? scripts/scratch.py\n?? store/new.json") == []


class TestRealCodeChangesStillFire:
    def test_a_modified_module_is_reported(self, lc):
        assert lc._code_changes(" M prospector/run.py") == [" M prospector/run.py"]

    def test_a_stripped_first_line_of_real_code_is_reported(self, lc):
        assert lc._code_changes("M prospector/run.py") == ["M prospector/run.py"]

    def test_a_staged_addition_is_reported(self, lc):
        assert lc._code_changes("A  tools/new_tool.py") == ["A  tools/new_tool.py"]

    def test_a_rename_out_of_store_is_reported(self, lc):
        """Judged by its destination: the file now lives in code."""
        line = "R  store/old.json -> tools/old.json"
        assert lc._code_changes(line) == [line]

    def test_a_rename_within_store_is_ignored(self, lc):
        assert lc._code_changes("R  store/a.json -> store/b.json") == []

    def test_code_and_runtime_state_together_report_only_the_code(self, lc):
        porcelain = (
            "T store/provider_health.json\n"
            " M prospector/run.py\n"
            " D store/scheduler/audit/1970-01-01.jsonl\n"
        )
        assert lc._code_changes(porcelain) == [" M prospector/run.py"]
