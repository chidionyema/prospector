"""A red pull request is a pointer to a reason. These tests pin the two reasons that lie.

On 2026-08-19 twenty-seven pull requests were red and FOUR had a test failure. The other
twenty-three were a ghost run, a killed machine, a cancellation or a run that never happened.
Two sessions independently mis-read them, and one wrote a memory file naming the wrong cause.

Both traps are invisible from the shape of the data, which is why they are tests and not notes:

  GHOST RUN      conclusion `action_required`, zero jobs. GitHub will not build a push made
                 with GITHUB_TOKEN, and automerge.yml makes exactly that push. The real run is
                 the OLDER dispatched one, so "newest run" returns the ghost.
  KILLED RUNNER  a failed job with no failed STEP. The cause is only in the annotation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pr_triage.py"


def _load():
    spec = importlib.util.spec_from_file_location("pr_triage", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conclusion="failure", status="completed", rid=1, created="2026-08-19T18:00:00Z"):
    return {"conclusion": conclusion, "status": status, "databaseId": rid, "createdAt": created}


def _job(name, conclusion="failure", jid=10, failed_steps=(), total_steps=11):
    """A job. `failed_steps` empty with steps that never concluded is the killed-runner shape."""
    steps = [{"name": f"step{i}", "conclusion": "success"} for i in range(total_steps)]
    for s in failed_steps:
        steps.append({"name": s, "conclusion": "failure"})
    return {"name": name, "conclusion": conclusion, "id": jid, "steps": steps}


LOSS = "The self-hosted runner lost communication with the server. Verify the machine is running"


def test_a_killed_runner_is_not_a_test_failure():
    mod = _load()
    verdict, detail = mod.classify(_run(), [_job("python", jid=10)], {10: LOSS})
    assert verdict == "RUNNER KILLED", (
        f"a job whose machine died has no failed step; only the annotation says so. got {verdict}"
    )
    assert "python" in detail


def test_a_real_test_failure_is_still_reported_as_real():
    """The check must not launder genuine failures into infrastructure."""
    mod = _load()
    verdict, detail = mod.classify(
        _run(), [_job("python", jid=10, failed_steps=["Test suite"])], {10: "boring warning"})
    assert verdict == "REAL FAIL"
    assert "Test suite" in detail


def test_ci_ok_is_never_the_cause():
    """`ci-ok` fails BECAUSE something else did, so counting it doubles every failure."""
    mod = _load()
    jobs = [_job("python", jid=10), _job("ci-ok", jid=11, failed_steps=["Every job passed"])]
    verdict, detail = mod.classify(_run(), jobs, {10: LOSS, 11: ""})
    assert verdict == "RUNNER KILLED", f"ci-ok must not be read as the cause. got {verdict}"
    assert "ci-ok" not in detail


def test_a_ghost_run_never_hides_the_real_one():
    """TRAP 1: the ghost is NEWER, so sorting by time without filtering returns the wrong run."""
    mod = _load()
    real = _run(conclusion="success", rid=111, created="2026-08-19T18:43:00Z")
    ghost = _run(conclusion="action_required", rid=222, created="2026-08-19T18:43:29Z")
    picked = mod.newest_real_run([real, ghost])
    assert picked["databaseId"] == 111, (
        "the action_required run is newer and built nothing; picking it hides the verdict"
    )


def test_a_head_with_only_a_ghost_is_reported_as_a_ghost():
    """Not green, and not a failure either. It means nothing ever built this commit."""
    mod = _load()
    ghost = _run(conclusion="action_required", rid=222)
    assert mod.newest_real_run([ghost])["databaseId"] == 222
    verdict, _ = mod.classify(ghost, [], {})
    assert verdict == "GHOST ONLY"


def test_no_run_at_all_is_not_green():
    """Silence is the one answer that must never be read as health."""
    mod = _load()
    assert mod.newest_real_run([]) is None
    assert mod.classify(None, None, None)[0] == "NO RUN"


@pytest.mark.parametrize("conclusion,want", [
    ("success", "GREEN"),
    ("cancelled", "CANCELLED"),
])
def test_the_uninteresting_verdicts(conclusion, want):
    mod = _load()
    assert mod.classify(_run(conclusion=conclusion), [], {})[0] == want


def test_infrastructure_and_timing_never_ask_for_a_person():
    """The whole point: 27 red PRs must not read as 27 investigations."""
    mod = _load()
    assert mod.NEEDS_A_PERSON == {"REAL FAIL", "CONFLICT"}
    for v in ("RUNNER KILLED", "CANCELLED", "GHOST ONLY", "GREEN", "IN PROGRESS"):
        assert v not in mod.NEEDS_A_PERSON, f"{v} is infrastructure or timing, not code"


def test_a_blocked_pull_request_is_never_summarised_as_all_clear():
    """The defect this tool had: it counted only REAL FAIL, so a conflict read as fine.

    Measured 2026-08-19: it printed "0 of 6 open pull request(s) need a person" while #458 and
    #426 both had merge conflicts with main. Neither could land on any CI verdict, and no re-run
    and no waiting would have changed that. A summary that cannot see a blocker reports all-clear,
    which is the most expensive thing a status tool can do.
    """
    mod = _load()
    assert "CONFLICT" in mod.NEEDS_A_PERSON
    assert "CONFLICT" in mod.STUCK, "a conflicting PR is not moving on its own"
    for v in ("GREEN", "IN PROGRESS"):
        assert v not in mod.STUCK, f"{v} is moving; counting it as stuck cries wolf"
    assert set(mod.SEVERITY) - {"GREEN", "IN PROGRESS"} == mod.STUCK, (
        "every verdict is either moving or stuck; a new one must be classified as one of them"
    )


def test_a_conflict_outranks_the_run_even_when_ci_is_green():
    """CI passing on a branch that cannot merge is not progress, and must not read as green."""
    mod = _load()
    green = _run(status="completed", conclusion="success")

    assert mod.classify(green, [], {}, "CONFLICTING")[0] == "CONFLICT"
    assert mod.classify(None, None, None, "CONFLICTING")[0] == "CONFLICT"
    assert mod.classify(green, [], {}, "MERGEABLE")[0] == "GREEN"


def test_github_still_computing_the_merge_is_not_a_conflict():
    """GitHub answers UNKNOWN until it has computed the merge. Every fresh PR passes through it.

    UNKNOWN must not become CONFLICT -- that would mark every newly-opened pull request as
    needing a rebase. It must not become GREEN either, which is what this test used to pin and
    what reported #445 as green on 2026-08-19 while it had a merge conflict with main.
    """
    mod = _load()
    green = _run(status="completed", conclusion="success")

    verdict, detail = mod.classify(green, [], {}, "UNKNOWN")
    assert verdict != "CONFLICT", "unknown is not a conflict"
    assert verdict == "MERGE UNKNOWN", (
        f"an uncomputed merge is neither clean nor conflicting, and reporting it GREEN is a "
        f"claim the data does not support. got {verdict!r}"
    )
    assert "re-run" in detail, "it must say what the action is"
    assert verdict in mod.STUCK, "nothing about this PR moves until GitHub answers"
    assert verdict not in mod.NEEDS_A_PERSON, (
        "it usually resolves itself on the next ask; escalating it to a person would make the "
        "'needs a person' number noise, and a noisy number gets ignored"
    )


def test_a_caller_that_never_asked_about_the_merge_still_gets_the_ci_verdict():
    """`mergeable=None` means this caller did not ask, which is different from GitHub not knowing.

    Conflating the two would turn every unit-level call of classify() into MERGE UNKNOWN and
    make the verdict depend on the caller's curiosity rather than on the pull request.
    """
    mod = _load()
    green = _run(status="completed", conclusion="success")
    assert mod.classify(green, [], {}, None)[0] == "GREEN"
    assert mod.classify(green, [], {})[0] == "GREEN"


def test_a_draft_is_never_reported_as_green():
    """A draft does not merge, however green it is. #461 was green, a draft, and unlandable."""
    mod = _load()
    green = _run(status="completed", conclusion="success")

    verdict, detail = mod.classify(green, [], {}, "MERGEABLE", True)
    assert verdict == "DRAFT", f"a green draft is not a landed PR. got {verdict!r}"
    assert "ready for review" in detail, "it must name the action that unblocks it"
    assert verdict in mod.STUCK, "a draft moves only when someone marks it ready"
    assert mod.classify(green, [], {}, "MERGEABLE", False)[0] == "GREEN", (
        "a non-draft green PR must still read GREEN"
    )


