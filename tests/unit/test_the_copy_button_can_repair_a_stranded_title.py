"""The console's copy-repair button must be able to move the packs it is offered for.

On 2026-08-18, 14 of the 34 stranded PASS packs were blocked on one rule: a title over 60
characters. The Stranded page marked every one of them `shelf.repair_copy` and offered the
button. The button ran `tools/sweep_shelf_copy.py`, which rewrites one-liners: its grader is
`check_shelf_copy`, which carries no title rule, so it printed `defective: 0` and exited
clean. `tools/recover_stranded_passes.py` routed the same packs to the same sweep, recorded
the clean exit as a failed attempt, and after three of them marked the pack `unrecoverable`.
60 rows in `store/ops/pack_recovery.jsonl` had been retired that way.

These tests pin the three joints of that failure.
"""
from __future__ import annotations

import sys
import types

import pytest

from prospector import field_write, shelf_copy_repair
from tools import recover_stranded_passes

LONG_TITLE = ("Driver and Vehicle Standards Agency (DVSA) Operator Compliance Risk Score "
              "evidence packs for UK haulage operators")


def _cand(title: str):
    """The smallest candidate `field_write.breaches` reads."""
    return types.SimpleNamespace(
        candidate_id="test0000",
        title=title,
        one_liner="Prepares the operator's compliance evidence before the audit lands.",
        who_pays="haulage operators",
        market="UK",
        tags={"sector": "transport"},
    )


def test_the_copy_sweeps_grader_cannot_see_a_breached_title():
    """The premise. `shelf_copy_repair.breaches` is what the sweep selects on, and a title
    119 characters long is invisible to it — which is why the sweep reported nothing to fix."""
    assert len(LONG_TITLE) > 60
    found = shelf_copy_repair.breaches(LONG_TITLE, _cand(LONG_TITLE).one_liner)
    assert not [d for _field, d in found if "60 limit" in d]


def test_the_replacements_grader_does_see_it():
    """`field_write.breaches` grades the title with the publish gate's own `check_title`."""
    found = field_write.breaches(_cand(LONG_TITLE), "title", "one_liner")
    assert any("60 limit" in d for d in found), found


def test_the_recovery_tools_copy_route_runs_the_tool_that_can_repair_a_title():
    cmd = recover_stranded_passes._cmd("copy", "abc123", publish=False)
    assert cmd is not None
    joined = " ".join(cmd)
    assert "repair_stranded_shelf_lines.py" in joined, joined
    assert "sweep_shelf_copy.py" not in joined, joined
    assert "--only" in cmd and "abc123" in cmd


def test_the_console_button_names_the_stranded_packs_it_was_offered_for(monkeypatch):
    """The sweep selects by whether a local `store/listings/*.json` exists, which is not the
    shelf: 26 of the 29 copy-blocked packs on 2026-08-17 had a listing file and were still
    absent from it. So the action must name the ids the shelf reader marked, not leave the
    tool to find them."""
    api = pytest.importorskip("prospector.ops.console_api")

    monkeypatch.setattr(api, "_read_shelf", lambda cfg, params: {
        "reachable": True,
        "rows": [
            {"id": "aaa", "repair": "shelf.repair_copy"},
            {"id": "bbb", "repair": "shelf.publish_pending"},
            {"id": "ccc", "repair": "shelf.repair_copy"},
        ],
    })
    seen = {}

    def _fake_run_repair(cfg, name, argv, preview, *, effect, payload):
        seen["name"], seen["argv"] = name, argv
        return {"action": name, "command": " ".join(argv)}

    monkeypatch.setattr(api, "_run_repair", _fake_run_repair)
    api._act_shelf_repair_copy(object(), {}, True)

    assert seen["name"] == "shelf.repair_copy"
    argv = seen["argv"]
    assert "tools/repair_stranded_shelf_lines.py" in argv[0]
    assert "--only" in argv
    # Named, and only the two rows the shelf reader marked for this repair.
    assert argv[argv.index("--only") + 1] == "aaa,ccc"


def test_an_unreadable_shelf_raises_rather_than_reporting_no_work(monkeypatch):
    """UNKNOWN is not zero. Returning an empty id list would render as "nothing needs
    repairing", which is the swallowed-outage defect this page already guards elsewhere."""
    api = pytest.importorskip("prospector.ops.console_api")
    monkeypatch.setattr(api, "_read_shelf",
                        lambda cfg, params: {"reachable": False, "reason": "timeout"})
    with pytest.raises(RuntimeError, match="UNKNOWN"):
        api._repair_copy_ids(object())


def test_the_sweeps_store_path_follows_the_store_not_the_code(monkeypatch, tmp_path):
    """A `__file__`-derived store path wrote `sqlite3.OperationalError: unable to open
    database file` into the recovery ledger on 2026-08-17, and two PASS packs were marked
    unrecoverable over it."""
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path))
    for mod in ("tools.sweep_shelf_copy", "prospector.config"):
        sys.modules.pop(mod, None)
    import tools.sweep_shelf_copy as sweep

    assert sweep.DB == tmp_path / "prospector.db", sweep.DB
    assert sweep.DOSSIERS == tmp_path / "dossiers"


SWEEP = "/x/python tools/sweep_shelf_copy.py --fix --stranded --only p1 --jobs 1"
REPAIR = "/x/python tools/repair_stranded_shelf_lines.py --fix --only p1 --jobs 1"


def _attempt(cmd: str, outcome: str = "blocked") -> dict:
    return {"pack": "p1", "route": "copy", "signature": "title", "cmd": cmd,
            "outcome": outcome, "ts": "2026-08-18T12:00:00+00:00", "why": "defective: 0"}


def test_a_mark_earned_by_the_old_repair_does_not_block_the_new_one():
    """Without this, the fixed route is inert for exactly the 60 packs it was written for."""
    history = [_attempt(SWEEP), _attempt(SWEEP), _attempt(SWEEP, "unrecoverable")]
    assert recover_stranded_passes.verdict(history, "copy", "title")[0] == "skip"
    action, why = recover_stranded_passes.verdict(
        history, "copy", "title", tool="repair_stranded_shelf_lines.py")
    assert action == "run", why


def test_the_new_repairs_own_failures_still_count():
    """The reset is about a CHANGED repair, not an amnesty. Three failures by the tool that
    runs today still retire the pack."""
    history = [_attempt(REPAIR) for _ in range(recover_stranded_passes.MAX_ATTEMPTS)]
    action, why = recover_stranded_passes.verdict(
        history, "copy", "title", tool="repair_stranded_shelf_lines.py")
    assert action == "skip", why


def test_a_published_pack_stays_published_whichever_tool_listed_it():
    history = [_attempt(SWEEP, "published")]
    action, why = recover_stranded_passes.verdict(
        history, "copy", "title", tool="repair_stranded_shelf_lines.py")
    assert action == "skip" and "published" in why


def test_the_tool_is_read_from_the_command_not_the_interpreter():
    assert recover_stranded_passes.tool_of(SWEEP) == "sweep_shelf_copy.py"
    assert recover_stranded_passes.tool_of(
        "/x/python -m tools.publish_passes --dry-run a.json") == "tools.publish_passes"
    assert recover_stranded_passes.tool_of("") == ""
