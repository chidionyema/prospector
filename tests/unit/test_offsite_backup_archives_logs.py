"""The log cold tier, graded by running the command the declaration actually ships.

`docs/LOGGING_AND_RETENTION.md` Part 8 step 12. `ops/config/log_rotation.yaml` deletes
`/data/logs/*.jsonl` at 14 days as a data-protection bound, so 14 days is the whole margin
between "hot copy expired" and "gone". If the offsite copy stops landing and nobody notices for
two weeks, the logs are gone from both places at once.

Every test here reads the argv out of `ops/config/offsite_backup.yaml` and runs THAT, rather
than a copy of it pasted into this file. A test that re-states the command tests the paste. The
one thing it substitutes is the source directory: `/data/logs` exists on the engine and on no
developer machine, so argv[-2] is swapped for a tmp_path and the swap is asserted, not assumed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tarfile
from datetime import date, timedelta
from pathlib import Path

import pytest

import ops.automations.offsite_backup as offsite

REPO = Path(__file__).resolve().parents[2]
DECLARATION = REPO / "ops" / "config" / "offsite_backup.yaml"

#: The literal the declaration must name. Not derived from the declaration, or the test that
#: checks the path would read the path it is checking.
ENGINE_LOG_DIR = "/data/logs"


@pytest.fixture(scope="module")
def source() -> offsite.Source:
    sources = {s.name: s for s in offsite.load_declaration(DECLARATION).sources}
    assert "logs" in sources, (
        "ops/config/offsite_backup.yaml declares no `logs` source, so nothing copies "
        "/data/logs off the engine before log_rotation deletes it at 14 days")
    return sources["logs"]


def _run(source: offsite.Source, src_dir: Path, dest: Path) -> subprocess.CompletedProcess:
    """Run the declared command with argv[-2] pointed at a real directory."""
    argv = list(source.fetch)
    assert argv[-2] == ENGINE_LOG_DIR, (
        "the log directory is expected at argv[-2]; the declaration now reads %r" % (argv,))
    argv[-2] = str(src_dir)
    argv = [str(dest) if part == "{dest}" else part for part in argv]
    assert argv[0] in ("python3", "python", sys.executable), argv[0]
    argv[0] = sys.executable  # the engine's python3 is this interpreter's stand-in
    return subprocess.run(argv, capture_output=True, text=True)


def _write_day(directory: Path, service: str, day: date, lines: int = 1) -> Path:
    path = directory / ("%s-%s.jsonl" % (service, day.isoformat()))
    path.write_text("".join(json.dumps({"svc": service, "n": i}) + "\n" for i in range(lines)))
    return path


def test_it_archives_yesterday_and_only_yesterday(source: offsite.Source, tmp_path: Path):
    """Today's file is still being written to. Older files were archived on their own day."""
    logs = tmp_path / "logs"
    logs.mkdir()
    today = date.today()
    yesterday = today - timedelta(days=1)
    _write_day(logs, "scheduler", yesterday, lines=3)
    _write_day(logs, "store-api", yesterday, lines=2)
    _write_day(logs, "scheduler", today)
    _write_day(logs, "scheduler", today - timedelta(days=2))

    dest = tmp_path / "out.tgz"
    done = _run(source, logs, dest)
    assert done.returncode == 0, done.stderr

    with tarfile.open(dest, "r:gz") as archive:
        names = sorted(archive.getnames())
    assert names == ["scheduler-%s.jsonl" % yesterday, "store-api-%s.jsonl" % yesterday], (
        "the archive holds %r; it must hold yesterday's files, and no others" % (names,))


def test_an_empty_day_fails_loudly_instead_of_uploading_nothing(
    source: offsite.Source, tmp_path: Path
):
    """`[program:log-ingest]` runs continuously, so no file for a whole day is an outage.

    An empty archive would upload, pass `verify: tgz`, and be graded fresh -- a green light
    reporting the exact failure it exists to catch.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    _write_day(logs, "scheduler", date.today())  # today only: nothing to archive

    dest = tmp_path / "out.tgz"
    done = _run(source, logs, dest)
    assert done.returncode != 0, (
        "an empty day exited 0; a run that archived nothing would be recorded as a backup")
    combined = done.stdout + done.stderr
    assert str(date.today() - timedelta(days=1)) in combined, combined
    assert str(logs) in combined, (
        "the failure must name the directory it looked in, or on-call has to go and find it")


def test_it_survives_a_directory_that_does_not_exist(source: offsite.Source, tmp_path: Path):
    """First boot, or a volume mounted late. A traceback and a stated cause are not the same."""
    done = _run(source, tmp_path / "never-created", tmp_path / "out.tgz")
    assert done.returncode != 0
    assert "Traceback" not in done.stderr, (
        "a missing log directory must be stated, not raised:\n%s" % done.stderr)


def test_the_declared_path_is_where_the_ingest_actually_writes(monkeypatch, tmp_path: Path):
    """The declaration hardcodes /data/logs. `log_ingest.log_dir()` derives it from the store.

    Two statements of one fact, so this fails if either moves. The reason the declaration cannot
    use ${PROSPECTOR_LOG_DIR} is in the comment beside it: `_expand` raises on an unset variable
    and would take the whole run -- money database included -- to unknown.
    """
    from prospector import log_ingest

    monkeypatch.delenv("PROSPECTOR_LOG_DIR", raising=False)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", "/data/store")  # the engine image's value
    assert str(log_ingest.log_dir()) == ENGINE_LOG_DIR, (
        "the ingest writes to %s but ops/config/offsite_backup.yaml archives %s"
        % (log_ingest.log_dir(), ENGINE_LOG_DIR))


def test_retention_and_verification_are_declared_not_defaulted(source: offsite.Source):
    """90 days of cold copies, and an archive opened before it counts.

    `keep` is the retention rule itself: this repo holds the number, not a lifecycle rule in
    Cloudflare's console that no clone can read and nothing here can grade. Dropping the key
    silently falls back to DEFAULT_KEEP and shortens retention by two thirds.
    """
    assert source.keep == 90, (
        "cold retention is %d copies, not the 90 days docs/LOGGING_AND_RETENTION.md "
        "Part 8 step 12 states" % source.keep)
    assert source.verify == "tgz", (
        "verify=%r: a size check is believed, and a gzip stream that ends mid-member is "
        "still non-empty" % source.verify)
    assert source.keep != offsite.DEFAULT_KEEP or offsite.DEFAULT_KEEP == 90
