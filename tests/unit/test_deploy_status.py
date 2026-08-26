"""The deploy probe's decisions, without touching gh, flyctl or the network.

The failure this guards: on 2026-08-19 a merge to main sat undeployed for twelve hours and every
check in the estate read green, because nothing compared the live release to origin/main. So the
rules that decide STALLED are pure functions here, and each of them is driven directly.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("deploy_status", ROOT / "scripts/deploy_status.py")
ds = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(ds)


NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_workflow_paths_reads_the_trigger_list():
    text = (
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "    paths:\n"
        '      - "store_platform/src/Store.Web/**"\n'
        '      - "store_platform/scripts/deploy_web.sh"\n'
        "  workflow_dispatch:\n"
        "jobs:\n"
    )
    assert ds.workflow_paths(text) == [
        "store_platform/src/Store.Web/**",
        "store_platform/scripts/deploy_web.sh",
    ]


def test_workflow_with_no_paths_block_yields_nothing():
    """Which the caller must turn into UNKNOWN. An empty list must never read as 'nothing to
    watch' -- that is the shape of the original blind spot."""
    assert ds.workflow_paths("on:\n  push:\n    branches: [main]\njobs:\n") == []


def test_pathspecs_turn_glob_filters_into_directories():
    assert ds.pathspecs(["a/b/**", "a/b/*", "config.yaml", "c/d/"]) == ["a/b", "config.yaml", "c/d"]


def test_every_declared_workflow_exists_and_still_has_paths():
    """The drift guard. Rename or restructure a deploy workflow and this fails here, rather than
    the probe quietly watching nothing."""
    for d in ds.DEPLOYABLES:
        if not d.get("workflow"):
            continue
        wf = ds.WORKFLOWS / d["workflow"]
        assert wf.exists(), f"{d['name']} names {d['workflow']}, which does not exist"
        assert ds.workflow_paths(wf.read_text()), f"no paths: filter parsed out of {d['workflow']}"


def test_unmeasured_is_never_a_pass():
    state, why = ds.verdict({"unknown_reason": "gh is not installed"}, stall_after_s=600)
    assert state == "UNKNOWN"
    assert "gh" in why
    assert state in ds.ATTENTION


def test_nothing_pending_is_live():
    state, _ = ds.verdict(
        {"has_workflow": True, "pending_commits": [], "running": []}, stall_after_s=600
    )
    assert state == "LIVE"


def test_commits_waiting_with_nothing_running_is_stalled():
    state, why = ds.verdict(
        {"has_workflow": True, "pending_commits": [{"sha": "abc"}], "running": []},
        stall_after_s=600,
    )
    assert state == "STALLED"
    assert "1 commit" in why


def test_a_run_in_flight_is_shipping_until_the_stall_threshold():
    facts = {
        "has_workflow": True,
        "pending_commits": [{"sha": "abc"}],
        "running": [{"status": "queued", "age_s": 120}],
    }
    assert ds.verdict(facts, stall_after_s=600)[0] == "SHIPPING"
    facts["running"] = [{"status": "queued", "age_s": 3600}]
    state, why = ds.verdict(facts, stall_after_s=600)
    assert state == "STALLED"
    assert "60 min" in why


def test_a_failed_run_outranks_the_queue():
    """A red deploy with commits behind it is not 'shipping'."""
    state, _ = ds.verdict(
        {
            "has_workflow": True,
            "pending_commits": [{"sha": "a"}],
            "running": [{"status": "queued", "age_s": 5}],
            "last_run_failed": True,
            "last_run_url": "https://x",
        },
        stall_after_s=600,
    )
    assert state == "FAILED"


def test_a_hand_deployed_component_drifts_rather_than_stalls():
    state, why = ds.verdict(
        {"has_workflow": False, "pending_commits": [{"sha": "a"}], "running": []}, stall_after_s=600
    )
    assert state == "DRIFTED"
    assert "by hand" in why


def test_age_reads_both_zulu_and_offset_stamps():
    assert ds.age_s("2026-08-19T11:00:00Z", NOW) == 3600
    assert ds.age_s("2026-08-19T11:00:00+00:00", NOW) == 3600
    assert ds.age_s(None, NOW) is None
    assert ds.age_s("not a time", NOW) is None
