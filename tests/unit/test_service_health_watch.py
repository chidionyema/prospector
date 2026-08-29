"""Every edge case of the rail that notices production is down.

Founder, 2026-08-20: "needs to be absolutely rock solid and bulletproof, rollback also, verified
with automated tests and a drill function in ops and realtime notifying", then: "need to have
tests for all edge cases, every conceivable edge case".

The monitor is the feedback half of the Deploy and Roll back buttons. Its failure modes are worse
than being absent, so each one is pinned here:

  * accusing a live service because the MONITOR broke (no curl, a probe that raised) - that pages
    the founder about production every five minutes for a packaging bug,
  * calling a service healthy when nothing measured it (searxng has no public route),
  * paging on a single transient blip, or on the same outage forever,
  * never clearing, so the next real outage is indistinguishable from the last one's residue,
  * losing its own state file and either crashing or re-paging.

Nothing here touches the network and nothing here can emit a real alert: every test drives
`_probe_all` through a monkeypatched double and records `emit_alert`/`resolve_alert` instead of
calling them. That is deliberate — this estate has sent the founder a real message from a test
suite before.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import service_health as sh  # noqa: E402

from prospector.ops import console_api as api  # noqa: E402

# --------------------------------------------------------------------------------------------
# doubles
# --------------------------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path):
    """A config double whose store is a temp directory. Never the live store."""
    return SimpleNamespace(store_dir=tmp_path)


@pytest.fixture
def sinks(monkeypatch):
    """Record what would have been sent, and prove nothing real is."""
    emitted, resolved = [], []

    def fake_emit(cfg, **kw):
        emitted.append(kw)
        return dict(kw)

    def fake_resolve(cfg, **kw):
        resolved.append(kw)
        return True

    monkeypatch.setattr(sh, "emit_alert", fake_emit)
    monkeypatch.setattr(sh, "resolve_alert", fake_resolve)
    return SimpleNamespace(emitted=emitted, resolved=resolved)


def probes(monkeypatch, verdicts: dict):
    """Answer every service's probe from a table: name -> True/False/Exception instance."""
    def fake_probe_all(name, svc):
        outcome = verdicts.get(name, True)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome, [f"  {'ok' if outcome else 'FAIL'}   {name} line"]
    monkeypatch.setattr(sh, "_probe_all", fake_probe_all)


@pytest.fixture(autouse=True)
def a_curl_exists(monkeypatch):
    """Default to a host that CAN measure; the no-curl case gets its own test."""
    monkeypatch.setattr(sh.shutil, "which", lambda name: "/usr/bin/curl")


# The real table, captured before any test narrows it, so `only()` can be called twice in one
# test (that is what "a service left the table" looks like).
_ALL_SERVICES = dict(sh.SERVICES)


def only(name: str, monkeypatch):
    """Narrow SERVICES to one entry so a test states exactly what it drives."""
    svc = _ALL_SERVICES[name]
    monkeypatch.setattr(sh, "SERVICES", {name: svc})


# --------------------------------------------------------------------------------------------
# 1. what a pass measures
# --------------------------------------------------------------------------------------------

