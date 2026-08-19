"""The console may run any catalogued tool, and undo is what makes that safe.

These tests pin the two halves of the founder's 2026-08-16 directive — "we just need rollback to
be safe not to hide actions". The first half is that tools are reachable; the second is that the
reachability does not turn the console into a web shell, and that the preview tells the truth
about what undo covers.

Nothing here touches the operator's own store/: the undo tests build a tree under `tmp_path` and
the run tests stop at preview or stub the child process.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from prospector.ops import console_api as api
from prospector.ops import undo


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #
def test_console_tool_registry_has_no_drift():
    """Every tool on disk is either a console button or is named as not being one.

    The registry is hand-written, so before this test a new tool was invisible from the console
    until someone remembered to add it, and nothing failed when they did not. Measured on
    2026-08-17: twenty files in `tools/` and `scripts/` were in neither list, so the operator
    could not see them and no test could say so.

    A file in neither list fails here by name. Adding a tool now costs one line in TOOLS or one
    line in NOT_AN_OPS_TOOL with the reason, and the choice is forced rather than forgotten.
    """
    root = Path(api.__file__).resolve().parents[2]
    on_disk = {
        str(p.relative_to(root))
        for d in ("tools", "scripts")
        for p in (root / d).glob("*")
        if p.is_file() and p.suffix in (".py", ".sh") and p.name != "__init__.py"
    }
    registered = {t["path"] for t in api.TOOLS}
    classified = registered | set(api.NOT_AN_OPS_TOOL)

    unclassified = sorted(on_disk - classified)
    assert not unclassified, (
        "these tools are on disk but in neither TOOLS nor NOT_AN_OPS_TOOL, so the operator "
        "cannot see them and cannot be told why:\n  " + "\n  ".join(unclassified)
    )

    # The other direction: an excuse for a file that no longer exists is rot of its own.
    stale = sorted(p for p in api.NOT_AN_OPS_TOOL if not (root / p).exists())
    assert not stale, "NOT_AN_OPS_TOOL names files that are gone:\n  " + "\n  ".join(stale)

    overlap = sorted(registered & set(api.NOT_AN_OPS_TOOL))
    assert not overlap, "these are both a button and excluded:\n  " + "\n  ".join(overlap)


def test_every_excluded_tool_gives_a_reason():
    """An exclusion with no reason is the same silence the drift test exists to end."""
    for path, reason in api.NOT_AN_OPS_TOOL.items():
        assert reason and len(reason) > 15, f"{path} is excluded with no usable reason"


def test_registered_tool_paths_all_exist():
    """A button pointing at a deleted file is a dead button the operator finds by clicking it.

    A path starting with `~` is an ESTATE tool that lives outside this repo — Hermes is its own
    checkout at ~/.hermes, and the operator should not have to know which repo a button came
    from. Those resolve against the home directory instead of the repo root, and are skipped
    when absent, because CI has no ~/.hermes and a missing sibling checkout is not a dead
    button, it is a different machine.
    """
    root = Path(api.__file__).resolve().parents[2]
    missing = []
    for path in sorted({t["path"] for t in api.TOOLS}):
        if path.startswith("~"):
            continue          # an external estate tool; see the docstring
        if not (root / path).exists():
            missing.append(path)
    assert not missing, "TOOLS points at files that are gone:\n  " + "\n  ".join(missing)


def test_every_tool_id_is_unique():
    """Catches an id collision, which would make the console run the wrong tool.

    Two rows share the command `launchctl list | grep com.prospector`, so an id hashed from the
    command alone is not unique — the browser would preview one row and execute the other.
    """
    ids = [t["id"] for t in api.TOOLS]
    assert len(set(ids)) == len(ids), "tool ids collide"


def test_tool_ids_are_stable_across_rebuilds():
    """Catches an id derived from list position. A browser holds the id between preview and
    confirm; if inserting a tool renumbered the others, the confirm would hit a different tool."""
    again = api._t("tools/spend_today.py", "Today's spend against the cap", False, "/spend")
    assert again["id"] == next(t["id"] for t in api.TOOLS
                               if t["path"] == "tools/spend_today.py")


def test_every_tool_declares_a_known_risk_and_matching_undo_coverage():
    """Catches a tool added with no risk classification, which would render as if undo covered
    it. `writes` and `risk` must agree: a writing tool is never classified "read"."""
    for tool in api.TOOLS:
        assert tool["risk"] in api.RISKS, tool["path"]
        assert tool["undo_covers"], tool["path"]
        if tool["writes"] and tool["risk"] == "read":
            pytest.fail(f"{tool['path']} writes but is classified read")


def test_the_only_unrunnable_tools_are_the_daemons():
    """Catches a return of the old `run=False` fence. Refusing to run a tool does not stop it
    being run; it moves the run to a terminal with no preview, receipt or undo. The only rows
    that are not runnable are the two launchd daemons, which are not tools."""
    blocked = [t["path"] for t in api.TOOLS if not t["run"]]
    assert sorted(blocked) == ["prospector/consumer.py",
                               "prospector/scheduler/run_scheduled.py"], blocked
    for tool in api.TOOLS:
        if not tool["run"]:
            assert tool["danger"], f"{tool['path']} is refused with no reason given"


def test_money_rail_tools_are_runnable_but_declare_that_undo_cannot_reach_stripe():
    """Catches the money rail being made safe by hiding it. Hiding does not undo a charge; saying
    plainly that undo cannot reach Stripe is the only honest guard."""
    money = [t for t in api.TOOLS if (t["danger"] or "").startswith("MONEY RAIL")]
    assert money, "the money rail tools vanished from the catalogue"
    for tool in money:
        assert tool["run"] is True
        assert tool["risk"] == "external"
        assert tool["undo_covers"] == "the local half only"


def test_reconcile_orphan_index_is_no_longer_refused_by_name():
    """Catches the stale refusal. It was refused for being destructive; it now runs behind a
    rollback snapshot, so a REFUSED_ACTIONS entry would contradict the catalogue."""
    assert "index.reconcile" not in api.REFUSED_ACTIONS
    assert any(t["path"] == "scripts/reconcile_orphan_index.py" and t["run"] for t in api.TOOLS)


def test_the_browser_allowlist_matches_the_gateway():
    """Catches the defect that made `daemon.restart` unreachable.

    The Next console keeps its own copy of the action names and 404s anything not on it. That copy
    drifted: `daemon.restart` was added to the Python gateway on 2026-08-16 and never added to the
    browser's list, so the action existed, was tested, and could not be pressed. An action list in
    two places needs a test that they are the same list.
    """
    route = (Path(__file__).resolve().parents[2] / "store_platform" / "src" / "Ops.Console"
             / "src" / "pages" / "api" / "ops" / "act" / "[action].ts")
    if not route.exists():
        pytest.skip("the Next console is not in this checkout")
    block = route.read_text(encoding="utf-8").split("export const ACTIONS = [", 1)[1]
    listed = set(re.findall(r"'([a-z_.]+)'", block.split("]", 1)[0]))
    assert listed == set(api.ACTIONS), (
        f"only in the browser: {sorted(listed - set(api.ACTIONS))}; "
        f"only in the gateway: {sorted(set(api.ACTIONS) - listed)}")


# --------------------------------------------------------------------------- #
# argv construction — the web-shell fence
# --------------------------------------------------------------------------- #
def test_the_command_comes_from_the_catalogue_not_the_payload():
    """Catches the console becoming a web shell. A caller who sends their own `command` must be
    ignored entirely; only the id selects what runs."""
    tool = next(t for t in api.TOOLS if t["path"] == "scripts/store_audit.py")
    argv = api._tool_argv(tool, {"command": "rm -rf /", "path": "/etc/passwd"})
    assert argv[-1] == "scripts/store_audit.py"
    assert "rm" not in argv and "/etc/passwd" not in argv


def test_a_placeholder_value_is_one_argument_even_when_it_looks_like_a_command():
    """Catches shell injection through a placeholder. The child runs without a shell, so `;` and
    `&&` must stay inside a single argv element rather than starting a second command."""
    tool = next(t for t in api.TOOLS if "--idea" in t["command"])
    argv = api._tool_argv(tool, {"idea": "solar; rm -rf ~"})
    assert "solar; rm -rf ~" in argv
    assert "rm" not in argv


def test_a_missing_placeholder_names_the_value_it_needs():
    """Catches a silent run with `<idea>` sent literally to the tool, which would vet the string
    '<idea>' and charge for it."""
    tool = next(t for t in api.TOOLS if "--idea" in t["command"])
    with pytest.raises(ValueError, match="idea"):
        api._tool_argv(tool, {})


def test_the_catalogued_python_path_is_resolved_to_the_running_interpreter(monkeypatch):
    """Catches the catalogue's relative interpreter path being spawned against whatever cwd
    launchd gave the job. The table writes what an operator types; the console must resolve it."""
    monkeypatch.setenv("PROSPECTOR_PYTHON", "/opt/fake/python")
    tool = next(t for t in api.TOOLS if t["path"] == "scripts/store_audit.py")
    assert api._tool_argv(tool, {})[0] == "/opt/fake/python"


def test_a_non_python_command_keeps_its_own_interpreter(monkeypatch):
    """Catches the resolver rewriting `bash script.sh` into a python invocation."""
    monkeypatch.setenv("PROSPECTOR_PYTHON", "/opt/fake/python")
    tool = next(t for t in api.TOOLS if t["command"].startswith("bash "))
    assert api._tool_argv(tool, {})[0] == "bash"


# --------------------------------------------------------------------------- #
# preview
# --------------------------------------------------------------------------- #
def test_preview_of_an_external_tool_says_undo_will_not_cover_it():
    """Catches a preview that offers rollback for a Stripe write. An undo that covers half the
    blast radius is worse than none, because the operator acts as if it covered all of it."""
    tool = next(t for t in api.TOOLS if t["path"] == "tools/set_live_pack_price.py")
    out = api._act_tools_run(None, {"id": tool["id"], "pack": "x", "rung": "y"}, True)
    assert out["risk"] == "external"
    assert "OFF THIS MACHINE" in out["note"]
    assert out["undo_covers"] == "the local half only"


def test_preview_of_a_read_only_tool_promises_no_snapshot():
    """Catches an 11-second snapshot being taken before a tool that writes nothing."""
    tool = next(t for t in api.TOOLS if t["path"] == "scripts/store_audit.py")
    out = api._act_tools_run(None, {"id": tool["id"]}, True)
    assert out["snapshot"] == "none — this tool writes nothing"


def test_running_a_daemon_row_is_refused_with_its_reason():
    """Catches a refusal that says only 'not runnable'. The operator needs to be told to use
    daemon.restart instead."""
    tool = next(t for t in api.TOOLS if t["path"] == "prospector/consumer.py")
    with pytest.raises(ValueError, match="daemon.restart"):
        api._act_tools_run(None, {"id": tool["id"]}, True)


def test_an_unknown_id_is_refused():
    """Catches an id off the wire selecting nothing and falling through to a default."""
    with pytest.raises(ValueError, match="no tool with id"):
        api._act_tools_run(None, {"id": "deadbeef00"}, True)


# --------------------------------------------------------------------------- #
# the background job
# --------------------------------------------------------------------------- #
def _audit(tool_path: str = "scripts/store_audit.py") -> dict:
    return next(t for t in api.TOOLS if t["path"] == tool_path)


def test_running_a_tool_returns_a_job_id_instead_of_waiting_for_it(monkeypatch):
    """Catches the run going back to a blocking HTTP request.

    `scripts/store_audit.py` measured 239.9s. Holding the request open for that gives the operator
    a spinner, kills the run if the tab closes, and puts every timeout between here and the browser
    in a position to lose a job that was working.
    """
    spawned: list[dict] = []
    monkeypatch.setattr(api.subprocess, "Popen",
                        lambda cmd, **kw: spawned.append({"cmd": cmd, **kw}) or object())

    out = api._act_tools_run(None, {"id": _audit()["id"], "reason": "test"}, False)

    assert out["state"] == "running" and len(out["job"]) >= 8
    assert out["exit_code"] is None, "a job that has not finished cannot have an exit code"
    assert len(spawned) == 1
    cmd = spawned[0]["cmd"]
    assert "run-tool" in cmd and out["job"] in cmd
    # Its own session, so the console killing the gateway does not kill a running tool with it.
    assert spawned[0]["start_new_session"] is True


def test_the_background_worker_writes_the_finishing_receipt(monkeypatch):
    """Catches a job that starts and never reports. The started receipt is not an outcome; without
    the second one, `read job` says "running" forever and nobody learns the tool failed."""
    written: list[dict] = []
    monkeypatch.setattr(api, "_record_intent", lambda cfg, rec: written.append(rec))
    monkeypatch.setattr(api, "_exec", lambda cmd, cwd, timeout: ("STORE_AUDIT FAIL", 1, False))

    out = api._run_tool_job(None, _audit()["id"], "job123", {"reason": "test", "undo_id": "u1"})

    assert written == [out]
    assert out["job"] == "job123" and out["state"] == "finished"
    assert out["applied"] is False and out["exit_code"] == 1, "exit 1 is not a success"
    assert out["undo_id"] == "u1", "the snapshot taken before the run must stay on the receipt"
    assert "STORE_AUDIT FAIL" in out["message"]


def test_a_timed_out_worker_says_so_rather_than_reporting_a_failure(monkeypatch):
    """Catches a timeout rendered as exit-code failure. The tool wrote whatever it wrote before the
    kill; "we stopped waiting" and "it failed" are different facts."""
    monkeypatch.setattr(api, "_record_intent", lambda cfg, rec: None)
    monkeypatch.setattr(api, "_exec", lambda cmd, cwd, timeout: ("half done", None, True))

    out = api._run_tool_job(None, _audit()["id"], "job456", {})
    assert out["state"] == "timed_out" and out["timed_out"] is True and out["exit_code"] is None


def _write_receipts(tmp_path: Path, rows: list[dict]) -> None:
    (tmp_path / "intents.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_reading_a_job_reports_the_latest_receipt_for_it(tmp_path, monkeypatch):
    """Catches the reader picking the started receipt over the finished one."""
    monkeypatch.setattr(api, "_store_ops_dir", lambda cfg: tmp_path)
    _write_receipts(tmp_path, [
        {"job": "j1", "state": "running", "ts": api._now_iso()},
        {"job": "other", "state": "finished", "ts": api._now_iso()},
        {"job": "j1", "state": "finished", "ts": api._now_iso(), "exit_code": 0},
    ])
    out = api._read_job(None, {"job": "j1"})
    assert out["state"] == "finished" and out["receipt"]["exit_code"] == 0 and out["rows"] == 2


def test_a_job_whose_worker_died_is_lost_not_running(tmp_path, monkeypatch):
    """Catches "running" being asserted about a process nobody can see. A reboot or a SIGKILL
    leaves the started receipt as the last word; past the tool's own ceiling that is not progress,
    and a console that shows a spinner forever is the prose-drift failure in UI form."""
    monkeypatch.setattr(api, "_store_ops_dir", lambda cfg: tmp_path)
    old = datetime.now(timezone.utc) - timedelta(seconds=api._JOB_LOST_AFTER_S + 60)
    _write_receipts(tmp_path, [{"job": "j2", "state": "running", "ts": old.isoformat()}])
    assert api._read_job(None, {"job": "j2"})["state"] == "lost"

    _write_receipts(tmp_path, [{"job": "j3", "state": "running", "ts": api._now_iso()}])
    assert api._read_job(None, {"job": "j3"})["state"] == "running"


def test_an_unknown_job_says_unknown_rather_than_inventing_a_state(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_store_ops_dir", lambda cfg: tmp_path)
    _write_receipts(tmp_path, [])
    assert api._read_job(None, {"job": "nope"})["state"] == "unknown"
    with pytest.raises(ValueError, match="job id is required"):
        api._read_job(None, {})


def test_the_browser_view_allowlist_matches_the_gateway():
    """The same drift as the actions list, on the read door. `job` was added to the gateway and the
    console's own copy would have 404ed it, so the job would run and be unwatchable."""
    route = (Path(__file__).resolve().parents[2] / "store_platform" / "src" / "Ops.Console"
             / "src" / "pages" / "api" / "ops" / "read" / "[view].ts")
    if not route.exists():
        pytest.skip("the Next console is not in this checkout")
    block = route.read_text(encoding="utf-8").split("export const VIEWS = [", 1)[1]
    listed = set(re.findall(r"'([a-z_]+)'", block.split("]", 1)[0]))
    assert listed == set(api.READS), (
        f"only in the browser: {sorted(listed - set(api.READS))}; "
        f"only in the gateway: {sorted(set(api.READS) - listed)}")


