"""The EXECUTION half of the two production buttons: what happens when the CLI misbehaves.

Founder, 2026-08-21: "T gap, deploying and rollback to prod need seriouis edge case testig".

WHAT WAS ALREADY PROVEN AND IS NOT RE-PROVEN HERE. Selection and refusal logic:
tests/unit/test_rollback_is_wired_to_the_console.py holds 41 tests on `choose_target`,
`parse_releases` and the console wiring, and
tests/unit/test_every_service_can_be_deployed_from_the_console.py holds 8 on routing and
dispatch inputs. Those grade the PURE half of both scripts - the half above the
"everything below shells out" line.

WHAT WAS NOT PROVEN, AND IS THE GAP THIS FILE CLOSES. Below that line, both scripts had twelve
`subprocess.run` call sites and NOT ONE was inside a try. Every one of them passes a timeout, so
every one of them could raise. Measured 2026-08-21 by driving each branch with a fake CLI:

  scripts/deploy_now.py:249   `gh auth status` exits non-zero saying nothing  -> IndexError
  scripts/deploy_now.py:257   a workflow named in DEPLOYABLES but not on disk -> FileNotFoundError
  scripts/deploy_now.py:154   `gh run list` returns junk or fails             -> DEPLOYS ANYWAY
  scripts/rollback_now.py:231 the health curl hangs, AFTER flyctl deployed    -> TimeoutExpired
  scripts/rollback_now.py:384 flyctl still deploying at 900s                  -> TimeoutExpired

The first two turn the operator's Deploy button into a Python traceback. The third turns off the
one check that stops the same commit shipping twice. The last two fire at the worst possible
moment - production is already mid-change and the script dies without saying what is live.

The rule this file enforces is one sentence: A COMMAND THAT DOES NOT ANSWER IS AN ANSWER. It is
a refusal or a failed health check, never an exception, because an exception reaches the console
as a stack trace with no statement about whether anything shipped.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import deploy_now  # noqa: E402
import rollback_now  # noqa: E402


def _cp(rc: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, out, err)


def _raise_timeout(cmd, **kw):
    raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))


def _raise_missing(cmd, **kw):
    raise FileNotFoundError(2, "No such file or directory", cmd[0] if cmd else "?")


# --------------------------------------------------------------------------- #
# 1. The funnel. Both scripts route every captured shell-out through their own `_run`,
#    so one guard covers every call site - and this is what pins that guard in place.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mod", [deploy_now, rollback_now], ids=["deploy_now", "rollback_now"])
@pytest.mark.parametrize("boom,rc", [(_raise_timeout, 124), (_raise_missing, 127)],
                         ids=["timeout", "binary missing"])
def test_run_reports_a_command_that_never_answered_instead_of_raising(monkeypatch, mod, boom, rc):
    monkeypatch.setattr(subprocess, "run", boom)
    p = mod._run(["some-cli", "arg"])
    assert p.returncode == rc, (
        f"{mod.__name__}._run must turn this into a non-zero return code. Every caller in that "
        f"file branches on returncode and none of them is inside a try, so an exception here "
        f"travels all the way to the console as a traceback."
    )
    assert p.stderr.strip(), "the reason must survive; a silent refusal is not actionable"
    assert "some-cli" in p.stderr, "the reason must name the command that did not answer"


@pytest.mark.parametrize("mod", [deploy_now, rollback_now], ids=["deploy_now", "rollback_now"])
def test_run_still_passes_a_working_command_straight_through(monkeypatch, mod):
    """The guard must not swallow ordinary failures, which callers already handle."""
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(3, "out", "err"))
    p = mod._run(["x"])
    assert (p.returncode, p.stdout, p.stderr) == (3, "out", "err")


# --------------------------------------------------------------------------- #
# 2. The class, closed mechanically. A shell-out added tomorrow without a guard fails here.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("script", ["scripts/deploy_now.py", "scripts/rollback_now.py"])
def test_every_subprocess_call_is_either_the_guarded_funnel_or_inside_a_try(script):
    """No bare `subprocess.run` anywhere in either production button.

    This is the guard rather than the memory. The five defects above were five instances of ONE
    mistake - shelling out without deciding what happens when the command does not come back -
    and it recurs every time someone adds a call. Two shapes are legal:

      inside `_run`          the funnel, which catches TimeoutExpired and OSError itself
      inside a `try:` block  the two streaming deploys, which cannot use the funnel because they
                             let flyctl and the deploy script write to the operator's terminal
    """
    tree = ast.parse((ROOT / script).read_text(encoding="utf-8"))

    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for child in ast.walk(node):
                guarded.add(id(child))
        if isinstance(node, ast.FunctionDef) and node.name == "_run":
            for child in ast.walk(node):
                guarded.add(id(child))

    bare = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
        and id(node) not in guarded
    ]
    assert not bare, (
        f"{script} shells out at line(s) {bare} with no guard. Every subprocess.run in these two "
        f"files passes a timeout, so every one of them can raise TimeoutExpired, and a missing "
        f"binary raises OSError. Route it through `_run`, or wrap it in a try that says what "
        f"production is doing when the command does not come back."
    )


# --------------------------------------------------------------------------- #
# 3. deploy(): every way the CLI can misbehave, and what the operator is told.
# --------------------------------------------------------------------------- #
def _gh_answering(**overrides):
    """A fake `_run` for deploy_now: authenticated gh, no runs in flight, unless overridden."""
    def fake(cmd, **kw):
        if "auth" in cmd:
            return overrides.get("auth", _cp(0, "Logged in"))
        if "run" in cmd and "list" in cmd:
            return overrides.get("run_list", _cp(0, "[]"))
        if cmd and cmd[0] == "git":
            return overrides.get("git", _cp(0, ""))
        return overrides.get("default", _cp(0, ""))
    return fake


@pytest.mark.parametrize("name,needle", [
    ("does-not-exist", "unknown component"),
    ("engine-standby", "already deployable from the console"),
    ("ci-runner", "deliberately not a one-click deploy"),
])
def test_a_component_with_no_dispatch_route_is_refused_by_name(capsys, name, needle):
    assert deploy_now.deploy(name, True) == 2
    out = capsys.readouterr()
    assert needle in (out.err + out.out)


def test_a_gh_that_exits_without_saying_why_refuses_rather_than_crashing(monkeypatch, capsys):
    """The one that was an IndexError.

    `(auth.stderr or auth.stdout).strip().splitlines()[0]` indexes an empty list the moment gh
    exits non-zero and prints nothing, which is what a killed or sandboxed gh does. The refusal
    crashed instead of refusing.
    """
    monkeypatch.setattr(deploy_now, "find_gh", lambda: "/fake/gh")
    monkeypatch.setattr(deploy_now, "_run", _gh_answering(auth=_cp(1, "", "")))
    assert deploy_now.deploy("engine", True) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and "gh auth status" in err
    assert "exited 1" in err, "with nothing to quote, the refusal must still say what happened"


def test_a_gh_auth_failure_quotes_gh_when_it_does_say_why(monkeypatch, capsys):
    monkeypatch.setattr(deploy_now, "find_gh", lambda: "/fake/gh")
    monkeypatch.setattr(deploy_now, "_run", _gh_answering(auth=_cp(1, "", "You are not logged in")))
    assert deploy_now.deploy("engine", True) == 2
    assert "You are not logged in" in capsys.readouterr().err


def test_a_workflow_named_in_deployables_but_missing_on_disk_is_refused(monkeypatch, capsys):
    """DEPLOYABLES names the workflow; the file lives on disk. Rename one and not the other and
    this button used to raise FileNotFoundError straight through the console."""
    monkeypatch.setattr(deploy_now, "find_gh", lambda: "/fake/gh")
    monkeypatch.setattr(deploy_now, "_run", _gh_answering())
    monkeypatch.setattr(deploy_now, "routes", lambda: {
        "engine": {"kind": "workflow", "workflow": "deploy-nowhere.yml", "what": ""}})
    assert deploy_now.deploy("engine", True) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and "deploy-nowhere.yml" in err
    assert "deploy_status.py" in err, "the refusal must name where the two lists drift apart"


@pytest.mark.parametrize("run_list,why", [
    (_cp(0, "<html>502 Bad Gateway</html>"), "did not return JSON"),
    (_cp(1, "", "API rate limit exceeded"), "API rate limit exceeded"),
    (_cp(0, '{"not": "a list"}'), "not a list"),
], ids=["junk", "gh failed", "wrong json shape"])
def test_an_unknowable_in_flight_state_refuses_rather_than_deploying(monkeypatch, capsys,
                                                                    run_list, why):
    """The fail-OPEN one, and the only fix here that can block a deploy that used to work.

    `_in_flight` returned `[]` for both "no run is in flight" and "GitHub did not tell me", so a
    rate limit silently disabled the check that stops a second dispatch queueing behind the first
    and shipping the same commit twice. A check a network hiccup turns off is not a check.

    The cost of failing closed is close to zero: if `gh run list` cannot reach the API then
    `gh workflow run` almost certainly cannot either.
    """
    monkeypatch.setattr(deploy_now, "find_gh", lambda: "/fake/gh")
    monkeypatch.setattr(deploy_now, "_run", _gh_answering(run_list=run_list))
    assert deploy_now.deploy("engine", False) == 2
    err = capsys.readouterr().err
    assert "cannot tell whether" in err and why in err
    assert "Retry" in err, "a refusal the operator can clear must say how to clear it"


def test_a_run_already_in_flight_is_still_refused_with_its_url(monkeypatch, capsys):
    live = '[{"status":"in_progress","url":"https://x/run/1","headBranch":"main"}]'
    monkeypatch.setattr(deploy_now, "find_gh", lambda: "/fake/gh")
    monkeypatch.setattr(deploy_now, "_run", _gh_answering(run_list=_cp(0, live)))
    assert deploy_now.deploy("engine", False) == 2
    assert "https://x/run/1" in capsys.readouterr().err


def test_no_refusal_ever_reaches_the_dispatch(monkeypatch):
    """Every branch above must return before `gh workflow run` executes.

    A refusal that prints and ships is worse than no refusal, because the operator believes
    nothing happened.
    """
    dispatched: list[list[str]] = []

    def recording(cmd, **kw):
        if "workflow" in cmd and "run" in cmd:
            dispatched.append(cmd)
            return _cp(0, "")
        return _gh_answering(auth=_cp(1, "", ""))(cmd, **kw)

    monkeypatch.setattr(deploy_now, "find_gh", lambda: "/fake/gh")
    monkeypatch.setattr(deploy_now, "_run", recording)
    assert deploy_now.deploy("engine", False) == 2
    assert dispatched == [], f"a refused deploy still ran {dispatched}"


# --------------------------------------------------------------------------- #
# 4. The script route, which builds THIS WORKING TREE and so is the one that can ship
#    another session's half-finished edit into production.
# --------------------------------------------------------------------------- #
def test_a_modified_shipping_path_refuses_and_names_the_file(monkeypatch, capsys):
    monkeypatch.setattr(deploy_now, "_run",
                        lambda cmd, **kw: _cp(0, " M deploy/searxng/fly.toml\n"))
    assert deploy_now.deploy("searxng", True) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and "deploy/searxng/fly.toml" in err


def test_a_tree_git_cannot_read_refuses_without_inventing_a_modified_file(monkeypatch, capsys):
    """Both answers refuse, so this is about the MESSAGE.

    A failed `git status` used to be reported as the string "git status failed: ..." inside the
    list of modified files, so the refusal told the operator their shipping paths were modified
    and then named a file that does not exist. They go looking for an edit nobody made.
    """
    monkeypatch.setattr(deploy_now, "_run",
                        lambda cmd, **kw: _cp(128, "", "fatal: not a git repository"))
    assert deploy_now.deploy("searxng", True) == 2
    err = capsys.readouterr().err
    assert "cannot say whether" in err
    assert "not a git repository" in err
    assert "these shipping paths are modified" not in err, (
        "an unreadable tree is not a dirty tree; saying so sends the operator hunting a "
        "modification that was never made"
    )


def test_a_local_build_that_outlives_its_timeout_is_not_reported_as_a_failure(monkeypatch,
                                                                             capsys):
    """The build was still running when we stopped watching, so it may yet ship.

    Calling that a failure sends the operator to redeploy on top of a deploy still in flight.
    """
    monkeypatch.setattr(deploy_now, "_run", lambda cmd, **kw: _cp(0, ""))
    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    rc = deploy_now.deploy("searxng", False)
    err = capsys.readouterr().err
    assert rc == 1
    assert "may" in err and "still be deploying" in err
    assert "Do NOT redeploy" in err


# --------------------------------------------------------------------------- #
# 5. rollback health probes. These run AFTER flyctl has already changed production, which is
#    what makes an exception here the worst-timed one in the estate.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("check", [
    {"url": "https://x", "expect": "200", "means": "it serves"},
    {"url": "https://x", "expect_body": '"mode":"live"', "means": "the money rail is live"},
], ids=["status probe", "body probe"])
@pytest.mark.parametrize("boom", [_raise_timeout, _raise_missing], ids=["hangs", "no curl"])
def test_a_probe_that_never_ran_fails_and_says_it_never_ran(monkeypatch, check, boom):
    monkeypatch.setattr(subprocess, "run", boom)
    ok, line = rollback_now._probe_one(check)
    assert ok is False, "a probe that did not run must never read as a pass"
    assert "curl" in line, (
        "the line must say the probe never ran. Without it a hung curl reads as "
        "'GET <url> ->  (want 200)', an empty status code that looks like a server "
        "answering nothing rather than a check that never happened."
    )


def test_a_probe_that_answers_correctly_still_passes(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0, "200"))
    assert rollback_now._probe_one({"url": "https://x", "expect": "200"})[0] is True
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0, '{"mode":"live"}'))
    assert rollback_now._probe_one(
        {"url": "https://x", "expect_body": '"mode":"live"'})[0] is True


def test_one_failing_check_fails_the_whole_service(monkeypatch):
    """`_probe_all` is an AND. A service that serves its homepage but whose money rail answers
    test-mode is not healthy, and must never be reported as rolled back and fine."""
    answers = iter([_cp(0, "200"), _cp(0, '{"mode":"test"}')])
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: next(answers))
    ok, lines = rollback_now._probe_all("store-api", rollback_now.SERVICES["store-api"])
    assert ok is False
    assert any(line.startswith("  FAIL") for line in lines)


# --------------------------------------------------------------------------- #
# 6. The rollback itself: flyctl misbehaving while production is mid-change.
# --------------------------------------------------------------------------- #
def _releases_with_a_target(monkeypatch):
    rows = [
        {"Version": 2, "Status": "complete", "ImageRef": "img:new", "InProgress": False},
        {"Version": 1, "Status": "complete", "ImageRef": "img:old", "InProgress": False},
    ]
    monkeypatch.setattr(rollback_now, "find_fly", lambda: "/fake/flyctl")
    monkeypatch.setattr(rollback_now, "_releases", lambda fly, app: (rows, ""))


def test_a_rollback_still_running_at_its_timeout_says_production_is_between_two_images(
        monkeypatch, capsys):
    """The single most dangerous moment in either script.

    flyctl was still deploying the previous image when we stopped watching, so nobody knows which
    image production is serving. Reporting either success or failure here is a lie, and the
    dangerous one is failure: it invites a second rollback on top of a running one.
    """
    _releases_with_a_target(monkeypatch)
    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    rc = rollback_now.rollback("engine", False)
    err = capsys.readouterr().err
    assert rc == 1
    assert "TIMED OUT" in err
    assert "v2" in err and "v1" in err, "it must name both images production is between"
    assert "Do NOT run this again" in err
    assert "flyctl releases -a prospector-engine" in err, (
        "the operator needs the command that says what is actually live"
    )


def test_a_rollback_that_deploys_but_does_not_answer_is_never_reported_as_done(monkeypatch,
                                                                              capsys):
    """flyctl exits 0, health check red. Saying "rolled back" here is the worst possible lie
    because the operator stops looking."""
    _releases_with_a_target(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0))
    monkeypatch.setattr(rollback_now, "_probe_all", lambda n, s: (False, ["  FAIL GET / -> 502"]))
    assert rollback_now.rollback("engine", False) == 1
    assert "NOT HEALTHY" in capsys.readouterr().err


def test_a_missing_flyctl_at_the_moment_of_the_rollback_is_refused_not_crashed(monkeypatch,
                                                                              capsys):
    _releases_with_a_target(monkeypatch)
    monkeypatch.setattr(subprocess, "run", _raise_missing)
    assert rollback_now.rollback("engine", False) == 2
    assert "cannot run" in capsys.readouterr().err


def test_a_rollback_that_deploys_and_answers_reports_the_version_it_landed_on(monkeypatch,
                                                                             capsys):
    _releases_with_a_target(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0))
    monkeypatch.setattr(rollback_now, "_probe_all", lambda n, s: (True, ["  ok   GET / -> 200"]))
    assert rollback_now.rollback("engine", False) == 0
    assert "rolled engine back to v1" in capsys.readouterr().out


def test_flyctl_failing_to_read_releases_refuses_before_anything_is_deployed(monkeypatch,
                                                                            capsys):
    deployed: list = []
    monkeypatch.setattr(rollback_now, "find_fly", lambda: "/fake/flyctl")
    monkeypatch.setattr(rollback_now, "_releases",
                        lambda fly, app: ([], "flyctl did not answer within 120s"))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: deployed.append(cmd) or _cp(0))
    assert rollback_now.rollback("engine", False) == 2
    assert deployed == [], "a rollback that could not read releases must not deploy anything"
    assert "did not answer within 120s" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# 7. The concurrent rollback. Found 2026-08-21 while reading the two scripts against each other:
#    .github/workflows/deploy-engine.yml ends with a step that runs `python3
#    scripts/rollback_now.py engine` on the runner when a deploy does not answer, and the console
#    offers the operator the same button. Neither script took any lock. So the likeliest moment
#    for a human to press Rollback - a deploy that just went wrong - is the exact moment CI is
#    already rolling the same one-machine, strategy=`immediate` app back by itself.
#
#    `choose_target`'s InProgress guard cannot close it. That reads FLY releases, and at the
#    instant both start neither has created a release, so both see InProgress False and proceed.
#    The check that works has to ask GitHub, which is why `_ci_deploy_in_flight` exists.
# --------------------------------------------------------------------------- #

def _fake_gh(monkeypatch, result):
    monkeypatch.setattr(rollback_now.shutil, "which", lambda p: "/fake/gh")
    monkeypatch.setattr(rollback_now, "_run", lambda cmd, **kw: result)


@pytest.mark.parametrize("name,workflow", [("engine", "deploy-engine.yml"),
                                           ("store-web", "deploy-web.yml"),
                                           ("store-api", "deploy-api.yml")])
def test_the_workflow_to_watch_is_read_from_deployables_not_retyped(name, workflow):
    """A second copy of this mapping is a second thing to forget when a workflow is renamed."""
    assert rollback_now._deploy_workflow(name) == workflow


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting", "requested", "pending"])
def test_a_ci_deploy_that_has_not_finished_blocks_the_rollback(monkeypatch, status):
    _fake_gh(monkeypatch, _cp(0, f'[{{"status":"{status}","url":"https://gh/run/9",'
                                 f'"headBranch":"main"}}]'))
    blocker, unknown = rollback_now._ci_deploy_in_flight("engine")
    assert "https://gh/run/9" in blocker, "the operator needs the run, not just the word no"
    assert unknown == ""


def test_a_finished_ci_run_does_not_block_anything(monkeypatch):
    _fake_gh(monkeypatch, _cp(0, '[{"status":"completed","url":"u","headBranch":"main"}]'))
    assert rollback_now._ci_deploy_in_flight("engine") == ("", "")


@pytest.mark.parametrize("name", ["searxng", "ci-runner", "engine-standby"])
def test_a_service_with_no_deploy_workflow_has_nothing_to_race_with(monkeypatch, name):
    """No workflow deploys these, so there is no CI run that could be deploying them."""
    monkeypatch.setattr(rollback_now, "_run",
                        lambda *a, **k: pytest.fail("must not ask gh about a service CI cannot "
                                                    "deploy"))
    assert rollback_now._ci_deploy_in_flight(name) == ("", "")


@pytest.mark.parametrize("result,fragment", [
    (_cp(1, "", "gh: not logged in"), "not logged in"),
    (_cp(0, "not json"), "did not return JSON"),
    (_cp(0, '{"status":"queued"}'), "not a list"),
    (_cp(rollback_now.RC_TIMEOUT, "", "gh did not answer within 60s"), "did not answer"),
])
def test_a_check_github_cannot_answer_says_so_and_does_not_block(monkeypatch, result, fragment):
    """UNKNOWN IS NOT A BLOCKER HERE, and that is the one asymmetry in this file.

    Everywhere else in these two scripts, a command that does not answer produces a refusal. This
    one produces a note. The reason is where the button lives: the ops console runs inside the
    prospector-engine image, which has flyctl and no `gh` at all - so failing closed would mean
    the console cannot roll production back during precisely the incident it exists for. LAW 1,
    restoring service, outranks closing a race. The operator is told, and decides.
    """
    _fake_gh(monkeypatch, result)
    blocker, unknown = rollback_now._ci_deploy_in_flight("engine")
    assert blocker == "", "a check that could not run must never read as 'CI is deploying'"
    assert fragment in unknown


def test_no_gh_on_this_host_is_a_note_not_a_refusal(monkeypatch):
    monkeypatch.setattr(rollback_now.shutil, "which", lambda p: None)
    blocker, unknown = rollback_now._ci_deploy_in_flight("engine")
    assert blocker == ""
    assert "no `gh` on this host" in unknown


def test_a_rollback_refuses_while_ci_is_deploying_the_same_service(monkeypatch, capsys):
    """The whole point: two `flyctl deploy --image` at one app, and nothing deploys."""
    _releases_with_a_target(monkeypatch)
    deployed: list = []
    monkeypatch.setattr(rollback_now, "_ci_deploy_in_flight",
                        lambda name: ("deploy-engine.yml has a run in_progress on main: "
                                      "https://gh/run/9", ""))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: deployed.append(cmd) or _cp(0))
    assert rollback_now.rollback("engine", False) == 2
    assert deployed == [], "refused, so nothing may have been deployed"
    assert "https://gh/run/9" in capsys.readouterr().err


def test_force_rolls_back_anyway_and_says_it_did(monkeypatch, capsys):
    """An operator watching a genuinely stuck CI run must not be locked out of production."""
    _releases_with_a_target(monkeypatch)
    monkeypatch.setattr(rollback_now, "_ci_deploy_in_flight", lambda name: ("run 9 in_progress", ""))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0))
    monkeypatch.setattr(rollback_now, "_probe_all", lambda n, s: (True, ["  ok   x"]))
    assert rollback_now.rollback("engine", False, force=True) == 0
    assert "--force: proceeding while run 9 in_progress" in capsys.readouterr().out


def test_the_race_check_runs_before_flyctl_every_time(monkeypatch):
    """Fails if anyone removes the call, or moves it below the deploy where it proves nothing."""
    _releases_with_a_target(monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(rollback_now, "_ci_deploy_in_flight",
                        lambda name: order.append("asked-github") or ("", ""))
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: order.append("deployed") or _cp(0))
    monkeypatch.setattr(rollback_now, "_probe_all", lambda n, s: (True, ["  ok   x"]))
    assert rollback_now.rollback("engine", False) == 0
    assert order == ["asked-github", "deployed"]


def test_check_mode_asks_nobody_anything(monkeypatch):
    """--check is a preflight the console runs to draw the button; it must stay cheap and silent.

    It reads flyctl releases and stops. Adding a GitHub round-trip here would put a network call
    on every page render, and the race it guards cannot happen to a command that deploys nothing.
    """
    _releases_with_a_target(monkeypatch)
    monkeypatch.setattr(rollback_now, "_ci_deploy_in_flight",
                        lambda name: pytest.fail("--check must not ask GitHub anything"))
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: pytest.fail("--check must invoke nothing"))
    assert rollback_now.rollback("engine", check_only=True) == 0
