"""The migration, in the ops console.

The founder's bar, 2026-08-19: "if i have 30 ninutes to nigrate the wwhole stack ... i should
not epericne ny downtine and get this seanlessly done fron ops dashboard and prove and see
realtine progress."

The last four words are this module. The runner already moves things and already says what it
is doing, but it says it into a JSON-lines file, so proving the move meant reading a log over
somebody's shoulder. An operator watching a migration at 3am needs a screen.

THIS MODULE ADDS NO JUDGEMENT. Every number on the page comes back out of `kit/migrate/
progress.py`, which is pure arithmetic over the runner's own events, so the bar the operator
watches and the exit code of the run are the same claim. Every class, target and adapter comes
out of the project's declaration and `kit/projects/schema.py`. This module loads, calls, and
shapes for a screen. If it ever starts deciding whether a run is healthy, the page and the run
will one day disagree about the same migration, and the page is the one nobody can check.

It does not START anything either. It hands back the exact argv for start, resume and rollback,
and the console's own tool runner is what executes them. A read view that can also move a
production database is not a read view.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

#: What each downtime class actually costs a customer, in the words an operator needs at 3am.
#: `schema.CLASS_DOWNTIME` is the source of the values; these sentences are the translation.
#: Clause A3 budgets the background pause at 120s and the customer-visible pause at zero, so an
#: operator picking an order of work needs to see which of the two a step is about to spend.
DOWNTIME_MEANING = {
    "none": "nothing pauses, and no customer can tell",
    "background": "the engine pauses; no customer request is affected",
    "customer": "a customer can see this one -- clause A3 budgets it at zero",
}


def _root() -> Path:
    """The repo, found from this file. Safe here because `kit/` is CODE, not state.

    The rule this deliberately does not break: a STORE path derived from `__file__` follows the
    code rather than the store, which is how the health marks and the retrieval cache once ended
    up beside a new checkout while the ledger stayed behind. Store paths come from
    `config.store_root()` below. The repo root is the other thing entirely -- `kit/projects/` and
    `kit/classes/` ship with the code and move with it by design.
    """
    return Path(__file__).resolve().parents[2]


def _kit():
    """Import the kit, with the repo root on the path.

    The console is started from several directories and `kit` is a top-level package, so the
    import can only be relied on once the root is present. Doing it here rather than at module
    scope keeps the cost off every console start that never opens this page.
    """
    root = _root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from kit.migrate import plan as plan_mod
    from kit.migrate import progress as progress_mod
    from kit.projects import schema as schema_mod

    return plan_mod, progress_mod, schema_mod


def store_dir(project: str) -> Path:
    """Where a project's plan and its event stream live.

    Under the store, never under the code: a migration's event stream is the only record that
    the move happened, and a record written beside whichever checkout happened to run it is a
    record the next operator cannot find.
    """
    from prospector import config

    return Path(config.store_root()) / "migrations" / project


def declarations(root: Path | None = None) -> list[Path]:
    """Every project declaration on disk, sorted.

    Clause A7: one declaration file per project, and no code change to add the second. This
    function is that clause -- it globs, it does not enumerate a list somebody has to maintain.
    """
    return sorted((root or _root()).glob("kit/projects/*.yaml"))


def _classes(project, root: Path) -> list[dict[str, Any]]:
    rows = []
    for name, decl in sorted(project.classes.items()):
        adapter = root / decl.adapter
        rows.append({
            "class": name,
            "adapter": decl.adapter,
            "adapter_exists": adapter.is_file(),
            "targets": list(decl.targets),
            "needs": list(decl.needs),
            "downtime": decl.downtime,
            "downtime_means": DOWNTIME_MEANING.get(decl.downtime, decl.downtime),
        })
    return rows


def migration_view(root: Path | None = None, *, project: str | None = None,
                   now: float | None = None) -> dict[str, Any]:
    """The page: what can be moved, where to, and how the live run is going.

    `project` names a declaration by its stem. With one declaration on disk and no argument, it
    picks that one -- an operator with a single project should not have to name it, and an
    operator with four should not be shown one at random, so the choice is only automatic when
    there is nothing to choose.
    """
    root = root or _root()
    plan_mod, progress_mod, schema_mod = _kit()

    found = declarations(root)
    listing = []
    chosen_path = None
    for path in found:
        entry: dict[str, Any] = {"name": path.stem, "file": str(path.relative_to(root))}
        try:
            decl = schema_mod.load(path)
        except schema_mod.DeclarationError as bad:
            entry["refused"] = str(bad)
        else:
            entry["project"] = decl.project
            entry["targets"] = list(decl.targets())
            entry["classes"] = _classes(decl, root)
            entry["names"] = list(decl.names)
        listing.append(entry)
        if project is None and len(found) == 1:
            chosen_path = path
        elif project is not None and path.stem == project:
            chosen_path = path

    out: dict[str, Any] = {
        "projects": listing,
        "chosen": chosen_path.stem if chosen_path else None,
        "downtime_meaning": dict(DOWNTIME_MEANING),
        "state_meaning": dict(progress_mod.STATE_MEANING),
    }
    if chosen_path is None:
        out["run"] = {"state": "no run", "detail": "pick a project"}
        return out

    where = store_dir(chosen_path.stem)
    events = where / "events.jsonl"
    plan_file = where / "plan.json"
    report = where / "estate.json"
    out["paths"] = {
        "events": str(events),
        "plan": str(plan_file),
        "report": str(report),
        "plan_exists": plan_file.is_file(),
        "report_exists": report.is_file(),
    }
    out["run"] = progress_mod.read(events, now=now)

    rel = str(chosen_path.relative_to(root))
    out["commands"] = {
        "probe": ["scripts/estate_inventory.py", "--json", "--out", str(report)],
        "compile": ["kit/migrate/plan.py", "--report", str(report), "--project", rel,
                    "--to", "<target>", "--out", str(plan_file)],
        "start": ["kit/migrate/run.py", "--plan", str(plan_file), "--events", str(events)],
    }
    resume = out["run"].get("resume_with")
    if resume:
        # The runner writes this line itself, from the step that actually failed. The console
        # repeats it verbatim rather than composing its own, because a resume line the page
        # invented is a resume line nobody has tested against the run it is resuming.
        out["commands"]["resume"] = out["commands"]["start"] + resume.split()
    return out
