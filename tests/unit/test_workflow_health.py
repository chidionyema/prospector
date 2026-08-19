"""A fence that stops firing must grade worse than one that fails.

`scripts/workflow_health.py` exists because the ops console could be green for two opposite
reasons: everything passed, or nothing checked. These tests pin the three states that are
invisible to a dashboard showing only last-results -- NEVER-RAN, STOPPED and NOT REGISTERED --
and the one regression that produced the module.

That regression: `process_audit.grade_workflows` used to ask `gh run list --limit 200`, a single
global window across every workflow. Measured 2026-08-19T14:11Z, those 200 runs covered 3h39m
because CI and auto-merge produced 164 of them, so five of ten workflows fell out of the window
and were reported NEVER-RAN when four had run that morning. `test_an_old_but_green_run_is_not_a_
never_ran` is that bug as a test: the window is gone, so a workflow whose last run is old and
successful grades ok.

No network. `sh` is replaced with a table of canned GitHub answers.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "workflow_health.py"


def _load():
    spec = importlib.util.spec_from_file_location("workflow_health", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wh = _load()


def _fake_gh(workflows: list[dict], last_run: dict[int, dict | None], list_rc: int = 0):
    """Stand in for `sh`, answering the two calls collect() makes.

    `last_run[id] is None` means the workflow exists on GitHub and has never produced a run --
    the API returns an empty `workflow_runs` array, which is not an error.
    """

    def sh(cmd, timeout=60):
        joined = " ".join(cmd)
        if "actions/workflows" in joined and "/runs" not in joined:
            if list_rc != 0:
                return list_rc, "gh: HTTP 401: Bad credentials"
            return 0, "\n".join(json.dumps(w) for w in workflows)
        wf_id = int(joined.split("actions/workflows/")[1].split("/runs")[0])
        run = last_run.get(wf_id)
        return 0, ("" if run is None else json.dumps(run))

    return sh


def _wf(wf_id: int, name: str, path: str, state: str = "active") -> dict:
    return {"id": wf_id, "name": name, "path": path, "state": state}


def _run(conclusion: str, ago_s: float, now: float) -> dict:
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - ago_s))
    return {
        "conclusion": conclusion,
        "status": "completed",
        "event": "schedule",
        "created_at": at,
        "html_url": "https://example.invalid/run/1",
    }


@pytest.fixture()
def estate(tmp_path, monkeypatch):
    """A workflow directory on disk that the tests write files into."""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    monkeypatch.setattr(wh, "ROOT", tmp_path)
    monkeypatch.setattr(wh, "WORKFLOW_DIR", wf_dir)
    return wf_dir


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0 7 * * *", "daily"),
        ("0 4 * * 0", "weekly"),
        ("0 8 * * 1", "weekly"),
        ("0 3 1 * *", "monthly"),
        ("*/15 * * * *", "hourly"),
        ("nonsense", "daily"),
    ],
)
def test_cron_cadence(expr, expected):
    assert wh.cron_cadence(expr) == expected


def test_declared_crons_reads_the_expression(estate):
    (estate / "nightly.yml").write_text(
        'name: Nightly\non:\n  schedule:\n    - cron: "0 7 * * *"  # every morning\njobs: {}\n'
    )
    assert wh.declared_crons(estate / "nightly.yml") == ["0 7 * * *"]


def test_a_scheduled_workflow_that_went_quiet_is_bad(estate, monkeypatch):
    """The live-smoke class. It never went red; it stopped firing, and nothing said so.

    A daily workflow whose last run succeeded nine days ago is green by every last-result
    measure. It is also not running, which is the failure.
    """
    now = time.time()
    (estate / "nightly.yml").write_text(
        'name: Nightly\non:\n  schedule:\n    - cron: "0 7 * * *"\n'
    )
    monkeypatch.setattr(
        wh,
        "sh",
        _fake_gh(
            [_wf(1, "Nightly", ".github/workflows/nightly.yml")],
            {1: _run("success", 9 * 86400, now)},
        ),
    )

    row = wh.collect(now=now)["rows"][0]
    assert row["grade"] == "bad", row
    assert "STOPPED" in row["detail"], row["detail"]


def test_an_old_but_green_run_is_not_a_never_ran(estate, monkeypatch):
    """The regression that produced this module.

    An unscheduled workflow that last ran eight hours ago is healthy. Under the old global
    200-run window it fell out of view on a busy CI day and was reported NEVER-RAN.
    """
    now = time.time()
    (estate / "deploy-api.yml").write_text("name: Deploy Store.Api\non:\n  workflow_dispatch:\n")
    monkeypatch.setattr(
        wh,
        "sh",
        _fake_gh(
            [_wf(7, "Deploy Store.Api", ".github/workflows/deploy-api.yml")],
            {7: _run("success", 8 * 3600, now)},
        ),
    )

    row = wh.collect(now=now)["rows"][0]
    assert row["grade"] == "ok", row
    assert row["ever_ran"] is True


def test_a_workflow_with_no_runs_at_all_is_bad(estate, monkeypatch):
    now = time.time()
    (estate / "drill.yml").write_text("name: Escape hatch drill\non:\n  workflow_dispatch:\n")
    monkeypatch.setattr(
        wh, "sh", _fake_gh([_wf(3, "Escape hatch drill", ".github/workflows/drill.yml")], {3: None})
    )

    row = wh.collect(now=now)["rows"][0]
    assert row["grade"] == "bad", row
    assert "NEVER-RAN" in row["detail"]
    assert row["ever_ran"] is False


def test_a_file_github_has_never_registered_is_bad(estate, monkeypatch):
    """On disk, unknown to GitHub. It has never reached the default branch, so it guards nothing."""
    now = time.time()
    (estate / "brand-new.yml").write_text("name: Brand new\non:\n  push:\n")
    monkeypatch.setattr(wh, "sh", _fake_gh([], {}))

    row = wh.collect(now=now)["rows"][0]
    assert row["grade"] == "bad", row
    assert "NOT REGISTERED" in row["detail"]


def test_a_red_last_run_is_bad_and_carries_its_url(estate, monkeypatch):
    now = time.time()
    (estate / "smoke.yml").write_text(
        'name: Live storefront smoke\non:\n  schedule:\n    - cron: "0 7 * * *"\n'
    )
    monkeypatch.setattr(
        wh,
        "sh",
        _fake_gh(
            [_wf(9, "Live storefront smoke", ".github/workflows/smoke.yml")],
            {9: _run("failure", 3600, now)},
        ),
    )

    report = wh.collect(now=now)
    row = report["rows"][0]
    assert row["grade"] == "bad" and "FAILING" in row["detail"]
    assert row["url"] == "https://example.invalid/run/1"
    # Lifted out so a tile can show it without knowing which file is the live smoke.
    assert report["live_storefront"] is None  # the real file name is e2e-live-smoke.yml


def test_a_cancelled_run_is_a_warning_not_a_failure(estate, monkeypatch):
    """CI cancels superseded runs by design. Grading that red would make the page cry wolf."""
    now = time.time()
    (estate / "ci.yml").write_text("name: CI\non:\n  pull_request:\n")
    monkeypatch.setattr(
        wh,
        "sh",
        _fake_gh([_wf(2, "CI", ".github/workflows/ci.yml")], {2: _run("cancelled", 600, now)}),
    )

    assert wh.collect(now=now)["rows"][0]["grade"] == "warn"


def test_an_unreachable_github_is_never_reported_as_healthy(estate, monkeypatch):
    """Silence from the API is not a pass.

    The whole point of this module is that a dashboard must not be green because nothing checked.
    That applies to the module itself: if it cannot ask, it says so and fails.
    """
    now = time.time()
    (estate / "ci.yml").write_text("name: CI\non:\n  pull_request:\n")
    monkeypatch.setattr(wh, "sh", _fake_gh([], {}, list_rc=1))

    report = wh.collect(now=now)
    assert report["reachable"] is False
    assert report["ok"] is False
    assert "not evidence" in report["note"]


def test_the_live_storefront_is_lifted_out_by_its_real_filename(estate, monkeypatch):
    now = time.time()
    (estate / "e2e-live-smoke.yml").write_text(
        'name: Live storefront smoke\non:\n  schedule:\n    - cron: "0 7 * * *"\n'
    )
    monkeypatch.setattr(
        wh,
        "sh",
        _fake_gh(
            [_wf(9, "Live storefront smoke", ".github/workflows/e2e-live-smoke.yml")],
            {9: _run("failure", 3600, now)},
        ),
    )

    live = wh.collect(now=now)["live_storefront"]
    assert live is not None and live["grade"] == "bad"


def test_the_console_read_view_is_registered():
    """A view the console cannot reach is a page that renders an error."""
    from prospector.ops.console_api import READS

    assert "workflows" in READS
