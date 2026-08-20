#!/usr/bin/env python3
"""PreToolUse guard: keep the global rules file free of project-specific content.

WHY THIS EXISTS
---------------
2026-08-19, founder: "why do we have 2 claude mds, split brain, only one, only critical and
useful and relevant info."

Measured that day: `~/.claude/CLAUDE.md` was 28,885 chars and carried a `# graphify` section, a
`# Tracked programmes` section, prospector paths inside the agent tenets, and a `~/.hermes`
command inside "State is a probe" -- all of it about ONE repo, all of it billed into the window
of every session in every other repo. Six repos (lux, popdd-py, popdd-ts, sentinel-loop,
signalengine, vault-201) have no CLAUDE.md of their own, so they paid for prospector's paths and
got nothing back.

The class is: A FILE WHOSE SCOPE IS NOT ENFORCED DRIFTS INTO THE SCOPE BELOW IT. It cannot be
closed by tidying the file once. It drifts back the next time an agent has a prospector fact and
the global file is the one already open. So the boundary is a refusal, not a paragraph.

THE RULE
--------
`~/.claude/CLAUDE.md` is HOW to work, in any repo. A project's own `CLAUDE.md` is WHAT that
project is. A project name, a project path or a project doc written into the global file is
refused, and the message names the file it belongs in instead.

HOW IT FAILS
------------
Open. Any exception, any unparseable payload -> exit 0 and the tool call proceeds. A guard that
wedges ~18 Claude processes is a worse outage than the drift it prevents.

THE ESCAPE
----------
Put `SCOPE-LEAK-OK` in the command or the content. The laws block itself contains
`prospector-ci` inside LAW 1's worked example, which the founder ordered kept verbatim, so a
legitimate rewrite of the laws needs the marker -- and stating that intent out loud is the point.

    python3 scope-guard.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import sys

GLOBAL_RULES = os.path.expanduser("~/.claude/CLAUDE.md")
ESCAPE = "SCOPE-LEAK-OK"

#: Tokens that name ONE project or ONE machine's estate. Case-insensitive.
PROJECT_TOKENS = (
    "prospector", "hermes", "graphify", "mumchimp", "store_platform", "popdd",
    "COST_PROGRAM", "PLATFORM_MANIFESTO", "WAYS_OF_WORKING", "SITE_SPEC_PROGRAM",
    "PACK_NARRATIVE", "LAUNCH_OPS", "Documents/code/",
)
_TOKENS = re.compile("|".join(re.escape(t) for t in PROJECT_TOKENS), re.I)

#: A Bash command only counts when it WRITES the file. Reading it must stay free.
_WRITES_GLOBAL = re.compile(
    r"(?:>>?|tee\b[^|;]*|sed\s+-i[^|;]*|cp\b[^|;]*|mv\b[^|;]*)\s*"
    r"(?:'|\")?(?:~|\$HOME|/Users/[^/\s]+)/\.claude/CLAUDE\.md"
)


def _is_global(path: str) -> bool:
    if not path:
        return False
    return os.path.realpath(os.path.expanduser(path)) == os.path.realpath(GLOBAL_RULES)


def verdict(tool: str, ti: dict) -> str | None:
    """A refusal message, or None to allow."""
    if tool == "Bash":
        cmd = ti.get("command") or ""
        if ESCAPE in cmd or not _WRITES_GLOBAL.search(cmd):
            return None
        hits = _TOKENS.findall(cmd)
    elif tool in ("Write", "Edit", "NotebookEdit"):
        if not _is_global(ti.get("file_path") or ""):
            return None
        body = (ti.get("content") or "") + (ti.get("new_string") or "")
        if ESCAPE in body:
            return None
        hits = _TOKENS.findall(body)
    else:
        return None
    if not hits:
        return None
    names = sorted({h.lower() for h in hits})
    return (
        f"REFUSED: this writes {', '.join(names)} into ~/.claude/CLAUDE.md.\n"
        "That file is HOW to work, in ANY repo. It is resident in every session in every repo, "
        "including six that have no CLAUDE.md of their own, so a fact about one project is "
        "billed to all of them and useful to none.\n"
        "Put it in that project's own CLAUDE.md instead (e.g. "
        "~/Documents/code/<project>/CLAUDE.md), or in a memory file.\n"
        f"If the content genuinely belongs in the global rules, add {ESCAPE} to say so out loud."
    )


def selftest() -> int:
    W = "cat > ~/.claude/CLAUDE.md <<'EOF'\n"
    cases = [
        # (tool, tool_input, should_refuse)
        ("Bash", {"command": W + "# graphify\nrun prospector\nEOF"}, True),
        ("Bash", {"command": "echo '# graphify' >> /Users/chidionyema/.claude/CLAUDE.md"}, True),
        ("Bash", {"command": "echo '# graphify' >> $HOME/.claude/CLAUDE.md"}, True),
        ("Bash", {"command": W + "# LAW 0\nrules only\nEOF"}, False),
        ("Bash", {"command": "cat ~/.claude/CLAUDE.md | rg prospector"}, False),   # read is free
        ("Bash", {"command": "echo prospector >> ~/Documents/code/prospector/CLAUDE.md"}, False),
        ("Bash", {"command": W + "prospector\nEOF\n# SCOPE-LEAK-OK"}, False),      # escape
        ("Write", {"file_path": GLOBAL_RULES, "content": "# graphify\nprospector"}, True),
        ("Write", {"file_path": GLOBAL_RULES, "content": "# LAW 0\nrules only"}, False),
        ("Write", {"file_path": GLOBAL_RULES, "content": "prospector SCOPE-LEAK-OK"}, False),
        ("Write", {"file_path": "~/.claude/CLAUDE.md", "content": "hermes"}, True),
        ("Write", {"file_path": "/Users/chidionyema/Documents/code/prospector/CLAUDE.md",
                   "content": "prospector runs here"}, False),
        ("Edit", {"file_path": GLOBAL_RULES, "new_string": "see docs/COST_PROGRAM.md"}, True),
        ("Edit", {"file_path": GLOBAL_RULES, "new_string": "measure before building"}, False),
        ("Read", {"file_path": GLOBAL_RULES}, False),
    ]
    bad = 0
    for tool, ti, want in cases:
        got = verdict(tool, ti) is not None
        if got != want:
            bad += 1
            print(f"FAIL {tool} {ti} -> refuse={got}, want={want}")
    print(f"{len(cases) - bad}/{len(cases)} passed")
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
        msg = verdict(payload.get("tool_name") or "", payload.get("tool_input") or {})
    except Exception:
        return 0
    if not msg:
        return 0
    print(msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
