"""Every app running on Fly must be described by a committed file.

Measured 2026-08-19: `prospector-hermes` had been running since the day before with no `fly.toml`
anywhere in the repo, and nothing in the estate said so. See scripts/fly_estate_probe.py for the
incident. These tests pin the three ways such a probe fails silently.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("fly_estate_probe",
                                               ROOT / "scripts" / "fly_estate_probe.py")
probe = importlib.util.module_from_spec(_spec)
sys.modules["fly_estate_probe"] = probe
_spec.loader.exec_module(probe)


def test_described_apps_reads_the_committed_configs():
    """A real assertion against this repo, not a fixture: the engine's config declares its app."""
    described = probe.described_apps("HEAD")
    assert described.get("prospector-engine") == "deploy/engine/fly.toml"
    assert described.get("prospector-ci") == "deploy/runner/fly.toml"


def test_an_app_with_no_committed_config_is_reported(monkeypatch):
    monkeypatch.setattr(probe, "live_apps",
                        lambda: ["prospector-engine", "prospector-nobody-committed-me"])

    result = probe.audit("HEAD")

    assert result["undescribed"] == ["prospector-nobody-committed-me"]


def test_tie_apps_are_out_of_scope_not_defects(monkeypatch):
    """The founder keeps the tie-* apps (directive 2026-08-18). They must never read as a defect."""
    monkeypatch.setattr(probe, "live_apps", lambda: ["tie-api", "tie-db"])

    result = probe.audit("HEAD")

    assert result["undescribed"] == []
    assert result["out_of_scope"] == ["tie-api", "tie-db"]


def test_a_probe_that_cannot_reach_fly_raises_rather_than_reporting_nothing(monkeypatch):
    """An empty list would grade every missing config as fine. That is worse than no probe."""
    def dead_fly(*a, **k):
        return subprocess.CompletedProcess(a, 1, stdout="", stderr="Error: not logged in")

    monkeypatch.setattr(probe.subprocess, "run", dead_fly)

    with pytest.raises(RuntimeError, match="cannot ask Fly"):
        probe.live_apps()


def test_unparseable_output_raises_too(monkeypatch):
    """`fly apps list --json` printing a banner instead of JSON must not read as zero apps."""
    def chatty_fly(*a, **k):
        return subprocess.CompletedProcess(a, 0, stdout="Update available!\n", stderr="")

    monkeypatch.setattr(probe.subprocess, "run", chatty_fly)

    with pytest.raises(RuntimeError, match="no JSON"):
        probe.live_apps()


def test_the_app_line_tolerates_a_trailing_comment():
    """store_platform's configs carry `app = "x"  # rename to your Fly app name`."""
    m = probe.APP_LINE.match('app = "prospector-store-api"          # rename to your Fly app name')
    assert m and m.group(1) == "prospector-store-api"
