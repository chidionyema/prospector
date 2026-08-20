"""A lane that stops at its first failing step must SAY which steps never ran.

The defect this pins, measured 2026-08-20. `run_lane` breaks out of its step loop on the first
non-zero exit. For the python lane that means a ruff failure returns in about a second having
never started pytest. The counts printed and signed come from parsing whatever output the loop
collected, which for ruff is zero of each -- so the gate printed

    python: FAIL (0 passed, 0 failed)

and signed a receipt saying the same. "0 passed, 0 failed" reads as a suite that ran and found
nothing wrong. It is a suite that never ran.

It cost real confusion the same day. A peer session timed the gate at 1.0s on a real staged
edit and reported that as the gate's cost, concluding it was safe to reinstall a hook that holds
.git/index.lock for its whole runtime. The 1.0s was rc=1 -- ruff short-circuiting. The true cost
of a PASSING python lane, measured on the same machine minutes later, was 287s with 6147 tests
run. Deciding whether a lock is held for one second or five minutes on that evidence is the
failure mode; the gate now refuses to be read that way.

The class is broader than this gate and has bitten this estate twice: A FAST RETURN IS NOT PROOF
OF SPEED -- it is often proof the expensive half was skipped. The sibling is
`popdd_verify.py --staged` on an empty index, which grades nothing and prints a tick (memory
`popdd-staged-passes-on-an-empty-index.md`). Both are cheap green from work not done.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "popdd_verify.py"


def _load_runner():
    """Import by path; scripts/ is not a package. See test_popdd_gate_lanes for the
    sys.modules registration, which @dataclass needs before exec_module."""
    spec = importlib.util.spec_from_file_location("popdd_verify", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["popdd_verify"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


class _RecordingAgent:
    """Captures signed receipts instead of writing to the chain."""

    def __init__(self):
        self.signed = []

    def sign_generic(self, **kw):
        self.signed.append(kw)


def _two_step_lane(runner, first_exit: int):
    """A python-shaped lane whose FIRST step exits `first_exit` and whose second records that
    it ran. Real argv, real subprocesses, so the step loop's own break is what is under test
    rather than a mock of it."""
    return replace(
        runner.LANES["python"],
        steps=(
            ("ruff", [sys.executable, "-c", f"import sys; sys.exit({first_exit})"]),
            ("pytest", [sys.executable, "-c", "print('1 passed')"]),
        ),
        preflight=(),
    )


class TestASkippedStepIsNamed:

    def test_a_failing_first_step_reports_the_second_as_never_run(self, runner, capsys):
        agent = _RecordingAgent()
        ok = runner.run_lane(agent, _two_step_lane(runner, first_exit=1))
        out = capsys.readouterr().out

        assert ok is False, "a non-zero first step must still fail the lane"
        assert "NEVER RAN" in out, (
            "the lane stopped before pytest and did not say so. '(0 passed, 0 failed)' on its "
            f"own reads as a clean suite:\n{out}")
        assert "pytest" in out.split("NEVER RAN", 1)[1].splitlines()[0], (
            f"the skipped step must be named, not merely counted:\n{out}")

    def test_the_receipt_records_which_steps_ran_and_which_did_not(self, runner):
        agent = _RecordingAgent()
        runner.run_lane(agent, _two_step_lane(runner, first_exit=1))

        complete = [r for r in agent.signed if r.get("action") == "test-run:complete"]
        assert len(complete) == 1, agent.signed
        receipt = complete[0]
        assert receipt["stepsRun"] == ["ruff"], receipt
        assert receipt["stepsSkipped"] == ["pytest"], receipt
        # The counts stay as they were. They are not wrong, they are unreadable alone, and the
        # two fields above are what makes them readable. A test that demanded the counts change
        # would pin a cosmetic choice rather than the defect.
        assert receipt["passed"] == 0 and receipt["failed"] == 0, receipt

    def test_a_clean_run_skips_nothing_and_says_nothing(self, runner, capsys):
        """The warning must not fire on a passing lane, or it becomes noise and stops being read."""
        agent = _RecordingAgent()
        ok = runner.run_lane(agent, _two_step_lane(runner, first_exit=0))
        out = capsys.readouterr().out

        assert ok is True, out
        assert "NEVER RAN" not in out, out
        complete = [r for r in agent.signed if r.get("action") == "test-run:complete"]
        assert complete[0]["stepsSkipped"] == [], complete[0]
        assert complete[0]["stepsRun"] == ["ruff", "pytest"], complete[0]


class TestEveryLaneCanReportThis:

    def test_no_lane_signs_a_completion_without_the_two_fields(self, runner):
        """Not just the python lane. Any multi-step lane can short-circuit the same way, and a
        lane added later must not silently opt out — the fields are set in `run_lane`, which is
        shared, so this fails only if someone moves them into a per-lane branch."""
        source = RUNNER.read_text(encoding="utf-8")
        body = source.split("def run_lane(", 1)[1].split("\ndef ", 1)[0]
        assert body.count('"stepsRun"') == 2, (
            "both the TIMEOUT receipt and the complete receipt must carry stepsRun; a timeout "
            "skips later steps too, and a receipt that omits it is the same defect")
        assert body.count('"stepsSkipped"') == 2, body.count('"stepsSkipped"')


class TestASkippedLaneIsNamed:
    """The same defect one level up, in the block a human actually reads.

    `main` breaks out of its lane loop on the first failing lane, then printed the SELECTED lanes
    under "Lanes run:". Measured 2026-08-20 on a merge blocked by the console lane: the summary
    read "Lanes run: engine, console, web, dotnet, python" while verdict lines existed for engine
    and console only. Three lanes were claimed as run and were never started, and one of them is
    the python suite -- the lane that does the actual grading.
    """

    def test_it_names_only_the_lanes_that_ran(self, runner, capsys):
        runner.print_summary(ran=["engine", "console"],
                             selected=["engine", "console", "web", "dotnet", "python"],
                             ok=False, chain_valid=True)
        out = capsys.readouterr().out
        lanes_line = next(ln for ln in out.splitlines() if "Lanes run:" in ln)

        assert "python" not in lanes_line, (
            "the python lane never started; naming it under 'Lanes run' tells the reader the "
            f"suite graded this diff:\n{lanes_line}")
        assert "dotnet" not in lanes_line and "web" not in lanes_line, lanes_line
        assert "engine" in lanes_line and "console" in lanes_line, lanes_line

    def test_it_says_out_loud_that_the_rest_were_never_graded(self, runner, capsys):
        runner.print_summary(ran=["engine", "console"],
                             selected=["engine", "console", "web", "dotnet", "python"],
                             ok=False, chain_valid=True)
        out = capsys.readouterr().out

        assert "SKIPPED" in out, (
            "omitting the skipped lanes is quieter but leaves the reader to notice an absence. "
            f"Say it:\n{out}")
        skipped_line = next(ln for ln in out.splitlines() if "SKIPPED" in ln)
        for lane in ("web", "dotnet", "python"):
            assert lane in skipped_line, f"{lane} missing from:\n{skipped_line}"

    def test_a_full_pass_says_nothing_about_skipping(self, runner, capsys):
        """Or the warning becomes furniture and stops being read."""
        lanes = ["engine", "console", "python"]
        runner.print_summary(ran=lanes, selected=lanes, ok=True, chain_valid=True)
        out = capsys.readouterr().out

        assert "SKIPPED" not in out, out
        assert "Verdict:       PASS" in out, out


class TestTheTimeoutReceiptCarriesItToo:
    """The TIMEOUT receipt has its own `stepsRun`, and it was proved only by a source-count
    assertion until 2026-08-20. Mutation testing caught that: replacing `"stepsRun": ran` with the
    configured step list at the TIMEOUT site left the whole file green, because nothing exercised
    that path. The complete-receipt sibling died on the same mutation. One mutation, two sites,
    opposite verdicts -- so a mutation run that stops at the first anchor grades a half-blind test
    sound (memory `a-mutation-test-can-be-vacuous-for-one-family-member`).

    A timeout is the case where the fields matter MOST. It is the one verdict where the lane
    stopped part-way for a reason that is not a test failure, so "which steps got as far as
    running" is the only thing separating "the suite is slow" from "the suite never started".
    """

    def test_a_timed_out_lane_records_what_it_reached_and_what_it_did_not(
            self, runner, monkeypatch, capsys):
        monkeypatch.setattr(runner, "TEST_TIMEOUT_SECONDS", 1)
        lane = replace(
            runner.LANES["python"],
            steps=(
                ("slow", [sys.executable, "-c", "import time; time.sleep(30)"]),
                ("pytest", [sys.executable, "-c", "print('1 passed')"]),
            ),
            preflight=(),
        )
        agent = _RecordingAgent()
        ok = runner.run_lane(agent, lane)
        capsys.readouterr()

        assert ok is False, "a timed-out lane must block the commit"
        complete = [r for r in agent.signed if r.get("action") == "test-run:complete"]
        assert len(complete) == 1, agent.signed
        receipt = complete[0]
        assert receipt["verdict"] == "TIMEOUT", receipt
        assert receipt["stepsRun"] == ["slow"], (
            "the timeout receipt must name the step it was inside, not the configured list; "
            f"otherwise it reads as though pytest ran and hung: {receipt}")
        assert receipt["stepsSkipped"] == ["pytest"], receipt
