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

import json
import sys
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------------------------
# The refusals a rollback makes before it reaches flyctl at all.
#
# Founder, 2026-08-20: "need to have tests for all edge cases, every conceivable edge case".
# Everything above pins how a TARGET is chosen. These pin what happens when the machine running
# the button is not in a position to choose one - no flyctl, an unreadable app, a name nobody
# knows - because each of those reaches the operator as a message, and a wrong message during an
# outage costs more than the outage.
# --------------------------------------------------------------------------------------------

def test_an_unknown_service_is_refused_and_lists_the_real_ones(capsys):
    assert rollback_now.rollback("stroe-web", check_only=True) == 2
    err = capsys.readouterr().err
    assert "unknown service" in err
    for name in rollback_now.SERVICES:
        assert name in err


def test_a_service_that_cannot_be_rolled_back_is_refused_with_its_stated_reason(capsys):
    name = next(iter(rollback_now.NO_ROLLBACK))
    assert rollback_now.rollback(name, check_only=True) == 2
    err = capsys.readouterr().err
    assert "no image rollback" in err
    assert rollback_now.NO_ROLLBACK[name][:40] in err


def test_no_flyctl_on_the_host_is_refused_not_crashed(monkeypatch, capsys):
    """The console runs under launchd, whose PATH omits /usr/local/bin."""
    monkeypatch.setattr(rollback_now, "find_fly", lambda: None)
    assert rollback_now.rollback("store-web", check_only=True) == 2
    assert "no flyctl on PATH" in capsys.readouterr().err


def test_an_app_flyctl_cannot_read_is_refused_with_flyctls_own_words(monkeypatch, capsys):
    monkeypatch.setattr(rollback_now, "find_fly", lambda: "/usr/local/bin/flyctl")
    monkeypatch.setattr(rollback_now, "_releases", lambda fly, app: ([], "Error: App not found"))
    assert rollback_now.rollback("store-web", check_only=True) == 2
    err = capsys.readouterr().err
    assert "cannot read releases for prospector-store-web" in err
    assert "App not found" in err


def _stub_releases(monkeypatch, rows):
    monkeypatch.setattr(rollback_now, "find_fly", lambda: "/usr/local/bin/flyctl")
    monkeypatch.setattr(rollback_now, "_releases", lambda fly, app: (rows, ""))


def test_check_mode_prints_the_command_and_runs_nothing(monkeypatch, capsys):
    _stub_releases(monkeypatch, [_rel(2, "NEW"), _rel(1, "OLD")])

    def explode(*a, **k):
        raise AssertionError("--check must never invoke flyctl")
    monkeypatch.setattr(rollback_now.subprocess, "run", explode)
    assert rollback_now.rollback("store-web", check_only=True) == 0
    out = capsys.readouterr().out
    assert "deployment-OLD" in out
    assert "nothing was rolled back" in out


def test_a_rollback_that_deploys_but_does_not_answer_is_not_reported_as_success(monkeypatch,
                                                                               capsys):
    """The worst possible lie is "rolled back" while the service is still down."""
    _stub_releases(monkeypatch, [_rel(2, "NEW"), _rel(1, "OLD")])
    monkeypatch.setattr(rollback_now.subprocess, "run",
                        lambda *a, **k: type("P", (), {"returncode": 0})())
    monkeypatch.setattr(rollback_now, "_probe_all", lambda name, svc: (False, ["  FAIL x"]))
    assert rollback_now.rollback("store-web", check_only=False) == 1
    assert "ROLLED BACK, BUT NOT HEALTHY" in capsys.readouterr().err


def test_a_failing_flyctl_returns_its_own_exit_code(monkeypatch, capsys):
    _stub_releases(monkeypatch, [_rel(2, "NEW"), _rel(1, "OLD")])
    monkeypatch.setattr(rollback_now.subprocess, "run",
                        lambda *a, **k: type("P", (), {"returncode": 137})())
    assert rollback_now.rollback("store-web", check_only=False) == 137
    assert "flyctl exited 137" in capsys.readouterr().err


def test_a_successful_rollback_that_answers_its_checks_exits_zero(monkeypatch, capsys):
    _stub_releases(monkeypatch, [_rel(2, "NEW"), _rel(1, "OLD")])
    monkeypatch.setattr(rollback_now.subprocess, "run",
                        lambda *a, **k: type("P", (), {"returncode": 0})())
    monkeypatch.setattr(rollback_now, "_probe_all", lambda name, svc: (True, ["  ok   x"]))
    assert rollback_now.rollback("store-web", check_only=False) == 0
    assert "rolled store-web back to v1" in capsys.readouterr().out


def test_every_refusal_happens_before_flyctl_is_ever_run(monkeypatch):
    """A refusal that has already shelled out is a refusal that already cost something."""
    monkeypatch.setattr(rollback_now, "find_fly", lambda: "/usr/local/bin/flyctl")

    ran = []
    monkeypatch.setattr(rollback_now, "_run", lambda *a, **k: ran.append(a) or
                        type("P", (), {"returncode": 1, "stdout": "", "stderr": "no"})())
    rollback_now.rollback("stroe-web", check_only=True)
    assert ran == []


# --- what `flyctl releases --json` can hand back on a bad day -------------------------------

@pytest.mark.parametrize("text", ["", "not json", "null", '{"Version": 3}', "[]", "   "])
def test_junk_release_output_is_no_releases_never_a_guess(text):
    assert rollback_now.parse_releases(text) == []


def test_a_release_row_with_no_version_sorts_last_and_never_becomes_the_current_one():
    rows = rollback_now.parse_releases(json.dumps([
        {"Status": "complete", "ImageRef": "registry.fly.io/app:deployment-NOVER"},
        _rel(4, "NEW"), _rel(3, "OLD")]))
    assert rows[0]["Version"] == 4
    target, why = rollback_now.choose_target(rows)
    assert target["Version"] == 3, why


def test_duplicate_versions_still_resolve_a_target():
    rows = [_rel(2, "NEW"), _rel(1, "OLD"), _rel(1, "OLD")]
    target, why = rollback_now.choose_target(rows)
    assert target is not None and target["ImageRef"].endswith("OLD"), why


def test_non_dict_rows_are_dropped_rather_than_crashing_the_sort():
    rows = rollback_now.parse_releases(json.dumps([_rel(2, "NEW"), "a string", 7, None,
                                                   _rel(1, "OLD")]))
    assert [r["Version"] for r in rows] == [2, 1]


def test_every_older_release_failed_is_refused_with_the_reason():
    rows = [_rel(3, "NEW"), _rel(2, "MID", status="failed"), _rel(1, "OLD", status="failed")]
    target, why = rollback_now.choose_target(rows)
    assert target is None
    assert "no earlier release completed" in why
