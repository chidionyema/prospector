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
    PruneTarget,
    Target,
    check,
    check_prune,
    load_declaration,
    main,
    prune,
    resolve,
    resolve_prune,
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


# --- pruning: directories of many files ----------------------------------------------------
#
# Rotation truncates ONE file that grew. Most of this estate's waste is 32,415 small files
# that add up, and the verb for those is delete, not truncate. These tests carry more weight
# than the rotation ones above for one reason: rotation loses history, pruning loses FILES.

def _aged(path: Path, days: float, size: int = 16) -> Path:
    """A file with a chosen age. mtime is set explicitly — a test that waits is a test that
    is skipped."""
    import os
    import time
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    when = time.time() - days * 86400
    os.utime(path, (when, when))
    return path


def _pin_root(monkeypatch, tmp_path: Path) -> None:
    """run() asks git for the repo root; a tmp_path is not a repo."""
    import ops.automations.log_rotation as engine
    monkeypatch.setattr(engine, "repo_root", lambda _start: tmp_path)


def _prune_decl(tmp_path: Path, **entry) -> Path:
    body = {"targets": [{"path": "noisy.log", "why": "a test log"}],
            "prune": [{"path": "junk/*", "why": "throwaway", **entry}]}
    path = tmp_path / "decl.yaml"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_age_prunes_the_old_and_spares_the_new(tmp_path):
    _aged(tmp_path / "junk" / "old.txt", days=30)
    _aged(tmp_path / "junk" / "new.txt", days=1)
    decl = load_declaration(_prune_decl(tmp_path, older_than_days=14))

    entry = check_prune(decl, tmp_path)[0]
    assert entry["files"] == 2
    assert [Path(p).name for p in entry["paths"]] == ["old.txt"]


def test_keep_newest_bounds_a_series_that_grows_faster_than_it_ages(tmp_path):
    """Six 51 MB snapshots in one morning is the real shape. Age cannot bound that."""
    for i in range(6):
        _aged(tmp_path / "junk" / f"snap-{i}.gz", days=i / 24)
    decl = load_declaration(_prune_decl(tmp_path, keep_newest=3))

    entry = check_prune(decl, tmp_path)[0]
    assert entry["doomed"] == 3
    kept = {Path(p).name for p in entry["paths"]}
    assert kept == {"snap-3.gz", "snap-4.gz", "snap-5.gz"}, kept


def test_both_bounds_together_are_a_conjunction_not_a_union(tmp_path):
    """`older_than_days: 30, keep_newest: 5` must mean "thirty days AND never fewer than
    five copies". Read as a union it deletes recent files the operator asked to keep."""
    for i in range(8):
        _aged(tmp_path / "junk" / f"f{i}.txt", days=i * 10)   # 0, 10, 20 ... 70 days
    decl = load_declaration(_prune_decl(tmp_path, older_than_days=30, keep_newest=5))

    entry = check_prune(decl, tmp_path)[0]
    doomed = sorted(Path(p).name for p in entry["paths"])
    # Older than 30d: f4..f7. Outside the newest five (f0..f4): f5, f6, f7. Both: f5, f6, f7.
    assert doomed == ["f5.txt", "f6.txt", "f7.txt"], doomed


def test_a_prune_target_with_no_bound_is_refused(tmp_path):
    """A declaration that can express "delete everything" will eventually contain one."""
    with pytest.raises(CannotEstablish) as exc:
        load_declaration(_prune_decl(tmp_path))
    assert "delete everything" in str(exc.value)


def test_a_symlink_is_never_deleted(tmp_path):
    """Following one deletes a file somewhere the declaration never named."""
    outside = _aged(tmp_path / "elsewhere" / "precious.txt", days=99)
    (tmp_path / "junk").mkdir(parents=True, exist_ok=True)
    (tmp_path / "junk" / "link.txt").symlink_to(outside)
    decl = load_declaration(_prune_decl(tmp_path, older_than_days=1))

    entry = check_prune(decl, tmp_path)[0]
    assert entry["paths"] == []
    prune({**entry, "paths": entry["paths"]})
    assert outside.exists()


def test_a_directory_is_never_deleted(tmp_path):
    _aged(tmp_path / "junk" / "sub" / "leaf.txt", days=99)
    decl = load_declaration(_prune_decl(tmp_path, older_than_days=1))
    entry = check_prune(decl, tmp_path)[0]
    assert entry["paths"] == [], "a glob of one level matched a directory"
    assert (tmp_path / "junk" / "sub").is_dir()


def test_a_git_directory_is_skipped_however_the_glob_is_written(tmp_path):
    """A glob reaching into an object store destroys history and looks like deleting logs."""
    _aged(tmp_path / "junk" / ".git" / "objects" / "ab" / "cd", days=99)
    body = {"targets": [{"path": "noisy.log", "why": "t"}],
            "prune": [{"path": "junk/**/*", "why": "t", "older_than_days": 1}]}
    decl_path = tmp_path / "d.yaml"
    decl_path.write_text(json.dumps(body), encoding="utf-8")
    decl = load_declaration(decl_path)

    assert check_prune(decl, tmp_path)[0]["paths"] == []


