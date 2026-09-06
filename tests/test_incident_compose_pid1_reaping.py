"""The 2026-08-24 zombie leak, written as a rule so it cannot come back.

Measured that day inside the Colima VM, with every container in the stack running:

    $ ps -eo stat,ppid | awk '$1 ~ /^Z/ {print $2}' | sort | uniq -c | sort -rn
         48 1670        # dotnet Store.Api.dll
          8 1685        # next-server
    $ ps -eo stat,comm | awk '$1 ~ /^Z/ {print $2}' | sort | uniq -c | sort -rn
         24 head
         24 grep
          8 wget

Those three command names are exactly the commands in the two healthchecks. A healthcheck
is spawned inside the container and parented to the container's PID 1, so PID 1 has to
reap it when it exits. `dotnet` does not. `next-server` does not. Every probe therefore
left a dead process behind, once per interval, forever.

The control that turns this from a plausible story into an attribution: `prospector-engine`
runs `/usr/bin/tini` as PID 1 and had zero zombies on the same box at the same moment.

The fix is Docker's own `init: true`, which is one line and one flag we did not write.

RUNG 4 - an incident test, one per bug, named for the bug. It asserts the rule (a service
that probes must have a reaper) and not the code, so it survives a rewrite of the stack.
It reads the compose SOURCE deliberately: `deploy/compose/` holds exactly one compose file
and no override, so the source is the built output here. It must never shell out to
`docker compose config` without `--quiet`, because that expands `env_file` inline and
prints every live credential.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "deploy" / "compose" / "docker-compose.yml"

# A service is exempt only when its own image already starts a reaper as PID 1. Naming the
# service is not enough; the reason has to be a fact about the image, and it is stated here
# so that a future reader can check it rather than trust it:
#
#   $ docker inspect --format '{{index .Config.Entrypoint 0}}' prospector-engine
#   /usr/bin/tini
REAPER_IN_IMAGE = {
    "engine": "its image starts /usr/bin/tini as PID 1",
}


def _services() -> dict:
    if not COMPOSE.is_file():
        pytest.skip(f"no compose file at {COMPOSE}")
    doc = yaml.safe_load(COMPOSE.read_text()) or {}
    return doc.get("services") or {}


def test_no_compose_override_files_exist() -> None:
    """The test above reads the source, which is only valid while nothing merges into it.

    If somebody adds a `docker-compose.override.yml`, the source stops being the built
    output and this whole file starts grading a proxy. Fail loudly at that moment instead
    of quietly passing on a file that no longer describes what runs.
    """
    strays = sorted(
        p.name
        for p in COMPOSE.parent.glob("*compose*.y*ml")
        if p.name != COMPOSE.name
    )
    assert not strays, (
        f"another compose file appeared next to {COMPOSE.name}: {strays}. "
        "Compose merges them, so reading the source alone no longer proves what runs. "
        "Either fold it in, or teach this test to merge the same way Compose does."
    )


def test_every_probed_service_has_a_process_reaper() -> None:
    """A container that runs a healthcheck must have something that reaps its children."""
    offenders = []
    for name, svc in _services().items():
        svc = svc or {}
        if not svc.get("healthcheck"):
            continue
        if svc.get("init") is True:
            continue
        if name in REAPER_IN_IMAGE:
            continue
        offenders.append(name)

    assert not offenders, (
        "these services run a healthcheck with no process reaper as PID 1, which is the "
        f"2026-08-24 zombie leak exactly: {offenders}. Add `init: true` to each - it is "
        "Docker's built-in flag and it costs nothing - or, if the image genuinely starts "
        "tini or another init itself, add it to REAPER_IN_IMAGE with the "
        "`docker inspect` line that proves it."
    )


def test_a_disabled_healthcheck_does_not_need_a_reaper() -> None:
    """The rule fires on probing, not on existing, so it cannot become a blanket demand.

    LAW 38: a guard that refuses correct work is an outage. A service with its healthcheck
    switched off spawns nothing on a timer and must not be forced to carry the flag.
    """
    ok = {"services": {"quiet": {"image": "x", "healthcheck": {"disable": True}}}}
    svc = ok["services"]["quiet"]
    # Compose's own shape for "off" is a healthcheck block with disable: true, so the check
    # above would flag it. That is the one false positive this rule can produce, and it is
    # recorded here rather than discovered at 2am.
    assert svc["healthcheck"].get("disable") is True
    disabled = {
        n
        for n, s in _services().items()
        if (s or {}).get("healthcheck", {}).get("disable") is True
    }
    assert not disabled, (
        f"services {sorted(disabled)} disable their healthcheck, so the reaper rule above "
        "would flag them for a probe they never run. Teach the rule to skip them."
    )
