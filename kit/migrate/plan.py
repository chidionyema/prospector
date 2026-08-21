"""Compile a migration plan from what is actually running.

THE INPUT IS A PROBE REPORT, NEVER A LIST SOMEONE MAINTAINS. `scripts/estate_inventory.py`
asks the platforms what exists and writes `{"resources": [...]}`. This compiler turns that
into an ordered plan. A resource that appears in the world therefore appears in the plan,
and the only way to leave one behind is to be told to, in writing, with a reason.

THE INVARIANT, WHICH IS CLAUSE A2 ENFORCED AT SECOND 0. Every resource in the report is
either in a step or in `skipped` with a reason. There is no third bucket, and the two
reasons a skip may carry are both facts about the world rather than opinions:

    already on the target      moving a thing to where it already is, is not work
    an admitted gap            the probe says an open issue owns this resource

Anything else REFUSES the plan. A class the project has not declared, or a target its
adapter cannot reach, comes back as exit 78 with the class and the target named — before
anything has been stopped, packed or pointed anywhere. The alternative is finding out at
minute 20 of a 30 minute budget, with the source already down.

THREE VERBS, NOT ONE. `move` carries a thing from one substrate to another. `repoint`
re-aims a pointer a third party holds at us, and nothing about it is visible at cutover:
it breaks hours later, at the next webhook or the next alert. `rebuild` makes a thing
again at the target because carrying it makes no sense — a certificate, a runner.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from kit.projects.schema import ClassDecl, DeclarationError, Project, load  # noqa: E402

EX_CONFIG = 78  # sysexits.h — the configuration is wrong, not the run

# What is done to a resource of each class. A class absent here has no verb and the plan
# is refused rather than guessed at.
CLASS_VERBS: dict[str, str] = {
    "secret": "move",
    "datastore": "move",
    "object_storage": "move",
    "compute": "move",
    "scheduled_job": "rebuild",
    "ci_runner": "rebuild",
    "tls_certificate": "rebuild",
    "dns": "repoint",
    "log_sink": "repoint",
    "payment_integration": "repoint",
}


class PlanRefused(Exception):
    """The plan cannot be compiled. The message names the class and what is wrong."""


_ISSUE_RE = re.compile(r"#(\d+)")


def _gap_reason(resource: dict[str, Any]) -> str:
    """Why a resource is left behind, naming the issue that owns it wherever one exists.

    The probe records the owning issue in `problem` for some classes and in `restore` for
    others -- the storefront's DNS zone carries `problem: null` and the issue number in
    `restore`. Reading only `problem` reported "see the resource declaration" for 30 of the
    66 real gaps, which is a skip that names nobody, and a skip that names nobody is the
    silent skip clause A2 exists to forbid.
    """
    for field in ("problem", "restore"):
        found = _ISSUE_RE.search(str(resource.get(field) or ""))
        if found:
            return f"admitted gap, owned by issue #{found.group(1)}"
    return "admitted gap with NO owning issue -- nobody is on the hook for this resource"

def adapter_present(adapter: str | None) -> bool:
    """Is the file that would actually run this step on disk?

    `_step` used to copy `decl.adapter` into the plan and stop there, so a plan to any target
    read as 80 runnable steps while 73 of them named a file that does not exist. The runner
    does fail loudly at such a step, and the migration page does admit which classes are
    unwired -- but the PLAN is the artifact a person reads BEFORE starting the clock, and it
    was the one place that could not say so. Under a 30-minute whole-stack budget, finding out
    at minute 40 is the same as not having a plan.

    Relative adapter paths are resolved against the repo root rather than the caller's cwd:
    the plan is compiled from the console, from CI and from a terminal in a worktree, and the
    answer to "does this file exist" must not depend on which.
    """
    if not adapter:
        return False
    path = Path(adapter)
    if not path.is_absolute():
        path = REPO / path
    return path.is_file()


def substrate_of(where: str | None) -> str:
    """The platform half of the probe's `where` field, which reads `<substrate>/<state>`."""
    if not where:
        return "unknown"
    return where.split("/", 1)[0]