def test_exclude_spares_the_live_file_a_daemon_is_writing(tmp_path):
    """The live *.log files are ROTATED, never deleted underneath an open descriptor."""
    _aged(tmp_path / "junk" / "gateway.log", days=99)
    _aged(tmp_path / "junk" / "gateway.log.3", days=99)
    decl = load_declaration(_prune_decl(tmp_path, older_than_days=1, exclude=["*.log"]))

    entry = check_prune(decl, tmp_path)[0]
    assert [Path(p).name for p in entry["paths"]] == ["gateway.log.3"]


def test_over_the_blast_radius_cap_nothing_is_deleted(tmp_path):
    """Deleting "most of it" and reporting success leaves a half-applied policy."""
    for i in range(5):
        _aged(tmp_path / "junk" / f"f{i}.txt", days=99)
    decl = load_declaration(_prune_decl(tmp_path, older_than_days=1, max_delete=2))

    entry = check_prune(decl, tmp_path)[0]
    assert entry["over_cap"] is True
    receipt = prune(entry)
    assert receipt["deleted"] == 0
    assert "max_delete" in receipt["refused"]
    assert len(list((tmp_path / "junk").iterdir())) == 5


def test_a_report_only_run_deletes_nothing(tmp_path, monkeypatch):
    """Report mode before fix mode. The check must never be the change."""
    for i in range(4):
        _aged(tmp_path / "junk" / f"f{i}.txt", days=99)
    config = _prune_decl(tmp_path, older_than_days=1)
    _pin_root(monkeypatch, tmp_path)

    result = run(config, tmp_path, fix=False)
    assert result["status"] == "findings"
    assert len(list((tmp_path / "junk").iterdir())) == 4


def test_fix_deletes_and_reports_what_it_freed(tmp_path, monkeypatch):
    for i in range(4):
        _aged(tmp_path / "junk" / f"f{i}.txt", days=99, size=1000)
    _aged(tmp_path / "junk" / "keep.txt", days=0)
    config = _prune_decl(tmp_path, older_than_days=1)
    _pin_root(monkeypatch, tmp_path)

    result = run(config, tmp_path, fix=True)
    assert result["pruned"][0]["deleted"] == 4
    assert result["pruned"][0]["bytes_freed"] == 4000
    assert [p.name for p in (tmp_path / "junk").iterdir()] == ["keep.txt"]
    # Re-checked after the fix, so a green report means green NOW, not green before the work.
    assert result["status"] == "ok"


def test_a_prune_finding_reaches_the_same_findings_list_the_console_reads(tmp_path, monkeypatch):
    """Consumers already read `findings`. A second list would be a second thing to teach them."""
    _aged(tmp_path / "junk" / "old.txt", days=99)
    _pin_root(monkeypatch, tmp_path)
    result = run(_prune_decl(tmp_path, older_than_days=1), tmp_path, fix=False)
    assert any("past 1d" in f["what"] for f in result["findings"]), result["findings"]


def test_the_live_declaration_bounds_every_prune_target_and_spares_durable_state(tmp_path):
    """The guard on the declaration itself. Everything the file says is deliberately NOT
    pruned is named here, so adding it later fails a test rather than a disk."""
    repo = Path(__file__).resolve().parents[2]
    decl = load_declaration(repo / "ops" / "config" / "log_rotation.yaml")

    assert decl.prunes, "the declaration must prune something"
    for target in decl.prunes:
        assert target.why, f"{target.path} has no reason"
        assert target.older_than_days > 0 or target.keep_newest > 0, target.path
        for durable in ("prospector.jsonl", "complaint_ledger", "complaint_register",
                        "node_modules", "venv", ".git/"):
            assert durable not in target.path, f"{target.path} names durable state"


# ── a declared path must follow the STORE, not the checkout the process runs from ──────────

def test_an_environment_variable_in_a_declared_path_expands(tmp_path, monkeypatch):
    store = tmp_path / "canonical-store"
    store.mkdir()
    (store / "backup.log").write_text("x" * 2_000_000)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(store))

    decl = Declaration(targets=[Target(path="$PROSPECTOR_STORE_DIR/*.log", max_mb=1.0)])
    found = resolve(decl.targets[0], tmp_path / "some-other-checkout")
    assert found == [store / "backup.log"]


def test_an_unset_variable_is_refused_not_silently_matched_as_nothing(tmp_path, monkeypatch):
    """expandvars leaves an unset $VAR literal, so the glob matches nothing and the target
    reports ABSENT. A policy that is switched off must not report as a policy with no work."""
    monkeypatch.delenv("PROSPECTOR_STORE_DIR", raising=False)
    with pytest.raises(CannotEstablish) as exc:
        resolve(Target(path="$PROSPECTOR_STORE_DIR/*.log", max_mb=1.0), tmp_path)
    assert "not set" in str(exc.value)


def test_a_prune_target_gets_the_same_variable_guard(tmp_path, monkeypatch):
    monkeypatch.delenv("PROSPECTOR_STORE_DIR", raising=False)
    with pytest.raises(CannotEstablish):
        resolve_prune(PruneTarget(path="$PROSPECTOR_STORE_DIR/**/*", older_than_days=1), tmp_path)


