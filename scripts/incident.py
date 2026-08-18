#!/usr/bin/env python3
"""The incident loop: record, sweep, guard, grade. The process is docs/INCIDENT_PROCESS.md.

WHY THIS EXISTS. Founder, 2026-08-18: "we don't have a process and we should. self healing and
self governing with ops visibility. and self improving. by having incident reports, root causes,
never repeating mistakes... second order effects. classes of mistakes. most platform issues are
recurring."

The estate's own tenets already said "never make the same mistake twice" and "follow the root
cause chain to the end". They were words, and the words lost: on 2026-08-17 a rule was written
that no store path may be derived from `__file__`, four constants were fixed, and on 2026-08-18
a fifth resolver was found writing live listing files into the container image layer. The rule
existed. Nothing swept for siblings, and nothing graded the rule afterwards.

So a record here cannot reach `closed` without all four:

    first_order   the instance, with a receipt
    second_order  the sibling sweep: the command, and the count it returned
    third_order   the mechanism that kills the class (heal > refuse > test > memory)
    grade         occurrences of the signature before the mechanism, and after it

REPORT MODE ONLY. `check` returns a non-zero exit code and `ticket` opens GitHub issues. Nothing
here edits a record, invents a cause, or closes an incident on your behalf.

USAGE
    .venv/bin/python scripts/incident.py list
    .venv/bin/python scripts/incident.py check        # CI gate
    .venv/bin/python scripts/incident.py friction     # slow / repeated / expensive + recommendations
    .venv/bin/python scripts/incident.py ticket [--dry-run]
    .venv/bin/python scripts/incident.py --json [PATH]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The store is resolved by config.store_root() and nothing else. A path derived from __file__
# follows the CODE, not the store, and on 2026-08-18 that cost eight live files. See
# docs/INCIDENT_PROCESS.md, "second order".
sys.path.insert(0, str(REPO_ROOT))
try:
    from prospector.config import store_root  # noqa: E402
except Exception:  # noqa: BLE001 — this script must still run on a box with no venv
    def store_root() -> Path:  # type: ignore[misc]
        import os
        return Path(os.environ.get("PROSPECTOR_STORE_DIR") or (REPO_ROOT / "store"))

INCIDENT_DIR = REPO_ROOT / "docs" / "incidents"
ROLLUP = Path(store_root()) / "ops" / "incidents.json"

TRANSCRIPTS = Path.home() / ".claude" / "projects"
DEFAULT_SLUG = "-Users-chidionyema-Documents-code-prospector"

#: The mechanism tiers, strongest first. The order is the rule, not a preference: a system that
#: repairs itself beats one that refuses, which beats one that only notices afterwards.
TIERS = ("heal", "refuse", "test", "memory")

#: How long a mechanism must hold before its incident may close. Two weeks is short enough to
#: keep the loop moving and long enough that a quiet fortnight is not the whole of the evidence.
DEFAULT_WINDOW_DAYS = 14

REQUIRED = {
    "first_order": ("what_broke", "receipt"),
    "second_order": ("sweep_command", "siblings_found"),
    "third_order": ("tier", "mechanism"),
    "grade": ("signature", "window_days"),
}


def _today() -> str:
    return _dt.date.today().isoformat()


def load() -> list[dict]:
    """Every record on disk, oldest first. A malformed file is a finding, never a crash."""
    out: list[dict] = []
    if not INCIDENT_DIR.is_dir():
        return out
    for path in sorted(INCIDENT_DIR.glob("INC-*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out.append({"id": path.stem, "state": "malformed", "error": str(exc),
                        "_path": str(path)})
            continue
        rec["_path"] = str(path)
        out.append(rec)
    return out


def validate(rec: dict) -> list[str]:
    """What stops this record closing. Empty list means it may close.

    Deliberately strict about the second order. `siblings_found: 0` is a valid answer and passes;
    a MISSING siblings_found does not, because "I did not look" and "I looked and found none" are
    the two states this whole process exists to keep apart.
    """
    problems: list[str] = []
    if rec.get("state") == "malformed":
        return [f"file does not parse: {rec.get('error')}"]

    for section, fields in REQUIRED.items():
        block = rec.get(section)
        if not isinstance(block, dict):
            problems.append(f"{section}: missing")
            continue
        for field in fields:
            if block.get(field) in (None, "", []):
                problems.append(f"{section}.{field}: missing")

    chain = rec.get("cause_chain")
    if not isinstance(chain, list) or len(chain) < 2:
        problems.append("cause_chain: needs at least two links — what broke, and what let it break")
    elif not str(chain[-1]).strip():
        problems.append("cause_chain: the last link is empty; it must name a CLASS of failure")

    tier = (rec.get("third_order") or {}).get("tier")
    if tier and tier not in TIERS:
        problems.append(f"third_order.tier: {tier!r} is not one of {', '.join(TIERS)}")

    grade = rec.get("grade") or {}
    verdict = grade.get("verdict")
    if verdict not in (None, "unproven", "proven", "failed"):
        problems.append(f"grade.verdict: {verdict!r} is not unproven/proven/failed")
    if rec.get("state") == "closed" and verdict != "proven":
        problems.append("state is closed but the grade is not `proven` — an ungraded guard is a belief")
    return problems


def overdue(rec: dict) -> str | None:
    """A mechanism whose window has elapsed and which nobody has graded.

    This is the stage that rots, so it is the stage with a deadline. Returns a sentence, or None.
    """
    grade = rec.get("grade") or {}
    if grade.get("verdict") == "proven":
        return None
    landed = (rec.get("third_order") or {}).get("landed_on")
    if not landed:
        return None
    try:
        due = _dt.date.fromisoformat(str(landed)) + _dt.timedelta(
            days=int(grade.get("window_days") or DEFAULT_WINDOW_DAYS))
    except ValueError:
        return f"third_order.landed_on is not a date: {landed!r}"
    if _dt.date.today() >= due:
        return (f"the {grade.get('window_days', DEFAULT_WINDOW_DAYS)}-day window closed on "
                f"{due.isoformat()} and the grade is still {grade.get('verdict') or 'unset'}")
    return None


# ---------------------------------------------------------------------------------------------
# Friction. The self-improvement half: what takes long, what repeats, what costs.
# ---------------------------------------------------------------------------------------------

#: Durations are derived from the gap between a transcript record and the next one. That is an
#: APPROXIMATION and is labelled as one everywhere it is printed: the gap also contains the
#: model's own thinking time, and a record the founder interrupted has no successor at all. It
#: is honest enough to RANK operations against each other, and not honest enough to quote as a
#: latency figure.
MAX_PLAUSIBLE_GAP_S = 900


#: Shell preamble that says nothing about what a command DOES. The first version of this ranking
#: put `cd /Users/.../prospector` at the top three times, because almost every command starts by
#: changing directory. Ranking the preamble is worse than not ranking at all: it looks like a
#: finding and points at nothing.
_PREAMBLE = re.compile(
    r"^\s*(?:cd\s+\S+|set\s+[-+]\w+|export\s+\S+=\S*|source\s+\S+|"
    r"[A-Z_][A-Z0-9_]*=\S*|bash\s+-c|sh\s+-c|timeout\s+\d+|"
    r"echo\s+(?:\"[^\"]*\"|'[^']*'|\S+))\s*(?:;|&&)?\s*")


def _signature(name: str, inp: dict) -> str:
    """A stable name for a kind of operation, so repeats can be counted across sessions."""
    if name == "Bash":
        cmd = str(inp.get("command", "")).replace("\n", " ").strip().lstrip("'\"")
        # Peel the preamble until a real verb is exposed. Bounded, because a pathological
        # command should cost a wrong label, never a hang.
        for _ in range(8):
            stripped = _PREAMBLE.sub("", cmd, count=1)
            if stripped == cmd:
                break
            cmd = stripped.lstrip("'\" ")
        head = " ".join(cmd.split()[:2])
        return f"Bash: {head}" if head else "Bash"
    if name in {"Read", "Edit", "Write"}:
        return f"{name}: {Path(str(inp.get('file_path', '?'))).name}"
    return name


def mine(slug: str, limit_files: int = 0) -> dict:
    """Rank operations by wall clock, by repetition, and by how often they end in a stop."""
    durations: defaultdict[str, list[float]] = defaultdict(list)
    counts: Counter = Counter()
    files = sorted((TRANSCRIPTS / slug).glob("*.jsonl"))
    if limit_files:
        files = files[-limit_files:]
    for path in files:
        pending: tuple[str, _dt.datetime] | None = None
        try:
            handle = path.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with handle:
            for line in handle:
                # A substring test before json.loads. The transcripts are over a gigabyte and
                # parsing every line is the entire cost of this function.
                if '"tool_use"' not in line and pending is None:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                stamp = rec.get("timestamp")
                when = None
                if isinstance(stamp, str):
                    try:
                        when = _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    except ValueError:
                        when = None
                if pending and when:
                    sig, started = pending
                    gap = (when - started).total_seconds()
                    if 0 <= gap <= MAX_PLAUSIBLE_GAP_S:
                        durations[sig].append(gap)
                    pending = None
                content = (rec.get("message") or {}).get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            sig = _signature(str(block.get("name", "?")),
                                             block.get("input") or {})
                            counts[sig] += 1
                            if when:
                                pending = (sig, when)
    slow = sorted(
        ({"signature": s, "calls": len(v), "total_s": round(sum(v), 1),
          "median_s": round(sorted(v)[len(v) // 2], 1)}
         for s, v in durations.items() if len(v) >= 3),
        key=lambda r: r["total_s"], reverse=True)[:15]
    repeated = [{"signature": s, "calls": n} for s, n in counts.most_common(15)]
    return {
        "note": "Durations are the gap to the next transcript record. That gap also contains "
                "thinking time, so these RANK operations against each other and are not latency "
                "figures. Counts are exact.",
        "transcripts": len(files),
        "slowest_by_total_time": slow,
        "most_repeated": repeated,
        "recommendations": recommend(slow, repeated),
    }


def recommend(slow: list[dict], repeated: list[dict]) -> list[dict]:
    """Turn the two tables into things somebody could actually do.

    Deliberately blunt rules, not a model call. A recommendation that needs judgement belongs in
    an incident record where a human or an agent signs it; this is the cheap first pass that says
    where to look.
    """
    out: list[dict] = []
    for row in slow[:5]:
        out.append({
            "kind": "slow",
            "signature": row["signature"],
            "evidence": f"{row['calls']} calls, {row['total_s']}s total, {row['median_s']}s median",
            "recommendation": "Background it, or fold it into a neighbouring call. Anything over "
                              "~30s should never be waited on in the foreground.",
        })
    for row in repeated[:5]:
        if row["calls"] < 20:
            continue
        out.append({
            "kind": "repeated",
            "signature": row["signature"],
            "evidence": f"{row['calls']} calls across the transcripts scanned",
            "recommendation": "Run this often enough to be worth a script with a name. A "
                              "repeated command is an automation that has not been written yet.",
        })
    return out


# ---------------------------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------------------------

def needs_ticket(rec: dict) -> bool:
    """An incident with no landed mechanism, and no issue already tracking it."""
    if rec.get("state") == "closed":
        return False
    if rec.get("issue"):
        return False
    return not (rec.get("third_order") or {}).get("landed_on")


def open_ticket(rec: dict, dry_run: bool) -> str:
    body = [
        f"Opened by `scripts/incident.py` from `{rec.get('_path', '?')}`.",
        "",
        f"**What broke.** {(rec.get('first_order') or {}).get('what_broke', '(unrecorded)')}",
        f"**Receipt.** `{(rec.get('first_order') or {}).get('receipt', '(none)')}`",
        "",
        "**Cause chain.**",
    ]
    for i, link in enumerate(rec.get("cause_chain") or ["(unrecorded)"], 1):
        body.append(f"{i}. {link}")
    second = rec.get("second_order") or {}
    third = rec.get("third_order") or {}
    body += [
        "",
        f"**Second order.** `{second.get('sweep_command', '(no sweep run)')}` found "
        f"{second.get('siblings_found', '?')} siblings, {second.get('siblings_fixed', '?')} fixed.",
        f"**Third order.** tier `{third.get('tier', '(unchosen)')}`: "
        f"{third.get('mechanism', '(none yet)')}",
        "",
        "This issue closes when the mechanism has landed and "
        "`scripts/incident.py check` grades it `proven`. The process is "
        "[docs/INCIDENT_PROCESS.md](../blob/main/docs/INCIDENT_PROCESS.md).",
    ]
    if dry_run:
        return f"[dry-run] would open: {rec.get('title', rec.get('id'))}"
    proc = subprocess.run(
        ["gh", "issue", "create", "--title", f"incident: {rec.get('title', rec.get('id'))}",
         "--label", "incident", "--body", "\n".join(body)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    return proc.stdout.strip() or proc.stderr.strip()


# ---------------------------------------------------------------------------------------------

def rollup(records: list[dict]) -> dict:
    rows = []
    for rec in records:
        problems = validate(rec)
        late = overdue(rec)
        rows.append({
            "id": rec.get("id"),
            "title": rec.get("title"),
            "opened": rec.get("opened"),
            "severity": rec.get("severity"),
            "state": rec.get("state", "open"),
            "tier": (rec.get("third_order") or {}).get("tier"),
            "landed_on": (rec.get("third_order") or {}).get("landed_on"),
            "verdict": (rec.get("grade") or {}).get("verdict") or "unset",
            "issue": rec.get("issue"),
            "blocking": problems,
            "overdue": late,
        })
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "process": "docs/INCIDENT_PROCESS.md",
        "headline": {
            "total": len(rows),
            "open": sum(1 for r in rows if r["state"] != "closed"),
            "unguarded": sum(1 for r in rows if not r["landed_on"] and r["state"] != "closed"),
            "unproven": sum(1 for r in rows if r["verdict"] != "proven" and r["state"] != "closed"),
            "overdue_grades": sum(1 for r in rows if r["overdue"]),
            "untracked": sum(1 for r in rows if not r["issue"] and r["state"] != "closed"),
        },
        "incidents": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?", default="list",
                    choices=["list", "check", "friction", "ticket"])
    ap.add_argument("--json", nargs="?", const=str(ROLLUP), metavar="PATH")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--project", default=DEFAULT_SLUG)
    ap.add_argument("--files", type=int, default=0,
                    help="only the N most recent transcripts (friction)")
    args = ap.parse_args(argv)

    records = load()

    if args.json:
        snap = rollup(records)
        out = Path(args.json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, indent=2))
        tmp.replace(out)  # atomic: the console may be reading it
        h = snap["headline"]
        print(f"wrote {out}  total={h['total']} open={h['open']} unguarded={h['unguarded']} "
              f"overdue={h['overdue_grades']}")
        return 0

    if args.command == "friction":
        print(json.dumps(mine(args.project, args.files), indent=2))
        return 0

    if args.command == "ticket":
        todo = [r for r in records if needs_ticket(r)]
        if not todo:
            print("no incident needs a ticket.")
            return 0
        for rec in todo:
            print(open_ticket(rec, args.dry_run))
        return 0

    snap = rollup(records)
    h = snap["headline"]
    print(f"incidents: {h['total']} recorded, {h['open']} open, {h['unguarded']} with no "
          f"mechanism, {h['unproven']} unproven, {h['overdue_grades']} overdue, "
          f"{h['untracked']} with no ticket")
    print()
    for row in snap["incidents"]:
        mark = "closed " if row["state"] == "closed" else "OPEN   "
        print(f"{mark} {row['id']}  [{row['tier'] or 'no mechanism'}/{row['verdict']}]  "
              f"{row['title'] or ''}")
        for p in row["blocking"]:
            print(f"          blocked: {p}")
        if row["overdue"]:
            print(f"          overdue: {row['overdue']}")
    if args.command == "check":
        bad = sum(1 for r in snap["incidents"] if r["blocking"] or r["overdue"])
        if bad:
            print(f"\n{bad} record(s) need attention. The process: docs/INCIDENT_PROCESS.md")
            return 1
        print("\nevery record is complete and every mechanism is graded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
