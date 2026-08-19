"""The founder's task list must outlive the session that took it.

WHY THIS EXISTS. Measured 2026-08-20: tasks were already written to disk, at
`~/.claude/tasks/<session-id>/<n>.json`. Persistence was never the problem. That store is keyed by
SESSION, so a new session opens on an empty list -- 231 open tasks across 45 prospector session
directories, 231 distinct subjects, zero overlap, because no session can see another one's. The
founder asked for the list to survive; what was missing was the reading of it, not the writing.

So the durable list is GitHub issues labelled `founder-task`, `scripts/founder_tasks.py` prints
them from a local cache, and `ops/state_probe.sh` runs that at every session start.

Two failures are guarded here, and both are failures of SILENCE, which is why a test is the only
thing that catches them:

  * The reader raises or exits non-zero on a cache that is missing, empty or corrupt. The probe
    swallows its stderr -- it must, a probe may never be why a session fails to start -- so a
    reader that dies just makes the list disappear.
  * The probe stops calling it, or --install stops installing it. Nothing else notices: the probe
    still prints eleven other correct sections and the task list is simply not there.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
READER = ROOT / "scripts" / "founder_tasks.py"
PROBE = ROOT / "ops" / "state_probe.sh"


def _run(cache: Path) -> subprocess.CompletedProcess[str]:
    """Print mode only. --refresh is the only mode that touches the network and is never run here."""
    return subprocess.run(
        [sys.executable, str(READER)],
        capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "HOME": str(cache.parent),
             "FOUNDER_TASKS_CACHE": str(cache)},
    )


def _write(cache: Path, tasks: list[dict], age_s: float = 0.0) -> None:
    cache.write_text(json.dumps({"fetched_at": time.time() - age_s, "label": "founder-task",
                                 "repo": "chidionyema/prospector", "tasks": tasks}))


@pytest.mark.parametrize("state", ["missing", "corrupt", "empty-file"])
def test_a_cache_it_cannot_read_still_exits_zero(tmp_path: Path, state: str) -> None:
    """The probe cannot distinguish a crash from an empty list. Neither can the founder."""
    cache = tmp_path / "founder-tasks.json"
    if state == "corrupt":
        cache.write_text("{not json")
    elif state == "empty-file":
        cache.write_text("")

    proc = _run(cache)
    assert proc.returncode == 0, (
        f"the reader exited {proc.returncode} on a {state} cache. The state probe discards its "
        f"stderr, so this does not surface as an error -- the task list just vanishes from every "
        f"session start:\n{proc.stderr}")
    assert proc.stdout.strip(), (
        f"the reader printed NOTHING on a {state} cache. Silence is the failure mode this whole "
        "mechanism exists to fix: a list that disappears reads exactly like a list with nothing "
        "on it.")
    assert "founder_tasks.py --refresh" in proc.stdout, (
        "a reader that cannot show the list must name the command that fixes it, or the session "
        f"is told there is a problem and not what to do:\n{proc.stdout}")


def test_no_open_tasks_says_so_rather_than_printing_nothing(tmp_path: Path) -> None:
    cache = tmp_path / "founder-tasks.json"
    _write(cache, [])
    proc = _run(cache)
    assert proc.returncode == 0
    assert "none open" in proc.stdout, proc.stdout


def test_the_list_carries_the_number_the_title_and_who_holds_it(tmp_path: Path) -> None:
    """Each of the three is load-bearing: the number to claim it, the title to judge it, the
    holder so a second session does not take work someone is already doing."""
    cache = tmp_path / "founder-tasks.json"
    _write(cache, [{"number": 486, "title": "The task list dies with the session",
                    "assignees": [], "updated_at": ""},
                   {"number": 478, "title": "Model pinning", "assignees": ["chidionyema"],
                    "updated_at": ""}])
    out = _run(cache).stdout
    assert "#486" in out and "The task list dies with the session" in out, out
    assert "unclaimed" in out, f"an unassigned task must say so:\n{out}"
    assert "chidionyema" in out, f"a claimed task must name its holder:\n{out}"


def test_a_stale_cache_says_stale_and_never_pretends_to_be_current(tmp_path: Path) -> None:
    """A task list quietly three days old is worse than no task list: it is acted on."""
    cache = tmp_path / "founder-tasks.json"
    _write(cache, [{"number": 1, "title": "old", "assignees": [], "updated_at": ""}],
           age_s=3 * 24 * 3600)
    out = _run(cache).stdout
    assert "STALE" in out, f"a 3-day-old cache printed as if current:\n{out}"
    assert "founder_tasks.py --refresh" in out, out


def _probe(home: Path) -> subprocess.CompletedProcess[str]:
    """Run the real probe against a throwaway HOME.

    Grepping the script for "founder_tasks.py" is what this replaces, and it was worthless: the
    string also appears in the install block and in three comments, so deleting the call left the
    assertion satisfied. Measured -- the mutant passed. Only running it proves the section exists.
    """
    return subprocess.run(
        ["bash", str(PROBE)], capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(home)},
    )


def test_the_probe_prints_the_task_list_it_is_given(tmp_path: Path) -> None:
    """End to end: reader installed, cache present, list on screen at session start."""
    installed = tmp_path / ".claude" / "state-probe"
    installed.mkdir(parents=True)
    (installed / "founder_tasks.py").write_text(READER.read_text())
    cache = tmp_path / ".claude" / "state" / "founder-tasks.json"
    cache.parent.mkdir(parents=True)
    _write(cache, [{"number": 486, "title": "The task list dies with the session",
                    "assignees": [], "updated_at": ""}])

    proc = _probe(tmp_path)
    assert proc.returncode == 0, f"the probe must always exit 0:\n{proc.stderr}"
    assert "#486" in proc.stdout and "The task list dies with the session" in proc.stdout, (
        "the probe ran but the founder's task list is not in its output, so no session is shown "
        f"it any more:\n{proc.stdout[-2000:]}")


def test_the_probe_says_so_when_the_reader_is_missing(tmp_path: Path) -> None:
    """Skipping the section in silence is how this shipped broken the first time: the block
    resolved to nothing and no run of the probe looked any different."""
    proc = _probe(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "FOUNDER TASKS" in proc.stdout, (
        "with no reader installed the probe printed nothing at all about the task list. A section "
        f"that vanishes reads exactly like a list with nothing on it:\n{proc.stdout[-2000:]}")
    assert "--install" in proc.stdout, (
        f"it must name the command that fixes it:\n{proc.stdout[-2000:]}")


def test_install_puts_the_reader_beside_the_probe(tmp_path: Path) -> None:
    """The probe calls the INSTALLED reader, not one out of a checkout -- the main checkout was 11
    commits behind when this was written, and prospector-live is pinned to origin/main by a
    different job on its own cadence."""
    proc = subprocess.run(
        ["bash", str(PROBE), "--install"], capture_output=True, text=True, timeout=120,
        cwd=str(ROOT), env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)})
    assert proc.returncode == 0, proc.stderr
    reader = tmp_path / ".claude" / "state-probe" / "founder_tasks.py"
    assert reader.exists(), (
        "--install did not put the reader beside the probe, so the installed probe calls a file "
        f"that is not there:\n{proc.stdout}\n{proc.stderr}")
    assert reader.read_text() == READER.read_text(), "the installed reader is not the source"
