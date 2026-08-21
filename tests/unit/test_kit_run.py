"""What the runner promises while it is running, which is the only time anyone can act on it.

Clause A4 of `docs/GOLD_STANDARD_SPEC.md` says no step may be silent for 5s. That is not a
logging preference: a migration nobody can watch is a migration nobody can abort, and the
whole 1800s bar assumes a person can tell a slow step from a wedged one and stop it.

Every test here drives a fake adapter runner, so nothing touches a substrate.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from kit.migrate.run import (
    EX_CONFIG,
    EX_FAILED,
    StepFailed,
    child_env,
    covers_every_resource,
    execute,
    jsonl_sink,
    main,
    ordered,
)


def step(sid, klass, verb="move", needs=(), resource=None, downtime="none",
         frm="fly", to="sshdocker"):
    return {"id": sid, "class": klass, "verb": verb, "needs": list(needs),
            "adapter": f"kit/classes/{klass}.sh", "resource": resource or f"{klass}-1",
            "from": frm, "to": to, "downtime": downtime, "described_by": None}


def plan(*steps, skipped=(), resources=None):
    steps = list(steps)
    skipped = list(skipped)
    return {"project": "p", "target": "sshdocker", "steps": steps, "skipped": skipped,
            "counts": {"resources": resources if resources is not None else len(steps) + len(skipped),
                       "steps": len(steps), "skipped": len(skipped)}}


class Adapter:
    """A fake `subprocess.run` that records calls and fails whichever verbs it is told to."""

    def __init__(self, fail_on=(), rollback_fails=False):
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []
        self.fail_on = set(fail_on)
        self.rollback_fails = rollback_fails

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.envs.append(kw.get("env"))
        adapter, verb = argv[0], argv[1]
        bad = (adapter in self.fail_on and verb != "rollback") or \
              (verb == "rollback" and self.rollback_fails)
        return subprocess.CompletedProcess(argv, 1 if bad else 0, "", "boom" if bad else "")


def collect():
    events: list[dict] = []
    return events, events.append


# ── clause A2, re-checked at the door ────────────────────────────────────────

def test_a_plan_that_does_not_account_for_every_resource_is_refused():
    short = plan(step("s1", "compute"), resources=9)
    with pytest.raises(ValueError, match="1 of 9"):
        covers_every_resource(short)


def test_the_refusal_says_why_it_matters_not_just_that_it_happened():
    with pytest.raises(ValueError, match="already"):
        covers_every_resource(plan(step("s1", "compute"), resources=4))


def test_a_plan_with_no_counts_block_is_refused_rather_than_assumed_complete():
    with pytest.raises(ValueError, match="recompile"):
        covers_every_resource({"steps": [], "skipped": []})


# ── order is proven, not trusted ─────────────────────────────────────────────

def test_a_hand_edited_plan_with_a_prerequisite_out_of_order_is_refused():
    with pytest.raises(ValueError, match="out of order"):
        ordered([step("s1", "compute", needs=["secret"]), step("s2", "secret")])


def test_the_compilers_own_order_passes_unchanged():
    steps = [step("s1", "secret"), step("s2", "compute", needs=["secret"])]
    assert ordered(steps) == steps


# ── clause A4, the thing you can only check while it runs ────────────────────

def test_every_transition_emits_an_event():
    events, sink = collect()
    assert execute(plan(step("s1", "secret")), sink=sink, runner=Adapter()) == 0
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run_started"
    assert "step_started" in kinds and "step_done" in kinds and kinds[-1] == "run_done"


def test_a_resource_left_behind_is_announced_by_name_before_anything_moves():
    left = {"resource": "zone", "class": "dns", "reason": "admitted gap, owned by issue #99"}
    events, sink = collect()
    execute(plan(step("s1", "secret"), skipped=[left]), sink=sink, runner=Adapter())
    said = [e for e in events if e["kind"] == "left_behind"]
    assert len(said) == 1 and said[0]["resource"] == "zone" and "#99" in said[0]["reason"]
    assert [e["kind"] for e in events].index("left_behind") < \
           [e["kind"] for e in events].index("step_started")


# ── failure unwinds exactly one step ─────────────────────────────────────────

def test_a_failed_step_rolls_itself_back_and_stops():
    adapter = Adapter(fail_on={"kit/classes/compute.sh"})
    events, sink = collect()
    code = execute(plan(step("s1", "secret"), step("s2", "compute", needs=["secret"])),
                   sink=sink, runner=adapter)
    assert code == EX_FAILED
    assert [c[1] for c in adapter.calls] == ["move", "move", "rollback"]


def test_the_steps_behind_the_failure_are_left_alone():
    """Their adapters own their own reversal. Unwinding them here would be the runner
    deciding something, which is the one thing it is built not to do."""
    adapter = Adapter(fail_on={"kit/classes/compute.sh"})
    events, sink = collect()
    execute(plan(step("s1", "secret"), step("s2", "compute", needs=["secret"])),
            sink=sink, runner=adapter)
    rolled = [c[0] for c in adapter.calls if c[1] == "rollback"]
    assert rolled == ["kit/classes/compute.sh"]


def test_a_rollback_tells_you_how_to_resume():
    adapter = Adapter(fail_on={"kit/classes/secret.sh"})
    events, sink = collect()
    execute(plan(step("s1", "secret")), sink=sink, runner=adapter)
    done = [e for e in events if e["kind"] == "rollback_done"]
    assert done and done[0]["resume_with"] == "--from-step s1"


def test_a_failed_rollback_says_a_person_is_needed():
    adapter = Adapter(fail_on={"kit/classes/secret.sh"}, rollback_fails=True)
    events, sink = collect()
    assert execute(plan(step("s1", "secret")), sink=sink, runner=adapter) == EX_FAILED
    failed = [e for e in events if e["kind"] == "rollback_failed"]
    assert failed and failed[0]["needs_a_person"] is True


# ── resuming reports what it skips ───────────────────────────────────────────

def test_resuming_names_the_steps_it_passes_over_rather_than_hiding_them():
    adapter = Adapter()
    events, sink = collect()
    execute(plan(step("s1", "secret"), step("s2", "compute", needs=["secret"])),
            sink=sink, runner=adapter, from_step="s2")
    assert [e["step"] for e in events if e["kind"] == "resumed_past"] == ["s1"]
    assert [c[0] for c in adapter.calls] == ["kit/classes/compute.sh"]


# ── clause A1, the clock ─────────────────────────────────────────────────────

def test_a_step_that_would_start_after_the_budget_is_blown_does_not_start():
    """The check has to be BEFORE a step, not after the run. Finding out at the end that
    1800s was missed is a report; refusing to begin the next move is a decision, and it
    leaves the source intact for whoever has to put it back."""
    adapter = Adapter()
    # started, s1 check, s1 done, s2 check -- the clock jumps past the budget between them, then
    # HOLDS. It holds rather than running dry because a test that supplies exactly as many ticks
    # as the code takes is pinning the number of clock calls, which is not the promise; adding
    # one terminal event to the failure path broke it while the behaviour was unchanged.
    ticks = iter([0.0, 0.0, 100.0, 5000.0])
    last = [0.0]

    def clock():
        last[0] = next(ticks, last[0])
        return last[0]

    events, sink = collect()
    code = execute(plan(step("s1", "secret"), step("s2", "compute", needs=["secret"])),
                   sink=sink, runner=adapter, budget_s=1800.0, clock=clock)
    assert code == EX_FAILED
    blown = [e for e in events if e["kind"] == "budget_exceeded"]
    assert blown and blown[0]["step"] == "s2"
    assert [c[0] for c in adapter.calls] == ["kit/classes/secret.sh"]
    assert events[-1]["kind"] == "run_done" and events[-1]["exit_code"] == EX_FAILED, (
        "a run that stopped for time must SAY it stopped -- a console tailing this file sees "
        "nothing else, and a stream that just ends looks identical to a wedged one")


# ── the sink a console actually reads ────────────────────────────────────────

def test_every_event_is_one_flushed_json_line(tmp_path):
    path = tmp_path / "events.jsonl"
    with path.open("w") as handle:
        sink = jsonl_sink(handle)
        sink({"kind": "a"})
        # Flushed on write, so a console tailing the file sees it before the run ends.
        assert json.loads(path.read_text().splitlines()[0])["kind"] == "a"


# ── the CLI ──────────────────────────────────────────────────────────────────

def test_an_unreadable_plan_exits_config_not_failure(tmp_path):
    assert main(["--plan", str(tmp_path / "nope.json")]) == EX_CONFIG


def test_a_plan_that_is_not_json_exits_config(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["--plan", str(bad)]) == EX_CONFIG


def test_a_plan_refused_at_the_door_exits_config_not_failure(tmp_path):
    """A bad plan is a configuration problem. Exiting 1 would make it look like the world
    resisted, which sends whoever is watching to the wrong place at the worst moment."""
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan(step("s1", "compute"), resources=9)))
    assert main(["--plan", str(path), "--events", str(tmp_path / "e.jsonl")]) == EX_CONFIG


def test_step_failed_carries_the_step_so_the_caller_can_unwind_it():
    failure = StepFailed(step("s1", "secret"), "boom")
    assert failure.step["id"] == "s1" and failure.detail == "boom"


# ── the adapter's environment ────────────────────────────────────────────────

def test_the_adapter_inherits_this_process_environment():
    """`subprocess.run(env=...)` REPLACES rather than adds, and every adapter shells out.

    Handing an adapter only RESOURCE and TO gives it no PATH, so `deploy/cutover.sh` fails on
    `fly: command not found` -- at the point in the run where the source is already stopped.
    """
    built = child_env({"RESOURCE": "engine"}, base={"PATH": "/usr/bin", "HOME": "/home/x"})
    assert built["PATH"] == "/usr/bin"
    assert built["HOME"] == "/home/x"
    assert built["RESOURCE"] == "engine"


def test_a_step_variable_wins_over_an_ambient_one_of_the_same_name():
    """The plan decides which resource this step moves, never whatever was exported in a shell."""
    built = child_env({"RESOURCE": "engine"}, base={"RESOURCE": "something-stale"})
    assert built["RESOURCE"] == "engine"


def test_every_adapter_call_in_a_real_run_carries_a_path():
    adapter = Adapter()
    events, sink = collect()
    execute(plan(step("s1", "secret"), step("s2", "compute", needs=["secret"])),
            sink=sink, runner=adapter)
    assert adapter.envs, "no adapter was called"
    for env in adapter.envs:
        assert env.get("PATH"), "an adapter was handed an environment with no PATH"


def test_the_adapter_is_told_where_the_resource_is_now_not_only_where_it_is_going():
    """`from` was computed by the compiler and used only to label the console event.

    An adapter that knows only TO cannot build `--from X --to Y`, and cannot put the resource
    back, because putting it back is the same move with the ends swapped.
    """
    adapter = Adapter()
    events, sink = collect()
    execute(plan(step("s1", "compute", frm="laptop", to="fly")), sink=sink, runner=adapter)
    env = adapter.envs[0]
    assert env["FROM"] == "laptop"
    assert env["TO"] == "fly"


def test_the_rollback_call_carries_both_ends_too():
    """The rollback path used to carry neither end -- it was worse than the step path."""
    adapter = Adapter(fail_on=["kit/classes/compute.sh"])
    events, sink = collect()
    execute(plan(step("s1", "compute", frm="laptop", to="fly")), sink=sink, runner=adapter)
    rollbacks = [e for c, e in zip(adapter.calls, adapter.envs, strict=True) if c[1] == "rollback"]
    assert rollbacks, "no rollback was attempted"
    assert rollbacks[0]["FROM"] == "laptop" and rollbacks[0]["TO"] == "fly"


def test_every_way_a_run_can_end_ends_with_one_run_done_carrying_the_code():
    """Three endings, one terminal event. Before this, only the happy path emitted `run_done`,
    so the two endings a person actually has to act on were the two with no sign they had
    happened -- the events stopped, which is also what a killed process looks like."""
    endings = {
        0: Adapter(),
        EX_FAILED: Adapter(fail_on={"kit/classes/compute.sh"}),
    }
    for expected, adapter in endings.items():
        events, sink = collect()
        code = execute(plan(step("s1", "compute")), sink=sink, runner=adapter)
        assert code == expected
        terminal = [e for e in events if e["kind"] == "run_done"]
        assert len(terminal) == 1, f"{len(terminal)} terminal events, expected exactly 1"
        assert terminal[0]["exit_code"] == expected
        assert events[-1] is terminal[0], "the terminal event must be the LAST one"

    # And the worst ending of all: the rollback failed too, so a person has to go and look.
    events, sink = collect()
    code = execute(plan(step("s1", "compute")), sink=sink,
                   runner=Adapter(fail_on={"kit/classes/compute.sh"}, rollback_fails=True))
    assert code == EX_FAILED
    assert events[-1]["kind"] == "run_done" and events[-1]["exit_code"] == EX_FAILED
    assert any(e["kind"] == "rollback_failed" for e in events)