def test_a_healthy_service_is_up_and_the_run_exits_zero(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": True})
    report = sh.run_once(cfg)
    assert [r["status"] for r in report["results"]] == ["up"]
    assert report["down"] == [] and report["alerted"] == []


def test_every_service_in_the_table_is_reported_in_one_pass(cfg, sinks, monkeypatch):
    probes(monkeypatch, {})
    report = sh.run_once(cfg)
    assert {r["service"] for r in report["results"]} == set(sh.SERVICES)


def test_one_failing_check_out_of_two_makes_the_service_down(cfg, sinks, monkeypatch):
    """The engine has two checks. Half-healthy is not healthy."""
    calls = []

    def half(check):
        calls.append(check["url"])
        return (len(calls) == 1), f"GET {check['url']}"
    monkeypatch.setattr(sh, "_probe_one", half)
    only("engine", monkeypatch)
    assert len(sh.SERVICES["engine"]["probe"]) == 2
    report = sh.run_once(cfg)
    assert report["down"] == ["engine"]


def test_a_probe_that_raises_is_down_not_a_crash(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": RuntimeError("boom")})
    report = sh.run_once(cfg)
    assert report["down"] == ["store-web"]
    assert "RuntimeError" in report["results"][0]["lines"][0]


def test_one_exploding_service_does_not_stop_the_others_being_checked(cfg, sinks, monkeypatch):
    probes(monkeypatch, {"engine": RuntimeError("boom"), "store-api": True, "store-web": True})
    report = sh.run_once(cfg)
    by = {r["service"]: r["status"] for r in report["results"]}
    assert by["engine"] == "down"
    assert by["store-api"] == "up" and by["store-web"] == "up"


# --------------------------------------------------------------------------------------------
# 2. the monitor must never accuse a service it did not measure
# --------------------------------------------------------------------------------------------

def test_no_curl_means_unproven_never_down(cfg, sinks, monkeypatch):
    monkeypatch.setattr(sh.shutil, "which", lambda name: None)
    report = sh.run_once(cfg)
    assert report["down"] == [] and report["alerted"] == []
    assert {r["status"] for r in report["results"]} == {"unproven"}
    assert "nothing was measured" in report["results"][0]["lines"][0]


def test_a_service_with_no_probe_is_unproven_not_healthy(cfg, sinks, monkeypatch):
    only("searxng", monkeypatch)
    assert sh.SERVICES["searxng"]["probe"] == []
    report = sh.run_once(cfg)
    assert report["results"][0]["status"] == "unproven"
    assert report["down"] == [] and report["alerted"] == []


def test_a_run_that_can_only_reach_unproven_services_is_not_a_failure(cfg, sinks, monkeypatch):
    """A permanently red exit code is an exit code nobody reads again."""
    only("searxng", monkeypatch)
    monkeypatch.setattr(sh, "load_config", lambda path: cfg)
    report = sh.run_once(cfg)
    assert report["down"] == [] and report["alerted"] == []
    assert sh.main([]) == 0


def test_an_unproven_pass_neither_escalates_nor_clears_an_existing_outage(cfg, sinks, monkeypatch):
    """searxng-shaped: no measurement must not reset a real failure count, or clear an alert."""
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    sh.run_once(cfg)
    assert sinks.emitted, "second failure should have alerted"
    monkeypatch.setattr(sh.shutil, "which", lambda name: None)
    sh.run_once(cfg)
    assert sinks.resolved == [], "an unmeasured pass must not clear an outage"
    state = json.loads(sh.state_path(cfg).read_text())
    assert state["store-web"]["failures"] == 2
    assert state["store-web"]["alerted"] is True


# --------------------------------------------------------------------------------------------
# 3. when it pages, and when it stays quiet
# --------------------------------------------------------------------------------------------

def test_the_first_failure_does_not_page_anyone(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    report = sh.run_once(cfg)
    assert report["down"] == ["store-web"] and report["alerted"] == []
    assert sinks.emitted == []


def test_the_second_consecutive_failure_pages(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    report = sh.run_once(cfg)
    assert report["alerted"] == ["store-web"]
    assert len(sinks.emitted) == 1
    alert = sinks.emitted[0]
    assert alert["severity"] == sh.CRITICAL
    assert alert["key"] == "service_down:store-web"
    assert alert["consecutive_failures"] == 2


def test_the_threshold_is_more_than_one_pass(cfg):
    """A one-pass pager turns every edge blip into a 3am message. Pinned, not incidental."""
    assert sh.FAILURES_BEFORE_ALERT >= 2


def test_a_recovery_between_failures_resets_the_count(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    probes(monkeypatch, {"store-web": True})
    sh.run_once(cfg)
    probes(monkeypatch, {"store-web": False})
    report = sh.run_once(cfg)
    assert report["alerted"] == [], "one failure after a recovery is the FIRST failure again"


def test_a_persistent_outage_keeps_emitting_so_the_audit_trail_is_complete(cfg, sinks, monkeypatch):
    """Throttling governs the PUSH, inside alerts.py. Every occurrence still gets recorded."""
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    for _ in range(4):
        sh.run_once(cfg)
    assert len(sinks.emitted) == 3
    assert all(a["throttle_s"] == sh.THROTTLE_S for a in sinks.emitted)


def test_recovery_after_an_alert_resolves_it(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    sh.run_once(cfg)
    probes(monkeypatch, {"store-web": True})
    report = sh.run_once(cfg)
    assert report["resolved"] == ["store-web"]
    assert sinks.resolved[0]["key"] == "service_down:store-web"
    assert "store-web" in sinks.resolved[0]["reason"]


def test_recovery_without_a_prior_alert_resolves_nothing(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    probes(monkeypatch, {"store-web": True})
    report = sh.run_once(cfg)
    assert report["resolved"] == [] and sinks.resolved == []


def test_recovering_twice_only_resolves_once(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    sh.run_once(cfg)
    probes(monkeypatch, {"store-web": True})
    sh.run_once(cfg)
    sh.run_once(cfg)
    assert len(sinks.resolved) == 1


def test_a_flapping_service_pages_again_after_it_recovers(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    sh.run_once(cfg)
    probes(monkeypatch, {"store-web": True})
    sh.run_once(cfg)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    sh.run_once(cfg)
    assert len(sinks.emitted) == 2, "the second outage is a new event, not a throttled repeat"


def test_two_services_down_alert_independently(cfg, sinks, monkeypatch):
    probes(monkeypatch, {"engine": False, "store-api": False, "store-web": True})
    sh.run_once(cfg)
    report = sh.run_once(cfg)
    assert sorted(report["alerted"]) == ["engine", "store-api"]
    assert {a["key"] for a in sinks.emitted} == {"service_down:engine", "service_down:store-api"}


def test_the_alert_carries_the_failing_line_and_the_way_to_undo_it(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    sh.run_once(cfg)
    body = sinks.emitted[0]["message"]
    assert "store-web line" in body, "the alert must say which check failed"
    assert "rollout undo deployment/prospector-store-web" in body
    assert "prospector-store-web" in body


# --------------------------------------------------------------------------------------------
# 4. the state file
# --------------------------------------------------------------------------------------------

def test_a_missing_state_file_is_an_empty_one(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    assert not sh.state_path(cfg).exists()
    assert sh.run_once(cfg)["alerted"] == []


@pytest.mark.parametrize("junk", ["not json at all", "[1, 2, 3]", "", "null"])
def test_a_corrupt_state_file_does_not_stop_the_pass(cfg, sinks, monkeypatch, junk):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": True})
    path = sh.state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(junk)
    assert sh.run_once(cfg)["results"][0]["status"] == "up"


def test_a_state_entry_of_the_wrong_type_is_ignored(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    path = sh.state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"store-web": "down since tuesday"}))
    assert sh.run_once(cfg)["alerted"] == [], "a junk entry must not count as a prior failure"


def test_the_state_file_is_valid_json_after_a_pass(cfg, sinks, monkeypatch):
    probes(monkeypatch, {})
    sh.run_once(cfg)
    state = json.loads(sh.state_path(cfg).read_text())
    assert set(state) == set(sh.SERVICES)


def test_a_state_file_that_cannot_be_written_still_reports_correctly(cfg, sinks, monkeypatch,
                                                                    capsys):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})

    def refuse(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(sh.Path, "write_text", refuse)
    report = sh.run_once(cfg)
    assert report["down"] == ["store-web"]
    assert "could not write" in capsys.readouterr().err


def test_no_temp_file_is_left_behind(cfg, sinks, monkeypatch):
    probes(monkeypatch, {})
    sh.run_once(cfg)
    assert list(sh.state_path(cfg).parent.glob("service_health.tmp")) == []


def test_the_state_goes_to_the_configured_store_not_the_cwd(cfg, sinks, monkeypatch, tmp_path):
    probes(monkeypatch, {})
    sh.run_once(cfg)
    assert sh.state_path(cfg) == tmp_path / "scheduler" / "service_health.json"
    assert sh.state_path(cfg).exists()


# --------------------------------------------------------------------------------------------
# 5. the CLI
# --------------------------------------------------------------------------------------------

def test_main_exits_one_when_something_is_down(cfg, sinks, monkeypatch, capsys):
    monkeypatch.setattr(sh, "load_config", lambda path: cfg)
    probes(monkeypatch, {"engine": False})
    assert sh.main([]) == 1
    assert "DOWN engine" in capsys.readouterr().out


def test_main_exits_zero_when_everything_measurable_is_up(cfg, sinks, monkeypatch, capsys):
    monkeypatch.setattr(sh, "load_config", lambda path: cfg)
    probes(monkeypatch, {})
    assert sh.main([]) == 0
    assert "every service with a public route answered its checks" in capsys.readouterr().out


def test_main_exits_zero_when_the_only_finding_is_unproven(cfg, sinks, monkeypatch):
    monkeypatch.setattr(sh, "load_config", lambda path: cfg)
    monkeypatch.setattr(sh.shutil, "which", lambda name: None)
    assert sh.main([]) == 0, "unproven is not a failure, or the exit code is red forever"


def test_json_output_parses_and_names_the_down_services(cfg, sinks, monkeypatch, capsys):
    monkeypatch.setattr(sh, "load_config", lambda path: cfg)
    probes(monkeypatch, {"engine": False})
    sh.main(["--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["down"] == ["engine"]
    assert set(report) == {"checked_at", "results", "alerted", "resolved", "down"}


# --------------------------------------------------------------------------------------------
# 6. no second definition of "healthy", and it is actually scheduled
# --------------------------------------------------------------------------------------------

def test_there_is_one_probe_table(cfg):
    """One probe table, in service_health.py. A second copy drifts, and the copy nobody runs
    is the stale one. Before crew#203 the table lived in rollback_now.py and this file
    imported it; now the rule is that no OTHER script under scripts/ carries a probe URL."""
    for path in sorted((ROOT / "scripts").glob("*.py")):
        if path.name == "service_health.py":
            continue
        code = "\n".join(line for line in path.read_text().splitlines()
                         if not line.lstrip().startswith("#"))
        assert '"probe": [' not in code, f"{path.name} carries a second probe table"


def test_every_monitored_service_is_a_deployment_on_the_cluster(cfg):
    """The table names what deploy/k8s/base/*.yaml runs, so an alert names a Deployment that
    `kubectl rollout undo` can act on. A row for something the cluster does not run is a
    UNPROVEN line forever, which is noise nobody reads."""
    manifests = "\n".join(p.read_text() for p in (ROOT / "deploy" / "k8s" / "base").glob("*.yaml"))
    assert sh.SERVICES, "empty table grades nothing"
    for name, svc in sh.SERVICES.items():
        if not svc["probe"]:
            continue  # searxng: no probe, so no alert names its Deployment (tests above)
        assert f"name: {svc['app']}" in manifests, f"{name}: no Deployment {svc['app']} in deploy/k8s/base"


def test_the_engine_image_runs_it_on_a_schedule(cfg):
    """The drill before it was written, wired into a screen and scheduled nowhere."""
    conf = (ROOT / "deploy" / "engine" / "supervisord.conf").read_text()
    assert "[program:health-watch]" in conf
    line = next(ln for ln in conf.splitlines()
                if ln.startswith("command=") and "service_health.py" in ln)
    assert "periodic.sh 300 " in line, "the interval is a claim; pin it"
    assert "python scripts/service_health.py" in line


def test_the_scheduled_command_is_a_file_that_exists(cfg):
    assert (ROOT / "scripts" / "service_health.py").is_file()


def test_the_console_has_a_button_for_it(cfg):
    rows = [t for t in api.TOOLS if t["path"] == "scripts/service_health.py"]
    assert len(rows) == 1
    row = rows[0]
    assert row["screen"] == "/deploys"
    assert row["writes"] is False, "it changes nothing on this machine"
    assert row["risk"] == "external", "a Telegram alert cannot be unsent"
    assert row["run"] is True


def test_the_alert_key_is_unique_per_service(cfg):
    keys = {sh.alert_key(name) for name in sh.SERVICES}
    assert len(keys) == len(sh.SERVICES)


def test_the_repair_hint_names_the_right_app_for_each_service(cfg):
    for name, svc in sh.SERVICES.items():
        hint = sh.repair_hint(name)
        assert svc["app"] in hint
        assert f"rollout undo deployment/{svc['app']}" in hint


# --------------------------------------------------------------------------------------------
# 7. a service that leaves the table
# --------------------------------------------------------------------------------------------

def test_a_removed_service_with_a_live_alert_has_it_cleared(cfg, sinks, monkeypatch):
    """Nothing checks it any more, so nothing else could ever clear it."""
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": False})
    sh.run_once(cfg)
    sh.run_once(cfg)
    assert sinks.emitted, "precondition: it alerted"

    only("engine", monkeypatch)
    probes(monkeypatch, {"engine": True})
    report = sh.run_once(cfg)
    assert report["resolved"] == ["store-web"]
    assert "no longer a deployed service" in sinks.resolved[0]["reason"]
    assert "store-web" not in json.loads(sh.state_path(cfg).read_text())


def test_a_removed_service_that_was_healthy_is_pruned_quietly(cfg, sinks, monkeypatch):
    only("store-web", monkeypatch)
    probes(monkeypatch, {"store-web": True})
    sh.run_once(cfg)
    only("engine", monkeypatch)
    report = sh.run_once(cfg)
    assert report["resolved"] == [] and sinks.resolved == []
    assert set(json.loads(sh.state_path(cfg).read_text())) == {"engine"}


def test_pruning_never_removes_a_service_that_is_still_watched(cfg, sinks, monkeypatch):
    probes(monkeypatch, {})
    sh.run_once(cfg)
    sh.run_once(cfg)
    assert set(json.loads(sh.state_path(cfg).read_text())) == set(sh.SERVICES)


def test_a_junk_state_entry_for_a_removed_service_does_not_crash_the_prune(cfg, sinks,
                                                                          monkeypatch):
    only("engine", monkeypatch)
    probes(monkeypatch, {"engine": True})
    path = sh.state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"engine": {}, "an-app-that-left": "a string, not a dict"}))
    report = sh.run_once(cfg)
    assert report["resolved"] == []
    assert set(json.loads(path.read_text())) == {"engine"}


# --------------------------------------------------------------------------------------------
# 8. the one check that makes a public ops console acceptable
# --------------------------------------------------------------------------------------------

def test_the_engine_probe_still_proves_the_console_fails_closed(cfg):
    """deploy/engine/supervisord.conf cites this check as the reason a PUBLIC console is safe.

    prospector-engine has an [http_service] on 8611, so the console is on the open internet.
    Deleting the 401 check would leave that claim standing with nothing measuring it.
    """
    checks = sh.SERVICES["engine"]["probe"]
    unauth = [c for c in checks if c.get("expect") == "401"]
    assert len(unauth) == 1
    assert unauth[0]["url"].endswith("/api/ops/read/status")


# --------------------------------------------------------------------------------------
# 9. Two passes running at once
#
# supervisord runs this every 300s inside the engine image AND it is a button on the
# /deploys screen, so a scheduled pass and a hand-run pass can overlap on the same store.
# That is not hypothetical: the console tool row exists precisely so an operator can ask
# right now instead of waiting for the next tick.
# --------------------------------------------------------------------------------------


def test_two_passes_running_at_once_do_not_write_to_the_same_temp_file(cfg, monkeypatch):
    """A shared temp name lets one process write into the other's promoted file.

    The sequence that corrupts it: A opens the temp and writes half of it; B opens the
    SAME temp, writes all of it, and renames it onto the state file; A then finishes
    writing through its still-open descriptor, which now points at the live state file.
    The result is B's document with A's tail appended - not valid JSON.

    A per-process temp name makes that sequence impossible, because `Path.replace` is
    atomic and the two processes never share a descriptor. This test pins the name.
    """
    seen: list[str] = []
    real_write = Path.write_text

    def spy(self, data, *args, **kwargs):
        seen.append(self.name)
        return real_write(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy)

    monkeypatch.setattr(sh.os, "getpid", lambda: 111)
    sh.save_state(cfg, {"engine": {"failures": 1}})
    monkeypatch.setattr(sh.os, "getpid", lambda: 222)
    sh.save_state(cfg, {"engine": {"failures": 2}})

    temps = [n for n in seen if n.endswith(".tmp")]
    assert len(temps) == 2, seen
    assert len(set(temps)) == 2, (
        f"both passes wrote to the same temp file {temps[0]!r}; one can rename the "
        "other's half-written document onto the state file"
    )


def test_the_last_pass_to_finish_wins_and_the_state_is_whole(cfg, monkeypatch):
    """Whatever the interleaving, the file on disk is one complete document.

    There is no merge to do here. The counters are cheap to rebuild - a lost count costs
    at most one extra pass before paging - so last-writer-wins is the right answer and a
    lock would be a second thing to go wrong.
    """
    monkeypatch.setattr(sh.os, "getpid", lambda: 111)
    sh.save_state(cfg, {"engine": {"failures": 1, "alerted": False}})
    monkeypatch.setattr(sh.os, "getpid", lambda: 222)
    sh.save_state(cfg, {"store-api": {"failures": 2, "alerted": True}})

    on_disk = json.loads(sh.state_path(cfg).read_text())
    assert on_disk == {"store-api": {"failures": 2, "alerted": True}}
    assert sh.load_state(cfg) == on_disk


def test_a_temp_file_left_behind_by_a_killed_pass_is_never_read_as_the_state(cfg):
    """A SIGKILLed pass leaves its temp behind. It must not become the state.

    `load_state` reads exactly one path. This pins that a stray sibling - which a killed
    process WILL leave, since nothing sweeps them - cannot be picked up, and that junk in
    it changes nothing.
    """
    sh.save_state(cfg, {"engine": {"failures": 1}})
    stray = sh.state_path(cfg).with_name(sh.state_path(cfg).name + ".999.tmp")
    stray.write_text('{"engine": {"failu')  # truncated, exactly as a kill leaves it

    assert sh.load_state(cfg) == {"engine": {"failures": 1}}
    assert stray.exists(), "the test's own premise: nothing sweeps the stray"
