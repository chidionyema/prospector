"""A stopped machine whose runner is still busy must be started, not left to time out.

THE INCIDENT, 2026-08-19. Seven of nine GitHub runner registrations read `status: offline,
busy: true`. A registration outlives its machine, so stopping the machine leaves GitHub holding
a job against a runner that no longer exists. GitHub does not reassign it: it waits out the
timeout and marks the job failed with NO LOG, because no runner ever wrote one. The founder was
watching jobs die with no output while nothing had been pushed.

`deploy/runners.sh heal` reconciles that, and `cmd_autoscale` calls it before it sizes anything.
This test pins the wiring. Without it the reconciler is one refactor away from being a function
nothing calls -- which is the same defect as an ignore file nothing reads, or a warning fence
that only warns.

It is a source test on purpose. Running the real verb needs `fly` and `gh` credentials, which no
CI job has and no test should want; what can go wrong here mechanically is the CALL going
missing, and that is exactly what this reads.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "runners.sh"


def _body(name: str, text: str) -> str:
    """The source of one shell function, from `name() {` to the next top-level `}`."""
    start = text.index(f"{name}() {{")
    end = text.index("\n}\n", start)
    return text[start:end]


def test_heal_verb_is_dispatchable():
    text = SCRIPT.read_text()
    assert "cmd_heal() {" in text, "deploy/runners.sh has no cmd_heal"
    assert re.search(r"^\s*heal\)\s+cmd_heal ;;", text, re.M), (
        "cmd_heal exists but `runners.sh heal` does not reach it: no case arm in the dispatcher"
    )


def test_autoscale_heals_before_it_sizes():
    text = SCRIPT.read_text()
    body = _body("cmd_autoscale", text)
    assert "cmd_heal" in body, (
        "cmd_autoscale does not call cmd_heal. A machine stopped under a live job is a job that "
        "dies with no log, and it is capacity the queue reading cannot see."
    )
    assert body.index("cmd_heal") < body.index("_cfg_num autoscale_min"), (
        "cmd_heal must run BEFORE the queue is read: a stranded run is not `queued`, so sizing "
        "against it undercounts the work by however many jobs are stranded."
    )


def test_heal_starts_rather_than_deregisters():
    """Deleting a busy runner is refused by GitHub, so the repair has to be `machine start`."""
    body = _body("cmd_heal", SCRIPT.read_text())
    assert "fly machine start" in body, "cmd_heal does not start anything"
    assert "-X DELETE" not in body and "runners/$" not in body, (
        "cmd_heal must not try to deregister a busy runner: GitHub answers HTTP 422, "
        "'is currently running a job and cannot be deleted'"
    )