# --------------------------------------------------------------------------- #
# undo
# --------------------------------------------------------------------------- #
def _tree(root: Path) -> Path:
    store = root / "store"
    (store / "dossiers").mkdir(parents=True)
    (store / "_cache").mkdir(parents=True)
    (store / "dossiers" / "a.json").write_text('{"v": 1}', encoding="utf-8")
    (store / "keep.json").write_text("keep", encoding="utf-8")
    (store / "_cache" / "big.json").write_text("cache", encoding="utf-8")
    return store


def test_snapshot_skips_the_regenerable_cache(tmp_path):
    """Catches the cache being snapshotted. It is 26,939 of store/'s 29,993 files — 90% of the
    cost — and rolling it back would restore stale search results."""
    _tree(tmp_path)
    rec = undo.snapshot("test", root=tmp_path)
    snap = undo.undo_root(tmp_path) / rec["id"]
    assert not (snap / "_cache").exists()
    assert (snap / "dossiers" / "a.json").exists()
    assert rec["excluded"] == ["_cache"]


def test_undo_restores_a_modified_file_and_deletes_one_written_since(tmp_path):
    """Catches a half rollback. Putting files back is not enough: a tool that CREATED files leaves
    them behind, so the tree does not end up as it was."""
    store = _tree(tmp_path)
    rec = undo.snapshot("test", root=tmp_path)

    (store / "dossiers" / "a.json").write_text('{"v": 999}', encoding="utf-8")
    (store / "dossiers" / "new.json").write_text("written by the tool", encoding="utf-8")
    (store / "keep.json").unlink()

    plan = undo.restore_plan(rec["id"], root=tmp_path)
    assert plan["overwrite"] == 1 and plan["recreate"] == 1 and plan["delete"] == 1

    out = undo.restore(rec["id"], root=tmp_path)
    assert out["applied"] and out["errors"] == []
    assert json.loads((store / "dossiers" / "a.json").read_text()) == {"v": 1}
    assert (store / "keep.json").read_text() == "keep"
    assert not (store / "dossiers" / "new.json").exists()


