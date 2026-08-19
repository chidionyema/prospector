"""The deploy-age view: every trap it has already fallen into, pinned.

Each test here is a defect this module produced during the hour it was written, not a
hypothetical. A view whose whole job is to say "this is older than you think" is worthless if it
can say "fine" for the wrong reason.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from prospector.ops import console_api, deploys

REPO = Path(__file__).resolve().parents[2]


def test_an_untracked_file_is_not_a_local_edit(monkeypatch):
    """The reimplementation trap.

    `deploys` first rolled its own "is the live checkout dirty" check: any porcelain output at
    all meant LOCAL EDITS. The live checkout has an untracked `.venv`, so the console reported a
    wedged production checkout while `live_checkout.py --update` -- which owns that rule and
    ignores untracked paths -- was perfectly happy to fast-forward it. Two definitions of one
    fact always drift. This module now calls the other one.
    """
    monkeypatch.setattr(deploys, "_behind_main", lambda sha: 0)
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, timeout=20):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, "abc1234abc1234abc1234abc1234abc1234abc12"
        if "--format=%ct" in cmd:
            return 0, str(int(time.time()) - 3600)
        if cmd[:2] == ["git", "status"]:
            return 0, "?? .venv"
        return 1, ""

    monkeypatch.setattr(deploys, "_run", fake_run)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    row = deploys._engine_deployable()
    assert row["detail"] == "clean mirror of a commit", row
    assert "LOCAL EDITS" not in row["detail"]


def test_a_tracked_modification_is_a_local_edit(monkeypatch):
    """The other half: the check must still fire on something that really would wedge --update."""
    monkeypatch.setattr(deploys, "_behind_main", lambda sha: 0)

    def fake_run(cmd, cwd=None, timeout=20):
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, "abc1234"
        if "--format=%ct" in cmd:
            return 0, str(int(time.time()))
        if cmd[:2] == ["git", "status"]:
            return 0, " M prospector/run.py"
        return 1, ""

    monkeypatch.setattr(deploys, "_run", fake_run)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    row = deploys._engine_deployable()
    assert "LOCAL EDITS" in row["detail"], row


def test_store_and_storage_are_not_local_edits(monkeypatch):
    """Runtime state is tracked and written by every run. `_code_changes` exists for exactly this.

    If this ever fails, the live checkout will read permanently red and the red will mean nothing,
    which is the failure mode `live_checkout._code_changes` was written to end.
    """
    monkeypatch.setattr(deploys, "_behind_main", lambda sha: 0)

    def fake_run(cmd, cwd=None, timeout=20):
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, "abc1234"
        if "--format=%ct" in cmd:
            return 0, str(int(time.time()))
        if cmd[:2] == ["git", "status"]:
            return 0, " T store/provider_health.json"
        return 1, ""

    monkeypatch.setattr(deploys, "_run", fake_run)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    assert deploys._engine_deployable()["detail"] == "clean mirror of a commit"


def test_a_deploy_stamp_in_the_future_is_clamped_and_named():
    """Measured: the first live run printed `age=-1h` for Store.Web.

    A negative age sorts to the top as the freshest deploy and grades `ok`. That is the single
    answer this module must never give by accident.
    """
    row = {"detail": "Deploy Store.Web"}
    age = deploys._age(time.time() + 3600, row)
    assert age == 0.0
    assert "clock skew" in row["detail"]
    assert "Deploy Store.Web" in row["detail"]


def test_a_small_skew_is_not_reported_as_skew():
    row = {"detail": "Deploy Store.Web"}
    assert deploys._age(time.time() + 5, row) == 0.0
    assert "clock skew" not in row["detail"]


def test_an_unprobeable_deployable_reads_unknown_never_ok():
    """Silence is not freshness. That equation is the whole blind spot."""
    row = deploys._unknown("store-web", "fly", "gh CLI not found")
    assert row["status"] == "unknown"
    assert row["age_s"] is None
    assert deploys._grade(dict(row))["status"] == "unknown"


def test_behind_main_beats_a_recent_deploy():
    """Deployed ten minutes ago and two commits behind is still behind.

    This is the 2026-08-17 shape: green, recent, and running code that is not main.
    """
    row = deploys._grade({"age_s": 600.0, "behind_main": 2})
    assert row["status"] == "behind"


def test_gh_is_found_when_launchd_hides_the_path(monkeypatch):
    """launchd does not hand a job the login shell's PATH.

    A bare `shutil.which("gh")` resolves in a terminal and returns None under the ops-console
    job, so the console would report every Fly deployable unknown while the same command worked
    by hand. That exact class of failure has bitten this estate before.
    """
    monkeypatch.setattr(deploys.shutil, "which", lambda _: None)
    monkeypatch.setattr(deploys.os, "access", lambda p, mode: p == "/opt/homebrew/bin/gh")
    assert deploys._gh() == "/opt/homebrew/bin/gh"


def test_gh_missing_is_unknown_not_a_crash(monkeypatch):
    monkeypatch.setattr(deploys, "_gh", lambda: None)
    row = deploys._fly_deployable("store-web", "Deploy Store.Web", "deploy-web.yml")
    assert row["status"] == "unknown"


def test_a_fly_row_is_built_from_the_last_successful_run(monkeypatch):
    monkeypatch.setattr(deploys, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(deploys, "_behind_main", lambda sha: 3)
    payload = json.dumps(
        [
            {
                "headSha": "0123456789abcdef",
                "updatedAt": "2026-08-19T09:00:00Z",
                "displayTitle": "Deploy Store.Web",
                "url": "https://example.invalid/run/1",
            }
        ]
    )
    monkeypatch.setattr(deploys, "_run", lambda *a, **k: (0, payload))

    row = deploys._fly_deployable("store-web", "Deploy Store.Web", "deploy-web.yml")
    assert row["sha"] == "0123456789abcdef"
    assert row["behind_main"] == 3
    assert row["status"] == "behind"
    assert row["age_s"] > 0


def test_the_view_is_registered_on_both_sides():
    """A read view the console cannot name is a view nobody will ever see.

    `READS` is the python half and `VIEWS` is the whitelist the Next.js route checks first. Wiring
    one and not the other produces a 400 that reads like a bug in the panel.
    """
    assert "deploys" in console_api.READS

    route = (
        REPO / "store_platform/src/Ops.Console/src/pages/api/ops/read/[view].ts"
    ).read_text()
    whitelist = re.search(r"export const VIEWS = \[(.*?)\] as const;", route, re.S)
    assert whitelist, "VIEWS array not found — this test is pinned to its shape"
    assert "'deploys'" in whitelist.group(1)


@pytest.mark.parametrize("key", ["name", "kind", "sha", "deployed_at", "age_s", "behind_main", "status", "detail"])
def test_every_row_carries_the_keys_the_panel_reads(key, monkeypatch):
    monkeypatch.setattr(deploys, "_gh", lambda: None)
    monkeypatch.setattr(deploys, "_engine_deployable", lambda: deploys._unknown("engine", "checkout", "x"))
    monkeypatch.setattr(deploys, "_console_deployable", lambda: deploys._unknown("ops-console", "build", "x"))

    view = deploys.deploys_view()
    assert view["rows"], "the view must never return an empty list — that reads as nothing to check"
    for row in view["rows"]:
        assert key in row, f"{row['name']} is missing {key}"
