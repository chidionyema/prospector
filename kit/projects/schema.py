"""What a project must declare before the kit will move it.

THE POINT OF THIS FILE IS THE SECOND PROJECT. Adding one must cost a declaration and
no code, so every fact that differs between two businesses lives here and nowhere
else: the names, where the resource inventory is written down, which classes of
resource the business has, and which substrates each class may be moved to.

IT FAILS AT SECOND 0, NAMING WHAT IS MISSING. A declaration validated at minute 20,
half way through a cutover, is a declaration that has already cost the downtime it
was supposed to prevent.

WHAT IT DELIBERATELY DOES NOT HOLD. The resource inventory itself. That is discovered
by asking the platforms (`scripts/estate_inventory.py`) and described by the file this
declaration POINTS AT. A declaration that listed resources could conceal one, and the
whole value of the inventory is that it cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# The adapter that speaks each class. This is kit-level truth, not project-level: two
# businesses moving a DNS zone need the same code. A project declares WHICH classes it
# has and WHERE each may go; it does not get to name a different script for `dns`.
CLASS_ADAPTERS: dict[str, str] = {
    "compute": "kit/classes/compute.sh",
    "datastore": "kit/classes/datastore.sh",
    "object_storage": "kit/classes/object_storage.sh",
    "dns": "kit/classes/dns.sh",
    "tls_certificate": "kit/classes/tls.sh",
    "secret": "kit/classes/secret.sh",
    "log_sink": "kit/classes/log_sink.sh",
    "scheduled_job": "kit/classes/scheduled_job.sh",
    "payment_integration": "kit/classes/payment_integration.sh",
    "ci_runner": "kit/classes/ci_runner.sh",
}

# Which classes must be finished before a class may start. Secrets first, because a
# target with no credentials comes up broken and every other class needs them there.
# DNS last, because pointing customers at a target that is not yet serving is the one
# ordering mistake that is visible from outside the building.
CLASS_NEEDS: dict[str, tuple[str, ...]] = {
    "secret": (),
    "object_storage": ("secret",),
    "datastore": ("secret",),
    "compute": ("secret", "datastore"),
    "scheduled_job": ("compute",),
    "log_sink": ("compute",),
    "payment_integration": ("compute",),
    "tls_certificate": ("compute",),
    "dns": ("compute", "tls_certificate"),
    "ci_runner": ("secret",),
}

# What a step of this class costs the business while it runs. The drill grades against
# these, so they are a declaration of intent that a measurement can contradict.
#   none       nothing stops
#   background work the business does not see pauses (clause A3's 120s budget)
#   customer   a customer could notice; only DNS earns this, and only during the flip
CLASS_DOWNTIME: dict[str, str] = {
    "secret": "none",
    "object_storage": "none",
    "datastore": "background",
    "compute": "background",
    "scheduled_job": "background",
    "log_sink": "none",
    "payment_integration": "none",
    "tls_certificate": "none",
    "dns": "customer",
    "ci_runner": "none",
}

REQUIRED = ("project", "names", "resources_declaration", "classes")


class DeclarationError(ValueError):
    """The declaration cannot be used. The message names what is missing or wrong."""


@dataclass(frozen=True)
class ClassDecl:
    """One class of resource, as one project declares it.

    `options` is the seam that keeps clause A5 and clause A7 from fighting each other. An
    adapter for `secret` has to know WHICH keys travel, and an adapter for `datastore` has
    to know where the state lands on the far side -- and both answers differ per business.
    Compiling either into `kit/` puts a product's private facts in the shared code, which is
    A5 gone; asking for a code change to add the second business is A7 gone. So every key in
    a class block other than `targets` becomes an option, the kit never reads one, and the
    runner hands them to the adapter as `OPT_<NAME>`. The kit stays ignorant of what any of
    them mean, which is what lets a class grow a knob without the kit learning about it.
    """

    name: str
    targets: tuple[str, ...]
    adapter: str
    needs: tuple[str, ...]
    downtime: str
    options: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Project:
    project: str
    names: tuple[str, ...]
    resources_declaration: str
    classes: dict[str, ClassDecl] = field(default_factory=dict)
    sell_check: dict[str, Any] = field(default_factory=dict)

    def targets(self) -> tuple[str, ...]:
        """Every substrate at least one class can reach."""
        seen: list[str] = []
        for decl in self.classes.values():
            for t in decl.targets:
                if t not in seen:
                    seen.append(t)
        return tuple(seen)


_OPTION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _options(klass: str, body: dict[str, Any], *, source: str) -> dict[str, str]:
    """Every key in a class block except `targets`, as strings the runner can put in an env.

    THE REFUSALS HERE ARE THE POINT. Each of them is knowable from this file alone, and each
    of them would otherwise surface as an adapter behaving oddly at whatever minute the move
    first reached this class -- which is the most expensive place in the run to learn anything.

    A value that is not a scalar is refused because an environment variable cannot carry a
    list or a mapping, and quietly stringifying one hands the adapter `['a', 'b']` to parse.
    A name that is not a plain identifier is refused because `OPT_MY-KEY` is not a variable
    any shell can read back. Two names differing only in case are refused because they
    collide once upper-cased, and the survivor would be whichever the mapping yielded last.
    """
    out: dict[str, str] = {}
    seen: dict[str, str] = {}
    for key, value in body.items():
        if key == "targets":
            continue
        if not isinstance(key, str) or not _OPTION_NAME.match(key):
            raise DeclarationError(
                f"{source}: class `{klass}`: option name `{key}` is not a plain identifier, so "
                f"it cannot be passed to the adapter as OPT_{str(key).upper()}"
            )
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise DeclarationError(
                f"{source}: class `{klass}`: option `{key}` must be a string or a number, got "
                f"{type(value).__name__} -- an environment variable cannot carry that"
            )
        upper = key.upper()
        if upper in seen:
            raise DeclarationError(
                f"{source}: class `{klass}`: options `{seen[upper]}` and `{key}` both become "
                f"OPT_{upper}. Rename one."
            )
        seen[upper] = key
        out[key] = str(value)
    return out


def validate(raw: Any, *, source: str = "<declaration>") -> Project:
    """Turn a parsed declaration into a Project, or raise naming the first defect."""
    if not isinstance(raw, dict):
        raise DeclarationError(f"{source}: the declaration must be a mapping, got {type(raw).__name__}")

    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise DeclarationError(f"{source}: missing required block(s): {', '.join(missing)}")

    project = raw["project"]
    if not isinstance(project, str) or not project.strip():
        raise DeclarationError(f"{source}: `project` must be a non-empty string")

    names = raw["names"]
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise DeclarationError(f"{source}: `names` must be a non-empty list of strings")

    decl_path = raw["resources_declaration"]
    if not isinstance(decl_path, str) or not decl_path.strip():
        raise DeclarationError(f"{source}: `resources_declaration` must be a path to the resource declaration")

    classes_raw = raw["classes"]
    if not isinstance(classes_raw, dict) or not classes_raw:
        raise DeclarationError(f"{source}: `classes` must be a non-empty mapping of class name to its targets")

    classes: dict[str, ClassDecl] = {}
    for name, body in classes_raw.items():
        if name not in CLASS_ADAPTERS:
            known = ", ".join(sorted(CLASS_ADAPTERS))
            raise DeclarationError(f"{source}: unknown resource class `{name}`. Known classes: {known}")
        if not isinstance(body, dict) or "targets" not in body:
            raise DeclarationError(f"{source}: class `{name}` must declare `targets`")
        targets = body["targets"]
        if not isinstance(targets, list) or not targets or not all(isinstance(t, str) for t in targets):
            raise DeclarationError(f"{source}: class `{name}`: `targets` must be a non-empty list of strings")
        classes[name] = ClassDecl(
            name=name,
            targets=tuple(targets),
            adapter=CLASS_ADAPTERS[name],
            needs=CLASS_NEEDS[name],
            downtime=CLASS_DOWNTIME[name],
            options=_options(name, body, source=source),
        )

    # A class whose prerequisite is not declared cannot be ordered, and finding that out
    # from a runner that has already started is exactly what this file exists to prevent.
    for name, decl in classes.items():
        for need in decl.needs:
            if need not in classes:
                raise DeclarationError(
                    f"{source}: class `{name}` needs `{need}`, which this project does not declare. "
                    f"Declare `{need}` or the run cannot be ordered."
                )

    sell = raw.get("sell_check") or {}
    if not isinstance(sell, dict):
        raise DeclarationError(f"{source}: `sell_check` must be a mapping when present")

    return Project(
        project=project,
        names=tuple(names),
        resources_declaration=decl_path,
        classes=classes,
        sell_check=sell,
    )


def load(path: str | Path) -> Project:
    """Read and validate a declaration file."""
    p = Path(path)
    if not p.is_file():
        raise DeclarationError(f"no project declaration at {p}")
    return validate(yaml.safe_load(p.read_text()), source=str(p))
