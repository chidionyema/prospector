"""The reconciler must heal a real drift and refuse everything else.

WHAT IT IS FOR. Production could run a commit main has already reverted, and nothing in the
estate would have said so: `main-green-guard.yml` reverts with GITHUB_TOKEN, which starts no
workflow runs, and a deploy that never happens leaves no failing run for an alert to fire on.
`scripts/deploy_reconcile.py` is the only thing here that can see an action that did not happen.

WHAT THESE TESTS PIN. The decision table, and specifically the four cases where the right answer
is to do NOTHING. A reconciler that deploys when it should wait is worse than no reconciler: it
ships ungraded code, it races a running release, and — the case that pays for the storm brake —
it can spend money on a Fly build every hour forever on a drift no deploy can close.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy_reconcile.py"
WORKFLOW = ROOT / ".github" / "workflows" / "production-runs-main.yml"

MAIN = "a" * 40
OLD = "b" * 40


def _load():
    """Load the module by path. `scripts/` is not a package, and the real module reaches for
    `gh`, `fly` and the network the moment any of its functions run."""
    spec = importlib.util.spec_from_file_location("deploy_reconcile", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def raw():
    """The module with NOTHING stubbed but `run`.

    The `mod` fixture below stubs `dispatch_storm` itself, so a test that calls it through `mod`
    grades the stub and passes whatever the real brake does. That mistake was live in this file
    for one commit; it is why these two fixtures are separate.
    """
    return _load()


@pytest.fixture()
def mod(monkeypatch):
    """The module with every door to the outside world shut, for the decision-table tests."""
    m = _load()

    calls: dict[str, int] = {"dispatch": 0}
    monkeypatch.setattr(m, "point_live_checkout_at_this_checkout", lambda: str(ROOT))
    monkeypatch.setattr(m, "main_sha", lambda: MAIN)
    monkeypatch.setattr(m, "ships_a_change", lambda live, target: (True, "shipped file changed"))
    monkeypatch.setattr(m, "deploy_in_flight", lambda: False)
    monkeypatch.setattr(m, "dispatch_storm", lambda: (False, ""))
    monkeypatch.setattr(m.lc, "deployed_commit", lambda: (OLD, "test"))
    monkeypatch.setattr(m.lc, "ci_verdict", lambda sha: ("pass", "test"))
    monkeypatch.setattr(m, "serving_side", lambda: ("fly", "test"))
    monkeypatch.setattr(m, "staged_secrets", lambda: ([], "test"))

    def _dispatch():
        calls["dispatch"] += 1
        return True, ""

    monkeypatch.setattr(m, "dispatch", _dispatch)
    # Anything not stubbed above must never reach a real command.
    monkeypatch.setattr(m, "run", lambda *a, **k: pytest.fail(f"unstubbed command: {a}"))
    m.calls = calls
    return m


def test_a_real_drift_on_a_green_main_is_deployed(mod):
    assert mod.reconcile(apply=True) == 0
    assert mod.calls["dispatch"] == 1


def test_production_already_on_main_does_nothing(mod, monkeypatch):
    monkeypatch.setattr(mod.lc, "deployed_commit", lambda: (MAIN, "test"))
    assert mod.reconcile(apply=True) == 0
    assert mod.calls["dispatch"] == 0


def test_a_dirty_stamp_still_matches_its_commit(mod, monkeypatch):
    """The build appends `-dirty` when the tree it shipped was not clean. The commit in front of
    it is still the commit; comparing the raw string reports a permanent drift and deploys on
    every single cycle."""
    monkeypatch.setattr(mod.lc, "deployed_commit", lambda: (f"{MAIN}-dirty", "test"))
    assert mod.reconcile(apply=True) == 0
    assert mod.calls["dispatch"] == 0


def test_an_unreadable_image_never_deploys(mod, monkeypatch):
    """"I could not tell" must never be handled as "it is fine", and must not be handled as a
    drift either — a deploy decided on a missing measurement is a guess."""
    monkeypatch.setattr(mod.lc, "deployed_commit", lambda: ("", "fly ssh failed"))
    assert mod.reconcile(apply=True) == 1
    assert mod.calls["dispatch"] == 0


def test_main_that_cannot_be_read_never_deploys(mod, monkeypatch):
    monkeypatch.setattr(mod, "main_sha", lambda: "")
    assert mod.reconcile(apply=True) == 1
    assert mod.calls["dispatch"] == 0


def test_a_docs_only_gap_is_not_a_drift(mod, monkeypatch):
    """Every docs merge moved the old "N commits behind" number, and an alarm that is usually
    wrong is one that gets ignored. It also costs a paid Fly build each time."""
    monkeypatch.setattr(mod, "ships_a_change", lambda live, target: (False, "docs only"))
    assert mod.reconcile(apply=True) == 0
    assert mod.calls["dispatch"] == 0


@pytest.mark.parametrize("verdict", ["fail", "none", "unknown"])
def test_an_ungraded_main_is_never_shipped(mod, monkeypatch, verdict):
    """"none" is a commit nobody ever tested — the shape of the cancelled-by-the-next-merge case
    — and it must be refused as hard as an outright failure."""
    monkeypatch.setattr(mod.lc, "ci_verdict", lambda sha: (verdict, "test"))
    assert mod.reconcile(apply=True) == 1
    assert mod.calls["dispatch"] == 0


def test_a_pending_main_waits_quietly(mod, monkeypatch):
    """Pending is not a problem, it is a deploy that has not happened yet. Exiting nonzero here
    would open a drift issue on every ordinary merge."""
    monkeypatch.setattr(mod.lc, "ci_verdict", lambda sha: ("pending", "still in_progress"))
    assert mod.reconcile(apply=True) == 0
    assert mod.calls["dispatch"] == 0


def test_a_running_deploy_is_not_raced(mod, monkeypatch):
    monkeypatch.setattr(mod, "deploy_in_flight", lambda: True)
    assert mod.reconcile(apply=True) == 0
    assert mod.calls["dispatch"] == 0


def test_the_storm_brake_stops_a_deploy_loop(mod, monkeypatch):
    """If the image stops carrying /app/GIT_SHA the drift can never close, and deploying is then
    the wrong answer once an hour, forever, each one a paid build."""
    monkeypatch.setattr(mod, "dispatch_storm", lambda: (True, "3 deploys in 6h"))
    assert mod.reconcile(apply=True) == 1
    assert mod.calls["dispatch"] == 0


def test_report_mode_never_dispatches(mod):
    assert mod.reconcile(apply=False) == 1
    assert mod.calls["dispatch"] == 0


def test_a_failed_dispatch_is_reported_not_swallowed(mod, monkeypatch):
    monkeypatch.setattr(mod, "dispatch", lambda: (False, "HTTP 403"))
    assert mod.reconcile(apply=True) == 1


def test_the_storm_brake_counts_only_recent_runs(raw, monkeypatch):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fresh = [{"createdAt": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")}] * 3
    stale = [{"createdAt": (now - timedelta(days=3)).isoformat().replace("+00:00", "Z")}] * 9
    import json as _json

    monkeypatch.setattr(raw, "run", lambda *a, **k: (0, _json.dumps(stale)))
    assert raw.dispatch_storm()[0] is False, "old deploys must not brake a fresh drift"
    monkeypatch.setattr(raw, "run", lambda *a, **k: (0, _json.dumps(fresh + stale)))
    assert raw.dispatch_storm()[0] is True


def test_the_brake_fails_open_on_a_broken_listing(raw, monkeypatch):
    """A brake that engages because `gh` errored would block every deploy this thing exists to
    make. Failing open leaves the other refusals in place."""
    monkeypatch.setattr(raw, "run", lambda *a, **k: (1, "gh: not found"))
    assert raw.dispatch_storm()[0] is False
    monkeypatch.setattr(raw, "run", lambda *a, **k: (0, "not json"))
    assert raw.dispatch_storm()[0] is False


def test_the_deploy_path_filter_is_never_copied_into_this_script():
    """`live_checkout._deployed_changes` reads the filter out of deploy-engine.yml on origin/main.
    A second copy drifts silently in the one direction that matters — production graded current
    while a real change sits unshipped."""
    text = SCRIPT.read_text()
    assert "_deployed_changes" in text, (
        "the reconciler no longer reuses live_checkout's filter, so it is deciding what "
        "production ships from some other list")
    for pattern in ("prospector/**", "deploy/engine/**", "store_platform/src/Ops.Console/**"):
        assert pattern not in text, (
            f"{pattern} is copied into deploy_reconcile.py. The filter has one home, in "
            "deploy-engine.yml, and one reader, in live_checkout._deployed_changes.")


# --------------------------------------------------------------------------------------------
# the workflow that runs it


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _on(doc: dict) -> dict:
    """`on:` is the YAML 1.1 boolean true, so PyYAML keys it as True, not "on"."""
    return doc.get(True, doc.get("on")) or {}


def _job() -> dict:
    return _doc()["jobs"]["reconcile"]


def test_it_actually_runs_on_a_clock():
    on = _on(_doc())
    assert on.get("schedule"), "no schedule, so nothing ever asks the question"
    assert "workflow_dispatch" in on, "no way to run it by hand when production looks wrong"


def test_it_runs_when_ci_finishes_on_main():
    """The moment a drift can first be healed is the moment CI concludes green on main — which
    is exactly the case main-green-guard.yml leaves behind after a revert."""
    wr = _on(_doc()).get("workflow_run") or {}
    assert "CI" in (wr.get("workflows") or []), "not wired to CI finishing"
    assert "main" in (wr.get("branches") or []), "not restricted to main"


def test_the_alarm_hangs_off_the_failure_of_the_check_itself():
    """The class this avoids: a reporting step attached to a job or condition narrower than the
    thing it reports on. It never fails, it is simply never reached, and every instrument still
    reads green (tests/unit/test_an_alarm_must_run_when_the_thing_it_alarms_on_fails.py)."""
    steps = _job()["steps"]
    alarms = [s for s in steps if "issues.create({" in yaml.dump(s)]
    assert alarms, "nothing opens an issue when production cannot be reconciled"
    for step in alarms:
        assert step.get("if") == "failure()", (
            f"the alarm step {step.get('name')!r} is guarded by {step.get('if')!r}. Anything "
            "narrower than failure() will not fire on the case it exists to report.")


def test_it_can_dispatch_and_can_speak(_=None):
    perms = _doc()["permissions"]
    assert perms.get("actions") == "write", "cannot dispatch the deploy without actions: write"
    assert perms.get("issues") == "write", "cannot open the drift issue without issues: write"
    assert perms.get("contents") == "read", "a reconciler must never be able to push"


def test_it_clones_deep_enough_to_answer_the_question():
    """The shipped-paths diff needs the DEPLOYED commit in the object store. A shallow clone does
    not have it, so every drift would read as unanswerable and deploy."""
    checkout = next(s for s in _job()["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["ref"] == "main"


def test_two_reconcilers_never_race():
    conc = _doc()["concurrency"]
    assert conc["group"] == "production-runs-main"
    assert conc["cancel-in-progress"] is False


def test_the_workflow_it_dispatches_exists():
    """The dispatch target is a string, and a renamed workflow would fail once an hour in a place
    nobody reads."""
    assert (ROOT / ".github" / "workflows" / _load().DEPLOY_WORKFLOW).exists()


# --- the two refusals a peer review found on 2026-08-21 ------------------------------------
# Both are about a deploy doing something other than shipping the commit I asked it to ship.


def test_a_staged_secret_stops_the_deploy(mod, monkeypatch):
    """A Fly deploy APPLIES staged secrets. Without this the robot converts "somebody staged a
    credential" into "it is live in production", hourly, with nobody in the path."""
    monkeypatch.setattr(mod, "staged_secrets", lambda: (["TELEGRAM_BOT_TOKEN"], "1 waiting"))
    assert mod.reconcile(apply=True) == 1
    assert mod.calls["dispatch"] == 0


