"""Two rules about what `ops/launchd/` is allowed to contain.

RULE 1 — other projects' jobs are not tracked here. `com.haworks.*` and `com.tie.*` belong to
other repositories. Their plists were installed on this Mac, `launchd_plists.py` snapshotted
them because nothing said not to, and once their checkouts went away `--check` reported three
BROKEN findings on every run about jobs Prospector does not own. A probe that always prints
findings you are meant to ignore is a probe nobody reads.

RULE 2 — no tracked job may write its logs under `/tmp`. macOS purges `/tmp`, so a log there
answers nothing after a reboot, which is the whole point of docs/LOGGING_AND_RETENTION.md
Part 8 step 3. Both jobs that did this are gone; this is what stops the third one.

Neither rule can be enforced by a habit. Both are read out of files in this repository, so
they hold on CI and on any machine, not just the Mac that has the plists.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TRACKED = REPO / "ops" / "launchd"
SCRIPT = REPO / "scripts" / "launchd_plists.py"

#: Prefixes of labels owned by other projects. Kept here as well as in the script on purpose:
#: this test is the thing that fails if someone deletes one from the script's tuple.
FOREIGN = ("com.haworks.", "com.tie.")


def _module():
    spec = importlib.util.spec_from_file_location("launchd_plists_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tracked_jobs() -> dict[str, dict]:
    jobs = {p.stem: json.loads(p.read_text()) for p in sorted(TRACKED.glob("*.json"))}
    # A guard that iterates an empty list passes. If the snapshot directory is ever empty or
    # moved, this test must fail rather than quietly certify nothing.
    assert len(jobs) >= 10, "ops/launchd/ holds %d job(s); the snapshot looks wrong" % len(jobs)
    return jobs


def _strings(obj):
    """Every string anywhere in a plist dict, so a log path hidden in an argv is still seen."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


@pytest.mark.parametrize("prefix", FOREIGN)
def test_another_projects_jobs_are_declared_foreign(prefix: str):
    """`owned()` must reject the prefix, or the next snapshot re-adopts the job."""
    mod = _module()
    assert prefix in mod._FOREIGN_PREFIXES, (
        "%r was dropped from _FOREIGN_PREFIXES; --check will report another project's jobs "
        "as BROKEN forever" % prefix)
    assert not mod.owned(prefix + "anything"), "%r is still treated as ours" % prefix


@pytest.mark.parametrize("prefix", FOREIGN)
def test_no_snapshot_file_belongs_to_another_project(prefix: str):
    stray = sorted(lbl for lbl in _tracked_jobs() if lbl.startswith(prefix))
    assert stray == [], (
        "ops/launchd/ tracks jobs from another project: %s. Delete the snapshot; the label "
        "prefix is already in _FOREIGN_PREFIXES so --snapshot will not write it again."
        % ", ".join(stray))


def test_no_tracked_job_logs_into_tmp():
    """`/tmp` is purged on reboot, so a log written there cannot answer a question later.

    Measured 2026-08-20 before this landed: `com.prospector.ops-console` declared
    /tmp/ops-console.{err,out}.log and `com.prospector.control-center` declared
    /tmp/prospector_control_center.log. The console's own error log -- the file you would open
    to find out why the console broke yesterday -- was the clearest case.
    """
    offenders = []
    for label, data in _tracked_jobs().items():
        for key in ("StandardOutPath", "StandardErrorPath"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith("/tmp/"):
                offenders.append("%s %s=%s" % (label, key, value))
        for text in _strings(data):
            if "/tmp/" in text and text.endswith((".log", ".out", ".err")):
                entry = "%s -> %s" % (label, text)
                if not any(e.endswith(text) for e in offenders):
                    offenders.append(entry)
    assert offenders == [], (
        "these jobs log into /tmp, which macOS purges on reboot:\n  "
        + "\n  ".join(sorted(offenders))
        + "\nWrite to the store instead and declare a prune target in "
          "ops/config/log_rotation.yaml (docs/LOGGING_AND_RETENTION.md Part 8 step 3).")
