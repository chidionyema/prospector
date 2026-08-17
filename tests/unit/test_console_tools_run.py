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
from pathlib import Path

import pytest

from prospector.ops import console_api as api
from prospector.ops import undo


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #
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
