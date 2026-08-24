"""What the console shows while a migration is running, folded from the runner's own events.

The bar on the page and the exit code of the run have to be the same claim. So the first test
here does not hand-build a stream: it drives the REAL runner and folds what the REAL runner
wrote. If someone renames an event, that test goes red, and it goes red in the file that would
otherwise have kept rendering an empty page for the whole of a migration.

The rest are the edge cases of reading a file that is still being written.
"""

from __future__ import annotations

import json
import subprocess

from kit.migrate.progress import QUIET_AFTER_S, fold, latest_run, read
from kit.migrate.run import execute, jsonl_sink


def step(sid, klass, verb="move", needs=(), resource=None, frm="fly", to="sshdocker"):
    return {"id": sid, "class": klass, "verb": verb, "needs": list(needs),
            "adapter": f"kit/classes/{klass}.sh", "resource": resource or f"{klass}-1",
            "from": frm, "to": to, "downtime": "none", "described_by": None}


def plan(*steps, skipped=(), resources=None):
    steps, skipped = list(steps), list(skipped)
    return {"project": "p", "target": "sshdocker", "steps": steps, "skipped": skipped,
            "counts": {"resources": resources if resources is not None
                       else len(steps) + len(skipped),
                       "steps": len(steps), "skipped": len(skipped)}}


class Adapter:
    def __init__(self, fail_on=(), rollback_fails=False):
        self.fail_on, self.rollback_fails = set(fail_on), rollback_fails

    def __call__(self, argv, **kw):
        adapter, verb = argv[0], argv[1]
        bad = (adapter in self.fail_on and verb != "rollback") or \
              (verb == "rollback" and self.rollback_fails)
        return subprocess.CompletedProcess(argv, 1 if bad else 0, "", "boom" if bad else "")


def run_to_events(the_plan, **kw):
    """Drive the real runner and hand back what it actually wrote, as the file would hold it."""
    events: list[dict] = []
    execute(the_plan, sink=events.append, runner=kw.pop("runner", Adapter()), **kw)
    return events


# ── the two ends of the wire, checked against each other ─────────────────────

def test_a_real_run_folds_to_every_step_done():
    """The emitter and the folder, driven end to end. This is the test that catches a rename."""
    events = run_to_events(plan(step("s1", "compute"), step("s2", "dns", needs=["compute"])))
    view = fold(events)

    assert view["state"] == "finished"
    assert view["done"] == view["total"] == 2
    assert [r["id"] for r in view["steps"]] == ["s1", "s2"]
    assert {r["state"] for r in view["steps"]} == {"done"}
    assert view["project"] == "p" and view["target"] == "sshdocker"
    assert view["stuck_at"] is None and view["needs_a_person"] is False


def test_a_real_failure_folds_to_a_rolled_back_step_with_the_resume_line():
    """The console's whole job at the worst moment: which step, and what to type next."""
    events = run_to_events(plan(step("s1", "compute"), step("s2", "dns", needs=["compute"])),
                           runner=Adapter(fail_on={"kit/classes/dns.sh"}))
    view = fold(events)

    assert view["state"] == "stopped"
    assert view["stuck_at"] is None, "a rolled-back step is not still stuck"
    by_id = {r["id"]: r for r in view["steps"]}
    assert by_id["s1"]["state"] == "done"
    assert by_id["s2"]["state"] == "rolled_back"
    assert by_id["s2"]["detail"] == "boom", "the adapter's own words, not a paraphrase"
    assert view["resume_with"] == "--from-step s2"


def test_a_rollback_that_also_fails_says_a_person_is_needed():
    events = run_to_events(plan(step("s1", "compute")),
                           runner=Adapter(fail_on={"kit/classes/compute.sh"},
                                          rollback_fails=True))
    view = fold(events)

    assert view["needs_a_person"] is True
    assert view["stuck_at"] == "s1"
    assert view["steps"][0]["state"] == "needs_a_person"


def test_what_is_left_behind_survives_the_fold():
    """Clause A2 is 0 resources left behind. A page that drops them cannot be used to check it."""
    events = run_to_events(plan(step("s1", "compute"),
                                skipped=[{"resource": "zone-1", "class": "dns",
                                          "reason": "no adapter"}]))
    view = fold(events)

    assert view["left_behind"] == [{"resource": "zone-1", "class": "dns",
                                    "reason": "no adapter"}]


# ── reading a file that is still being written ───────────────────────────────

