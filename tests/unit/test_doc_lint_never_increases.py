"""Docs may get more accurate. They may not get less accurate.

P5.2. ENG-6 was a doc telling an operator to run a provider no config had selected for weeks.
Prose has no compiler, so nothing caught it. `scripts/doc_lint.py` is the compiler; this test
is what makes it binding, and it rides the gate that already runs rather than needing a new
CI job that can rot on its own.

The ratchet is per file and deliberately not a total: a total lets one doc rot while another
is tidied, and the number still falls. Same shape as
`test_swallowed_failures_can_only_go_down.py`.

When this fails, the fix is to correct the doc — not to re-run `--write-baseline`. Raising the
ceiling to match the breakage is how a ratchet becomes decoration. Re-baseline only to lock in
an IMPROVEMENT, which the script says explicitly when it sees one.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "scripts"))

import doc_lint  # noqa: E402


def test_no_doc_gets_less_accurate_than_its_baseline():
    findings = doc_lint.lint()
    ok, messages = doc_lint.check_ratchet(findings)

    regressions = [m for m in messages if not m.startswith("IMPROVED")]
    assert ok, (
        "a doc points at more missing paths, empty files or unselected providers than it did:\n"
        + "\n".join(regressions)
        + "\n\nFix the doc. Run `python3 scripts/doc_lint.py` to see every finding."
    )


def test_the_baseline_only_names_docs_that_are_still_scanned():
    """A baseline entry for a deleted or renamed doc hides a regression somewhere else.

    The counts are keyed by path. If a doc is renamed and the old key stays, the new path has
    no ceiling at all and can rot freely while the file still reads as covered.
    """
    baseline = doc_lint.json.loads(doc_lint.BASELINE_PATH.read_text())
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in doc_lint._scan_files()}

    orphans = sorted(set(baseline) - scanned)
    assert not orphans, (
        f"the baseline names {len(orphans)} doc(s) that are no longer scanned: {orphans}. "
        "Remove them, or add the file back to SCAN_GLOBS."
    )


def test_a_path_is_graded_against_the_repo_not_against_this_machine():
    """The baseline is per-file, so it is only meaningful if the count is the same everywhere.

    It was not. `lint()` asked `Path.exists()`, so any untracked output lying around counted
    as a live path: the same commit scored 88 findings in the shared checkout and 91 in a
    fresh worktree, over `scratchpad/results.jsonl`, `.popdd/last_verify.json` and
    `graphify-out/graph.json`. The ratchet then fails in CI and in any clean clone, on docs
    nobody touched, and the only way out is to raise the baseline — which is the one thing
    this file forbids. Git's index is identical everywhere, so the count now is too.
    """
    probe = doc_lint.REPO_ROOT / "doc_lint_untracked_probe.tmp"
    probe.write_text("untracked\n")
    try:
        assert probe.exists(), "the probe must be on disk, or this proves nothing"
        doc_lint._tracked.cache_clear()
        assert doc_lint._resolve("doc_lint_untracked_probe.tmp") is None, (
            "a file git does not track is not a path a reviewer cloning the repo will have")
    finally:
        probe.unlink(missing_ok=True)
        doc_lint._tracked.cache_clear()


def test_a_tracked_path_still_resolves():
    """The guard above must not have turned the check into one that always fires."""
    doc_lint._tracked.cache_clear()
    assert doc_lint._resolve("scripts/doc_lint.py") is not None
    assert doc_lint._resolve("prospector/pack_linter.py") is not None