def _step(resource: dict[str, Any], decl: ClassDecl, target: str) -> dict[str, Any]:
    name = resource.get("name", "")
    cls = decl.name
    return {
        "id": f"{cls}:{name}",
        "class": cls,
        "resource": name,
        "verb": CLASS_VERBS[cls],
        "adapter": decl.adapter,
        "from": substrate_of(resource.get("where")),
        "to": target,
        "needs": list(decl.needs),
        "downtime": decl.downtime,
        "described_by": resource.get("described_by"),
        "adapter_present": adapter_present(decl.adapter),
        # Verbatim from the declaration, never read by the kit. See ClassDecl.options.
        "options": dict(decl.options),
    }


def compile_plan(report: dict[str, Any], project: Project, target: str) -> dict[str, Any]:
    """Turn a probe report into an ordered plan, or raise PlanRefused.

    Refusals happen here, before the runner exists, because every one of them is knowable
    from two files and costs nothing to find.
    """
    resources = report.get("resources")
    if not isinstance(resources, list):
        raise PlanRefused("the probe report has no `resources` list — is it the output of estate_inventory.py --json?")

    steps: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    undeclared: dict[str, list[str]] = {}
    unreachable: dict[str, list[str]] = {}

    for resource in resources:
        name = resource.get("name", "")
        cls = resource.get("class", "")

        admitted = resource.get("admitted")
        if admitted:
            skipped.append({"resource": name, "class": cls,
                            "reason": _gap_reason(resource), "admitted": str(admitted)})
            continue

        decl = project.classes.get(cls)
        if decl is None:
            undeclared.setdefault(cls, []).append(name)
            continue

        if target not in decl.targets:
            unreachable.setdefault(cls, []).append(name)
            continue

        if substrate_of(resource.get("where")) == target:
            skipped.append({"resource": name, "class": cls, "reason": f"already on {target}"})
            continue

        steps.append(_step(resource, decl, target))

    if undeclared:
        detail = "; ".join(f"{cls} ({len(names)}: {', '.join(sorted(names)[:3])})" for cls, names in sorted(undeclared.items()))
        raise PlanRefused(
            f"the probe found resources in class(es) this project does not declare: {detail}. "
            f"Declare them in the project file or they will be left behind."
        )
    if unreachable:
        detail = "; ".join(f"{cls} ({len(names)})" for cls, names in sorted(unreachable.items()))
        raise PlanRefused(
            f"target `{target}` is not in the declared targets for class(es): {detail}. "
            f"The adapter cannot honour this move, and finding that out mid-run costs the downtime budget."
        )

    steps.sort(key=lambda s: (len(s["needs"]), s["class"], s["resource"]))

    return {
        "project": project.project,
        "target": target,
        "steps": steps,
        "skipped": skipped,
        "unrunnable": sorted({s["adapter"] for s in steps if not s["adapter_present"]}),
        "counts": {"resources": len(resources), "steps": len(steps), "skipped": len(skipped),
                   # Steps whose adapter is not on disk. Reported rather than refused, on
                   # purpose: kit/classes/MISSING.md is the declared ledger of unwired classes,
                   # and a plan that refuses to compile until every adapter exists cannot be
                   # used to SEE how much is left. Loud, not fatal.
                   "unrunnable_steps": sum(1 for s in steps if not s["adapter_present"])},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True, help="JSON from `estate_inventory.py --json`")
    ap.add_argument("--project", required=True, help="a project declaration, e.g. kit/projects/<name>.yaml")
    ap.add_argument("--to", required=True, dest="target", help="the substrate to move to")
    ap.add_argument("--out", help="write the plan here as well as to stdout")
    args = ap.parse_args(argv)

    try:
        project = load(args.project)
    except DeclarationError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EX_CONFIG

    report_path = Path(args.report)
    if not report_path.is_file():
        print(f"REFUSED: no probe report at {report_path}", file=sys.stderr)
        return EX_CONFIG

    try:
        plan = compile_plan(json.loads(report_path.read_text()), project, args.target)
    except (PlanRefused, json.JSONDecodeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EX_CONFIG

    text = json.dumps(plan, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
