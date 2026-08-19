"""A green pull request that cannot land must be a finding, not a note.

WHY THIS EXISTS. Measured 2026-08-19: PR #374 passed every check and carried
`mergeStateStatus: DIRTY`. Auto-merge silently could not fire, and `session_check.py` read only
`statusCheckRollup`, so it printed "open and not failing. Follow it to merged." Both mechanisms
looked at the wrong field and both reported success.

THE NEGATIVE FIXTURE IS THE POINT. Every blocker below is paired with the same pull request in a
mergeable state, so a checker that flagged everything, or nothing, fails here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import session_check as sc  # noqa: E402


def pr(**over) -> dict:
    """An open pull request with green checks and nothing in its way."""
    base = {"number": 374, "state": "OPEN", "statusCheckRollup": [],
            "mergeStateStatus": "CLEAN", "isDraft": False}
    base.update(over)
    return base


def test_a_clean_green_pull_request_is_not_flagged():
    """THE NEGATIVE HALF. Without this, `return ("something", "")` would pass every other test."""
    assert sc.merge_blocker(pr()) == ("", "")


def test_a_conflicted_pull_request_is_flagged_with_the_rebase_command():
    """THE MEASURED CASE. This is exactly the state #374 sat in."""
    why, fix = sc.merge_blocker(pr(mergeStateStatus="DIRTY"))
    assert "conflicts" in why
    assert "rebase origin/main" in fix


@pytest.mark.parametrize("state", ["DIRTY", "BEHIND", "BLOCKED"])
def test_every_blocking_state_names_a_command_that_clears_it(state):
    """A finding with no command is a complaint. The script's own contract."""
    why, fix = sc.merge_blocker(pr(mergeStateStatus=state))
    assert why and fix


def test_a_draft_is_flagged_because_auto_merge_skips_drafts_in_silence():
    """automerge.yml: `if (pr.draft) { core.info('skipping: still a draft'); continue }`. A draft
    left behind never merges and nothing complains -- and the dead-branch guard's rescue opens
    drafts on purpose, so this estate creates them routinely."""
    why, fix = sc.merge_blocker(pr(isDraft=True, mergeStateStatus="CLEAN"))
    assert "draft" in why
    assert fix == "gh pr ready 374"


def test_draft_is_reported_before_the_merge_state():
    """A draft that is ALSO conflicted must read as a draft. `gh pr ready` is the first move; the
    rebase is pointless until someone means to land it."""
    why, _ = sc.merge_blocker(pr(isDraft=True, mergeStateStatus="DIRTY"))
    assert "draft" in why


def test_unknown_is_not_a_finding_because_github_computes_it_lazily():
    """A pull request pushed to seconds ago genuinely answers UNKNOWN. Flagging that would fire on
    every push, and a checker that cries wolf gets ignored -- which costs more than it is worth.
    Measured: `gh pr view 374 --json mergeStateStatus` answered UNKNOWN immediately after a
    force-push on 2026-08-19."""
    assert sc.merge_blocker(pr(mergeStateStatus="UNKNOWN")) == ("", "")
    assert sc.unknown_merge_state(pr(mergeStateStatus="UNKNOWN")) is True
    assert sc.unknown_merge_state(pr(mergeStateStatus="")) is True
    assert sc.unknown_merge_state(pr()) is False


def test_the_state_is_matched_case_insensitively():
    """The field is upper case today. A checker that goes quiet if that ever changes is worse than
    one that never worked, because it looks like it is still watching."""
    assert sc.merge_blocker(pr(mergeStateStatus="dirty"))[0] != ""


def _report_for(pr_rows: list[dict], monkeypatch) -> sc.Report:
    """Drive check_branch_has_pr with a fake `gh`, so the wiring is tested and not just the
    predicate. A predicate nobody calls is the classic way a guard reports green."""
    import json as _json

    def fake_run(cmd, cwd=None, timeout=25):
        if cmd[:2] == ["git", "rev-parse"] and "--abbrev-ref" in cmd:
            return 0, "feat/x"
        if cmd[:2] == ["git", "rev-parse"]:          # origin/feat/x exists
            return 0, "abc123"
        if cmd[0] == "gh":
            return 0, _json.dumps(pr_rows)
        return 0, ""

    monkeypatch.setattr(sc, "run", fake_run)
    r = sc.Report()
    sc.check_branch_has_pr(r, local_only=False)
    return r


def test_the_checker_actually_calls_it_and_a_dirty_pr_becomes_an_outstanding_finding(monkeypatch):
    r = _report_for([pr(mergeStateStatus="DIRTY")], monkeypatch)
    assert [f for f in r.findings if "cannot be merged" in f[1]]


def test_the_same_pull_request_clean_produces_no_finding(monkeypatch):
    """The other half. `session_check.py` exits 1 on any finding, so a false positive here walls
    every session."""
    r = _report_for([pr()], monkeypatch)
    assert r.findings == []
    assert any("Follow it to merged" in n for n in r.notes)


def test_a_merged_pull_request_is_not_re_examined(monkeypatch):
    """Only OPEN rows matter. `gh pr list --state all` returns the closed ones too, and a merged
    PR reports whatever mergeStateStatus it last had."""
    r = _report_for([pr(state="MERGED", mergeStateStatus="DIRTY")], monkeypatch)
    assert r.findings == []


def test_failing_checks_and_a_conflict_are_both_reported(monkeypatch):
    """They are different problems with different fixes. Reporting one and stopping sends a
    session to rebase a branch whose tests are red."""
    rollup = [{"name": "python", "conclusion": "FAILURE"}]
    r = _report_for([pr(statusCheckRollup=rollup, mergeStateStatus="DIRTY")], monkeypatch)
    assert len(r.findings) == 2
