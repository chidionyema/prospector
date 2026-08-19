"""A launchd job's script must be checked, not only its interpreter.

Measured 2026-08-19: `com.prospector.process-audit` had exited 2 every hour for a day with
"can't open file '/Users/chidionyema/Documents/code/prospector-live/scripts/process_audit.py'".
`broken_programs()` reported nothing, because it tested `ProgramArguments[0]` — the Python
interpreter, which existed — and the missing script sat at index 5. That job is the only caller
of `launchd_plists.py --check`, so the estate's drift detector was dead and could not say so.

These cases are built from that exact plist.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import launchd_plists  # noqa: E402


def _job(argv, wd):
    return {"ProgramArguments": argv, "WorkingDirectory": wd}


def test_missing_script_is_reported_when_the_interpreter_exists(tmp_path):
    """The real com.prospector.process-audit shape: python exists, script does not."""
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n")
    wrapper = tmp_path / "launchd_receipt.py"
    wrapper.write_text("")
    missing = tmp_path / "scripts" / "process_audit.py"   # never created

    live = {"com.prospector.process-audit": _job(
        [str(python), str(wrapper), "--label", "com.prospector.process-audit", "--",
         str(python), str(missing), "--quiet", "--alert"],
        str(tmp_path))}

    findings = launchd_plists.broken_programs(live, disabled=set())
    assert len(findings) == 1, findings
    assert "script not found" in findings[0]
    assert str(missing) in findings[0]


def test_a_whole_job_on_disk_is_silent(tmp_path):
    """The negative case: every path present means no finding at all."""
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n")
    script = tmp_path / "process_audit.py"
    script.write_text("")

    live = {"ok": _job([str(python), str(script), "--quiet"], str(tmp_path))}
    assert launchd_plists.broken_programs(live, disabled=set()) == []


def test_relative_and_bare_arguments_are_not_guessed_at(tmp_path):
    """A relative path resolves against WorkingDirectory and a bare word against PATH.

    Guessing at either is how a check earns false positives and then gets ignored.
    """
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n")
    live = {"rel": _job([str(python), "scripts/nope.py", "-m", "pkg.mod"], str(tmp_path))}
    assert launchd_plists.broken_programs(live, disabled=set()) == []


def test_a_disabled_job_is_still_skipped(tmp_path):
    """Unchanged behaviour: an operator disabled it on purpose, so it is not a fault."""
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n")
    live = {"off": _job([str(python), str(tmp_path / "gone.py")], str(tmp_path))}
    assert launchd_plists.broken_programs(live, disabled={"off"}) == []
