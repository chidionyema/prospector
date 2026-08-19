"""Every service on the stack can be shipped from the ops console, or says why not.

Founder instruction, 2026-08-19: "all our services must be deployable from the ops dashboard."

Before this, `/deploys` could report that the storefront was five commits behind main and offer
nothing to do about it. Shipping meant someone with a shell typing `gh workflow run`, which is the
single-human dependency deploy-engine.yml was written to remove.

What this pins is the CLASS, not the three buttons that exist today: a new entry in
`DEPLOYABLES` fails here until it has a route, and a route that claims a console button fails
until the button is really in the catalogue. Adding a service and forgetting the button is the
mistake this makes impossible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import deploy_now  # noqa: E402
from deploy_status import DEPLOYABLES  # noqa: E402

from prospector.ops import console_api as api  # noqa: E402


def _button_for(name: str) -> dict | None:
    command = f".venv/bin/python scripts/deploy_now.py {name}"
    for tool in api.TOOLS:
        if tool["command"] == command:
            return tool
    return None


def test_every_deployable_has_a_route():
    """A service with no route is a service that can only be shipped from a terminal."""
    unrouted = [n for n, r in deploy_now.routes().items() if r["kind"] == "unrouted"]
    assert not unrouted, (
        "these deployables have no way to ship from the console, and nothing says why:\n  "
        + "\n  ".join(unrouted)
        + "\n\nAdd a route to ROUTES in scripts/deploy_now.py — a workflow, a script, the "
          "console button that already ships it, or `manual` with the reason it is not a button."
    )


@pytest.mark.parametrize("name", [d["name"] for d in DEPLOYABLES])
def test_a_shippable_service_has_a_button_and_a_warning(name):
    """Anything the console CAN ship has a button, and the button admits what it does."""
    route = deploy_now.routes()[name]
    if route["kind"] not in ("workflow", "script"):
        pytest.skip(f"{name} ships by {route['kind']}, checked separately")

    tool = _button_for(name)
    assert tool is not None, (
        f"{name} can be deployed by scripts/deploy_now.py but has no row in console_api.TOOLS, "
        f"so the operator cannot reach it. Expected command: "
        f"'.venv/bin/python scripts/deploy_now.py {name}'"
    )
    assert tool["screen"] == "/deploys", (
        f"{name}'s deploy button is on {tool['screen']}, not the page that shows the gap"
    )
    assert tool["writes"] and tool["run"], f"{name}'s button must be runnable and marked writing"
    # `external` is the honest word: a deploy reaches Fly, and no store/ snapshot rolls it back.
    assert tool["risk"] == "external", f"{name}'s button claims risk={tool['risk']}"
    assert tool["danger"], f"{name}'s button carries no danger note; a deploy restarts production"


@pytest.mark.parametrize("name", [d["name"] for d in DEPLOYABLES])
def test_a_service_with_no_button_says_what_does_ship_it(name):
    """No silence. If there is no button the page says what ships it instead."""
    row = api._deploy_route(name)
    assert row["deploy_how"], f"{name} says nothing about how it ships"
    if row["deploy_tool_id"] is None:
        assert len(row["deploy_how"]) > 30, (
            f"{name} has no deploy button and the reason is too thin to act on: "
            f"{row['deploy_how']!r}"
        )
    else:
        assert _button_for(name) is not None
        assert row["deploy_tool_id"] == _button_for(name)["id"]


def test_the_view_carries_the_button_id_for_every_deployable():
    """The page renders `deploy_tool_id`; a missing key would render nothing and say nothing."""
    for d in DEPLOYABLES:
        row = api._deploy_route(d["name"])
        assert set(row) == {"deploy_tool_id", "deploy_how", "deploy_danger"}


@pytest.mark.parametrize("workflow", ["deploy-engine.yml", "deploy-api.yml", "deploy-web.yml"])
def test_a_dispatch_deploys_rather_than_dry_running(workflow):
    """`Deploy now` must deploy.

    Every deploy workflow has a `dry_run` input. If a button inherited a default that was later
    flipped to true, the run would go green having shipped nothing, and /deploys would keep
    reporting the gap while the operator watched a successful run.
    """
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    inputs = deploy_now.dispatch_inputs(text)
    assert inputs.get("dry_run") == "false", f"{workflow} would be dispatched with {inputs}"


def test_an_input_we_cannot_answer_is_refused_rather_than_guessed():
    """A required deploy input with no default stops the dispatch. Guessing one ships wrong."""
    with pytest.raises(ValueError):
        deploy_now.dispatch_inputs(
            "name: x\non:\n  workflow_dispatch:\n    inputs:\n"
            "      environment:\n        required: true\n        type: string\n"
        )


def test_declared_defaults_are_carried_through():
    """Anything not forced comes from the workflow, so adding an input needs no edit here."""
    text = (ROOT / ".github" / "workflows" / "deploy-web.yml").read_text(encoding="utf-8")
    assert deploy_now.dispatch_inputs(text)["target"] == "prod"


def test_a_dispatch_always_names_the_branch():
    """Without `--ref`, `gh` uses the checkout's current branch — a worktree could ship itself."""
    cmd = deploy_now.dispatch_command("/usr/local/bin/gh", "deploy-engine.yml", {"dry_run": "false"})
    assert cmd[:5] == ["/usr/local/bin/gh", "workflow", "run", "deploy-engine.yml", "--ref"]
    assert cmd[5] == "main"
    assert "-f" in cmd and "dry_run=false" in cmd
