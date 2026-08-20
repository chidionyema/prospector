"""The retention sweep must delete from the directory the ingest actually writes to.

Step 11 of `docs/LOGGING_AND_RETENTION.md`. Two halves have to agree and they are written in
different languages, which is the whole reason this file exists:

    prospector/log_ingest.py       Python. `log_dir()` decides where a line lands.
    ops/config/log_rotation.yaml   YAML. A glob decides what the sweep deletes.

Nothing makes them the same directory except a string typed twice. Get it wrong and the sweep
runs green forever while `/data/logs` fills, which is the class recorded in
`a-workflow-that-can-never-run-fails-as-noise.md`: the job cannot do its work, and it fails as
noise because "0 files deleted" and "0 files needed deleting" print identically.

The second thing pinned here is that something on the engine actually RUNS it. Measured
2026-08-20 before this step: `rg -n log_rotation ops/launchd/ .github/workflows/ deploy/engine/`
returned exactly one hit, the Mac plist. `/data/logs` had nothing pruning it at all, so adding a
declaration on its own would have been a policy that is off, reported as a policy with nothing
to do.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from ops.automations import log_rotation
from prospector import log_ingest

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "ops" / "config" / "log_rotation.yaml"
DOCKERFILE = REPO / "deploy" / "engine" / "Dockerfile"
SUPERVISORD = REPO / "deploy" / "engine" / "supervisord.conf"

HOT_DAYS = 14  # docs/LOGGING_AND_RETENTION.md §5.2. Not a disk number; see the doc and the why:.


def _log_target() -> dict:
    """The one prune target whose glob is the engine's ingest directory."""
    prunes = yaml.safe_load(CONFIG.read_text())["prune"]
    hits = [t for t in prunes if t["path"].endswith(".jsonl")]
    assert len(hits) == 1, f"expected exactly one ingested-log prune target, got {hits}"
    return hits[0]


def _engine_store_dir() -> str:
    m = re.search(r"^\s*(?:ENV\s+)?PROSPECTOR_STORE_DIR=(\S+)", DOCKERFILE.read_text(), re.M)
    assert m, "PROSPECTOR_STORE_DIR is not declared in the engine Dockerfile"
    return m.group(1)


# --------------------------------------------------------------------------- the agreement


def test_the_declared_sweep_path_is_where_the_ingest_writes(monkeypatch):
    """The regression this file exists for, checked in the engine's own declared environment.

    The config states `/data/logs` as a literal because an environment variable would have to
    be set on every host that runs the sweep, including this Mac, which has no ingest — and an
    unset one takes the whole run to `unknown` (see the test below). The price of the literal
    is that it can drift from `log_dir()`. This is the payment.
    """
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", _engine_store_dir())
    monkeypatch.delenv("PROSPECTOR_LOG_DIR", raising=False)

    swept = Path(log_rotation._expand(_log_target()["path"])).parent
    assert swept == log_ingest.log_dir(), (
        f"the sweep would delete from {swept}, the ingest writes to {log_ingest.log_dir()}")


def test_the_declaration_needs_no_environment_variable(monkeypatch):
    """An unset `$VAR` is not a quiet no-op here: it blanks the ENTIRE run.

    `_assert_expanded` raises `CannotEstablish`, and `run()` catches it at the top level and
    returns `status="unknown"` — so one unset variable on the Mac would also stop reporting on
    Hermes' logs, the Adobe pile and the daemon's own stdout. That is why the engine target is
    an absolute path, and this test is what stops someone "tidying" it into a variable.
    """
    assert "$" not in _log_target()["path"]

    monkeypatch.delenv("PROSPECTOR_LOG_DIR", raising=False)
    with pytest.raises(log_rotation.CannotEstablish) as exc:
        log_rotation.resolve_prune(
            log_rotation.PruneTarget(path="$PROSPECTOR_LOG_DIR/*.jsonl"), REPO)
    assert "not set" in str(exc.value)