def test_an_unreadable_secret_list_stops_the_deploy(mod, monkeypatch):
    """flyctl is installed and the token is in the step env, so a failure here is a fault. The
    safe direction for something irreversible is to stop."""
    monkeypatch.setattr(mod, "staged_secrets", lambda: (None, "flyctl said no"))
    assert mod.reconcile(apply=True) == 1
    assert mod.calls["dispatch"] == 0


def test_a_serving_side_that_is_not_fly_stops_the_deploy(mod, monkeypatch):
    """AUTOFAILOVER is armed, so this can move with no human. Deploying the side that is not
    serving restarts four processes on a box nobody is using."""
    monkeypatch.setattr(mod, "serving_side", lambda: ("other", "ACTIVE says laptop"))
    assert mod.reconcile(apply=True) == 1
    assert mod.calls["dispatch"] == 0


def test_an_unknown_serving_side_does_NOT_stop_the_deploy(mod, monkeypatch):
    """The opposite direction from the secrets check, deliberately. The marker lives in a home
    directory on the laptop and can never exist on a GitHub runner, so refusing on absence
    would make this robot inert in the only place it runs."""
    monkeypatch.setattr(mod, "serving_side", lambda: ("unknown", "no marker here"))
    assert mod.reconcile(apply=True) == 0
    assert mod.calls["dispatch"] == 1


