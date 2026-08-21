"""The incident report, in the ops console.

Founder, 2026-08-18: "we need extreme visibility into what could go wrong, also need incident
report, as we are going to be doing this for incidents now."

Incident records were already READABLE from ops — `docs_view` serves `docs/incidents/*.json` as
raw documents. Readable is not a report. Which incidents are still open, which have no mechanism
behind them, which have a mechanism nobody has graded, and which are past their grading window
existed in exactly one place: the terminal output of `scripts/incident.py check`. An operator
without a checkout could not see any of it, and nothing in the console got worse when a record
rotted.

THIS MODULE ADDS NO JUDGEMENT. Every verdict here — what blocks a record from closing, what is
overdue, what needs a ticket — comes from `scripts/incident.py`, which is also what the CI gate
runs. That is deliberate: a console that grades incidents by its own rules would eventually
disagree with the gate, and then the page and the build would be answering different questions
about the same file. This module loads records, calls those functions, and shapes the result for
a screen.

`scripts/` is not an importable package, so the script is loaded by path. `console_api` already
reaches scripts/ this way for the failover tool.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

#: The mechanism tiers, strongest first, with what each one actually promises. `incident.TIERS`
#: is the source of the names and their order; these sentences are the console's translation of
#: the tenet "self-healing first, guard second, memory file last".
TIER_MEANING = {
    "heal": "the system repairs it without anyone being told",
    "refuse": "a machine refuses the mistake before it lands",
    "test": "a test goes red when it comes back",
    "memory": "it is written down, and nothing enforces it",
}


def _incident_module(repo_root: Path) -> ModuleType:
    """Load `scripts/incident.py` as a module.

    Cached under a private name in `sys.modules` so repeated reads do not re-execute the file.
    """
    cached = sys.modules.get("_prospector_ops_incident_script")
    if cached is not None:
        return cached
    path = repo_root / "scripts" / "incident.py"
    spec = importlib.util.spec_from_file_location("_prospector_ops_incident_script", path)
    if spec is None or spec.loader is None:  # pragma: no cover — a missing file is the real case
        raise FileNotFoundError(f"the incident script is not at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _next_step(row: dict, needs_ticket: bool) -> str:
    """The single most useful thing to do about this record, in one sentence.

    Ordered by what blocks what. A record with no mechanism cannot be graded, so asking for a
    grade first would be advice nobody can act on.
    """
    if row["state"] == "malformed":
        return "The file does not parse. Fix the JSON; nothing else can be read from it."
    if not row["landed_on"]:
        return ("No mechanism has landed. Decide the tier — heal, refuse, test or memory — and "
                "build it; a record without one is a note, not a fix.")
    if row["blocking"]:
        return f"Fill in what the record is missing: {'; '.join(row['blocking'])}."
    if row["overdue"]:
        return f"Grade it: {row['overdue']}."
    if row["verdict"] != "proven":
        return "The mechanism is in place and the window is still open. Grade it when it closes."
    if needs_ticket:
        return "Open a ticket so the remaining work is tracked."
    return "Nothing outstanding. It may close."


def incidents_view(repo_root: Path) -> dict:
    """The rollup `incident.py check` prints, shaped for a screen."""
    incident = _incident_module(repo_root)
    records = incident.load(repo_root / "docs" / "incidents")
    report = incident.rollup(records)

    by_id = {rec.get("id"): rec for rec in records}
    rows = []
    for row in report["incidents"]:
        rec = by_id.get(row["id"], {})
        wants_ticket = bool(rec) and incident.needs_ticket(rec)
        rows.append({
            **row,
            # Deep link into the docs view, which already serves these files by name. The name
            # is REPO-RELATIVE since 2026-08-21, when the docs root widened from docs/ to the
            # whole repo: every row now names the same path the index lists and the share fence
            # mints a token from, so a link, a listing and a token cannot disagree. `_safe` still
            # accepts the old docs-relative form, so links minted before today keep opening.
            "doc": f"docs/incidents/{row['id']}.json" if row.get("id") else None,
            "needs_ticket": wants_ticket,
            "tier_means": TIER_MEANING.get(row.get("tier") or "", ""),
            "what_broke": (rec.get("first_order") or {}).get("what_broke"),
            "mechanism": (rec.get("third_order") or {}).get("mechanism"),
            # The last link of the chain is the CLASS of failure. It is the whole point of the
            # record and the only line most readers need.
            "class": (rec.get("cause_chain") or [None])[-1],
            "next": _next_step(row, wants_ticket),
            # `landed_on` is deliberately part of this. It is NOT one of incident.py's REQUIRED
            # fields, so a record can validate clean, be overdue for nothing, and still have no
            # mechanism behind it at all — which is the single worst state a record can be in and
            # read as fine on a dashboard. Caught by a test that asserted otherwise.
            "ok": row["state"] == "closed" or bool(
                row["landed_on"] and not (row["blocking"] or row["overdue"])),
        })

    # Worst first, and the order is an argument, not a preference. A file nobody can parse tells
    # us nothing. A record with no mechanism means the class of failure is still live. A record
    # that cannot close hides an unfinished sweep. An overdue grade is a mechanism that is at
    # least armed. Closed records go last.
    def _rank(r: dict) -> tuple:
        return (r["state"] == "closed", r["ok"], bool(r["landed_on"]), not r["blocking"],
                not r["overdue"], str(r.get("opened") or ""))

    rows.sort(key=_rank)

    headline = dict(report["headline"])
    headline["blocked"] = sum(1 for r in rows if r["blocking"] and r["state"] != "closed")
    headline["by_tier"] = {
        tier: sum(1 for r in rows if r.get("tier") == tier) for tier in incident.TIERS
    }
    headline["no_tier"] = sum(1 for r in rows if not r.get("tier"))

    return {
        "generated_at": report["generated_at"],
        "process": report["process"],
        "gate": ".venv/bin/python scripts/incident.py check",
        "note": ("Every verdict on this page comes from scripts/incident.py, the same code the "
                 "CI gate runs. Tiers rank strongest first: heal, refuse, test, memory."),
        "tier_meaning": TIER_MEANING,
        "headline": headline,
        "incidents": rows,
    }