def test_an_obstacle_never_hides_a_fault():
    """Draft and unknown-merge overrule GREEN only. A broken draft still reports as broken.

    The opposite ordering trades one silence for another: the queue stops lying about drafts
    and starts hiding their failures instead.
    """
    mod = _load()
    failed = _run(status="completed", conclusion="failure")
    jobs = [{"id": 1, "name": "python", "conclusion": "failure",
             "steps": [{"name": "Test suite", "conclusion": "failure"}]}]

    verdict, detail = mod.classify(failed, jobs, {}, "UNKNOWN", True)
    assert verdict == "REAL FAIL", (
        f"a draft with a failing test must still report the failure. got {verdict!r}"
    )
    assert "Test suite" in detail, "and it must still name the step that failed"


def test_the_merge_state_is_asked_again_before_it_is_believed(monkeypatch):
    """The first ask is what STARTS GitHub computing, so the first answer is routinely UNKNOWN.

    This is the mechanical half of the #445 fix. Without the re-ask, the tool's verdict depends
    on how recently the PR was touched, which is not a property of the pull request at all.
    """
    mod = _load()
    answers = [
        [{"number": 1, "mergeable": "UNKNOWN"}],
        [{"number": 1, "mergeable": "CONFLICTING"}],
    ]
    calls = []

    def fake_json(args):
        calls.append(args)
        return answers[min(len(calls) - 1, len(answers) - 1)]

    monkeypatch.setattr(mod, "_json", fake_json)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    prs = mod.list_open_prs()
    assert len(calls) == 2, f"it must ask again while the answer is UNKNOWN. calls={len(calls)}"
    assert prs[0]["mergeable"] == "CONFLICTING", "and it must report the resolved answer"


