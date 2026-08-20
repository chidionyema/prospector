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
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prune_branches.py"


@pytest.fixture(scope="module")
def pb():
    spec = importlib.util.spec_from_file_location("prune_branches", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_git(*, files, diffs, main_files, base="base0"):
    """Stand in for the module's `git()` so no repository is needed.

    UPDATED 2026-08-20, and the reason is the point. #467 (48465494) rewrote `absorbed()` to
    read the whole branch in two subprocesses instead of two per file, because a `--remote`
    report had stopped finishing. It changed both seams this fake stood on: one COMBINED
    `git diff -U0 --no-renames`, parsed by its `+++ b/<path>` headers, and `git cat-file
    --batch` in place of a `git show` per file. The old fake answered the old questions, so
    `absorbed()` saw an empty diff and returned (0, 0) for every case -- four failures that had
    nothing to do with the behaviour being asserted. Those assertions are unchanged below; only
    what they are fed has moved.

    `main_files` is no longer served from here. `git cat-file --batch` is not routed through
    `git()`, so it is stubbed by `fake_cat_file` at the subprocess seam instead.
    """
    def _git(*args, check=False):
        if args[0] == "merge-base":
            return base + "\n"
        if args[0] == "diff" and "--name-only" in args:
            return "\n".join(files) + "\n"
        if args[0] == "diff" and "-U0" in args:
            # One diff covering every file, headed the way git heads them. The parser keys on
            # `+++ b/<path>`, so a fake that emits bare `+line` runs would be parsed as belonging
            # to no file at all.
            out = []
            for path in files:
                out.append(f"--- a/{path}")
                out.append(f"+++ b/{path}")
                out.extend(f"+{line}" for line in diffs.get(path, []))
            return "\n".join(out) + "\n"
        return ""
    return _git


def fake_cat_file(main_files):
    """Stand in for the `git cat-file --batch` subprocess, framed exactly as git frames it.

    Real frames on purpose: a header line whose last field is the object's BYTE length, then the
    object, then the newline git writes after it. `_upstream_blobs` walks that stream by those
    byte offsets, and feeding it real frames is what keeps the walk honest -- decoding the stream
    first desynchronises on the first multi-byte character and every file after it is read from
    the wrong offset, silently.
    """
    def _run(cmd, input=None, capture_output=False, timeout=None, **kw):
        out = bytearray()
        for line in input.decode().splitlines():
            path = line.split(":", 1)[1]
            body = main_files.get(path)
            if body is None:
                out += f"{line} missing\n".encode()      # main does not have this file at all
                continue
            blob = body.encode()
            out += f"{'a' * 40} blob {len(blob)}\n".encode() + blob + b"\n"
        return SimpleNamespace(stdout=bytes(out), returncode=0)
    return _run


def install(pb, monkeypatch, *, files, diffs, main_files, base="base0"):
    """Both seams at once. Patching only one of them is how this file went stale."""
    monkeypatch.setattr(pb, "git", fake_git(
        files=files, diffs=diffs, main_files=main_files, base=base))
    monkeypatch.setattr(pb.subprocess, "run", fake_cat_file(main_files))


LONG_A = "        out.append(f'one_liner: {len(line)} chars, over the cut')"
LONG_B = "    from .shelf_copy_repair import voice_breaches as _voice"


class TestAbsorbedCountsWhatMainAlreadyHas:
    def test_a_branch_whose_lines_are_all_on_main_scores_every_line(self, pb, monkeypatch):
        install(pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [LONG_A, LONG_B]},
            main_files={"prospector/run.py": LONG_A + "\n" + LONG_B + "\n"})
        assert pb.absorbed("some/branch") == (2, 2)

    def test_a_branch_main_has_never_seen_scores_nothing(self, pb, monkeypatch):
        """The control. Without it the measure could pass by always saying absorbed."""
        install(pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [LONG_A, LONG_B]},
            main_files={"prospector/run.py": "something else entirely\n"})
        assert pb.absorbed("some/branch") == (0, 2)

    def test_short_lines_are_not_counted(self, pb, monkeypatch):
        """`)` and `import os` appear in every file and would score any branch as absorbed."""
        install(pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [")", "import os", "x = 1"]},
            main_files={"prospector/run.py": ")\nimport os\nx = 1\n"})
        assert pb.absorbed("some/branch") == (0, 0)

    def test_runtime_state_is_not_evidence_about_the_code(self, pb, monkeypatch):
        install(pb, monkeypatch,
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
        install(pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [LONG_A, LONG_B]},
            main_files={"prospector/run.py": LONG_A + "\n" + LONG_B + "\n"})
        assert "100% of its 2 added lines are already on main" in pb._kept_reason("b")

    def test_a_branch_with_real_content_is_not_dressed_up_as_merged(self, pb, monkeypatch):
        install(pb, monkeypatch,
            files=["prospector/run.py"],
            diffs={"prospector/run.py": [LONG_A, LONG_B]},
            main_files={"prospector/run.py": LONG_A + "\n"})
        assert "50% of its 2 added lines are already on main" in pb._kept_reason("b")

    def test_a_branch_that_added_no_gradeable_line_keeps_the_old_wording(self, pb, monkeypatch):
        """No percentage is better than a fabricated 0% or 100% on nothing."""
        install(pb, monkeypatch,
            files=["store/prospector.jsonl"],
            diffs={"store/prospector.jsonl": [LONG_A]},
            main_files={})
        reason = pb._kept_reason("b")
        assert "not in main" in reason and "%" not in reason
