"""A launchd job can match its snapshot perfectly and still be dead.

`--check` compared installed plists against a tracked snapshot and nothing else. On 2026-08-17
the checkout at /Users/chidionyema/Documents/code/prospector-live disappeared. Every path in
`com.prospector.backup` pointed into it, so the nightly git mirror to R2 stopped that day —
and the probe kept printing PASS, because the plist had not changed. The Hermes receipt for
`backup_store.py` stayed green too, because Fly writes one under the same key.

So this is judged against the filesystem, not against the snapshot: `--snapshot` cannot accept
a broken job into the baseline the way it can accept a drifted one.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_NAME = "launchd_plists_under_test"


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


def test_a_missing_interpreter_is_a_finding(tmp_path):
    """The exact 2026-08-17 failure: the plist is intact, the interpreter is gone."""
    mod = _module()
    gone = tmp_path / "prospector-live" / ".venv" / "bin" / "python"
    live = {"com.prospector.backup": {"ProgramArguments": [str(gone), "scripts/backup_store.py"]}}

    findings = mod.broken_programs(live, disabled=set())

    assert len(findings) == 1
    assert "com.prospector.backup" in findings[0]
    assert str(gone) in findings[0]


def test_a_missing_working_directory_is_a_finding(tmp_path):
    """A job whose cwd is gone starts and then fails, which reads as a code fault, not a setup one."""
    mod = _module()
    real = tmp_path / "python"
    real.write_text("#!/bin/sh\n")
    live = {"job": {"ProgramArguments": [str(real)],
                    "WorkingDirectory": str(tmp_path / "deleted-repo")}}

    findings = mod.broken_programs(live, disabled=set())

    assert len(findings) == 1
    assert "WorkingDirectory not found" in findings[0]


def test_a_disabled_job_is_not_a_finding(tmp_path):
    """Retiring a job and deleting its checkout is the intended end state, not a fault.

    Six com.prospector.* jobs are retired exactly this way. Reporting them would train the
    reader to ignore the whole section, which is how the real one stayed invisible.
    """
    mod = _module()
    gone = tmp_path / "nowhere" / "python"
    live = {"com.prospector.scheduler": {"ProgramArguments": [str(gone)]}}

    assert mod.broken_programs(live, disabled={"com.prospector.scheduler"}) == []


def test_a_bare_command_is_left_alone():
    """`bash` resolves against the job's own PATH at load time; guessing that is not this job."""
    mod = _module()
    live = {"job": {"ProgramArguments": ["bash", "-lc", "echo hi"]}}

    assert mod.broken_programs(live, disabled=set()) == []


def test_an_unreadable_plist_is_left_to_the_unreadable_check():
    """It is already reported once. Reporting it twice under a second name is noise."""
    mod = _module()
    live = {"job": {"__unreadable__": "ExpatError: mismatched tag"}}

    assert mod.broken_programs(live, disabled=set()) == []


def test_a_healthy_job_is_silent(tmp_path):
    mod = _module()
    real = tmp_path / "python"
    real.write_text("#!/bin/sh\n")
    live = {"job": {"ProgramArguments": [str(real)], "WorkingDirectory": str(tmp_path)}}

    assert mod.broken_programs(live, disabled=set()) == []


def test_disabled_labels_never_raises(monkeypatch):
    """The probe runs on boxes without launchctl. Unknown means check everything, not crash."""
    mod = _module()

    def boom(*_a, **_k):
        raise FileNotFoundError("launchctl")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    assert mod.disabled_labels() == set()
