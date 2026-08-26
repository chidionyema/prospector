"""The cold tier: the only copy of a log line that leaves the machine that made it.

`docs/LOGGING_AND_RETENTION.md` Part 8 step 12. Before this, everything the ingest received
lived on one Fly volume and `ops/automations/log_rotation.py` deleted it at 14 days, so losing
the volume lost the whole record and keeping the volume lost it anyway after a fortnight.

Three of the tests below are not about the upload at all. They are about the two places this
mechanism can be quietly switched off without anything going red: the supervisord program that
runs it, and the declaration that watches the result. A copy nothing runs and a copy nothing
grades are both indistinguishable from a healthy estate.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import backup_store as bs  # noqa: E402
from test_backup_store_coverage import FakeS3  # noqa: E402

TODAY = "2026-08-20"


def _line(svc: str, evt: str = "tick.done") -> str:
    """One line in the shape `log_ingest.normalise` guarantees: never less than these five."""
    return json.dumps({"ts": "2026-08-19T09:00:00.000Z", "svc": svc, "lvl": "info",
                       "evt": evt, "host": "engine-1", "msg": "a tick finished"})


@pytest.fixture
def logs(tmp_path, monkeypatch):
    """A log directory the real `log_ingest.log_dir()` resolves to, written in its own names."""
    directory = tmp_path / "logs"
    directory.mkdir()
    monkeypatch.setenv("PROSPECTOR_LOG_DIR", str(directory))
    return directory


def _write(directory: Path, svc: str, day: str, lines: int = 3) -> Path:
    path = directory / f"{svc}-{day}.jsonl"
    path.write_text("".join(_line(svc) + "\n" for _ in range(lines)), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- what is captured

def test_todays_file_is_never_captured(logs):
    """The one file guaranteed to be mid-write.

    The ingest names a file from its own clock at write time and appends to today's file
    continuously. Uploading it would store a torn tail and then have to replace it tomorrow.
    """
    _write(logs, "engine", TODAY)
    _write(logs, "engine", "2026-08-19")
    s3 = FakeS3()
    uploaded, _, problems = bs.archive_logs(s3, "b", today=TODAY)
    assert problems == []
    assert uploaded == ["logs/engine-2026-08-19.jsonl.gz"]
    assert f"logs/engine-{TODAY}.jsonl.gz" not in s3.objects


def test_every_closed_file_lands_and_gunzips_to_the_bytes_that_were_read(logs):
    _write(logs, "engine", "2026-08-18")
    original = _write(logs, "store-api", "2026-08-19", lines=5).read_bytes()
    s3 = FakeS3()
    uploaded, size, problems = bs.archive_logs(s3, "b", today=TODAY)
    assert problems == []
    assert sorted(uploaded) == ["logs/engine-2026-08-18.jsonl.gz",
                                "logs/store-api-2026-08-19.jsonl.gz"]
    assert gzip.decompress(s3.objects["logs/store-api-2026-08-19.jsonl.gz"]) == original
    assert size > 0


def test_a_file_already_in_the_bucket_is_not_uploaded_again(logs):
    _write(logs, "engine", "2026-08-19")
    s3 = FakeS3()
    assert bs.archive_logs(s3, "b", today=TODAY)[0] == ["logs/engine-2026-08-19.jsonl.gz"]
    before = dict(s3.objects)
    assert bs.archive_logs(s3, "b", today=TODAY)[0] == []
    assert s3.objects == before


def test_a_machine_with_no_ingest_reports_nothing_rather_than_failing(logs, tmp_path,
                                                                     monkeypatch, capsys):
    """The laptop, and any host that does not run the ingest. `logs=0` is the truth there, and
    it must not be a problem — a backup that fails over an absent optional source stops running
    for the money database too."""
    monkeypatch.setenv("PROSPECTOR_LOG_DIR", str(tmp_path / "absent"))
    uploaded, size, problems = bs.archive_logs(FakeS3(), "b", today=TODAY)
    assert (uploaded, size, problems) == ([], 0, [])
    assert "does not exist" in capsys.readouterr().out


def test_a_file_the_writer_did_not_name_is_left_alone(logs):
    """`day_files` skips a name its own regex cannot read. Guessing at it would upload a file
    that is not a day file under a key that claims it is."""
    (logs / "notes.jsonl").write_text(_line("engine") + "\n", encoding="utf-8")
    (logs / "engine.jsonl").write_text(_line("engine") + "\n", encoding="utf-8")
    assert bs.archive_logs(FakeS3(), "b", today=TODAY)[0] == []


# --------------------------------------------------------------------------- the read-back

def test_a_truncated_upload_is_caught_and_the_run_fails():
    """The difference between a copy and a backup, in one test.

    `verify: nonempty` was removed from ops/config/offsite_backup.yaml on 2026-08-19 because a
    size cannot tell a whole file from a download that stopped halfway. This is the same
    failure on the way OUT.
    """
    s3 = FakeS3()
    whole = gzip.compress(("".join(_line("engine") + "\n" for _ in range(50))).encode())
    s3.objects["logs/engine-2026-08-19.jsonl.gz"] = whole[: len(whole) // 2]
    problem = bs._verify_log_archive(s3, "b", "logs/engine-2026-08-19.jsonl.gz")
    assert problem, "a half-written gzip read back clean"
    assert "logs/engine-2026-08-19.jsonl.gz" in problem


def test_an_empty_archive_is_a_problem_not_a_success():
    s3 = FakeS3()
    s3.objects["logs/engine-2026-08-19.jsonl.gz"] = gzip.compress(b"")
    assert "zero records" in bs._verify_log_archive(s3, "b", "logs/engine-2026-08-19.jsonl.gz")


@pytest.mark.parametrize("field", bs._LOG_REQUIRED)
def test_a_line_that_lost_a_required_field_is_a_problem(field):
    """The five fields `log_ingest.normalise` guarantees on every line it writes. A restored
    line missing one did not survive the round trip, whatever its size says."""
    record = json.loads(_line("engine"))
    record.pop(field)
    s3 = FakeS3()
    s3.objects["logs/engine-2026-08-19.jsonl.gz"] = gzip.compress(
        (json.dumps(record) + "\n").encode())
    problem = bs._verify_log_archive(s3, "b", "logs/engine-2026-08-19.jsonl.gz")
    assert field in problem, problem


def test_a_line_that_is_not_json_names_its_line_number():
    s3 = FakeS3()
    s3.objects["logs/engine-2026-08-19.jsonl.gz"] = gzip.compress(
        (_line("engine") + "\n" + "{not json\n").encode())
    assert "line 2" in bs._verify_log_archive(s3, "b", "logs/engine-2026-08-19.jsonl.gz")


def test_a_run_that_could_not_verify_prunes_nothing(logs, monkeypatch):
    """The prune deletes the OLDEST copies. A run that cannot prove what it just uploaded is
    exactly the run that must not be trusted to choose what to delete."""
    _write(logs, "engine", "2026-08-19")
    s3 = FakeS3()
    s3.objects["logs/engine-2020-01-01.jsonl.gz"] = gzip.compress(b"{}\n")
    monkeypatch.setattr(bs, "_verify_log_archive", lambda *a, **k: "broken on purpose")
    uploaded, _, problems = bs.archive_logs(s3, "b", keep_days=1, today=TODAY)
    assert uploaded == [] and problems == ["broken on purpose"]
    assert s3.deleted == [], "a failing run deleted the old copies anyway"
    assert "logs/engine-2020-01-01.jsonl.gz" in s3.objects


def test_a_failed_verification_leaves_the_object_where_it_is():
    """It is still the only copy of that day that ever left the machine. Deleting it to keep
    the bucket tidy would turn a doubt into a loss."""
    source = re.sub(r"\s+", " ", (REPO / "scripts" / "backup_store.py").read_text())
    assert "problems.append(problem) continue" in source, (
        "archive_logs no longer records the problem and moves on; check it does not delete "
        "the object it failed to verify")


# --------------------------------------------------------------------------- the prune

def test_the_prune_reads_the_day_out_of_the_key_not_the_objects_timestamp():
    """An object re-uploaded, or copied inside the bucket during a provider move, gets a fresh
    LastModified while still holding a log from March. The key names the day the records are
    from, and it is the only thing that survives a copy."""
    s3 = FakeS3()
    for day in ("2026-01-01", "2026-05-22", "2026-08-19"):
        s3.objects[f"logs/engine-{day}.jsonl.gz"] = gzip.compress(b"{}\n")
    stale = bs._prune_log_archives(s3, "b", keep_days=90, today=TODAY)
    assert stale == ["logs/engine-2026-01-01.jsonl.gz"]
    assert sorted(s3.objects) == ["logs/engine-2026-05-22.jsonl.gz",
                                  "logs/engine-2026-08-19.jsonl.gz"]


def test_keep_days_zero_disables_the_prune():
    s3 = FakeS3()
    s3.objects["logs/engine-2001-01-01.jsonl.gz"] = gzip.compress(b"{}\n")
    assert bs._prune_log_archives(s3, "b", keep_days=0, today=TODAY) == []
    assert s3.deleted == []


def test_a_key_this_cannot_parse_is_never_deleted():
    """The safe direction for the one naming rule this script owns rather than imports."""
    s3 = FakeS3()
    for key in ("logs/README", "logs/engine-2001-01.jsonl.gz", "logs/nested/x-2001-01-01.jsonl.gz"):
        s3.objects[key] = b"x"
    assert bs._prune_log_archives(s3, "b", keep_days=1, today=TODAY) == []
    assert s3.deleted == []


# ------------------------------------------------------ the two ways this is switched off

def _supervisord_backup_command() -> str:
    text = (REPO / "deploy" / "engine" / "supervisord.conf").read_text()
    block = text[text.index("[program:backup]"):]
    for line in block.splitlines():
        if line.startswith("command="):
            return line
    raise AssertionError("[program:backup] has no command= line")


def test_the_job_that_runs_this_does_not_skip_it():
    command = _supervisord_backup_command()
    assert "scripts/backup_store.py" in command
    assert "--skip-logs" not in command, (
        "[program:backup] passes --skip-logs, so nothing copies the logs off the volume "
        "and every other check in this file passes anyway")


def test_the_cold_tier_runs_at_least_twice_inside_the_hot_window():
    """The coupling that makes this a mechanism rather than two settings.

    `ops/automations/log_rotation.py` DELETES the local file at `older_than_days`. This job is
    the only thing that copies it first. If the backup period ever grew past that window, log
    files would be deleted having never been uploaded, and nothing else in the estate would
    notice. Twice, not once, so one missed run is not a lost day.
    """
    command = _supervisord_backup_command()
    period_s = int(re.search(r"periodic\.sh (\d+)", command).group(1))
    rotation = yaml.safe_load((REPO / "ops" / "config" / "log_rotation.yaml").read_text())
    targets = [t for t in rotation["prune"] if t["path"] == "/data/logs/*.jsonl"]
    assert len(targets) == 1, "the /data/logs prune target moved; this check is now blind"
    window_days = targets[0]["older_than_days"]
    assert 2 * period_s / 86400 <= window_days, (
        f"the backup runs every {period_s}s but the hot tier deletes at {window_days} days, "
        "so a log file can be deleted before it is ever copied off the machine")


def test_the_declaration_watches_the_prefix_this_code_writes():
    """A copy nobody grades is discovered during a restore. The freshness entry and the prefix
    in the code are two halves of one mechanism, written in two files."""
    decl = yaml.safe_load((REPO / "ops" / "config" / "offsite_backup.yaml").read_text())
    watched = {entry["name"]: entry for entry in decl["watch"]}
    assert "engine-logs" in watched, (
        "nothing watches the log cold tier, so a cold tier that stops working is silent")
    assert watched["engine-logs"]["prefix"] == bs.LOGS_PREFIX, (
        "the watched prefix and the prefix archive_logs() writes to have drifted apart")


def test_the_cold_window_outlasts_the_hot_one():
    """90 against 14. A cold tier shorter than the hot tier answers no question the local disk
    does not already answer, and would make this whole file ceremony."""
    rotation = yaml.safe_load((REPO / "ops" / "config" / "log_rotation.yaml").read_text())
    hot = [t for t in rotation["prune"] if t["path"] == "/data/logs/*.jsonl"][0]
    assert bs.DEFAULT_LOGS_KEEP_DAYS > hot["older_than_days"]
