#!/usr/bin/env python3
"""Refuse a reply that talks to the founder in jargon.

WHY THIS IS A SCRIPT AND NOT A RULE. The rule already existed. `~/.claude/CLAUDE.md` has carried
the "Plain English - say it straight" section since 2026-08-16, written after the founder said
"you sound drunk". On 2026-08-20 I wrote him three bullet points containing "client-bundled
module", "source scan", "drift test", "path filter" and "unrefed", and he replied "not sure wht y
of thi neans", then asked "why dont we avoid jargon as law". It was already law. A rule I can
read and still break is the floor, so this is the machine that refuses it.

WHAT IT READS. The Stop hook payload names the transcript. This takes the last assistant message
in it and scans the text ABOVE the first `---` line, because that is the part written for a
person. Below the fold is evidence, where a flag, a file path and a command name are wanted.

WHAT IT SKIPS. Fenced code, inline backticks, URLs and file paths. A word inside `code` is a
name, not jargon.

WHY THE WORD LIST IS SHORT. Every entry is a word I actually used on the founder, or one of the
same kind. A long list invents offences, gets false positives, and an unsatisfiable guard gets
uninstalled. Add to it when a real reply earns it, not from a thesaurus.

WHY IT CANNOT LOOP. It blocks at most three times per session, and never twice for the same
text. Rewriting is the way past it; repeating yourself is not blocked forever.

  python3 jargon-guard.py --selftest    # proves it blocks the real reply and passes the rewrite
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

STATE = Path.home() / ".claude" / "state" / "jargon-guard.json"
MAX_BLOCKS_PER_SESSION = 3

#: word -> what to say instead. The right-hand side is printed, so it has to be usable as-is.
JARGON = {
    "no-op": "does nothing",
    "idempotent": "safe to run twice",
    "seam": "the place where X plugs in",
    "wire format": "the shape of the data on the network",
    "client-bundled": "code that ships to the browser",
    "source scan": "a test that reads the source",
    "drift test": "a test that fails if the two copies stop matching",
    "path filter": "the rule that decides which tests CI runs",
    "unrefed": "does not hold the process open",
    "unref": "does not hold the process open",
    "fan-out": "run several at once",
    "backpressure": "slowing down when the far end is full",
    "back-pressure": "slowing down when the far end is full",
    "orthogonal": "unrelated",
    "vacuous": "passes without checking anything",
    "blast radius": "how much it breaks",
    "footgun": "easy to get wrong",
    "affordance": "the thing you can click",
    "surface area": "how much of it is exposed",
    "hydrate": "fill in on the browser side",
    "rehydrate": "fill in on the browser side",
    "monotonic": "only ever goes up",
    "hermetic": "runs the same everywhere",
    "memoize": "remember the answer",
    "thunk": "a function you call later",
}

FENCE = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`]*`")
URL = re.compile(r"https?://\S+")
PATH = re.compile(r"\S*/\S*")


def strip_code(text: str) -> str:
    """Remove everything that is a name rather than prose."""
    text = FENCE.sub(" ", text)
    text = INLINE.sub(" ", text)
    text = URL.sub(" ", text)
    return PATH.sub(" ", text)


def above_the_fold(text: str) -> str:
    """The part written for a person. A line that is only dashes starts the evidence."""
    out = []
    for line in text.splitlines():
        if re.fullmatch(r"\s*-{3,}\s*", line):
            break
        out.append(line)
    return "\n".join(out)


def offences(text: str) -> list[tuple[str, str]]:
    prose = strip_code(above_the_fold(text))
    found = []
    for word, plain in JARGON.items():
        pattern = r"(?<![\w-])" + re.escape(word) + r"(?![\w-])"
        if re.search(pattern, prose, re.I):
            found.append((word, plain))
    return found


def last_assistant_text(transcript: Path) -> str:
    """The final assistant message. Text blocks only: thinking is not shown to the founder."""
    text = ""
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            parts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                text = joined
    return text


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a missing or corrupt state file means no history
        return {}


def save_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state), encoding="utf-8")
    except Exception:  # noqa: BLE001 - failing to record must not fail the turn
        pass


def report(found: list[tuple[str, str]]) -> str:
    lines = ["JARGON IN A REPLY TO THE FOUNDER. He should not have to decode it."]
    for word, plain in found:
        lines.append('  "%s"  ->  say "%s"' % (word, plain))
    lines.append("")
    lines.append("Law: ~/.claude/CLAUDE.md, \"Plain English - say it straight\". His words were "
                 "\"you sound drunk\" and \"not sure wht y of thi neans\".")
    lines.append("Rewrite the text above the --- line and stop again. Below the fold is "
                 "evidence and is not checked, and anything in backticks is a name, not jargon.")
    return "\n".join(lines)


def selftest() -> int:
    real = ("Three things worth a reviewer's eye: the client-bundled module never sees the key, "
            "a source scan proves it, and the drift test is single-lane because of the CI path "
            "filter. The timer is unrefed.")
    rewrite = ("Three things worth a reviewer's eye: the browser never gets the key, a test "
               "reads the source and fails if anything imports it, and the copy check only runs "
               "in one of the two apps. The timer does not hold the build open.")
    checks = []

    got = {w for w, _ in offences(real)}
    checks.append(("blocks the real reply",
                   got == {"client-bundled", "source scan", "drift test", "path filter",
                           "unrefed"}, sorted(got)))
    checks.append(("passes the rewrite", offences(rewrite) == [], offences(rewrite)))
    checks.append(("code is not jargon", offences("The `no-op` flag is set.") == [], None))
    checks.append(("a path is not jargon", offences("See src/seam/thunk.ts for it.") == [], None))
    checks.append(("below the fold is free",
                   offences("All good.\n\n---\n\nThe drift test is idempotent.") == [], None))
    checks.append(("a longer word is not a hit", offences("The seamstress arrived.") == [], None))
    checks.append(("hyphenated neighbours miss",
                   offences("A no-operation call.") == [], None))
    checks.append(("a real hit inside a sentence",
                   [w for w, _ in offences("This is idempotent.")] == ["idempotent"], None))
    checks.append(("the report names the word",
                   'idempotent' in report(offences("This is idempotent.")), None))

    bad = [(name, extra) for name, ok, extra in checks if not ok]
    for name, extra in bad:
        print("FAIL %s %r" % (name, extra), file=sys.stderr)
    if bad:
        return 1
    print("jargon-guard selftest: %d/%d passed" % (len(checks), len(checks)))
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}

    path = payload.get("transcript_path") or ""
    if not path or not os.path.exists(path):
        return 0  # a probe that cannot run means PASS
    try:
        text = last_assistant_text(Path(path))
    except OSError:
        return 0
    if not text:
        return 0

    found = offences(text)
    if not found:
        return 0

    session = str(payload.get("session_id") or "unknown")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    state = load_state()
    mine = state.get(session) or {"count": 0, "seen": []}
    # Never block the same text twice, and never more than three times in one session. An
    # unsatisfiable guard gets uninstalled, and a Stop hook that always blocks is a wedge.
    if digest in mine["seen"] or mine["count"] >= MAX_BLOCKS_PER_SESSION:
        return 0
    mine["count"] += 1
    mine["seen"] = (mine["seen"] + [digest])[-20:]
    state[session] = mine
    save_state(state)

    print(report(found), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
