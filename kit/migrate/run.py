"""Execute a migration plan, one step at a time, saying so as it goes.

The plan compiler decides WHAT moves and in what order. This decides WHEN, and it is the
only thing in the kit that touches the running world. Three clauses of
`docs/GOLD_STANDARD_SPEC.md` are enforced here rather than described:

  A1  the whole run fits in 1800s -- so the clock is checked at every transition, and a run
      that cannot finish says so while there is still time to stop it, not at minute 29.
  A4  no step is silent for 5s -- every transition emits an event, and a step that is still
      working emits a heartbeat. A migration you cannot watch is one you cannot abort.
  A2  nothing is left behind -- the runner refuses a plan whose steps and skips do not
      account for every resource the probe found.

The runner never decides anything the plan did not already say. If a decision has to be made
mid-flight, that is a bug in the compiler, because a decision made at minute 20 with the
source already stopped is a decision made under the worst conditions available.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

EX_CONFIG = 78  # sysexits.h EX_CONFIG -- a problem in the plan, not in the world
EX_FAILED = 1

HEARTBEAT_S = 4.0  # under A4's 5s, so a slow step still speaks before the bar is missed


class StepFailed(Exception):
    """A step's adapter exited non-zero. Carries the step so the caller can roll back."""

    def __init__(self, step: dict[str, Any], detail: str, *, started: bool = True) -> None:
        super().__init__(detail)
        self.step = step
        self.detail = detail
        #: Did the adapter actually RUN? An adapter that could not be started touched nothing,
        #: so there is nothing to undo -- and telling an operator at 3am that a rollback failed
        #: says a resource is stranded half-moved when in fact none of it happened. The two
        #: nights are not the same night and the console must not print the worse one.
        self.started = started


def _event(sink: Callable[[dict[str, Any]], None], kind: str, **fields: Any) -> None:
    sink({"kind": kind, "at": time.time(), **fields})


