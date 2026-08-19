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
import subprocess
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


def _dupe_keys(path: Path) -> list[str]:
    """Key names that appear twice inside ONE <dict>.

    plistlib keeps the LAST of a repeated key and says nothing, so a second
    EnvironmentVariables block silently deletes the first. That happened on 2026-08-17: a
    script added a store pin at the top of com.prospector.watchdog.plist while the file
    already carried an EnvironmentVariables block further down. plutil said OK, the pin was
    dead, the watchdog resolved its store next to the code, found no heartbeat, and paged
    the founder that the generation daemon was down while it was running normally.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []  # reported separately as UNREADABLE
    dupes = []
    for block in root.iter("dict"):
        seen: set[str] = set()
        for key in block.findall("key"):
            name = (key.text or "").strip()
            if name in seen:
                dupes.append(name)
            seen.add(name)
    return sorted(set(dupes))


def store_pin_faults() -> list[str]:
    """Prospector jobs must all name the SAME store, and never one inside their own checkout.

    The code runs from a checkout that rolls forward with origin/main; the catalogue, ledger,
    dossiers and provider health do not move with it. A store path resolved relative to the
    code splits the state in two, and the halves cannot see each other: a daemon writing one
    copy of provider_health.json while a probe reads another can never see a brain recover.

    Stated without naming a path, so it holds on any machine and after any checkout move. The
    pin must be present, must sit outside the job's own working directory, and every
    prospector job must agree on it.
    """
    faults: list[str] = []
    pins: dict[str, list[str]] = {}
    for path in sorted(LIVE.glob("com.prospector.*.plist")):
        label = path.stem
        for name in _dupe_keys(path):
            faults.append(
                "%s: key %r appears twice in one dict — plistlib keeps the LAST, "
                "so the first copy is dead config" % (label, name))
        try:
            with open(path, "rb") as fh:
                data = plistlib.load(fh)
        except Exception:  # noqa: BLE001 — already reported as UNREADABLE
            continue
        pin = (data.get("EnvironmentVariables") or {}).get("PROSPECTOR_STORE_DIR")
        if not pin:
            faults.append(
                "%s: no PROSPECTOR_STORE_DIR — its store resolves next to the code, so "
                "moving the checkout moves the state with it" % label)
            continue
        cwd = data.get("WorkingDirectory")
        if cwd and (pin == cwd or pin.startswith(cwd.rstrip("/") + "/")):
            faults.append(
                "%s: PROSPECTOR_STORE_DIR is inside its own checkout (%s) — the state will "
                "follow the code" % (label, pin))
        pins.setdefault(pin, []).append(label)
    if len(pins) > 1:
        faults.append("prospector jobs disagree on which store is canonical: " + "; ".join(
            "%s <- %s" % (pin, ",".join(labels)) for pin, labels in sorted(pins.items())))
    return faults


def disabled_labels() -> set[str]:
    """Labels launchd has been told never to load.

    Read from launchd, not from a `Disabled` key in the plist: `launchctl disable` writes to
    the per-user override database and the file on disk does not change. A retired job keeps
    its plist in ~/Library/LaunchAgents, so without this every retired job would be reported
    broken the moment its checkout was deleted — which is the outcome retiring it was for.

    Fails OPEN. If launchctl cannot be read the set is empty and every job is checked. A false
    alarm about a missing program is cheap; silence about one is what this exists to stop.
    """
    try:
        out = subprocess.run(["launchctl", "print-disabled", "gui/%d" % os.getuid()],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001 — no launchctl, timeout, permission: all mean "unknown"
        return set()
    return {m.group(1) for m in re.finditer(r'"([^"]+)"\s*=>\s*disabled', out)}


def broken_programs(live: dict[str, dict],
                    disabled: set[str] | None = None) -> list[str]:
    """Enabled jobs whose program or working directory is not on disk.

    Snapshot drift cannot see this, and the gap is not theoretical. `com.prospector.backup`
    matched its tracked snapshot exactly while every path in it pointed into
    /Users/chidionyema/Documents/code/prospector-live, a checkout that no longer exists. The
    nightly git mirror to R2 stopped on 2026-08-17, `--check` kept printing PASS, and the
    Hermes receipt for `backup_store.py` stayed green because Fly writes one under the same
    key. Nothing compared a declaration against the filesystem it names.

    Like the store-pin faults below, this is judged against the filesystem rather than against
    the snapshot, so `--snapshot` cannot silence it.
    """
    if disabled is None:
        disabled = disabled_labels()
    findings: list[str] = []
    for label in sorted(live):
        job = live[label]
        if label in disabled or "__unreadable__" in job:
            continue
        argv = job.get("ProgramArguments") or []
        program = str(argv[0]) if argv else str(job.get("Program") or "")
        # Absolute paths only. A bare `bash` is resolved against the job's own PATH at load
        # time, and this check has no business guessing what that resolves to.
        if program.startswith("/") and not Path(program).exists():
            findings.append("%s  program not found: %s" % (label, program))
            continue
        wd = str(job.get("WorkingDirectory") or "")
        if wd.startswith("/") and not Path(wd).exists():
            findings.append("%s  WorkingDirectory not found: %s" % (label, wd))
        # argv[0] above is the INTERPRETER, and every job in this estate is `python <script>`,
        # so checking only argv[0] validated the one argument that never goes missing. Measured
        # 2026-08-19: com.prospector.process-audit had exited 2 hourly for a day with
        # "can't open file '.../prospector-live/scripts/process_audit.py'", while its python and
        # its WorkingDirectory both existed and this function reported nothing. That job is the
        # only caller of `--check`, so the drift detector was dead and could not say so.
        #
        # Only absolute paths with a script suffix are judged. A relative path is resolved
        # against the job's own WorkingDirectory at load time and a bare word against its PATH;
        # guessing at either is how a check earns false positives and gets ignored.
        seen: set[str] = set()
        for arg in argv[1:]:
            a = str(arg)
            if not a.startswith("/") or a in seen:
                continue
            if not a.endswith((".py", ".sh", ".mjs", ".js")):
                continue
            seen.add(a)
            if not Path(a).exists():
                findings.append("%s  script not found: %s" % (label, a))
    return findings


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

    # Drift is measured against a snapshot, so a mistake that is snapshotted becomes the new
    # normal and stops being reported. These faults are judged against the invariant instead,
    # so --snapshot cannot silence them.
    faults = store_pin_faults()
    for fault in faults:
        print("STORE PIN    %s" % fault)

    broken = broken_programs(live)
    for finding in broken:
        print("BROKEN       %s" % finding)

    n = (len(added) + len(gone) + len(changed) + len(unreadable) + len(faults) + len(broken))
    if n == 0:
        print("LAUNCHD PLISTS PASS  %d job(s) match the tracked snapshot, and every enabled "
              "job's program is on disk" % len(live))
        return 0
    print("LAUNCHD PLISTS FAIL  %d finding(s)  "
          "(new=%d missing=%d drifted=%d unreadable=%d store-pin=%d broken=%d)  — review, "
          "then --snapshot to accept (store-pin and broken faults must be FIXED, not "
          "snapshotted)"
          % (n, len(added), len(gone), len(changed), len(unreadable), len(faults),
             len(broken)))
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