def test_the_re_ask_is_bounded_and_reports_what_it_could_not_resolve(monkeypatch):
    """A PR GitHub never resolves must end as UNKNOWN, not as an unbounded wait or a clean bill."""
    mod = _load()
    calls = []

    def fake_json(args):
        calls.append(args)
        return [{"number": 1, "mergeable": "UNKNOWN"}]

    monkeypatch.setattr(mod, "_json", fake_json)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    prs = mod.list_open_prs(attempts=3)
    assert len(calls) == 3, f"bounded at the attempt count. calls={len(calls)}"
    assert prs[0]["mergeable"] == "UNKNOWN", (
        "it must hand back the unresolved answer so classify() can report it, rather than "
        "dropping the field and letting the PR read green"
    )


def test_a_resolved_merge_state_is_asked_for_exactly_once(monkeypatch):
    """The retry must cost nothing on the normal path, or nobody will run the tool."""
    mod = _load()
    calls = []

    def fake_json(args):
        calls.append(args)
        return [{"number": 1, "mergeable": "MERGEABLE"}]

    monkeypatch.setattr(mod, "_json", fake_json)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: pytest.fail("must not sleep"))

    mod.list_open_prs()
    assert len(calls) == 1, f"one clean answer needs one call. calls={len(calls)}"


def test_the_cancelled_reason_names_no_mechanism_it_did_not_measure():
    """It used to blame `cancel-in-progress`, which ci.yml disproves by setting it false."""
    mod = _load()
    _, detail = mod.classify(_run(status="completed", conclusion="cancelled"), [], {})
    assert "cancel-in-progress" not in detail, (
        f"detail {detail!r} asserts a cause this tool never measured. ci.yml sets "
        f"`cancel-in-progress: false`, so the sentence sent the next reader to the wrong file."
    )
    assert "re-run" in detail, "it must still say what the action is"


def test_a_failure_naming_no_job_is_reported_not_swallowed():
    """An unexplained failure must stay loud. Silently calling it infrastructure is the bug."""
    mod = _load()
    verdict, detail = mod.classify(_run(), [], {})
    assert verdict == "REAL FAIL"
    assert "by hand" in detail
