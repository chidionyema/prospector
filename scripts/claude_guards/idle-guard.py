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
import sys

# The harness prints this when a command is backgrounded.
LAUNCH = re.compile(r"Command running in background with ID:\s*([A-Za-z0-9_-]+)")
# ...and this when it lands. Both appear in tool results / system records in the transcript.
DONE = re.compile(r"<task-id>\s*([A-Za-z0-9_-]+)\s*</task-id>")
KILLED = re.compile(r"(?:killed|stopped) task\s+([A-Za-z0-9_-]+)", re.I)


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
    return [t for t in launched if t not in finished]


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

    ok = True
    for name, passed in cases:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