def test_the_marker_is_read_from_the_same_place_engine_failover_writes_it(raw, monkeypatch, tmp_path):
    monkeypatch.setattr(raw, "CTRL", tmp_path)
    assert raw.serving_side()[0] == "unknown"          # absent
    (tmp_path / "ACTIVE").write_text("  fly\n")
    assert raw.serving_side()[0] == "fly"              # whitespace is not a side
    (tmp_path / "ACTIVE").write_text("laptop\n")
    assert raw.serving_side()[0] == "other"
    (tmp_path / "ACTIVE").write_text("")
    assert raw.serving_side()[0] == "unknown"          # empty is not a side either


def test_the_secret_check_reads_the_status_column(raw, monkeypatch):
    """Pins the shape `fly secrets list --json` actually returns, measured 2026-08-21:
    a list of {"name", "digest", "status"}, status "Deployed" once it is live."""
    payload = ('[{"name": "A", "digest": "x", "status": "Deployed"},'
               ' {"name": "B", "digest": "y", "status": "Staged"}]')
    monkeypatch.setattr(raw, "run", lambda *a, **k: (0, payload))
    pending, detail = raw.staged_secrets()
    assert pending == ["B"]
    assert "2 on the app" in detail

    monkeypatch.setattr(raw, "run", lambda *a, **k: (1, "no access token"))
    assert raw.staged_secrets()[0] is None
    monkeypatch.setattr(raw, "run", lambda *a, **k: (0, "not json"))
    assert raw.staged_secrets()[0] is None


