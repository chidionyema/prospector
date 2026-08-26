"""`ci_verdict` decides whether production may move. It must count only verdicts on the code.

WHAT WENT WRONG. Measured 2026-08-21 on e900a9ad, with every lane that grades the code green:

    ('fail', 'production runs main=failure, production runs main=failure,
              PR keeper=cancelled, PR keeper=cancelled')

Two different mistakes produced that, and each one alone was enough to wall every route to
production -- `deploy_reconcile.py` and the console's update button both refuse a `fail`.

  1. `production runs main` reports where production IS. When production drifts it fails, this
     gate then reads main as red, and the deploy that would have closed the drift is refused
     because of the drift. A loop with no way out of it.
  2. A `cancelled` run executed nothing, so it has no opinion about the code -- word for word
     the reason `skipped` is already dropped. The previous fix named the one workflow it had
     seen (`auto-merge`); `PR keeper` walled the deploy the same way three weeks later.

AND the gate could not read production at all from CI: `superfly/flyctl-actions/setup-flyctl`
installs the binary as `flyctl` and puts only that name on PATH, while this file looked for
`fly`. Nine consecutive reconciler runs reported "production cannot be read" and opened a
critical about a drift they had never measured.

These tests pin the behaviour, not the spelling: the fixed source quotes the old bad string in
its own comments, so a grep would grade the comment and pass either way.
"""
from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


