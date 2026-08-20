"""A declared launchd job that launchd is not holding must fail something.

Measured 2026-08-20: ten jobs were installed on this Mac and not held, every ai.hermes.*
daemon among them, and the estate had been blind to it for 13.5 hours. Two probes had the
fact and neither could act on it. `process_audit.py` graded it WARN on a written argument
that it could not know whether a job OUGHT to run -- correct, so ops/config/launchd_not_held.json
now supplies that missing input rather than arguing with the grade. And the receipts those
probes wrote were graded by no Hermes capability at all, so the WARN went into a log nobody
opened.

These tests pin the four ways this check can lie: passing when it could not ask, passing on
an unexplained dead job, failing on a job somebody wrote down a reason for, and accepting an
excuse with no reason in it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_NAME = "launchd_plists_held_under_test"


def _module():
    """Load `scripts/launchd_plists.py` by path — it is a script, not a package module."""
    if _NAME in sys.modules:
        return sys.modules[_NAME]
    spec = importlib.util.spec_from_file_location(_NAME, REPO / "scripts" / "launchd_plists.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[_NAME]
        raise
    return mod


@pytest.fixture()
def estate(tmp_path, monkeypatch):
    """A fake estate: declarations, installed plists, and whatever launchd is holding."""
    mod = _module()
    tracked = tmp_path / "launchd"
    live = tmp_path / "LaunchAgents"
    tracked.mkdir()
    live.mkdir()
    monkeypatch.setattr(mod, "TRACKED", tracked)
    monkeypatch.setattr(mod, "LIVE", live)
    monkeypatch.setattr(mod, "NOT_HELD", tmp_path / "launchd_not_held.json")

    def declare(label: str, *, installed: bool = True) -> None:
        (tracked / f"{label}.json").write_text(json.dumps({"Label": label}))
        if installed:
            (live / f"{label}.plist").write_text("")

    def excuse(mapping: dict) -> None:
        (tmp_path / "launchd_not_held.json").write_text(json.dumps({"not_held": mapping}))

    def holding(*labels) -> None:
        monkeypatch.setattr(mod, "held_labels", lambda: set(labels))

    class Estate:
        pass

    e = Estate()
    e.mod, e.declare, e.excuse, e.holding, e.tmp = mod, declare, excuse, holding, tmp_path
    return e


def test_a_declared_job_launchd_holds_passes(estate, capsys):
    estate.declare("com.example.alive")
    estate.holding("com.example.alive")
    assert estate.mod.cmd_assert_held() == 0
    assert "LAUNCHD HELD PASS" in capsys.readouterr().out


def test_a_declared_job_launchd_is_not_holding_fails(estate, capsys):
    estate.declare("com.example.dead")
    estate.holding()
    assert estate.mod.cmd_assert_held() == 1
    out = capsys.readouterr().out
    assert "NOT HELD     com.example.dead" in out
    assert "its plist is installed" in out


def test_a_declared_job_with_no_plist_at_all_fails_and_says_so(estate, capsys):
    estate.declare("com.example.uninstalled", installed=False)
    estate.holding()
    assert estate.mod.cmd_assert_held() == 1
    assert "NO plist installed" in capsys.readouterr().out


def test_a_job_excused_in_writing_does_not_fail(estate, capsys):
    estate.declare("com.example.moved")
    estate.excuse({"com.example.moved": "it runs on Fly now -- docs/X.md:1"})
    estate.holding()
    assert estate.mod.cmd_assert_held() == 0
    out = capsys.readouterr().out
    assert "off by design — it runs on Fly now" in out
    assert "NOT HELD" not in out


def test_an_excuse_with_no_reason_is_itself_a_finding(estate, capsys):
    estate.declare("com.example.hushed")
    estate.excuse({"com.example.hushed": "   "})
    estate.holding()
    assert estate.mod.cmd_assert_held() == 1
    out = capsys.readouterr().out
    assert "BAD EXCUSE" in out
    # It is not excused either, so the dead job is still named.
    assert "NOT HELD     com.example.hushed" in out


def test_launchctl_that_does_not_answer_exits_unknown_and_grades_nothing(
        estate, capsys, monkeypatch):
    estate.declare("com.example.dead")
    monkeypatch.setattr(estate.mod, "held_labels", lambda: None)
    assert estate.mod.cmd_assert_held() == 2
    out = capsys.readouterr().out
    assert "UNPROVEN" in out
    assert "NOT HELD" not in out


def test_an_empty_launchctl_answer_is_not_the_same_as_no_answer(estate, capsys):
    """launchd holding nothing is an alarm; being unable to ask is not. Exit 1 vs exit 2."""
    estate.declare("com.example.dead")
    estate.holding()
    assert estate.mod.cmd_assert_held() == 1


def test_no_declarations_at_all_is_unproven_not_a_pass(estate, capsys):
    estate.holding()
    assert estate.mod.cmd_assert_held() == 2
    assert "UNPROVEN" in capsys.readouterr().out


def test_a_stale_excuse_is_reported_and_does_not_fail(estate, capsys):
    estate.declare("com.example.alive")
    estate.excuse({"com.example.alive": "supposedly off", "com.example.ghost": "gone"})
    estate.holding("com.example.alive")
    assert estate.mod.cmd_assert_held() == 0
    out = capsys.readouterr().out
    assert "launchd IS holding it" in out
    assert "declared nowhere" in out


def test_a_missing_excuse_file_means_every_declared_job_must_be_held(estate, capsys):
    estate.declare("com.example.dead")
    estate.holding()
    assert not (estate.tmp / "launchd_not_held.json").exists()
    assert estate.mod.cmd_assert_held() == 1


def test_an_unreadable_excuse_file_is_a_finding_not_a_silent_pass(estate, capsys):
    estate.declare("com.example.alive")
    estate.holding("com.example.alive")
    (estate.tmp / "launchd_not_held.json").write_text("{ not json")
    assert estate.mod.cmd_assert_held() == 1
    assert "unreadable" in capsys.readouterr().out


def test_the_shipped_excuse_file_parses_and_every_entry_gives_a_reason():
    """The real ops/config/launchd_not_held.json, not a fixture."""
    mod = _module()
    excused, problems = mod.load_not_held(REPO / "ops" / "config" / "launchd_not_held.json")
    assert problems == []
    assert excused, "the shipped file excuses nothing, so it is not being exercised"
    for label, why in excused.items():
        assert len(why) > 30, f"{label} has a reason too short to check: {why!r}"


# --------------------------------------------- a receipt no capability grades is not a receipt

LAUNCHD = REPO / "ops" / "launchd"
CAPABILITIES = Path.home() / ".hermes" / "capabilities.json"
RECEIPT_WRAPPER = Path.home() / ".hermes" / "scripts" / "launchd_receipt.py"


def _receipt_wrapped_jobs() -> dict[str, str]:
    """label -> receipt key, for every declared launchd job wrapped in launchd_receipt.py.

    The key is asked of the wrapper itself rather than re-derived here. A guard that
    reimplements the rule it is guarding drifts from it, and this estate has already paid for
    that once: an AST check written to replace a regex sweep was pinned to one expression and
    left twenty offenders on disk reading green.
    """
    spec = importlib.util.spec_from_file_location("launchd_receipt_under_test", RECEIPT_WRAPPER)
    wrapper = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(wrapper)

    jobs: dict[str, str] = {}
    for path in sorted(LAUNCHD.glob("*.json")):
        try:
            argv = json.loads(path.read_text(encoding="utf-8")).get("ProgramArguments") or []
        except ValueError:
            continue
        argv = [str(a) for a in argv]
        if not any(a.endswith("launchd_receipt.py") for a in argv):
            continue
        if "--script" in argv:
            jobs[path.stem] = argv[argv.index("--script") + 1]
        elif "--" in argv:
            jobs[path.stem] = wrapper._default_script_key(argv[argv.index("--") + 1:])
    return jobs


@pytest.mark.skipif(not (CAPABILITIES.exists() and RECEIPT_WRAPPER.exists()),
                    reason="both files live in another repository and are not on a CI runner")
def test_every_receipt_wrapped_launchd_job_has_a_capability_that_grades_it():
    """Writing an exit code down is not the same as anyone reading it.

    com.prospector.process-audit exited 2 on all seventeen of its runs -- its plist pointed at
    a script inside the frozen standby checkout, where that file has never existed -- and every
    one of those exit codes was already in the Hermes ledger. No capability named the key, so
    nothing turned them into a colour and nobody looked. This is the join that would have made
    hour one loud.

    A job excused in ops/config/launchd_not_held.json is skipped: it is off by design, so a
    capability grading it would sit permanently DARK and teach the operator to ignore DARK.
    The reverse case -- an excuse that has gone stale because launchd IS holding the job again
    -- is not caught here; `launchd_plists.py --assert-held` prints it as a NOTE on the hourly
    run, because failing on it would turn a temporary manual load into a red estate.
    """
    graded = {
        (c.get("observable") or {}).get("script")
        for c in json.loads(CAPABILITIES.read_text(encoding="utf-8"))["capabilities"]
    }
    excused, _ = _module().load_not_held()
    jobs = {label: key for label, key in _receipt_wrapped_jobs().items() if label not in excused}
    assert jobs, f"no declaration in {LAUNCHD} is receipt-wrapped and expected to run; vacuous"

    ungraded = sorted(f"{label} -> {key}" for label, key in jobs.items() if key not in graded)
    assert not ungraded, (
        "these launchd jobs sign a receipt on every run and no capability grades it, so they "
        f"are instrumented and read by nobody: {ungraded}. Either add a capability whose "
        "observable.script is the key, or stop wrapping the job."
    )
# ------------------------------------- launchd's third state: disabled by hand, not crashed

def test_disabled_labels_reads_only_the_disabled_ones(monkeypatch):
    """`launchctl print-disabled` lists BOTH states in one table; only one of them is ours."""
    mod = _module()
    out = (
        "\n\tdisabled services = {\n"
        '\t\t"com.google.keystone.user.agent" => enabled\n'
        '\t\t"ai.hermes.cockpit" => disabled\n'
        '\t\t"ai.hermes.keepawake" => enabled\n'
        '\t\t"com.prospector.scheduler" => disabled\n'
        "\t}\n"
    )
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=out))
    assert mod.disabled_labels() == {"ai.hermes.cockpit", "com.prospector.scheduler"}


def test_disabled_labels_fails_open_when_launchctl_cannot_answer(monkeypatch):
    """Empty, not None, and that is #345's choice rather than this one.

    I wrote a second `disabled_labels()` at the bottom of the module that returned None on an
    unreadable launchctl, on the reasoning that "could not ask" is not "asked, nothing is off".
    The reasoning is fine and the act was not: #345 already defined the function 200 lines
    above, Python kept whichever came last, and `test_launchd_broken_program_paths.py` went red
    on a CI runner that has no launchctl at all. The surviving contract is #345's, because its
    caller needs it: `broken_programs` skips disabled jobs, so an unknown set must be EMPTY or
    a launchctl outage silently stops every job being checked for a missing program.
    """
    mod = _module()
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=""))
    assert mod.disabled_labels() == set()
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no launchctl")))
    assert mod.disabled_labels() == set()


def test_a_job_disabled_by_hand_still_fails_but_says_so(estate, capsys, monkeypatch):
    """Disabling is an ACT. The reason still has to be written down, so this is not an excuse."""
    estate.declare("com.prospector.deliberate")
    estate.holding()
    monkeypatch.setattr(estate.mod, "disabled_labels", lambda: {"com.prospector.deliberate"})
    assert estate.mod.cmd_assert_held() == 1
    out = capsys.readouterr().out
    assert "launchctl disable" in out
    assert "1 of them disabled by hand" in out


def test_a_job_that_is_merely_absent_is_not_called_disabled(estate, capsys, monkeypatch):
    """The wording must not claim an operator acted when nothing says one did."""
    estate.declare("com.prospector.crashed")
    estate.holding()
    monkeypatch.setattr(estate.mod, "disabled_labels", lambda: set())
    assert estate.mod.cmd_assert_held() == 1
    out = capsys.readouterr().out
    assert "launchctl disable" not in out
    assert "launchd is NOT holding it" in out


def test_not_knowing_what_is_disabled_does_not_change_the_verdict(estate, capsys, monkeypatch):
    """A probe that cannot answer costs the wording, never the finding."""
    estate.declare("com.prospector.crashed")
    estate.holding()
    monkeypatch.setattr(estate.mod, "disabled_labels", lambda: None)
    assert estate.mod.cmd_assert_held() == 1
    assert "0 of them disabled by hand" in capsys.readouterr().out