# --------------------------------------------------------------------------------------------
# what the step tells the workflow it did


def _outcome_of(mod, tmp_path, monkeypatch, *, apply: bool = True) -> str:
    """Run the reconciler with a GITHUB_OUTPUT file and return what it wrote there."""
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    mod.reconcile(apply=apply)
    if not out.exists():
        return ""
    written = [ln for ln in out.read_text().splitlines() if ln.startswith("outcome=")]
    assert len(written) <= 1, f"the step spoke more than once: {written}"
    return written[0].split("=", 1)[1] if written else ""


def test_a_dispatch_is_not_reported_as_ok(mod, tmp_path, monkeypatch):
    """THE DEFECT THIS CLOSES. `reconcile` exits 0 for five different reasons and only two of
    them mean production matches main. The closer was gated on `if: success()`, so on the three
    that do not — waiting for CI, a deploy already running, and this one, a deploy only just
    dispatched — it commented "Production matches `main` again" and closed the drift issue.

    A machine writing a false statement into the issue tracker is worse than the drift it was
    hired to report: it is the same class as the alarm the header of deploy_reconcile.py exists
    to prevent, every instrument reading green while production drifts.
    """
    assert _outcome_of(mod, tmp_path, monkeypatch) == "dispatched"
    assert mod.calls["dispatch"] == 1