def test_the_target_is_harmless_on_a_host_that_has_no_ingest():
    """The Mac runs this same declaration every six hours and must stay clean, not `unknown`."""
    target = _log_target()
    assert target["path"].startswith("/"), "an absolute path resolves the same on every host"
    assert not Path(target["path"]).parent.exists() or log_ingest.log_dir().exists()

    decl = log_rotation.Declaration(
        targets=[], prunes=[log_rotation.PruneTarget(path=target["path"],
                                                     older_than_days=HOT_DAYS)])
    entries = log_rotation.check_prune(decl, REPO)  # must not raise on this machine
    assert entries[0]["doomed"] >= 0


# --------------------------------------------------------------------------- the policy


def test_the_hot_window_is_the_one_the_policy_states():
    target = _log_target()
    assert target["older_than_days"] == HOT_DAYS
    assert not target.get("keep_newest"), (
        "a count bound holds a file forever on a service that stopped emitting, which is "
        "exactly the case where a stale log still holds personal data and answers nothing")
    assert "5.2" in target["why"] and "5.3" in target["why"], (
        "14 days is a data-protection decision; the declaration must say where that is written")


def test_something_on_the_engine_actually_runs_the_sweep():
    """The declaration is inert on its own. Before this step the only reference to
    log_rotation outside the config was the Mac plist, so nothing pruned /data/logs at all."""
    conf = SUPERVISORD.read_text()
    assert "[program:log-retention]" in conf
    block = conf.split("[program:log-retention]", 1)[1].split("[program:", 1)[0]
    command = next(l for l in block.splitlines() if l.startswith("command="))
    assert "ops.automations.log_rotation" in command, "a second module would be a second engine"
    assert "--fix" in command, "report-only on a schedule deletes nothing"
    assert "receipt.sh" in command, "an unrecorded exit code is the Step 2 defect again"


# --------------------------------------------------------------------------- the behaviour


def _aged(directory: Path, name: str, days: float) -> Path:
    path = directory / name
    path.write_text('{"ts":"x","svc":"store-api","level":"info","msg":"y"}\n')
    when = time.time() - days * 86400
    os.utime(path, (when, when))
    return path


def _decl(directory: Path) -> log_rotation.Declaration:
    return log_rotation.Declaration(
        targets=[],
        prunes=[log_rotation.PruneTarget(path=str(directory / "*.jsonl"),
                                         older_than_days=HOT_DAYS)])


def test_report_mode_names_the_old_files_and_deletes_nothing(tmp_path):
    """R2's report-first rule, checked on the behaviour rather than on the flag's presence."""
    old = _aged(tmp_path, "store-api-2026-07-01.jsonl", HOT_DAYS + 1)
    young = _aged(tmp_path, "store-api-2026-08-19.jsonl", 1)

    entries = log_rotation.check_prune(_decl(tmp_path), REPO)

    assert entries[0]["doomed"] == 1
    assert entries[0]["paths"] == [str(old)]
    assert old.exists() and young.exists(), "reporting must never delete"


def test_fix_deletes_only_past_the_window(tmp_path):
    old = _aged(tmp_path, "engine-2026-07-01.jsonl", HOT_DAYS + 1)
    edge = _aged(tmp_path, "engine-2026-08-07.jsonl", HOT_DAYS - 0.1)
    young = _aged(tmp_path, "engine-2026-08-19.jsonl", 1)

    for entry in log_rotation.check_prune(_decl(tmp_path), REPO):
        log_rotation.prune(entry)

    assert not old.exists()
    assert edge.exists(), "a file one hour inside the window is inside the window"
    assert young.exists()


def test_the_sweep_leaves_anything_that_is_not_an_ingested_log(tmp_path):
    """The glob is `*.jsonl`, and the ingest directory is not guaranteed to hold only those.

    §5.2 retains `alerts.jsonl` and `store/scheduler/audit/*.jsonl` FOREVER. They do not live
    here today; this asserts the glob is narrow enough that a future edit dropping a `.db` or a
    `.json` beside the logs does not sweep it away.
    """
    keep = _aged(tmp_path, "cursor.state.json", HOT_DAYS + 30)
    keep_db = _aged(tmp_path, "index.db", HOT_DAYS + 30)
    go = _aged(tmp_path, "ops-console-2026-07-01.jsonl", HOT_DAYS + 1)

    for entry in log_rotation.check_prune(_decl(tmp_path), REPO):
        log_rotation.prune(entry)

    assert not go.exists()
    assert keep.exists() and keep_db.exists()
