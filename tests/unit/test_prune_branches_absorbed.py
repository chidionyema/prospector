"""A branch that CONFLICTS with main is not the same thing as a branch main is missing.

Measured 2026-08-17. Thirteen worktree branches every merge test called unmerged were reviewed
by hand. Twelve of them added nothing: each had already landed as a squash, main had since
edited the same lines, and the conflict was main's NEWER version of the branch's own change.
Merging any of them would have reverted main -- `git merge -X theirs` on
`docs/ci-runner-tool-cache` produced 77 insertions against 164 deletions of main's own CI work.

`merged_tree_equals_upstream` cannot see this: it answers only for a branch that merges cleanly,
so a conflicting branch reads as unmerged forever and the report says "N file(s) not in main"
about work that is entirely in main. These tests pin the second measure that tells them apart.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prune_branches.py"


@pytest.fixture(scope="module")
def pb():
    spec = importlib.util.spec_from_file_location("prune_branches", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_git(*, files, diffs, base="base0"):
    """Stand in for the module's `git()` so no repository is needed.

    The `-U0` branch emits ONE combined diff with a `+++ b/<path>` header per file, because that
    is the shape `_added_lines` reads. It used to be one `git diff` per file with the path as the
    last argument, and when #467 replaced that with a single call for speed, this fake kept
    answering the old question: it matched on `args[-1]`, which is now the BRANCH, found no
    lines, and every assertion here started comparing (0, 0) to a real number. The tests went red
    for the right reason and the implementation was never wrong -- `absorbed()` on the live repo
    reads (1, 390) for this worktree's own branch.
    """
    def _git(*args, check=False):
        if args[0] == "merge-base":
            return base + "\n"
        if args[0] == "diff" and "--name-only" in args:
            return "\n".join(files) + "\n"
        if args[0] == "diff" and "-U0" in args:
            out = []
            for path in files:
                out.append(f"--- a/{path}")
                out.append(f"+++ b/{path}")
                out += [f"+{line}" for line in diffs.get(path, [])]
            return "\n".join(out) + "\n"
        return ""
    return _git


def install(pb, monkeypatch, *, files, diffs, main_files, base="base0"):
    """Patch BOTH seams `absorbed()` reads through.

    `_upstream_blobs` shells out to `git cat-file --batch` directly rather than through the
    module's `git()` helper, because it walks a byte-framed stream. Patching `git` alone
    therefore leaves main's copy of every file coming from the real repository, which is how a
    test can look wired up and be measuring nothing.
    """
    monkeypatch.setattr(pb, "git", fake_git(files=files, diffs=diffs, base=base))
    monkeypatch.setattr(pb, "_upstream_blobs",
                        lambda paths: {q: main_files[q] for q in paths if q in main_files})


LONG_A = "        out.append(f'one_liner: {len(line)} chars, over the cut')"
LONG_B = "    from .shelf_copy_repair import voice_breaches as _voice"


class TestAbsorbedCountsWhatMainAlreadyHas:
    def test_a_branch_whose_lines_are_all_on_main_scores_every_line(self, pb, monkeypatch):
        install(
            pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [LONG_A, LONG_B]},
            main_files={"prospector/run.py": LONG_A + "\n" + LONG_B + "\n"})
        assert pb.absorbed("some/branch") == (2, 2)

    def test_a_branch_main_has_never_seen_scores_nothing(self, pb, monkeypatch):
        """The control. Without it the measure could pass by always saying absorbed."""
        install(
            pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [LONG_A, LONG_B]},
            main_files={"prospector/run.py": "something else entirely\n"})
        assert pb.absorbed("some/branch") == (0, 2)

    def test_short_lines_are_not_counted(self, pb, monkeypatch):
        """`)` and `import os` appear in every file and would score any branch as absorbed."""
        install(
            pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [")", "import os", "x = 1"]},
            main_files={"prospector/run.py": ")\nimport os\nx = 1\n"})
        assert pb.absorbed("some/branch") == (0, 0)

    def test_runtime_state_is_not_evidence_about_the_code(self, pb, monkeypatch):
        install(
            pb, monkeypatch,
            files=["store/prospector.jsonl", "signals/pending/a.json"],
            diffs={"store/prospector.jsonl": [LONG_A],
                   "signals/pending/a.json": [LONG_B]},
            main_files={})
        assert pb.absorbed("some/branch") == (0, 0)

    def test_a_branch_with_no_merge_base_is_not_guessed_at(self, pb, monkeypatch):
        monkeypatch.setattr(pb, "git", lambda *a, **k: "")
        assert pb.absorbed("some/branch") == (0, 0)


class TestTheKeptLineSaysHowMuchIsAlreadyIn:
    def test_a_fully_absorbed_branch_says_so(self, pb, monkeypatch):
        install(
            pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [LONG_A, LONG_B]},
            main_files={"prospector/run.py": LONG_A + "\n" + LONG_B + "\n"})
        assert "100% of its 2 added lines are already on main" in pb._kept_reason("b")

    def test_a_branch_with_real_content_is_not_dressed_up_as_merged(self, pb, monkeypatch):
        install(
            pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [LONG_A, LONG_B]},
            main_files={"prospector/run.py": LONG_A + "\n"})
        assert "50% of its 2 added lines are already on main" in pb._kept_reason("b")

    def test_a_branch_that_added_no_gradeable_line_keeps_the_old_wording(self, pb, monkeypatch):
        """No percentage is better than a fabricated 0% or 100% on nothing."""
        install(
            pb, monkeypatch,
            files=["store/prospector.jsonl"],
            diffs={"store/prospector.jsonl": [LONG_A]},
            main_files={})
        reason = pb._kept_reason("b")
        assert "not in main" in reason and "%" not in reason
