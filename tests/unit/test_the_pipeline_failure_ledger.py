"""Every way the delivery pipeline can break is written down here, with the test that proves it.

FOUNDER DIRECTIVE, 2026-08-20: "we eed bsolte proof, we need to suinulte all that ould go wrong
all edge cases now and prove it is stable and trustworthy while we have capacity to do so. so the
onl thing that can ever go wrong is apacity, not a nillin things at once."

That is the goal state this file encodes. "Too many things can go wrong" is a feeling, and a
feeling cannot be closed. A LIST can. Each row below names one failure mode of the pipeline and
either points at the test that simulates it, or admits the mode is unguarded and names the issue
tracking it. The open list is ratcheted: it may shrink, and adding to it is a deliberate edit that
shows up in a diff.

WHY A LEDGER AND NOT A DOCUMENT. A document goes stale silently -- on 2026-08-19 a docstring in
this repo described ten standby machines that had already been repaired, and a session acted on
it. This file cannot go stale in that direction: `test_every_proven_mode_has_a_live_proof` opens
each proof file, and `test_every_workflow_is_named_by_the_ledger` fails the moment a workflow
appears that no row accounts for. You cannot add an automated actor to this pipeline without
saying, here, how it can hurt us.

WHAT THIS FILE IS NOT. It does not re-test the modes. Each proof file does that. This file tests
that the proofs EXIST and that the enumeration is complete, which is the part no individual test
can check about itself.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


class Mode(NamedTuple):
    """One way the pipeline can break."""

    id: str
    what_goes_wrong: str
    surfaces: tuple[str, ...]  # the workflow files or scripts this mode lives in
    proof: str | None  # repo-relative path to the test that simulates it
    issue: int | None  # tracking issue, required when proof is None
    why_open: str | None  # what is missing, required when proof is None


# ---------------------------------------------------------------- the ledger
#
# Ordered by where the failure happens: merge, then main, then observation, then deploy, then
# capacity. Every entry was paid for by an incident unless marked otherwise.

LEDGER: tuple[Mode, ...] = (
    # ---- at the merge
    Mode(
        "merge-over-a-red-check",
        "A pull request is merged while its own ci-ok is failing. Six PRs went in this way on "
        "2026-08-19 and main was red for over an hour.\n\n"
        "CLOSED 2026-08-21, and by GitHub rather than by a robot. This row read `both "
        "branch-protection endpoints answer 403 on this plan, so ci-ok is a required check in "
        "name only` -- true while the repository was private. It went public, so rulesets work: "
        "ruleset `strict` (id 20109556) is active on ~DEFAULT_BRANCH with bypass_actors: [] and "
        "requires guard, python, dotnet, nextjs and ci-ok. Nothing merges over a red ci-ok and "
        "nothing pushes to main at all, which is why main-admission-guard.yml and "
        "main-green-guard.yml were deleted rather than fixed.\n\n"
        "Verify the platform half with `gh api repos/chidionyema/prospector/rulesets/20109556`. "
        "The proof below covers the repository half, which is the half a merge can break: a "
        "required check that does not actually aggregate the lanes is green while a lane is red.",
        (".github/workflows/ci.yml",),
        "tests/unit/test_ci_ok_is_the_required_check.py",
        None,
        None,
    ),
    Mode(
        "merge-of-a-branch-behind-main",
        "A PR that is green on its own merge ref is merged while behind main, and the combination "
        "breaks main. The PR was never tested against what main actually contains. automerge.yml "
        "used to close this by calling pulls.updateBranch, which is the very call that jammed the "
        "board for thirty hours -- see a-workflow-pushes-to-an-open-prs-branch below. Since "
        "2026-08-20 the branch is the AUTHOR's to update: pr-keeper.yml counts how far behind it "
        "is, labels it needs-rebase and comments the command to run, and pushes nothing.",
        (".github/workflows/pr-keeper.yml",),
        "tests/unit/test_pr_keeper.py",
        None,
        None,
    ),
    Mode(
        "a-merge-robot-merges-and-nothing-ships-what-it-merged",
        "merge-when-green.yml merges with GITHUB_TOKEN, and GitHub starts NO workflow run from a "
        "GITHUB_TOKEN push. So the deploys that a human merge would have started never run, and "
        "the workflow has to dispatch them itself from a COPY of each deploy workflow's own "
        "`paths:` filter. A copy drifts. When the copy is narrower than the original, the queue "
        "drains, every pull request reads as merged, and production quietly stops tracking main "
        "with nothing red anywhere -- bounded at about an hour by production-runs-main.yml's "
        "cron, which is a detection, not a prevention. The two tests that used to grade exactly "
        "this drift were deleted with automerge.yml on 2026-08-20; the note recording that "
        "lived in main-admission-guard.yml:381, which went with it on 2026-08-21.",
        (".github/workflows/merge-when-green.yml",),
        "tests/unit/test_merge_when_green_dispatches_what_the_push_could_not.py",
        None,
        None,
    ),
    Mode(
        "a-workflow-pushes-to-an-open-prs-branch",
        "A workflow calls pulls.updateBranch, which pushes `Merge branch 'main' into <branch>` "
        "onto an open pull request whenever main moves. GitHub closes a pull request only when "
        "its own head COMMIT is reachable from main, so the moved head drops out of whatever "
        "branch was cut to close it -- and a batch cut to clear a backlog triggers this with its "
        "own merge, on every pull request at once. Measured 2026-08-20: fifteen pull requests, "
        "three failed batches, thirty hours, and the call lived in two workflows written weeks "
        "apart by different sessions.",
        (".github/workflows/pr-keeper.yml",),
        "tests/unit/test_nothing_pushes_to_a_pull_request_branch.py",
        None,
        None,
    ),
    Mode(
        "a-throw-mid-script-drops-everything-below-it",
        "An unhandled error part way through a github-script step silently skips the rest of the "
        "step. On 2026-08-19 checks.listForRef threw 403 above the CI dispatch, so the merge of "
        "#451 landed on main and main was never graded.",
        (".github/workflows/merge-when-green.yml",),
        "tests/unit/test_a_workflow_step_cannot_hide_its_own_failure.py",
        None,
        None,
    ),
    Mode(
        "a-permissions-block-denies-a-call-the-job-makes",
        "An explicit `permissions:` block is a whitelist: every scope it does not name is set to "
        "none, and a job-level block replaces the top-level one outright. The call fails with 403 "
        "at run time, not at lint time.",
        (".github/workflows/merge-when-green.yml", ".github/workflows/e2e-live-smoke.yml"),
        "tests/unit/test_a_workflow_permission_block_covers_its_api_calls.py",
        None,
        None,
    ),
    # ---- on main
    Mode(
        "a-push-lands-straight-on-main",
        "Someone or something pushes to main without a pull request, so no CI verdict ever "
        "covered the code that main now contains.",
        (".github/workflows/ci.yml",),
        "tests/unit/test_main_push_guard.py",
        None,
        None,
    ),
    Mode(
        "stale-closes-something-that-is-not-an-abandoned-pr",
        "The stale workflow holds issues:write and pull-requests:write. A config edit could let "
        "it close issues, close a pull request before the 14 idle days, or ignore keep-open.",
        (".github/workflows/stale.yml",),
        "tests/unit/test_stale_never_closes_issues_or_kept_prs.py",
        None,
        None,
    ),
    # ---- observing it
    Mode(
        "a-tool-calls-main-green-from-a-stale-run",
        "A probe reads the newest CI run and reports green, when that run tested an older commit "
        "than main's HEAD.",
        ("scripts/main_red.py",),
        "tests/unit/test_main_red_never_reports_a_stale_green.py",
        None,
        None,
    ),
    Mode(
        "a-run-with-no-jobs-is-read-as-a-verdict",
        "GitHub refuses to build a push made with the default GITHUB_TOKEN: it creates a run with "
        "conclusion action_required and ZERO jobs. It sorts newest, so any tool reading 'the "
        "latest run at this head' reports a green PR as pending, or a red one as unknown.",
        ("scripts/pr_triage.py",),
        "tests/unit/test_pr_triage_reads_the_cause_not_the_colour.py",
        None,
        None,
    ),
    Mode(
        "a-parked-run-stalls-the-queue-and-nothing-starts-it",
        "The run above is not only misread, it is never STARTED. GitHub parks it, and no event in "
        "this estate fires on `action_required`, so nothing notices. Measured 2026-08-20: four of "
        "the eight open pull requests sat behind one, including #474 — the one-file fix for the "
        "single test holding main red — so main stayed red, and a red main stops ci.yml building "
        "any pull request at all. The whole queue was stalled behind a run nobody had let start.",
        (".github/workflows/approve-parked-runs.yml",),
        "tests/unit/test_only_our_own_parked_runs_are_approved.py",
        None,
        None,
    ),
    Mode(
        "a-workflow-github-cannot-start-reports-nothing",
        "A workflow subscribing to an event GitHub does not have produces runs with no jobs and "
        "no red check anywhere. The alarm is silent in exactly the way a healthy alarm is.",
        (".github/workflows/ci.yml",),
        "tests/unit/test_workflow_triggers_are_real.py",
        None,
        None,
    ),
    Mode(
        "a-dead-or-disabled-workflow-reports-healthy",
        "A workflow that is disabled, or whose last run is ancient, is reported green because "
        "nothing failed. Absence of red is not presence of green.",
        (".github/workflows/e2e-live-smoke.yml",),
        "tests/unit/test_workflow_health_never_reports_a_dead_workflow_green.py",
        None,
        None,
    ),
    Mode(
        "a-pull-request-changes-code-whose-lane-never-runs",
        "ci.yml's changes filter decides which lanes run. A path it does not match ships "
        "ungraded, and the PR is green because nothing looked at it.",
        (".github/workflows/ci.yml",),
        "tests/unit/test_ci_change_filter_grades_every_lane.py",
        None,
        None,
    ),
    # ---- shipping it
    Mode(
        "production-ships-a-commit-ci-never-passed",
        "A deploy is dispatched for a commit whose CI run failed or never concluded. The Fly "
        "deploy workflows this row named were deleted on 2026-08-26 (crew#203); the same gate "
        "logic now stands in front of the image publish.",
        (".github/workflows/container-images.yml",),
        "tests/unit/test_deploy_gate_on_ci_verdict.py",
        None,
        None,
    ),
    # The three Fly-only rows that sat here (main-goes-green-and-a-component-never-deploys,
    # a-deploy-queues-behind-our-own-ci, main-moves-and-no-deploy-is-ever-dispatched) went with
    # the Fly pipeline on 2026-08-26 (crew#203, founder ruling R1). Under OKE the merge hands off
    # to container-images.yml and Flux; the two rows below are the OKE shapes of what is left.
    Mode(
        "main-moves-and-the-cluster-never-rolls-it-out",
        "container-images.yml publishes the commit-tagged image and Flux is expected to roll it "
        "out from deploy/k8s/overlays/oke. Nothing in this repository grades that Flux did: a "
        "publish that succeeded and a reconcile that never happened leave no failing run, so "
        "no alarm here can fire on it.",
        (".github/workflows/container-images.yml", ".github/workflows/k8s-manifests.yml",
         "scripts/oke_release_probe.py"),
        "tests/unit/test_the_cluster_runs_main.py",
        203,
        None,
    ),
    Mode(
        "production-runs-code-that-is-not-main",
        "The image published and the cluster is still executing an older one, so every "
        "instrument says shipped and none of them looked at what is running.",
        (".github/workflows/container-images.yml", "scripts/oke_release_probe.py"),
        "tests/unit/test_the_cluster_runs_main.py",
        203,
        None,
    ),
    # ---- the drills that watch the rest
    Mode(
        "an-alarm-that-runs-after-the-thing-it-guards",
        "A scheduled check that runs after a deploy cannot prevent that deploy, and a live smoke "
        "reported red to nobody for thirty hours.",
        (
            ".github/workflows/e2e-live-smoke.yml",
            ".github/workflows/dns-drift-drill.yml",
            ".github/workflows/weekly-estate-review.yml",
        ),
        "tests/unit/test_an_alarm_must_run_when_the_thing_it_alarms_on_fails.py",
        None,
        None,
    ),
    # ---- capacity: the one the founder has accepted
    Mode(
        "the-fleet-cannot-hold-the-work",
        "There are fewer usable runners than queued jobs, so builds wait. This is the ONE failure "
        "mode the founder has accepted as permanent: it is visible, it is a money decision, and "
        "it degrades rather than corrupts. Everything else in this ledger must be guarded so that "
        "this is the only thing left that can go wrong.",
        ("ops/config/ci_capacity.yaml", "scripts/ci_capacity.py"),
        "tests/unit/test_ci_capacity.py",
        None,
        None,
    ),
    Mode(
        "the-fleet-collapses-and-nothing-puts-it-back",
        "CI runner machines are stopped rather than broken, and no agent is watching. Measured "
        "2026-08-19: ten of the twelve prospector-ci machines were `stopped`, capacity was 2/12 "
        "for hours, and main's own run for 6054bf09 queued at 18:11:53Z and never got a machine. "
        "It passed first time, in full, the moment the machines were started by hand. Two things "
        "kept it invisible. The floor WAS the collapse -- ci_capacity.yaml declared runners: 2 "
        "and autoscale_min: 2, so a fleet of 2 online out of 12 graded as CONTRACT HOLDS, and a "
        "floor set to the minimum survivable number cannot detect a collapse to it. And nothing "
        "acted: ci_fleet_probe.py grades the fleet, but a report is only as good as whoever is "
        "reading it, and at 18:11 nobody was. fleet.min_started is a second, higher number whose "
        "only job is to notice, and the keeper runs hourly and STARTS machines -- it never stops, "
        "destroys or creates one, so the worst outcome of a bug in it is a machine running that "
        "did not need to be. It must stay on ubuntu-latest: a self-hosted runner cannot start a "
        "dead self-hosted fleet, because when the fleet is down nothing picks the job up.",
        ("scripts/ci_fleet_keeper.py", "ops/config/ci_capacity.yaml"),
        "tests/unit/test_ci_fleet_keeper.py",
        None,
        None,
    ),
    Mode(
        "a-machine-that-registers-as-a-runner-cannot-hold-a-job",
        "A Fly standby machine registers with GitHub and is stopped by the platform mid-build. "
        "Every count says twelve; the number that can work is two. The build dies as 'the "
        "self-hosted runner lost communication with the server', which reads as a flaky test.",
        ("scripts/ci_fleet_probe.py",),
        "tests/unit/test_a_standby_machine_is_not_capacity.py",
        None,
        None,
    ),
    Mode(
        "an-agent-push-destroys-another-agents-in-flight-run",
        "ci.yml sets cancel-in-progress for every ref that is not main, so a push cancels the run "
        "that was about to merge someone else's work. 49 of 195 runs on 2026-08-19 were cancelled.",
        (".github/workflows/ci.yml",),
        "tests/unit/test_dead_branch_push_guard.py",
        None,
        None,
    ),
    Mode(
        "a-run-is-cancelled-for-a-pull-request-that-is-still-open",
        "cancel-ci-on-pr-close.yml cancels runs when a PR closes. It holds actions: write, so a "
        "wrong match kills a live build, and a cancelled run is indistinguishable from a failure "
        "in every listing.",
        (".github/workflows/cancel-ci-on-pr-close.yml",),
        "tests/unit/test_a_pr_cleanup_cannot_cancel_a_live_build.py",
        None,
        None,
    ),
    # ---- at the standards gate
    Mode(
        "an-admission-gate-passes-on-nothing",
        "k8s-manifests.yml grades the Kubernetes manifests against the estate's own 26 admission "
        "policies. Handed no resources to grade, the Kyverno CLI prints `Applying 0 policy "
        "rule(s)` and `pass: 0, fail: 0, error: 0` and exits 0 — measured 2026-08-24 — so the gate "
        "goes green while grading nothing. Two ordinary edits produce that: dropping engine.yaml "
        "from base/kustomization.yaml, and pointing the CLI at a build that contains a non-policy "
        "document, which makes it silently load ZERO rules.\n\n"
        "This is the same class as `kyverno test` reporting `13 tests passed` with an assertion "
        "violated: every instrument in the chain reports a SHAPE, and a shape is green when there "
        "is nothing behind it. The gate therefore asserts what it graded, not merely that grading "
        "returned no failures — a Deployment present, at least 4 non-policy documents, at least "
        "50 rules loaded, and a non-zero pass count.",
        (".github/workflows/k8s-manifests.yml", "deploy/k8s/split_workloads.py"),
        "tests/unit/test_the_k8s_gate_cannot_pass_on_nothing.py",
        None,
        None,
    ),
    # ---- at the registry
    Mode(
        "the-cluster-runs-a-tag-that-moved",
        "container-images.yml holds `packages: write` and pushes three images to ghcr.io. The "
        "overlays under deploy/k8s/overlays name images by TAG, so if the tag CI publishes is a "
        "moving one — `latest`, `main`, `edge`, or a `type=sha` whose prefix is not pinned — the "
        "overlay names a moving target and the cluster runs whatever was pushed last rather than "
        "the commit that was graded. Nothing downstream catches it: the manifests apply, the pods "
        "start, and the running code is not the reviewed code. Kyverno's `disallow-latest-tag` "
        "does not catch it either — upstream it refuses `:latest` and an untagged image, and a "
        "moving `:main` sails past.\n\n"
        "Not paid for by an incident here, because nothing built these images until 2026-08-24. "
        "It is the shape of the incident this pipeline would otherwise import: a deploy path "
        "whose artifact identity is weaker than its review gate.\n\n"
        "The second mode in the same file is the storefront's build-time variables. NEXT_PUBLIC_* "
        "are inlined into the bundle at build time and an empty one does not fail the build; it "
        "ships a page that calls `undefined`. deploy-web.yml already checks this before handing "
        "off, and the image path has to check the same thing or the k8s route reintroduces the "
        "bug the Fly route fixed. The proof asserts the check runs BEFORE the build step and "
        "exits non-zero.",
        (".github/workflows/container-images.yml",),
        "tests/unit/test_the_image_pipeline_publishes_one_immutable_tag.py",
        None,
        None,
    ),
)

# The modes with no proof. This set is a RATCHET: removing an entry is the point of the
# exercise, and adding one must be a deliberate, reviewable edit rather than a regression
# that slips in. See test_the_open_list_does_not_grow.
#
# It reached empty on 2026-08-21. Its one entry, merge-over-a-red-check, closed when the
# repository went public and ruleset `strict` made ci-ok a required check with no bypass
# actors -- a platform control, not a test. That is also why five rows left this ledger the
# same day: they described robots (main-admission-guard.yml, main-green-guard.yml) that
# existed only because branch protection answered 403.
OPEN_BASELINE: frozenset[str] = frozenset(
    {
        # Admitted on 2026-08-26 with the Fly pipeline's deletion (crew#203). Their Fly proofs
        # (test_deploy_reconcile, test_live_checkout_deploy_gap) went with it. crew#203 PR 3
        # closed both rows with scripts/oke_release_probe.py (tests/unit/test_the_cluster_runs_main.py).
    }
)

# Workflows that grade or ship nothing and hold no write scope still have to be named, but a
# purely advisory workflow does not need its own failure mode. Nothing is exempt today; this
# exists so that adding an exemption is explicit rather than a silent gap in the sweep.
EXEMPT_WORKFLOWS: frozenset[str] = frozenset()


def _ids() -> list[str]:
    return [m.id for m in LEDGER]


def test_the_ledger_is_not_empty_and_ids_are_unique():
    """A broken constant must fail loudly, not make every other test in this file vacuous."""
    assert len(LEDGER) >= 15, f"the ledger has shrunk to {len(LEDGER)} rows; that is a deletion"
    assert len(set(_ids())) == len(LEDGER), "two rows share an id"


@pytest.mark.parametrize("mode", [m for m in LEDGER if m.proof], ids=lambda m: m.id)
def test_every_proven_mode_has_a_live_proof(mode: Mode):
    """The proof must be a real test file that really contains tests.

    This is the check that stops the ledger going stale the way a document does: a proof that was
    renamed, merged away or emptied fails here instead of quietly continuing to look guarded.
    """
    path = ROOT / mode.proof
    assert path.exists(), (
        f"{mode.id}: the proof {mode.proof} is not on disk. Either the test was renamed and this "
        f"row needs updating, or the guard was deleted and this mode is now OPEN."
    )
    body = path.read_text(encoding="utf-8")
    assert re.search(r"^\s*def test_", body, re.M), (
        f"{mode.id}: {mode.proof} exists but defines no test function, so it proves nothing"
    )


@pytest.mark.parametrize("mode", [m for m in LEDGER if not m.proof], ids=lambda m: m.id)
def test_every_open_mode_names_an_issue_and_says_what_is_missing(mode: Mode):
    """An admitted gap with no ticket is a gap nobody is going to close."""
    assert mode.issue, f"{mode.id} has no proof and no tracking issue"
    assert mode.why_open and len(mode.why_open) > 40, (
        f"{mode.id} must say what is missing, in enough detail that the next session can act on "
        f"it without re-deriving the incident"
    )


def test_the_open_list_does_not_grow():
    """The ratchet. The point of the exercise is for this set to shrink to nothing."""
    open_now = {m.id for m in LEDGER if not m.proof}
    added = open_now - OPEN_BASELINE
    assert not added, (
        f"new unguarded failure modes: {sorted(added)}. If that is deliberate, add them to "
        f"OPEN_BASELINE in the same commit and say why in the message."
    )
    closed = OPEN_BASELINE - open_now
    assert not closed, (
        f"{sorted(closed)} now has a proof — good. Remove it from OPEN_BASELINE so the ratchet "
        f"tightens, otherwise the next gap can take its place for free."
    )


def _workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS.glob("*.yml") if p.name not in EXEMPT_WORKFLOWS)


def test_there_are_workflows_to_grade():
    """Guards the glob: an empty sweep must not read as full coverage."""
    assert len(_workflow_files()) >= 10, "the workflow glob found almost nothing; check the path"


@pytest.mark.parametrize("wf", _workflow_files(), ids=lambda p: p.name)
def test_every_workflow_is_named_by_the_ledger(wf: Path):
    """Exhaustiveness. You cannot add an automated actor without saying how it can hurt us.

    This is the test that makes the enumeration complete by construction rather than by
    somebody's memory of what the pipeline contains.
    """
    rel = f".github/workflows/{wf.name}"
    named_by = [m.id for m in LEDGER if rel in m.surfaces]
    assert named_by, (
        f"{rel} is not named by any row in the ledger. Every workflow in this pipeline must have "
        f"at least one written-down way it can break, with either a proof or an issue. Add a Mode "
        f"for it in {Path(__file__).name}."
    )


@pytest.mark.parametrize("wf", _workflow_files(), ids=lambda p: p.name)
def test_a_workflow_that_can_write_is_covered_by_a_proof_or_an_admitted_gap(wf: Path):
    """A workflow holding contents: write or actions: write can damage the estate on its own.

    main-green-guard.yml reverted commits on main and had no test of any kind until this ledger
    said so out loud -- it was deleted on 2026-08-21, and this check is what would catch its
    replacement arriving unnamed. The scope is read from the file rather than from a list here, so granting a
    new write scope drags the workflow into this check automatically.
    """
    text = wf.read_text(encoding="utf-8")
    writes = sorted(
        set(re.findall(r"^\s*(contents|actions|issues|packages):\s*write\s*$", text, re.M))
    )
    if not writes:
        pytest.skip(f"{wf.name} holds no write scope")

    rel = f".github/workflows/{wf.name}"
    rows = [m for m in LEDGER if rel in m.surfaces]
    assert rows, f"{rel} holds {writes} and is not in the ledger at all"
    assert any(m.proof for m in rows) or any(m.issue for m in rows), (
        f"{rel} holds {writes} but every row naming it is silent: no proof, no issue"
    )
