#!/usr/bin/env python3
"""launchd_plists.py — track the estate's launchd job definitions, and detect drift.

WHY THIS EXISTS. Every scheduler on this estate is defined by a plist in
~/Library/LaunchAgents, and not one of them is in any repository. They exist on one disk.
On 2026-08-17 two fixes were applied to live plists and neither left a trace anywhere a
future session could read:

  * com.estate.costsentinel carried LowPriorityIO + ProcessType=Background, which set
    IOPOL_THROTTLE and starved a job that is entirely disk IO. Measured 0.54s of CPU in
    21 minutes, against 40.1s of CPU in 220s for the same scan in the normal band. Runs
    outlived the 900s StartInterval, launchd would not start the next run while the old
    one lived, and a capability with 408 clean runs behind it scored DARK.
  * ai.hermes.submodule-backup used StartCalendarInterval, which launchd SKIPS outright
    if the machine is asleep at that minute. The backup read last=3.5d.

Both fixes would revert silently. That is what this closes. See docs/ESTATE_QUIRKS.md Q1-Q4.

SECRETS. Plists carry real credentials: CONTROL_CENTER_PASSWORD in two of them and
DEEPSEEK_API_KEY in a third. Snapshots therefore REDACT any value whose key name looks
like a credential, and the comparison treats a redacted value as equal to a redacted
value. Drift in a secret's VALUE is deliberately invisible here — this tool tracks job
DEFINITIONS, not the secret store, and a tool that logs a password to catch drift is
worse than the drift.

Usage:
    python3 scripts/launchd_plists.py --check       # report drift, exit 1 if any
    python3 scripts/launchd_plists.py --snapshot    # write the tracked copies
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import sys
from pathlib import Path

LIVE = Path(os.path.expanduser("~/Library/LaunchAgents"))
TRACKED = Path(__file__).resolve().parent.parent / "ops" / "launchd"

REDACTED = "<REDACTED>"

# Key names whose VALUE must never be written to a tracked file. Matched case-insensitively
# against the key name, anywhere in it, so DEEPSEEK_API_KEY and CONTROL_CENTER_PASSWORD both
# match. Deliberately broad: a false positive costs one redacted line, a false negative
# commits a credential.
_SECRET_KEY_RE = re.compile(
    r"token|secret|api[_-]?key|password|passwd|credential|\bpem\b|private[_-]?key", re.I)

# Jobs we did not install and do not own. Tracking them would report drift every time a
# vendor updates its own agent, which trains the reader to ignore the output.
_FOREIGN_PREFIXES = ("com.adobe.", "com.expressvpn.", "com.valvesoftware.",
                     "com.google.", "com.microsoft.", "com.docker.")


def owned(label: str) -> bool:
    return not label.startswith(_FOREIGN_PREFIXES)


def redact(obj):
    """Deep-copy `obj`, replacing any value under a secret-looking key with REDACTED."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, bytes):
        return "<bytes:%d>" % len(obj)
    return obj


def load_live() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not LIVE.is_dir():
        return out
    for p in sorted(LIVE.glob("*.plist")):
        label = p.stem
        if not owned(label):
            continue
        try:
            with open(p, "rb") as fh:
                out[label] = redact(plistlib.load(fh))
        except Exception as exc:  # noqa: BLE001 — a malformed plist is itself a finding
            out[label] = {"__unreadable__": "%s: %s" % (type(exc).__name__, exc)}
    return out


def load_tracked() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not TRACKED.is_dir():
        return out
    for p in sorted(TRACKED.glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
    return out


def diff_keys(a: dict, b: dict, prefix: str = "") -> list[str]:
    """Flat list of human-readable differences between two plist dicts."""
    lines = []
    for k in sorted(set(a) | set(b)):
        path = prefix + k
        if k not in a:
            lines.append("    + %s = %r" % (path, b[k]))
        elif k not in b:
            lines.append("    - %s (was %r)" % (path, a[k]))
        elif isinstance(a[k], dict) and isinstance(b[k], dict):
            lines.extend(diff_keys(a[k], b[k], path + "."))
        elif a[k] != b[k]:
            lines.append("    ~ %s: %r -> %r" % (path, a[k], b[k]))
    return lines


def cmd_snapshot() -> int:
    live = load_live()
    TRACKED.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in TRACKED.glob("*.json")}
    for label, data in live.items():
        (TRACKED / (label + ".json")).write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n")
    removed = existing - set(live)
    for label in sorted(removed):
        (TRACKED / (label + ".json")).unlink()
    print("snapshot: %d job(s) written to %s" % (len(live), TRACKED))
    if removed:
        print("snapshot: %d removed (no longer installed): %s"
              % (len(removed), ", ".join(sorted(removed))))
    return 0


def cmd_check() -> int:
    live, tracked = load_live(), load_tracked()
    if not tracked:
        print("LAUNCHD PLISTS UNPROVEN — no snapshot yet. Run --snapshot.")
        return 2

    # A plist we could not parse is stored as its own error message. Two identical errors
    # compare equal, so an unreadable job used to be reported as "matches the snapshot" —
    # the check passed over a file it had never actually read. Measured 2026-08-17: two
    # plists carried a `--` inside an XML comment, which plutil tolerates and plistlib
    # refuses, and `--check` printed PASS 29 job(s) match over both of them.
    unreadable = sorted(lbl for lbl, d in live.items() if "__unreadable__" in d)

    added = sorted(set(live) - set(tracked))
    gone = sorted(set(tracked) - set(live))
    changed = {}
    for label in sorted(set(live) & set(tracked)):
        d = diff_keys(tracked[label], live[label])
        if d:
            changed[label] = d

    for label in added:
        print("NEW JOB      %s  (installed, never snapshotted)" % label)
    for label in gone:
        print("MISSING JOB  %s  (snapshotted, not installed)" % label)
    for label, d in changed.items():
        print("DRIFT        %s" % label)
        for line in d:
            print(line)

    for label in unreadable:
        print("UNREADABLE   %s  %s" % (label, live[label]["__unreadable__"]))

    n = len(added) + len(gone) + len(changed) + len(unreadable)
    if n == 0:
        print("LAUNCHD PLISTS PASS  %d job(s) match the tracked snapshot" % len(live))
        return 0
    print("LAUNCHD PLISTS FAIL  %d job(s) differ  "
          "(new=%d missing=%d drifted=%d unreadable=%d)  — review, then --snapshot to accept"
          % (n, len(added), len(gone), len(changed), len(unreadable)))
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true",
                   help="report drift against the tracked snapshot; exit 1 if any")
    g.add_argument("--snapshot", action="store_true",
                   help="overwrite the tracked snapshot with what is installed now")
    args = ap.parse_args()
    return cmd_snapshot() if args.snapshot else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