@pytest.fixture()
def lc():
    spec = importlib.util.spec_from_file_location("lc_verdicts", ROOT / "scripts" / "live_checkout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(*triples: tuple[str, str, str]) -> str:
    return "\n".join("\t".join(t) for t in triples) + "\n"


def _answer(lc, monkeypatch, rows: str):
    monkeypatch.setattr(lc.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(lc, "run", lambda *a, **k: (0, rows))
    return lc.ci_verdict(SHA)


CI_GREEN = ("CI", "completed", "success")


def test_a_workflow_that_reports_where_production_is_is_not_a_verdict_on_the_code(lc, monkeypatch):
    verdict, detail = _answer(lc, monkeypatch, _rows(
        CI_GREEN, ("production runs main", "completed", "failure")))
    assert verdict == "pass", (
        f"got {verdict!r} ({detail}). The reconciler's own workflow failing because production "
        "has drifted must not be the reason production is forbidden to move.")


def test_housekeeping_that_was_cancelled_cannot_fail_the_gate(lc, monkeypatch):
    """`PR keeper` acts on pull requests and tests nothing, so its two cancelled rows on
    e900a9ad were not a statement about the code. It walled every deploy anyway."""
    verdict, detail = _answer(lc, monkeypatch, _rows(
        CI_GREEN, ("PR keeper", "completed", "cancelled")))
    assert verdict == "pass", f"got {verdict!r} ({detail})"


def test_a_cancelled_CI_run_is_still_a_refusal(lc, monkeypatch):
    """THE HOLE THE OBVIOUS FIX OPENS, pinned so nobody reopens it.

    Dropping every `cancelled` row -- rather than naming the workflows that do not grade the
    code -- looks like the general version of the fix above and is not. A CI run cancelled by
    the next merge landing on top, sitting beside a green housekeeping row on the same sha,
    would then read `pass` and production would ship a commit CI never graded. That is the
    2026-08-17 shape verbatim: three runs cancelled by the merge on top, main's tip with no
    verdict at all, shipped inside 60 seconds.

    Whether a workflow has an opinion about the code is a fact about the WORKFLOW, not about
    one row's conclusion, which is why the list is by name.
    """
    verdict, _ = _answer(lc, monkeypatch, _rows(
        ("CI", "completed", "cancelled"),
        ("Main admission guard", "completed", "success")))
    assert verdict == "fail", (
        "a cancelled CI run read as clean because another workflow was green on the same sha")


def test_the_two_together_still_pass(lc, monkeypatch):
    """The exact row set measured on e900a9ad."""
    verdict, _ = _answer(lc, monkeypatch, _rows(
        CI_GREEN,
        ("production runs main", "completed", "failure"),
        ("production runs main", "completed", "failure"),
        ("PR keeper", "completed", "cancelled"),
        ("PR keeper", "completed", "cancelled"),
        ("Main admission guard", "completed", "success"),
    ))
    assert verdict == "pass"


def test_ignoring_a_workflow_can_never_turn_a_red_into_a_green(lc, monkeypatch):
    """Everything on the ignore list dropped leaves nothing, and nothing is `none` -- which
    `deploy_reconcile.reconcile` refuses exactly as hard as `fail`."""
    verdict, _ = _answer(lc, monkeypatch, _rows(
        ("production runs main", "completed", "failure"),
        ("PR keeper", "completed", "cancelled")))
    assert verdict == "none"


def test_a_real_failure_still_fails(lc, monkeypatch):
    verdict, detail = _answer(lc, monkeypatch, _rows(
        CI_GREEN, ("Main admission guard", "completed", "failure")))
    assert verdict == "fail" and "Main admission guard" in detail


def test_a_run_still_in_flight_still_holds(lc, monkeypatch):
    verdict, _ = _answer(lc, monkeypatch, _rows(("CI", "in_progress", "None")))
    assert verdict == "pending"


def test_production_can_be_read_where_only_flyctl_is_on_path(lc, monkeypatch, tmp_path):
    """A GitHub runner after setup-flyctl: `flyctl` exists, `fly` does not."""
    binary = tmp_path / "flyctl"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(lc, "IMAGE_STAMP", tmp_path / "not-in-a-container")

    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return 0, "6f7b2fc3ce95e11658d216922c5f2a3071be766f\n"

    monkeypatch.setattr(lc, "run", fake_run)
    sha, how = lc.deployed_commit()

    assert seen, (
        "nothing was executed, so the probe decided the CLI was missing on a PATH that has "
        "flyctl on it. That is the state every GitHub runner is in, and it is why the deploy "
        "reconciler failed nine times in a row reporting a drift it never measured.")
    assert seen[0][0] == str(binary)
    assert sha == "6f7b2fc3ce95e11658d216922c5f2a3071be766f", how


def test_the_machine_state_probe_reads_the_same_binary(lc, monkeypatch, tmp_path):
    binary = tmp_path / "flyctl"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(lc, "run", lambda cmd, **k: (0, '[{"state": "started"}]'))
    assert lc.fly_machine_state() == "started"


def test_no_fly_binary_anywhere_still_says_so(lc, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(lc, "find_fly", lambda: None)
    monkeypatch.setattr(lc, "IMAGE_STAMP", tmp_path / "absent")
    sha, how = lc.deployed_commit()
    assert sha == "" and "not on PATH" in how
    assert "not on PATH" in lc.fly_machine_state()


def test_the_resolver_is_the_estate_s_one_resolver(lc):
    """Not a second spelling of it. Two implementations of one class are worse than none."""
    import inspect
    owner = Path(inspect.getsourcefile(lc.find_fly)).name
    assert owner == "live_checkout.py", (
        f"find_fly came from {owner}; scripts/live_checkout.py owns it since "
        "rollback_now.py went (crew#203) and carries the launchd-PATH lesson.")


def test_os_import_is_present_for_the_outcome_file():
    assert os is not None


# --------------------------------------------------------------------------------------------
# the class: a workflow that does not grade the code must not be able to vote by default


#: Every workflow in this repo that DOES have an opinion about whether the code is good.
#: Everything else must be matched by `_IGNORED_WORKFLOWS`. This set is checked in so that
#: adding a workflow forces someone to answer the question, instead of the answer defaulting to
#: "it votes" and walling every deploy the first time it goes red or gets cancelled.
GRADES_THE_CODE = {
    "CI",
    "Main admission guard",
    "Main green guard",
    # `k8s manifests` grades repository content — the manifests and admission policies under
    # deploy/k8s — so a red run means this commit is wrong, which is the whole test on this list.
    # It cannot wall an unrelated deploy the way `production runs main` did: it carries path
    # filters for deploy/k8s/** and its own file, so a commit that touches neither starts no run
    # at all, and a workflow with no row cannot vote.
    "k8s manifests",
}


def _workflow_names() -> list[str]:
    names = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in path.read_text().splitlines():
            if line.startswith("name:"):
                names.append(line.split(":", 1)[1].strip().strip("'\""))
                break
        else:
            raise AssertionError(f"{path.name} has no top-level `name:`")
    return names


def test_every_workflow_is_classified(lc):
    """WHY THIS EXISTS. Twice now a workflow that tests nothing has walled every route to
    production: `Auto-merge green PRs` on 2026-08-18, `PR keeper` and `production runs main` on
    2026-08-21. Both times the fix was to add a name to the list after the fact, and the class
    stayed open because nothing asks the question when a workflow is ADDED.

    A new workflow fails this test until someone says which side of the line it is on.
    """
    unclassified = []
    for name in _workflow_names():
        low = name.lower()
        ignored = any(w in low for w in lc._IGNORED_WORKFLOWS)
        if ignored and name in GRADES_THE_CODE:
            unclassified.append(f"{name!r} is on BOTH lists; it cannot both vote and not vote")
        elif not ignored and name not in GRADES_THE_CODE:
            unclassified.append(name)
    assert not unclassified, (
        "these workflows are not classified: " + ", ".join(map(repr, unclassified)) + ".\n"
        "Either it grades the code -- add it to GRADES_THE_CODE in this file -- or it does not, "
        "and it must be matched by _IGNORED_WORKFLOWS in scripts/live_checkout.py. A workflow "
        "that does not grade the code but is allowed to vote refuses every deploy the first "
        "time it fails or is cancelled, and the drift it then reports is one it caused.")


def test_the_graders_are_not_accidentally_ignored(lc):
    """The mirror failure, and the dangerous one: a substring added to the ignore list that
    also matches CI would silence the only workflow whose opinion the gate exists to read."""
    for name in sorted(GRADES_THE_CODE):
        low = name.lower()
        hit = [w for w in lc._IGNORED_WORKFLOWS if w in low]
        assert not hit, (
            f"{name!r} grades the code and is silenced by _IGNORED_WORKFLOWS entry {hit!r}. "
            "Production would then deploy on a sha this workflow had failed.")
