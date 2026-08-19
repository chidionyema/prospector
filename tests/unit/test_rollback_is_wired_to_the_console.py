"""Every service that can be deployed from the console can be put back from the console.

Founder instruction, 2026-08-20: "this is deploying to prod, needs to be absolutely rock solid and
bulletproof, rollback also, verified with automated tests and a drill function in ops".

A Deploy button with no Rollback button is worse than neither: it lets an operator break
production from a web page and then sends them to a terminal to fix it, at the exact moment that
costs the most. What this file pins is the CLASS - a new entry in `DEPLOYABLES` fails here until
it has a rollback route or a stated reason it cannot have one - plus every refusal in
`choose_target`, because each of those refusals is an edge case that would otherwise be discovered
in production.

The refusals are the point. The dangerous one is "rollback a rollback": after a rollback the
newest release ships an OLDER release's image, so the naive "go back one" picks the broken build
and rolls FORWARD onto it while telling the operator it went back.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import rollback_now  # noqa: E402
from deploy_status import DEPLOYABLES  # noqa: E402

from prospector.ops import console_api as api  # noqa: E402


def _rel(version: int, image: str, status: str = "complete", in_progress: bool = False) -> dict:
    """One row shaped like `flyctl releases --json` really answers (measured 2026-08-20)."""
    return {"Version": version, "Status": status, "InProgress": in_progress,
            "ImageRef": f"registry.fly.io/app:deployment-{image}",
            "CreatedAt": "2026-08-19T23:10:19Z"}


def _button_for(name: str) -> dict | None:
    """The catalogued button that rolls `name` back, found the way the console finds it."""
    for tool in api.TOOLS:
        if tool["path"] == api._ROLLBACK_NOW and tool["command"].split()[-1] == name:
            return tool
    return None


# --------------------------------------------------------------------------- #
# Coverage: no service falls through the gap
# --------------------------------------------------------------------------- #
def test_every_deployable_has_a_rollback_route_or_a_stated_reason():
    unrouted = [n for n, r in rollback_now.routes().items() if r["kind"] == "unrouted"]
    assert not unrouted, (
        "these services can be deployed but nothing says how to put them back:\n  "
        + "\n  ".join(unrouted)
        + "\n\nAdd them to SERVICES in scripts/rollback_now.py, or to NO_ROLLBACK with the reason."
    )


def test_a_service_with_no_rollback_says_why_in_a_full_sentence():
    for name, why in rollback_now.NO_ROLLBACK.items():
        assert len(why) > 30, f"{name}: 'no rollback' needs a reason an operator can act on"


def test_every_rollback_service_names_the_app_deploy_status_names():
    """One name for one app. Two spellings is how a rollback lands on the wrong machine."""
    by_name = {d["name"]: d for d in DEPLOYABLES}
    for name, svc in rollback_now.SERVICES.items():
        assert name in by_name, f"{name} is not a DEPLOYABLE"
        assert svc["app"] == by_name[name]["app"], (
            f"{name}: rollback targets {svc['app']}, deploy_status watches {by_name[name]['app']}")


def test_every_rollback_config_file_exists_where_flyctl_will_look_for_it():
    """flyctl resolves --config relative to the WORKING DIRECTORY.

    deploy-api.yml carries the scar: from the wrong cwd flyctl logs `Validating --config path
    unset--`, loads no config at all, and the error text never mentions the config.
    """
    for name, svc in rollback_now.SERVICES.items():
        path = ROOT / svc["cwd"] / svc["config"]
        assert path.is_file(), f"{name}: no fly config at {path} (cwd {svc['cwd']})"


def test_every_rollback_says_what_restarts():
    for name, svc in rollback_now.SERVICES.items():
        assert len(svc.get("restarts", "")) > 20, (
            f"{name}: a rollback restarts something, and the operator must be told what")


# --------------------------------------------------------------------------- #
# The refusals
# --------------------------------------------------------------------------- #
def test_no_releases_is_refused():
    target, why = rollback_now.choose_target([])
    assert target is None and "no releases" in why


def test_a_single_release_is_refused():
    target, why = rollback_now.choose_target([_rel(1, "AAA")])
    assert target is None and "only release" in why


def test_a_deploy_in_flight_is_refused():
    """Two deploys racing one app can leave it serving neither image."""
    target, why = rollback_now.choose_target(
        [_rel(3, "CCC", status="running", in_progress=True), _rel(2, "BBB"), _rel(1, "AAA")])
    assert target is None and "in progress" in why


def test_rolling_back_a_rollback_is_refused():
    """The one that would be silent. v3 already ships v1's image, so the last deploy WAS a
    rollback; going back one more lands on v2, the build that was rolled away from."""
    releases = [_rel(3, "AAA"), _rel(2, "BBB"), _rel(1, "AAA")]
    target, why = rollback_now.choose_target(releases)
    assert target is None, "went back onto the image the last rollback escaped"
    assert "was a rollback" in why.lower() and "revert" in why.lower()


def test_the_target_is_the_newest_completed_release_below_the_current_one():
    target, why = rollback_now.choose_target([_rel(3, "CCC"), _rel(2, "BBB"), _rel(1, "AAA")])
    assert why == "" and target["Version"] == 2


def test_a_failed_release_is_never_a_rollback_target():
    """Going back to an image that never finished deploying is not a rollback."""
    target, _ = rollback_now.choose_target(
        [_rel(3, "CCC"), _rel(2, "BBB", status="failed"), _rel(1, "AAA")])
    assert target["Version"] == 1


def test_a_release_with_no_image_is_never_a_target():
    releases = [_rel(3, "CCC"), {"Version": 2, "Status": "complete", "ImageRef": ""}, _rel(1, "AAA")]
    target, _ = rollback_now.choose_target(releases)
    assert target["Version"] == 1


def test_releases_are_read_newest_first_whatever_order_fly_answers_in():
    out = rollback_now.parse_releases(
        '[{"Version":1,"ImageRef":"a"},{"Version":3,"ImageRef":"c"},{"Version":2,"ImageRef":"b"}]')
    assert [r["Version"] for r in out] == [3, 2, 1]


def test_unparseable_release_output_is_no_releases_never_a_guess():
    assert rollback_now.parse_releases("flyctl: error") == []
    assert rollback_now.parse_releases("") == []


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #
def test_the_rollback_command_ships_an_existing_image_and_never_a_build_context():
    cmd = rollback_now.rollback_command("flyctl", "app", "deploy/engine/fly.toml", "img:ref")
    assert cmd[:3] == ["flyctl", "deploy", "--image"] and cmd[3] == "img:ref"
    assert "--config" in cmd and "deploy/engine/fly.toml" in cmd
    assert "." not in cmd, (
        "a positional build context makes this build the console host's WORKING TREE, which is "
        "the opposite of shipping the image that already ran")


def test_the_rollback_command_does_not_override_the_deploy_strategy():
    """The strategy lives in each app's fly.toml. A rollback that used a different one from the
    deploy would be a second, untested code path through production."""
    cmd = rollback_now.rollback_command("flyctl", "app", "c.toml", "img")
    assert "--strategy" not in cmd


def test_a_service_with_no_public_probe_is_unproven_never_passing():
    ok, lines = rollback_now._probe_all("searxng", {"probe": []})
    assert ok is False and "UNPROVEN" in lines[0]


# --------------------------------------------------------------------------- #
# The console
# --------------------------------------------------------------------------- #
def test_every_rollbackable_service_has_a_button_on_the_deploys_page():
    for name in rollback_now.SERVICES:
        tool = _button_for(name)
        assert tool is not None, f"{name} can be rolled back but has no console button"
        assert tool["writes"] and tool["run"] and tool["screen"] == "/deploys"
        assert tool["risk"] == "external", (
            f"{name}: a rollback redeploys a Fly app; no local store snapshot undoes it")
        assert tool["danger"], f"{name}: a rollback button with no danger line"


def test_every_rollback_button_says_a_rollback_does_not_change_main():
    """The third-order effect that bites: the next merge redeploys the code you rolled away from."""
    for name in rollback_now.SERVICES:
        danger = (_button_for(name) or {}).get("danger", "")
        assert "does NOT change main" in danger or "only ever had ONE release" in danger, (
            f"{name}: the button must say a rollback is not a revert")


def test_the_drill_is_a_console_button_and_deploys_nothing():
    drill = [t for t in api.TOOLS
             if t["path"] == api._ROLLBACK_NOW and t["command"].endswith("--drill")]
    assert len(drill) == 1, "the rollback drill must be one button on the console"
    assert drill[0]["writes"] is False, "the drill must not be able to deploy anything"
    assert drill[0]["screen"] == "/deploys"


def test_the_deploys_view_carries_the_rollback_button_for_each_row():
    route = api._rollback_route("engine")
    assert set(route) == {"rollback_tool_id", "rollback_how", "rollback_danger"}
    assert route["rollback_tool_id"] == _button_for("engine")["id"]


def test_a_service_with_no_rollback_tells_the_page_what_does_put_it_back():
    route = api._rollback_route("engine-standby")
    assert route["rollback_tool_id"] is None
    assert "live_checkout" in route["rollback_how"]
