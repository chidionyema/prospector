"""Fold a run's event stream into the state of the run, for a screen.

The runner (`kit/migrate/run.py`) writes one JSON line per transition and flushes it, so this
reads a file that is still being written. Everything here is arithmetic over those events --
counting, subtracting, grouping. It decides nothing.

THAT IS THE POINT, and it is the same discipline the incident view follows against its own
script. If the console folded events by its own rules, the bar on the page and the exit code of
the run would eventually answer different questions about the same migration, and the person
watching at minute 12 of a bad night would have to guess which one to believe. One folder, used
by the page and by anything else that reports a run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

#: Clause A4: no step may go this long without an event. It lives here rather than in the view
#: because the runner's heartbeat (`run.HEARTBEAT_S`, 4s) is what has to stay under it, and a
#: threshold that lives next to the thing it grades cannot drift away from it unnoticed.
QUIET_AFTER_S = 5.0

#: A step's state, and what each one means to the person watching. `run.py` emits the event; this
#: is only the name the screen shows for it.
STATE_MEANING = {
    "waiting": "not started yet",
    "running": "in flight now",
    "done": "finished, and the adapter said so",
    "failed": "the adapter refused or errored",
    "rolled_back": "failed, and it was put back",
    "not_started": "the adapter could not be run, so nothing was touched",
    "needs_a_person": "failed, and putting it back also failed",
    "resumed_past": "skipped by --from-step, not run in this pass",
}


def _lines(text: str) -> Iterable[dict[str, Any]]:
    """Every complete event in the file, and nothing else.

    A tail of a live file ends mid-line as often as not: the console polls at whatever cadence it
    polls at, and the runner is writing between two of those polls. A half-written line is not a
    corrupt file, it is a file with more coming, so it is skipped rather than raised on. Raising
    would take the page down for the one second a step takes to start.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "kind" in event:
            yield event


def latest_run(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the most recent run in the file.

    `run.py --events` opens the file in APPEND mode, so a resume writes a second run into the
    same file behind the first. Folding all of it together would show the failed step of the
    earlier pass as still failed while the resume is fixing it -- the page would report a state
    that stopped being true the moment the operator did what the page told them to do.
    """
    events = list(events)
    starts = [i for i, e in enumerate(events) if e["kind"] == "run_started"]
    return events[starts[-1]:] if starts else events


def fold(events: Iterable[dict[str, Any]], *, now: float | None = None) -> dict[str, Any]:
    """The run, as it stands, from its events. Safe on a partial stream."""
    events = latest_run(events)
    steps: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    run: dict[str, Any] = {"project": None, "target": None, "planned_steps": 0,
                           "budget_s": None, "started_at": None, "finished_at": None,
                           "exit_code": None, "left_behind": [], "resume_with": None,
                           "stopped_reason": None}
    last_at = None

    for event in events:
        kind, at = event["kind"], event.get("at")
        if at is not None:
            last_at = at
        sid = event.get("step")
        if sid is not None and sid not in steps:
            order.append(sid)
            steps[sid] = {"id": sid, "class": event.get("klass"), "verb": event.get("verb"),
                          "resource": event.get("resource"), "state": "waiting",
                          "started_at": None, "finished_at": None, "elapsed_s": None,
                          "last_event_at": at, "detail": None}
        row = steps.get(sid) if sid is not None else None
        if row is not None:
            row["last_event_at"] = at
            for field in ("klass", "verb", "resource"):
                if event.get(field) is not None:
                    row["class" if field == "klass" else field] = event[field]

        if kind == "run_started":
            run.update(project=event.get("project"), target=event.get("target"),
                       planned_steps=event.get("steps", 0), budget_s=event.get("budget_s"),
                       started_at=at)
        elif kind == "left_behind":
            run["left_behind"].append({"resource": event.get("resource"),
                                       "class": event.get("klass"),
                                       "reason": event.get("reason")})
        elif kind == "run_done":
            run.update(finished_at=at, exit_code=event.get("exit_code"))
        elif kind == "budget_exceeded":
            run["stopped_reason"] = (
                f"the {run['budget_s'] or '?'}s budget ran out at step {sid}")
        elif row is None:
            continue
        elif kind == "step_started":
            row.update(state="running", started_at=at)
        elif kind == "step_done":
            row.update(state="done", finished_at=at, elapsed_s=event.get("elapsed_s"))
        elif kind == "step_failed":
            row.update(state="failed" if event.get("started", True) else "not_started",
                       finished_at=at, detail=event.get("detail"))
        elif kind == "rollback_skipped":
            run["resume_with"] = event.get("resume_with")
        elif kind == "rollback_done":
            row.update(state="rolled_back")
            run["resume_with"] = event.get("resume_with")
        elif kind == "rollback_failed":
            row.update(state="needs_a_person", detail=event.get("detail"))
        elif kind == "resumed_past":
            row.update(state="resumed_past")

    rows = [steps[sid] for sid in order]
    clock = now if now is not None else last_at
    for row in rows:
        if row["state"] == "running" and row["elapsed_s"] is None and row["started_at"]:
            row["elapsed_s"] = round((clock or row["started_at"]) - row["started_at"], 1)
        quiet = None
        if row["state"] == "running" and clock is not None and row["last_event_at"]:
            quiet = round(clock - row["last_event_at"], 1)
        row["quiet_s"] = quiet
        # Clause A4 is graded here, once, rather than by every reader of this dict.
        row["gone_quiet"] = quiet is not None and quiet > QUIET_AFTER_S
        row["means"] = STATE_MEANING.get(row["state"], row["state"])

    done = sum(1 for r in rows if r["state"] in ("done", "resumed_past"))
    stuck = [r for r in rows if r["state"] in ("failed", "needs_a_person")]
    # `not_started` is deliberately absent from that list. It is a step to WRITE, not a mess to
    # clear up, and putting it in the same bucket sends someone hunting for a stranded resource.
    if run["finished_at"] is not None:
        state = "finished" if run["exit_code"] == 0 else "stopped"
    elif run["started_at"] is None:
        state = "no run"
    else:
        state = "running"

    return {
        **run,
        "state": state,
        "steps": rows,
        "done": done,
        "total": max(run["planned_steps"], len(rows)),
        "elapsed_s": (round((run["finished_at"] or clock or run["started_at"])
                            - run["started_at"], 1) if run["started_at"] else None),
        "needs_a_person": any(r["state"] == "needs_a_person" for r in rows),
        "stuck_at": stuck[0]["id"] if stuck else None,
    }


def read(path: Path, *, now: float | None = None) -> dict[str, Any]:
    """Fold the events at `path`. A file that is not there yet is a run that has not started."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        text = ""
    except OSError as unreadable:
        return {**fold([]), "state": "unreadable", "stopped_reason": str(unreadable)}
    return fold(_lines(text), now=now)