def test_the_plan_warns_that_files_written_since_are_deleted(tmp_path):
    """Catches a preview that hides the destructive half of a rollback. If the daemon is running,
    its work since the snapshot is in the delete list."""
    _tree(tmp_path)
    rec = undo.snapshot("test", root=tmp_path)
    plan = undo.restore_plan(rec["id"], root=tmp_path)
    assert "DELETED" in plan["warning"] and "PAUSE" in plan["warning"]


def test_a_snapshot_id_cannot_escape_the_undo_directory(tmp_path):
    """Catches path traversal. The id arrives from the browser, so `../../` must not let a restore
    read or overwrite an arbitrary tree."""
    _tree(tmp_path)
    undo.snapshot("test", root=tmp_path)
    with pytest.raises(ValueError, match="no snapshot named"):
        undo.restore_plan("../../etc", root=tmp_path)


def test_prune_keeps_the_newest_and_never_deletes_below_zero(tmp_path):
    """Catches an unbounded snapshot series filling the disk, and a keep<=0 that wipes them all
    when a caller passes a falsy default."""
    _tree(tmp_path)
    for i in range(4):
        undo.snapshot(f"run-{i}", root=tmp_path)
    assert undo.prune(keep=2, root=tmp_path)
    assert len(undo.list_snapshots(tmp_path)) == 2
    assert undo.prune(keep=0, root=tmp_path) == []
    assert len(undo.list_snapshots(tmp_path)) == 2


def test_a_snapshot_with_an_unreadable_manifest_is_listed_as_broken_not_dropped(tmp_path):
    """Catches a corrupt snapshot silently vanishing from the list, which would read to the
    operator as 'that rollback point never existed'."""
    _tree(tmp_path)
    rec = undo.snapshot("test", root=tmp_path)
    (undo.undo_root(tmp_path) / rec["id"] / "manifest.json").write_text("{", encoding="utf-8")
    listed = undo.list_snapshots(tmp_path)
    assert len(listed) == 1 and listed[0]["broken"] is True
