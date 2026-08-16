"""The log-rotation automation, proved on the BROKEN state as well as the clean one.

Two things here are worth more than the rest. The rotation must keep the file's INODE, because
a daemon holds the log open by descriptor and a rename leaves it writing to the renamed file
forever. And an oversized log must be a finding, not a note: an unrotated log is what made a
lifetime count read as today's and put a wrong number in a planning document.

No network, no daemon. Every file is a throwaway.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from ops.automations.log_rotation import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_UNKNOWN,
    CannotEstablish,
    Declaration,
    Target,
    check,
    load_declaration,
    main,
    rotate,
    run,
)

MB = 1024 * 1024


def _log(path: Path, megabytes: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * int(megabytes * MB))
    return path


def _declaration(tmp_path: Path, **overrides) -> Path:
    body = {"max_mb": 1, "keep": 2, "targets": [{"path": "noisy.log", "why": "a test log"}]}
    body.update(overrides)
    path = tmp_path / "decl.yaml"
    path.write_text(json.dumps(body), encoding="utf-8")  # JSON is valid YAML
    return path


# --- the check fires on the broken state ---------------------------------------------------

def test_an_oversized_log_is_a_finding(tmp_path):
    _log(tmp_path / "noisy.log", 3)
    decl = Declaration(targets=[Target(path="noisy.log", max_mb=1)])

    looked, findings = check(decl, tmp_path)

    assert len(findings) == 1
    assert "3.0 MB, limit 1 MB" in findings[0]["what"]
    assert looked[0]["over"] is True


def test_a_log_under_its_limit_is_clean(tmp_path):
    _log(tmp_path / "noisy.log", 0.2)
    decl = Declaration(targets=[Target(path="noisy.log", max_mb=1)])

    _, findings = check(decl, tmp_path)

    assert findings == []


def test_a_declared_log_that_is_not_on_disk_is_reported_but_not_red(tmp_path):
    # A job that has not run yet has no log. Calling that red trains the reader to ignore red.
    decl = Declaration(targets=[Target(path="never-written.log", max_mb=1)])

    looked, findings = check(decl, tmp_path)

    assert findings == []
    assert looked[0]["exists"] is False


def test_a_glob_target_checks_every_match(tmp_path):
    _log(tmp_path / "logs" / "one.log", 3)
    _log(tmp_path / "logs" / "two.log", 0.1)
    decl = Declaration(targets=[Target(path="logs/*.log", max_mb=1)])

    looked, findings = check(decl, tmp_path)

    assert len(looked) == 2
    assert [f["where"] for f in findings] == [str(tmp_path / "logs" / "one.log")]


# --- rotation keeps the descriptor the daemon is holding -----------------------------------

def test_rotation_truncates_in_place_and_keeps_the_inode(tmp_path):
    """The trap this test exists for. Renaming a log a daemon holds open sends every later
    line into the renamed file: the fresh log stays empty and the process reads as silent."""
    log = _log(tmp_path / "noisy.log", 2)
    before = log.stat().st_ino

    rotate(log, keep=5)

    assert log.exists(), "the live path must still be there for the open descriptor"
    assert log.stat().st_ino == before, "rotation renamed the file instead of truncating it"
    assert log.stat().st_size == 0


def test_the_archive_holds_what_the_log_held(tmp_path):
    log = tmp_path / "noisy.log"
    log.write_bytes(b"the line that mattered\n" * 1000)

    receipt = rotate(log, keep=5)

    archive = log.with_name(receipt["archive"])
    assert gzip.open(archive, "rb").read() == b"the line that mattered\n" * 1000
    assert receipt["bytes_rotated"] == 23000


def test_a_line_written_during_the_copy_is_not_lost(tmp_path):
    """Copy-truncate has a real race: bytes appended after the copy would be dropped by a
    naive truncate. The tail is read back and rewritten instead."""
    log = tmp_path / "noisy.log"
    log.write_bytes(b"old\n")

    import ops.automations.log_rotation as engine

    original = engine.shutil.copyfileobj

    def copy_then_append(source, sink, length=0):
        original(source, sink, length)
        with log.open("ab") as racer:
            racer.write(b"written during the copy\n")

    engine.shutil.copyfileobj = copy_then_append
    try:
        rotate(log, keep=5)
    finally:
        engine.shutil.copyfileobj = original

    assert log.read_bytes() == b"written during the copy\n"


def test_pruning_keeps_the_newest_archives(tmp_path):
    log = tmp_path / "noisy.log"
    for stamp in ("20260810T000000Z", "20260811T000000Z", "20260812T000000Z"):
        log.with_name(f"noisy.log.{stamp}.gz").write_bytes(b"old")
    log.write_bytes(b"current\n")

    receipt = rotate(log, keep=2)

    # Three archives existed, this run adds a fourth, keep 2 -> the two oldest go and the
    # newest surviving archive is the one just written.
    left = sorted(p.name for p in tmp_path.glob("noisy.log.*.gz"))
    assert receipt["pruned"] == ["noisy.log.20260810T000000Z.gz", "noisy.log.20260811T000000Z.gz"]
    assert left[0] == "noisy.log.20260812T000000Z.gz"
    assert left[1] == receipt["archive"]
    assert len(left) == 2


# --- could not establish is never clean ----------------------------------------------------

def test_a_missing_declaration_is_unknown(tmp_path):
    result = run(tmp_path / "nope.yaml", tmp_path)

    assert result["status"] == "unknown"
    assert "not found" in result["reason"]


def test_a_declaration_with_no_targets_is_unknown(tmp_path):
    with pytest.raises(CannotEstablish, match="no targets"):
        load_declaration(_declaration(tmp_path, targets=[]))


def test_a_target_with_no_path_is_unknown(tmp_path):
    with pytest.raises(CannotEstablish, match="needs a `path:`"):
        load_declaration(_declaration(tmp_path, targets=[{"why": "forgot the path"}]))


# --- the interface -------------------------------------------------------------------------

def test_fix_rotates_what_is_over_and_leaves_the_rest(tmp_path, monkeypatch, capsys):
    _log(tmp_path / "noisy.log", 3)
    small = _log(tmp_path / "quiet.log", 0.1)
    config = _declaration(tmp_path, targets=[
        {"path": "noisy.log"}, {"path": "quiet.log"},
    ])
    import ops.automations.log_rotation as engine
    monkeypatch.setattr(engine, "repo_root", lambda _start: tmp_path)

    assert main(["--config", str(config)]) == EXIT_FINDINGS
    assert main(["--fix", "--config", str(config)]) == EXIT_OK
    assert main(["--config", str(config)]) == EXIT_OK

    assert (tmp_path / "noisy.log").stat().st_size == 0
    assert small.stat().st_size == int(0.1 * MB), "a log under its limit must not be touched"
    assert len(list(tmp_path.glob("noisy.log.*.gz"))) == 1


def test_exit_codes_are_distinct(tmp_path, monkeypatch):
    import ops.automations.log_rotation as engine
    monkeypatch.setattr(engine, "repo_root", lambda _start: tmp_path)

    assert main(["--config", str(tmp_path / "missing.yaml")]) == EXIT_UNKNOWN
    _log(tmp_path / "noisy.log", 3)
    assert main(["--config", str(_declaration(tmp_path))]) == EXIT_FINDINGS
    (tmp_path / "noisy.log").write_bytes(b"small")
    assert main(["--config", str(_declaration(tmp_path))]) == EXIT_OK


def test_json_mode_carries_what_the_console_renders(tmp_path, monkeypatch, capsys):
    import ops.automations.log_rotation as engine
    monkeypatch.setattr(engine, "repo_root", lambda _start: tmp_path)
    _log(tmp_path / "noisy.log", 3)

    main(["--json", "--config", str(_declaration(tmp_path))])

    payload = json.loads(capsys.readouterr().out)
    for key in ("automation", "status", "checked", "findings", "ran_at", "probe"):
        assert key in payload, f"the console renders {key}"
    assert payload["automation"] == "log_rotation"


def test_the_live_declaration_parses_and_leaves_the_ledger_alone(tmp_path):
    """store/prospector.jsonl looks like a log and is the durable spend ledger. Rotating it
    changes what the daily cap believes."""
    repo = Path(__file__).resolve().parents[2]
    decl = load_declaration(repo / "ops" / "config" / "log_rotation.yaml")

    assert decl.targets, "the declaration must name something"
    for target in decl.targets:
        assert "prospector.jsonl" not in target.path
        assert target.why, f"{target.path} has no reason for its limit"