def test_production_on_main_reports_ok(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod.lc, "deployed_commit", lambda: (MAIN, "test"))
    assert _outcome_of(mod, tmp_path, monkeypatch) == "ok"


def test_a_gap_that_ships_nothing_reports_ok(mod, tmp_path, monkeypatch):
    """The second true OK: production is behind main only by commits it does not ship."""
    monkeypatch.setattr(mod, "ships_a_change", lambda live, target: (False, "docs only"))
    assert _outcome_of(mod, tmp_path, monkeypatch) == "ok"


def test_waiting_for_ci_is_not_ok(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod.lc, "ci_verdict", lambda sha: ("pending", "still running"))
    assert _outcome_of(mod, tmp_path, monkeypatch) == "waiting"
    assert mod.calls["dispatch"] == 0


def test_a_deploy_already_running_is_not_ok(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "deploy_in_flight", lambda: True)
    assert _outcome_of(mod, tmp_path, monkeypatch) == "waiting"
    assert mod.calls["dispatch"] == 0


def test_it_says_nothing_when_nobody_is_listening(mod, monkeypatch):
    """A laptop run has no GITHUB_OUTPUT and must behave exactly as it did before this change.

    An operator running this by hand to answer "is production on main?" is the most common way
    it is used, and it is the one environment CI can never exercise.
    """
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert mod.reconcile(apply=True) == 0
    assert mod.calls["dispatch"] == 1, "the outcome report changed what the reconciler DID"
    mod._outcome("ok")  # the helper itself, with nowhere to write: silent, not an exception


def test_a_report_that_cannot_be_filed_does_not_fail_the_run(mod, monkeypatch, tmp_path):
    """GITHUB_OUTPUT pointing somewhere unwritable is a broken runner, not a broken production.
    Turning that into a failure would open a drift issue about a drift that does not exist."""
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "no-such-dir" / "out"))
    assert mod.reconcile(apply=True) == 0


def test_the_closer_is_gated_on_the_outcome_not_on_the_exit_code():
    """The workflow half of the same defect. `success()` is true on all five exits."""
    steps = _job()["steps"]
    closers = [s for s in steps if "issues.update({" in yaml.dump(s)
               or "state: 'closed'" in yaml.dump(s) or 'state: "closed"' in yaml.dump(s)]
    assert closers, "nothing ever closes the drift issue, so it would stay open forever"
    for step in closers:
        cond = step.get("if") or ""
        assert "outputs.outcome == 'ok'" in cond, (
            f"the closer {step.get('name')!r} is guarded by {cond!r}. `success()` is true on all "
            "five zero exits, three of which mean production has NOT moved.")


def test_the_step_that_produces_the_outcome_is_identified():
    """`steps.<id>.outputs` needs the id. Without it the condition is silently always false and
    the issue never closes — the failure mode is the mirror of the one above, and just as quiet."""
    steps = _job()["steps"]
    ids = {s.get("id") for s in steps}
    for step in steps:
        cond = step.get("if") or ""
        if "steps." in cond and "outputs.outcome" in cond:
            wanted = cond.split("steps.", 1)[1].split(".", 1)[0]
            assert wanted in ids, (
                f"{cond!r} names step id {wanted!r}, which no step in this job has. The "
                "condition is then always false and the drift issue is never closed.")
