"""Production is "behind" only when deployed code changed, never when a doc did.

live_checkout.py used to raise a problem for every commit between the deployed image and
origin/main. Docs merges, test-only fixes and storefront changes all moved that number, so the
probe reported production stale while production ran exactly the code it should. An alarm that is
usually wrong is an alarm that gets ignored, and the next real one arrives inside that habit.

These tests pin the two halves of the fix: the filter is the one deploy-engine.yml triggers on,
and it is read from origin/main rather than from a working tree that can be months behind.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-engine.yml"


@pytest.fixture()
def lc(monkeypatch):
    spec = importlib.util.spec_from_file_location("lc", ROOT / "scripts" / "live_checkout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Stand in for `git show origin/main:<workflow>` with this checkout's copy, so the test
    # measures the matching, not whatever a developer checkout happens to be sitting on.
    text = WORKFLOW.read_text(encoding="utf-8")
    monkeypatch.setattr(mod, "run", lambda *a, **k: (0, text))
    return mod


@pytest.mark.parametrize("changed,expected", [
    ("docs/A.md\ndocs/B.md\n", []),
    ("tests/unit/test_x.py\n", []),
    ("store_platform/src/Store.Web/pages/index.tsx\n", []),
    ("prospector/run.py\n", ["prospector/run.py"]),
    ("config.yaml\n", ["config.yaml"]),
    ("requirements.txt\n", ["requirements.txt"]),
    ("scripts/process_audit.py\n", ["scripts/process_audit.py"]),
    ("deploy/engine/fly.toml\n", ["deploy/engine/fly.toml"]),
    ("store_platform/src/Ops.Console/src/pages/index.tsx\n",
     ["store_platform/src/Ops.Console/src/pages/index.tsx"]),
])
def test_only_deployed_paths_count_as_behind(lc, changed, expected):
    assert lc._deployed_changes(changed) == expected


def test_a_docs_commit_beside_an_engine_commit_still_counts(lc):
    assert lc._deployed_changes("docs/A.md\nprospector/run.py\n") == ["prospector/run.py"]


def test_an_unreadable_filter_keeps_the_blunt_warning(lc, monkeypatch):
    """None, not [], when the filter cannot be read.

    Claiming "production is current" because the workflow could not be parsed would turn a
    read failure into an all-clear. The caller falls back to the old commit-count warning.
    """
    monkeypatch.setattr(lc, "run", lambda *a, **k: (1, ""))
    monkeypatch.setattr(lc, "DEV", ROOT / "does" / "not" / "exist")
    assert lc._deployed_changes("prospector/run.py\n") is None


def test_the_filter_is_read_from_origin_main_not_the_working_tree(lc, monkeypatch):
    """The developer checkout was 60 commits behind and its copy predated the path filter.

    Reading the working tree returned no patterns, so the helper silently fell back to the
    warning it exists to replace. The comparison is against origin/main, so the filter must
    come from origin/main.
    """
    seen: list[list[str]] = []

    def fake_run(cmd, *a, **k):
        seen.append(cmd)
        return 0, WORKFLOW.read_text(encoding="utf-8")

    monkeypatch.setattr(lc, "run", fake_run)
    lc._deployed_changes("prospector/run.py\n")
    assert seen and seen[0][:2] == ["git", "show"]
    assert seen[0][2].startswith("origin/main:")
