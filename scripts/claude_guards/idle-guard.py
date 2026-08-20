#!/usr/bin/env python3
"""Stop guard: refuse to end a turn while a background run is still going.

WHY THIS EXISTS
---------------
Founder, 2026-08-17: "this is another founder complaint, this is unacceptable, we need to
enforce multi tasking, i should not be having to sit watch a tool run for 15 mins while
agent is idle and there is work to do."

Measured that turn: the agent started the Hermes gate in the background — correctly — and
then ended its turn anyway. 15 minutes 50 seconds of wall clock with one shell running and
an agent doing nothing. The rule "never sit and watch a long command" has been in the global
CLAUDE.md since 2026-08-16 and was read, in context, at the moment it was broken.

So this is not a wording problem. A rule that is READ does not stop anything; a rule that
RUNS does. Same conclusion as rule-guard.py, one event later.

WHAT IT DOES
------------
On Stop, it reads the session transcript and works out which backgrounded commands were
launched and which have since reported completion. If any are still in flight, it blocks the
stop ONCE and tells the agent to start the next independent piece of work.

WHY IT CAN ONLY BLOCK ONCE
--------------------------
Claude Code sets stop_hook_active on the retry. If the agent comes back and still wants to
stop, it is allowed to: sometimes every remaining task genuinely depends on the run in
flight, and a guard that cannot be satisfied gets uninstalled. Blocking once forces the
question to be asked out loud; blocking forever just moves the outage.

HOW IT FAILS
------------
Open. Any exception, unreadable transcript, missing field -> exit 0 and the stop proceeds.
There are ~18 Claude processes against this estate. A guard that wedges them all is a worse
outage than any rule it enforces.

SELFTEST
    python3 idle-guard.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

# The harness prints this when a command is backgrounded.
LAUNCH = re.compile(r"Command running in background with ID:\s*([A-Za-z0-9_-]+)")
# ...and this when it lands. Both appear in tool results / system records in the transcript.
DONE = re.compile(r"<task-id>\s*([A-Za-z0-9_-]+)\s*</task-id>")
KILLED = re.compile(r"(?:killed|stopped) task\s+([A-Za-z0-9_-]+)", re.I)

# Where the harness parks a background run's output. Depth-bounded globs, and a module
# constant so the selftest can point them at a temp dir instead of the live estate.
_TASK_ROOTS = ("/private/tmp/claude-*", "/tmp/claude-*")


def _text_of(rec: dict) -> str:
    """Flatten one transcript record to searchable text, cheaply."""
    msg = rec.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    out: list[str] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if isinstance(block.get("text"), str):
                out.append(block["text"])
            inner = block.get("content")
            if isinstance(inner, str):
                out.append(inner)
            elif isinstance(inner, list):
                out.extend(b.get("text", "") for b in inner
                           if isinstance(b, dict) and isinstance(b.get("text"), str))
    if isinstance(rec.get("toolUseResult"), str):
        out.append(rec["toolUseResult"])
    return "\n".join(o for o in out if o)


def in_flight(transcript_path: str, tail: int = 400) -> list[str]:
    """Background task IDs launched but never reported finished."""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-tail:]
    except OSError:
        return []
    launched: list[str] = []
    finished: set[str] = set()
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        text = _text_of(rec)
        if not text:
            continue
        for tid in LAUNCH.findall(text):
            if tid not in launched:
                launched.append(tid)
        finished.update(DONE.findall(text))
        finished.update(KILLED.findall(text))
    return [t for t in launched if t not in finished and not _finished_on_disk(t)]


def _finished_on_disk(tid: str) -> bool:
    """True if this task's output file shows the process has already exited.

    THE TRANSCRIPT IS NOT THE ONLY TRUTH, AND AFTER A COMPACTION IT IS NOT A COMPLETE ONE.
    Measured 2026-08-17: this guard blocked a stop over bkibd8i24 and bv0kc1hr9. Both had
    already reported `completed`, and bv0kc1hr9's output file ended
    `442 passed, 1 warning in 387.35s` then `[exited with code 0]`. Compaction had
    rewritten the transcript, keeping the launch text inside the summary and dropping the
    `<task-id>` completion records, so the guard saw two runs that could never finish. A
    guard that cannot be satisfied gets uninstalled, which is the failure this file's own
    docstring warns about.

    The harness writes each background run to <scratchpad-root>/<session>/tasks/<id>.output
    and appends `[exited with code N]` when it exits. That line is on disk and survives
    compaction, so it is the check that cannot go stale. The glob is depth-bounded — never
    a recursive walk from a home directory (ESTATE_QUIRKS Q10).

    NO OUTPUT FILE MEANS IT WAS NEVER LAUNCHED, and that case must also clear. The launch
    marker is matched as TEXT, so text ABOUT a background run arms the guard just as well as
    a real one: this file's own selftest fixtures, a compaction summary, a doc quoting the
    marker. Measured 2026-08-17, minutes after the fix above: reading this script put its
    fixture ids `bbb` and `zzz` into the transcript and the guard blocked a stop over two
    tasks that had never existed. The harness creates the output file at launch, so its
    ABSENCE is proof the id is not a real run.

    THE EXIT LINE IS NOT WRITTEN BY EVERY HARNESS BUILD, so it cannot be the only check.
    Measured 2026-08-17, after the fix above shipped: this guard blocked three stops in a row
    over bqnq5m0wv, bi6s3igu1 and bgiikm8kq. All three had reported `completed`, all three
    had their output read, and not one output file contained `[exited with code` anywhere.
    The paragraph above states the harness appends it; on this build it does not, so the only
    disk signal never arrived and every finished run read as running forever.

    WHAT IS ACTUALLY ON DISK IS THE OPEN FILE HANDLE. A running background command holds its
    stdout open; an exited one does not. Measured the same day, one live run against four
    finished ones: the live run's output file had 2 open writers, each finished one had 0.
    That is the signal that cannot go stale, because it is the operating system's own record
    of the process rather than something the harness has to remember to write.

    A PROBE THAT CANNOT RUN MEANS FINISHED, NOT RUNNING. If lsof is missing or fails, this
    returns True and the guard does not block. A guard that blocks whenever its own probe
    breaks cannot be satisfied, and an unsatisfiable guard gets uninstalled — the failure this
    file's docstring warns about, and the one that produced both fixes above.
    """
    import glob as _glob
    for root in _TASK_ROOTS:
        for hit in _glob.glob("%s/*/*/tasks/%s.output" % (root, tid)):
            try:
                with open(hit, encoding="utf-8", errors="replace") as fh:
                    if "[exited with code" in fh.read()[-4000:]:
                        return True
            except OSError:
                continue
            return not _has_open_writer(hit)
    return True  # no output file anywhere: not a real background run


def _has_open_writer(path: str) -> bool:
    """True only when some process demonstrably holds `path` open.

    Anything else — no lsof, a non-zero exit, a timeout — is False, so the caller reports the
    run as finished and the guard stays satisfiable. See `_finished_on_disk`.
    """
    lsof = shutil.which("lsof")
    if not lsof:
        return False
    try:
        out = subprocess.run([lsof, "-t", "--", path], capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.stdout.strip())


REASON = (
    "IDLE GUARD: {n} background run(s) still going ({ids}) and you are ending the turn.\n"
    "\n"
    "Founder rule, global CLAUDE.md: never sit and watch a long command. Backgrounding it "
    "was right; stopping afterwards is the part that wastes the wall clock.\n"
    "\n"
    "Do the next INDEPENDENT thing now — check the task list for a pending item, or start "
    "work that does not depend on the run in flight.\n"
    "\n"
    "If every remaining task genuinely depends on that run, say so in one line and stop "
    "again. This guard blocks once, not twice."
)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    # The retry. The agent has already been asked once; let it stop.
    if payload.get("stop_hook_active"):
        return 0
    path = payload.get("transcript_path") or ""
    if not path or not os.path.exists(path):
        return 0
    try:
        pending = in_flight(path)
    except Exception:
        return 0
    if not pending:
        return 0
    print(json.dumps({
        "decision": "block",
        "reason": REASON.format(n=len(pending), ids=", ".join(pending)),
    }))
    return 0


def selftest() -> int:
    import tempfile

    def transcript(records: list[dict]) -> str:
        fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for r in records:
            fh.write(json.dumps(r) + "\n")
        fh.close()
        return fh.name

    def rec(text: str) -> dict:
        return {"type": "user", "message": {"role": "user", "content": text}}

    # Every fixture id below needs an output file, because an id with no file on disk is
    # now proof the run was never real (see _finished_on_disk). One sandbox for the whole
    # selftest; `done1` carries an exit line, the rest are still running.
    global _TASK_ROOTS
    sandbox = tempfile.mkdtemp(prefix="idleguard-")
    tasks = os.path.join(sandbox, "sess", "run", "tasks")
    os.makedirs(tasks, exist_ok=True)
    #
    # The "still running" fixtures keep their handle OPEN for the rest of the selftest. That is
    # not decoration: `_finished_on_disk` now asks whether a process holds the file open, so a
    # fixture written and closed would read as finished and cases 1, 3, 5 and 6 would pass for
    # the wrong reason. Holding the handle makes this process the writer, which is exactly the
    # state a live background run is in.
    held = []
    for tid in ("abc123", "aaa", "bbb", "zzz", "live1"):
        fh = open(os.path.join(tasks, tid + ".output"), "w")
        fh.write("....... still going, no exit line yet\n")
        fh.flush()
        held.append(fh)
    with open(os.path.join(tasks, "done1.output"), "w") as fh:
        fh.write("442 passed, 1 warning in 387.35s\n\n[exited with code 0]\n")
    _saved_roots, _TASK_ROOTS = _TASK_ROOTS, (sandbox,)

    cases = []

    # 1. One launched, never finished -> in flight.
    p = transcript([rec("Command running in background with ID: abc123")])
    cases.append(("launched only", in_flight(p) == ["abc123"]))

    # 2. Launched then completed -> clear.
    p = transcript([
        rec("Command running in background with ID: abc123"),
        rec("<task-id>abc123</task-id><status>completed</status>"),
    ])
    cases.append(("launched then done", in_flight(p) == []))

    # 3. Two launched, one done -> the other is still in flight.
    p = transcript([
        rec("Command running in background with ID: aaa"),
        rec("Command running in background with ID: bbb"),
        rec("<task-id>aaa</task-id>"),
    ])
    cases.append(("two launched one done", in_flight(p) == ["bbb"]))

    # 4. Nothing backgrounded -> clear.
    p = transcript([rec("ordinary reply with no background runs")])
    cases.append(("no background runs", in_flight(p) == []))

    # 5. Missing transcript never blocks.
    cases.append(("missing transcript", in_flight("/nonexistent/path.jsonl") == []))

    # 6. Structured content blocks are searched too, not just plain strings.
    p = transcript([{"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "content": [
            {"type": "text", "text": "Command running in background with ID: zzz"}]}]}}])
    cases.append(("structured content", in_flight(p) == ["zzz"]))

    # 7. The compaction defect: the launch text survives, the completion record does not,
    #    but the run's output file on disk says it exited. Disk wins.
    p = transcript([
        rec("Command running in background with ID: done1"),
        rec("Command running in background with ID: live1"),
    ])
    cases.append(("exited-on-disk clears a lost completion record",
                  in_flight(p) == ["live1"]))
    # 8. An id with no output file anywhere was never a real run. This is the guard reading
    #    its OWN fixtures: the ids above are text in this file, so once the file had been
    #    read they were text in the transcript too, and the guard blocked on them.
    p = transcript([
        rec("Command running in background with ID: ghost1"),
        rec("Command running in background with ID: ghost2"),
    ])
    cases.append(("text about a run is not a run", in_flight(p) == []))

    # 9. The defect this probe exists for: an output file with NO exit line and no process
    #    holding it open is a finished run, not a running one. On the harness build measured
    #    2026-08-17 the exit line is never written, so this is the only thing separating a
    #    completed run from a live one.
    with open(os.path.join(tasks, "closed1.output"), "w") as fh:
        fh.write("ran, said nothing about exiting, and the writer is gone\n")
    p = transcript([rec("Command running in background with ID: closed1")])
    cases.append(("no exit line and no open writer is finished", in_flight(p) == []))

    # 10. ...and the control that keeps case 9 from being vacuous: same shape, writer still
    #     holding the file open, so it IS in flight.
    p = transcript([rec("Command running in background with ID: live1")])
    cases.append(("no exit line but a live writer is in flight", in_flight(p) == ["live1"]))

    for fh in held:
        fh.close()
    _TASK_ROOTS = _saved_roots

    ok = True
    for name, passed in cases:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