def test_a_half_written_last_line_is_skipped_not_raised_on(tmp_path):
    """The runner flushes mid-line as often as not. A page that raises there is a page that
    blinks out for the one second a step takes to start."""
    events = run_to_events(plan(step("s1", "compute")))
    whole = "".join(json.dumps(e, sort_keys=True) + "\n" for e in events)
    log = tmp_path / "events.jsonl"
    log.write_text(whole[:-14])  # cut the final line in half

    view = read(log)
    assert view["state"] in ("running", "finished")
    assert view["steps"], "the complete lines before the tear must still be read"


def test_junk_in_the_stream_is_ignored(tmp_path):
    log = tmp_path / "events.jsonl"
    log.write_text('not json at all\n[]\n{"no": "kind"}\n'
                   '{"kind": "run_started", "at": 1.0, "steps": 1, "project": "p"}\n')
    assert read(log)["state"] == "running"
    assert read(log)["project"] == "p"


def test_a_file_that_is_not_there_yet_is_a_run_that_has_not_started(tmp_path):
    assert read(tmp_path / "nothing.jsonl")["state"] == "no run"


def test_a_resume_shows_only_the_second_run(tmp_path):
    """`--events` opens in APPEND mode, so a resume writes BEHIND the failed pass. Folding both
    together would show the failed step as still failed while the resume is fixing it."""
    first = run_to_events(plan(step("s1", "compute"), step("s2", "dns", needs=["compute"])),
                          runner=Adapter(fail_on={"kit/classes/dns.sh"}))
    second = run_to_events(plan(step("s1", "compute"), step("s2", "dns", needs=["compute"])),
                           from_step="s2")
    log = tmp_path / "events.jsonl"
    with log.open("w") as handle:
        write = jsonl_sink(handle)
        for event in first + second:
            write(event)

    view = read(log)
    assert view["state"] == "finished", "the fold reported the pass that is over, not the live one"
    by_id = {r["id"]: r for r in view["steps"]}
    assert by_id["s2"]["state"] == "done"
    assert by_id["s1"]["state"] == "resumed_past"


def test_only_the_last_run_started_begins_the_window():
    two = [{"kind": "run_started", "at": 1.0}, {"kind": "step_done", "at": 2.0, "step": "s1"},
           {"kind": "run_started", "at": 3.0}, {"kind": "step_done", "at": 4.0, "step": "s2"}]
    assert [e["at"] for e in latest_run(two)] == [3.0, 4.0]


# ── clause A4, graded in one place ───────────────────────────────────────────

def test_a_step_that_has_gone_quiet_is_flagged():
    """The heartbeat exists so a wedged step looks different from a slow one. If the fold does
    not grade the gap, the page shows a bar that is indistinguishable either way."""
    live = [{"kind": "run_started", "at": 0.0, "steps": 1},
            {"kind": "step_started", "at": 1.0, "step": "s1", "klass": "compute"}]

    quiet = fold(live, now=1.0 + QUIET_AFTER_S + 0.5)["steps"][0]
    assert quiet["gone_quiet"] is True
    assert quiet["quiet_s"] > QUIET_AFTER_S

    fresh = fold(live, now=1.0 + QUIET_AFTER_S - 0.5)["steps"][0]
    assert fresh["gone_quiet"] is False


def test_a_heartbeat_clears_the_quiet_flag():
    live = [{"kind": "run_started", "at": 0.0, "steps": 1},
            {"kind": "step_started", "at": 1.0, "step": "s1", "klass": "compute"},
            {"kind": "step_working", "at": 20.0, "step": "s1", "klass": "compute"}]
    row = fold(live, now=21.0)["steps"][0]

    assert row["gone_quiet"] is False
    assert row["quiet_s"] == 1.0
    assert row["elapsed_s"] == 20.0, "elapsed runs from the start, quiet from the last event"


def test_a_finished_step_is_never_quiet():
    """Only a running step can be silent. A done step with no further events is not a fault."""
    done = fold([{"kind": "run_started", "at": 0.0, "steps": 1},
                 {"kind": "step_started", "at": 1.0, "step": "s1"},
                 {"kind": "step_done", "at": 2.0, "step": "s1", "elapsed_s": 1.0}],
                now=9999.0)["steps"][0]
    assert done["gone_quiet"] is False and done["quiet_s"] is None


def test_the_budget_running_out_says_so_in_words():
    """Clause A1 is 1800s. A run that stopped for time must not read as a run that failed."""
    view = fold([{"kind": "run_started", "at": 0.0, "steps": 2, "budget_s": 1800.0},
                 {"kind": "budget_exceeded", "at": 5.0, "step": "s2", "elapsed_s": 1801.0},
                 {"kind": "run_done", "at": 5.0, "exit_code": 1}])
    assert "1800.0s budget ran out at step s2" in view["stopped_reason"]
    assert view["state"] == "stopped"