def ordered(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The plan's own order, with prerequisites proven rather than trusted.

    The compiler already sorts by prerequisite depth. This re-checks it, because a plan is a
    file and a file can be hand-edited between compiling and running -- which is exactly the
    thing someone does at minute 3 of a bad night.

    It grades ORDER, and only order. A prerequisite class that is nowhere in the plan is not
    late, it is absent: the probe found no resource of that class, so there is nothing to wait
    for. Reading absent as out-of-order refused every plan that did not happen to contain a
    secret -- which is every single-class move, and so every drill and every targeted repair.
    Whether the plan accounts for everything is clause A2, and `covers_every_resource` is where
    that is decided; two checks answering one question is how they end up disagreeing.
    """
    present = {step["class"] for step in steps}
    done: set[str] = set()
    for step in steps:
        late = [n for n in step.get("needs", ())
                if n in present and n not in done and n != step["class"]]
        if late:
            raise ValueError(
                f"step {step['id']} ({step['class']}) needs {late}, which the plan runs AFTER "
                f"it -- the plan is out of order, recompile it rather than editing it"
            )
        done.add(step["class"])
    return steps


def covers_every_resource(plan: dict[str, Any]) -> None:
    """Clause A2, re-checked at the door.

    The compiler enforces this, and it is checked again here for the same reason `ordered`
    re-checks the order: what runs is a FILE, and the gap between compiling and running is
    where a hand edit lands.
    """
    counts = plan.get("counts") or {}
    resources = counts.get("resources")
    covered = len(plan.get("steps", ())) + len(plan.get("skipped", ()))
    if resources is None:
        raise ValueError("the plan has no `counts.resources` -- recompile it with kit/migrate/plan.py")
    if covered != resources:
        raise ValueError(
            f"the plan accounts for {covered} of {resources} resources. The missing "
            f"{resources - covered} would be discovered mid-flight with the source already "
            f"stopped, which is the failure clause A2 exists to prevent."
        )


def child_env(verb_env: dict[str, str], base: dict[str, str] | None = None) -> dict[str, str]:
    """This process's environment, with the step's variables laid over it.

    `subprocess.run(env=...)` REPLACES the environment rather than adding to it, so handing it
    the two step variables alone would run every adapter with no PATH, no HOME and no SSH agent.
    `deploy/cutover.sh` needs all three -- it shells out to `git`, to the platform CLI, and to
    the credentials under `$HOME`. The failure would arrive as "fly: command not found" at the
    moment the source is already stopped, which is the most expensive minute of the whole move.
    """
    return {**(os.environ if base is None else base), **verb_env}


def step_vars(step: dict[str, Any]) -> dict[str, str]:
    """The variables one step hands its adapter. BOTH ends, on the move and on the rollback.

    `from` is computed by the compiler and was, until this was fixed, used only to label the
    console event -- so the adapter was told where the resource was GOING and never where it
    was. `deploy/cutover.sh` needs both (`--from X --to Y`), and so does putting it back: a
    rollback is the same move with the ends swapped, which the adapter can only do if it holds
    both. The rollback path was worse than the step path, carrying neither end.
    """
    return {"RESOURCE": step["resource"],
            "FROM": str(step.get("from") or ""),
            "TO": str(step.get("to") or ""),
            "VERB": step["verb"], "CLASS": step["class"], "STEP_ID": step["id"]}


def run_step(step: dict[str, Any], *, verb_env: dict[str, str],
             runner: Callable[..., subprocess.CompletedProcess]) -> None:
    """Hand one step to its class adapter. The adapter owns the substrate; this owns nothing.

    An adapter that cannot be STARTED is a failed step, not a crashed runner. `subprocess.run`
    raises `OSError` for a missing file, a file with no execute bit, and a script with no
    interpreter line -- and an exception raised here escapes the whole walk: no `step_failed`,
    no rollback, no terminal event. The operator's console showed the events stop and their
    terminal showed a Python traceback, at whatever minute the plan first named a class nobody
    had written an adapter for. A class declared and unwired is the ordinary case in a kit that
    is still being built, so this is the ordinary path, not the exotic one.
    """
    try:
        done = runner([step["adapter"], step["verb"]], env=child_env(verb_env),
                      capture_output=True, text=True)
    except OSError as unrunnable:
        raise StepFailed(step, f"cannot run {step['adapter']}: {unrunnable.strerror or unrunnable}",
                         started=False) from unrunnable
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise StepFailed(step, " / ".join(tail) or f"exit {done.returncode}")



def _heartbeat(sink: Callable[[dict[str, Any]], None], step: dict[str, Any],
               clock: Callable[[], float], started: float) -> threading.Event:
    """Emit `step_working` every HEARTBEAT_S until the returned Event is set.

    Clause A4 says no step may be silent for 5s. Without this, a step that legitimately
    takes four minutes -- a volume copy, a certificate issuance -- looks identical from the
    console to a step that has hung, and the person watching cannot tell whether to abort.
    The thread is a daemon so a crash in the main path can never leave it holding the process
    open. It runs during ROLLBACK too, which is where A4 matters most: that is the moment the
    person watching most needs to know the difference between unwinding and wedged.
    """
    stop = threading.Event()

    def tick() -> None:
        while not stop.wait(HEARTBEAT_S):
            _event(sink, "step_working", step=step["id"], klass=step["class"],
                   elapsed_s=round(clock() - started, 1))

    threading.Thread(target=tick, daemon=True, name=f"heartbeat-{step['id']}").start()
    return stop


def execute(plan: dict[str, Any], *, sink: Callable[[dict[str, Any]], None],
            runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
            from_step: str | None = None, budget_s: float = 1800.0,
            clock: Callable[[], float] = time.monotonic) -> int:
    """Run the plan, emitting an event at every transition. Returns a process exit code.

    `from_step` resumes: everything before it is emitted as `resumed` rather than silently
    absent, because a step nobody mentions is a step nobody checks. Failure rolls back only
    the step that failed -- the ones behind it succeeded and their adapters own their own
    reversal, so unwinding them here would be this runner making a decision, which is exactly
    what it is built not to do.

    EVERY exit goes out through one `run_done`, carrying the code. The walk used to return
    straight out of the loop on any failure, so the only terminal event in the stream was the
    one on the happy path -- and a console tailing a failed run saw the events simply stop.
    Stopped, wedged, and killed are three different nights, and the person watching could not
    tell them apart from the only thing they can see.
    """
    covers_every_resource(plan)
    steps = ordered(plan.get("steps", []))
    started = clock()

    _event(sink, "run_started", target=plan.get("target"), project=plan.get("project"),
           steps=len(steps), skipped=len(plan.get("skipped", ())), budget_s=budget_s)
    for skip in plan.get("skipped", ()):
        _event(sink, "left_behind", resource=skip["resource"], klass=skip["class"],
               reason=skip["reason"])

    code = _walk(steps, sink=sink, runner=runner, from_step=from_step, budget_s=budget_s,
                 clock=clock, started=started)
    elapsed = clock() - started
    _event(sink, "run_done", elapsed_s=round(elapsed, 1), exit_code=code,
           within_budget=elapsed <= budget_s)
    return code


def _walk(steps: list[dict[str, Any]], *, sink: Callable[[dict[str, Any]], None],
          runner: Callable[..., subprocess.CompletedProcess], from_step: str | None,
          budget_s: float, clock: Callable[[], float], started: float) -> int:
    """The steps themselves. Returns the exit code; emits no terminal event of its own."""
    reached = from_step is None
    for step in steps:
        if not reached:
            if step["id"] == from_step:
                reached = True
            else:
                _event(sink, "resumed_past", step=step["id"], klass=step["class"])
                continue

        elapsed = clock() - started
        if elapsed > budget_s:
            _event(sink, "budget_exceeded", step=step["id"], elapsed_s=round(elapsed, 1),
                   budget_s=budget_s)
            return EX_FAILED

        _event(sink, "step_started", step=step["id"], klass=step["class"], verb=step["verb"],
               resource=step["resource"], downtime=step["downtime"],
               was=step.get("from"), will_be=step.get("to"), elapsed_s=round(elapsed, 1))
        beat = _heartbeat(sink, step, clock, started)
        try:
            run_step(step, verb_env=step_vars(step), runner=runner)
        except StepFailed as failure:
            beat.set()
            _event(sink, "step_failed", step=step["id"], klass=step["class"],
                   detail=failure.detail, started=failure.started)
            if not failure.started:
                _event(sink, "rollback_skipped", step=step["id"],
                       reason="the adapter never ran, so nothing was touched",
                       resume_with=f"--from-step {step['id']}")
                return EX_FAILED
            _event(sink, "rollback_started", step=step["id"])
            unwinding = _heartbeat(sink, step, clock, started)
            try:
                run_step({**step, "verb": "rollback"}, verb_env=step_vars(step), runner=runner)
            except StepFailed as unwound:
                unwinding.set()
                _event(sink, "rollback_failed", step=step["id"], detail=unwound.detail,
                       needs_a_person=True)
                return EX_FAILED
            unwinding.set()
            _event(sink, "rollback_done", step=step["id"],
                   resume_with=f"--from-step {step['id']}")
            return EX_FAILED
        beat.set()
        _event(sink, "step_done", step=step["id"], elapsed_s=round(clock() - started, 1))

    return 0



def jsonl_sink(stream: Any) -> Callable[[dict[str, Any]], None]:
    """One event per line, flushed immediately.

    Flushing on every event is the whole point: a console tailing this file is the only way
    anyone sees a migration while it is happening, and a buffered event is an event that
    arrives after the decision it was supposed to inform.
    """

    def write(event: dict[str, Any]) -> None:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()

    return write


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a migration plan compiled by kit/migrate/plan.py")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--from-step", default=None,
                        help="resume at this step id; earlier steps are reported, not hidden")
    parser.add_argument("--budget-s", type=float, default=1800.0,
                        help="clause A1's wall clock; the run stops rather than overrun it")
    parser.add_argument("--events", type=Path, default=None,
                        help="write events here as JSON lines (default: stderr)")
    args = parser.parse_args(argv)

    try:
        plan = json.loads(args.plan.read_text())
    except (OSError, json.JSONDecodeError) as bad:
        print(f"cannot read the plan: {bad}", file=sys.stderr)
        return EX_CONFIG

    stream = args.events.open("a") if args.events else sys.stderr
    try:
        return execute(plan, sink=jsonl_sink(stream), from_step=args.from_step,
                       budget_s=args.budget_s)
    except ValueError as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return EX_CONFIG
    finally:
        if args.events:
            stream.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