def test_a_bare_run_still_works_without_the_variable_set(tmp_path, monkeypatch):
    """The scheduled job exports it; a developer typing the command does not."""
    monkeypatch.delenv("PROSPECTOR_STORE_DIR", raising=False)
    _pin_root(monkeypatch, tmp_path)
    store = tmp_path / "store"
    store.mkdir()
    (store / "backup.log").write_text("x" * 2_000_000)
    config = tmp_path / "decl.yaml"
    config.write_text("targets:\n  - path: $PROSPECTOR_STORE_DIR/*.log\n    max_mb: 1\n    keep: 2\n")

    result = run(config, tmp_path)
    assert result["status"] == "findings", result
    assert any("backup.log" in f["where"] for f in result["findings"]), result["findings"]


def test_a_file_git_tracks_is_never_pruned(tmp_path, monkeypatch):
    """The first --fix run deleted six committed files: ~/.hermes/backups/*.bak are in git
    and the declaration named them by glob. `git checkout` brought them back, so nothing was
    lost that time. Skipping a `.git` path segment protects the object store and says nothing
    about a tracked file in an ordinary directory."""
    import subprocess

    from ops.automations.log_rotation import _tracked_under
    _tracked_under.cache_clear()

    repo = tmp_path / "repo"
    (repo / "backups").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    committed = repo / "backups" / "state.db.bak"
    scratch = repo / "backups" / "scratch.db.bak"
    for path in (committed, scratch):
        path.write_text("x")
        _aged(path, days=90)
    subprocess.run(["git", "-C", str(repo), "add", "backups/state.db.bak"], check=True)

    found = resolve_prune(PruneTarget(path=str(repo / "backups" / "*.bak"),
                                      older_than_days=30), tmp_path)
    assert found == [scratch], found
    _tracked_under.cache_clear()


def test_when_git_cannot_answer_nothing_is_pruned(tmp_path, monkeypatch):
    """Cannot-establish is a refusal, not a green light. If the tool that knows what is in
    version control will not answer, deleting anyway is the incident this fence prevents,
    with the evidence removed."""

    from ops.automations import log_rotation as engine
    engine._tracked_under.cache_clear()

    old = tmp_path / "old.log"
    old.write_text("x")
    _aged(old, days=90)

    def broken(*a, **kw):
        raise OSError("git is not installed")
    monkeypatch.setattr(engine.subprocess, "run", broken)

    assert engine.resolve_prune(PruneTarget(path=str(tmp_path / "*.log"),
                                            older_than_days=30), tmp_path) == []
    engine._tracked_under.cache_clear()


def test_the_tracked_file_list_is_read_once_per_repository(tmp_path, monkeypatch):
    """One `git ls-files` per repository, however many directories the glob spans.

    This is a performance fence with a real incident behind it. The first version cached the
    tracked-file set with `@functools.lru_cache(maxsize=64)` keyed by DIRECTORY. The declared
    prune targets span 17,065 files across far more than 64 parent directories, so the cache
    thrashed and `git ls-files` re-ran for the same repository over and over. Measured on this
    estate: 67.9s wall for one read-only run, against the 25s the console allows an automation,
    so `/processes` reported log rotation `unknown` rather than clean. Splitting the cache into
    `_repo_top` (per directory) and `_tracked_in_repo` (per repository), both unbounded, took the
    same run to 15.8s with byte-identical output.

    Counting subprocess calls is the only honest way to pin this: a wall-clock assertion would be
    flaky on a loaded box, and it would pass again the day someone re-introduces the bug on a
    faster machine.
    """
    import subprocess as sp

    from ops.automations import log_rotation as engine
    # `getattr` on purpose: the assertion below is what must fail when someone drops a cache,
    # not an AttributeError in the setup. A guard that dies before it measures proves nothing.
    for cache in (engine._tracked_under, engine._repo_top, engine._tracked_in_repo):
        getattr(cache, "cache_clear", lambda: None)()

    repo = tmp_path / "repo"
    repo.mkdir()
    sp.run(["git", "init", "-q", str(repo)], check=True)
    for n in range(200):                     # comfortably past the old maxsize of 64
        _aged(repo / f"d{n}" / "old.log", days=90)

    real_run = engine.subprocess.run
    calls: list[str] = []

    def counting(args, *a, **kw):
        if isinstance(args, (list, tuple)) and "ls-files" in args:
            calls.append("ls-files")
        return real_run(args, *a, **kw)

    monkeypatch.setattr(engine.subprocess, "run", counting)

    found = engine.resolve_prune(PruneTarget(path=str(repo / "**" / "*.log"),
                                             older_than_days=30), tmp_path)
    assert len(found) == 200, len(found)
    assert calls == ["ls-files"], f"{len(calls)} ls-files calls for one repository"

    # `getattr` on purpose: the assertion below is what must fail when someone drops a cache,
    # not an AttributeError in the setup. A guard that dies before it measures proves nothing.
    for cache in (engine._tracked_under, engine._repo_top, engine._tracked_in_repo):
        getattr(cache, "cache_clear", lambda: None)()
