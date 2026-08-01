"""Proof that the UNATTENDED daemon engages the configured ambition lanes.

The bug this holds shut (found 2026-08-01): `_default_generate` called `run_signal("", cfg=cfg,
k=batch_size, publish=True)` with no `lanes=` argument. `run_signal` therefore took its no-lane
default branch (run.py:604) and every unattended batch generated under the single implicit default
archetype, `generation.operator_archetype: solo_agent`. `active_lanes: [side_hustle, smb, growth,
venture]` and the `small_team` / `startup` archetypes bound to them were dead config in the daemon —
`_resolve_lanes` was only ever called on the CLI paths (run.py:1182/1224/1277/1837).

It was invisible because nothing asserted on the ARGUMENTS of the run_signal call: the existing
seam tests (test_batch_summary_seam.py) stub run_signal with `lambda *a, **k: batch` and only
inspect the returned summary, so a batch that silently ran one lane looked identical to a batch
that fanned out across four. These tests capture the kwargs instead.
"""
from __future__ import annotations

import argparse

from prospector.config import load_config
from prospector.run import _resolve_lanes
from prospector.scheduler import run_scheduled as rs


class _Cfg:
    """The only two attributes `_resolve_lanes` reads off a config."""

    def __init__(self, active_lane="", active_lanes=None):
        self.active_lane = active_lane
        self.active_lanes = active_lanes


def _capture(monkeypatch) -> dict:
    """Stub run_signal, recording the kwargs the daemon actually passed."""
    seen: dict = {}

    def _fake(signal_text, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr("prospector.run.run_signal", _fake)
    return seen


def test_daemon_fans_out_across_configured_lanes(monkeypatch):
    """RED before the fix: `lanes` was absent, so run_signal ran the single solo_agent default."""
    seen = _capture(monkeypatch)

    rs._default_generate(cfg=_Cfg(active_lanes=["side_hustle", "smb", "growth", "venture"]),
                         batch_size=15)

    assert seen["lanes"] == ["side_hustle", "smb", "growth", "venture"]
    # >1 lane is what selects run_signal's generate_multilane branch (run.py:574) — a single-item
    # list would take the pinned-tier branch and re-collapse the catalogue onto one ambition class.
    assert len(seen["lanes"]) > 1


def test_active_lane_still_pins_a_single_tier(monkeypatch):
    """The singular pin keeps CLI precedence: active_lane overrides active_lanes everywhere."""
    seen = _capture(monkeypatch)

    rs._default_generate(cfg=_Cfg(active_lane="venture", active_lanes=["side_hustle", "smb"]),
                         batch_size=6)

    assert seen["lanes"] == ["venture"]


def test_unconfigured_daemon_keeps_the_pre_fix_behaviour(monkeypatch):
    """No lane config => lanes=None => byte-for-byte the single-default path. No forced change."""
    seen = _capture(monkeypatch)

    rs._default_generate(cfg=_Cfg(), batch_size=3)

    assert seen["lanes"] is None


def test_shipped_config_actually_engages_more_than_solo():
    """The real config.yaml must reach the daemon as a MIXED-ambition fan-out, not just solo.

    Guards the outcome the fix exists for: at least one lane whose generation archetype is not
    `solo_agent`, so the unattended catalogue cannot silently revert to solo-operator-only ideas.
    """
    cfg = load_config()
    lanes = _resolve_lanes(cfg, argparse.Namespace(lane=None))
    assert lanes and len(lanes) > 1, "shipped config must fan the daemon out across lanes"

    archetypes = {t: cfg.for_lane(t).generation.get("operator_archetype") for t in lanes}
    assert any(a != "solo_agent" for a in archetypes.values()), archetypes
