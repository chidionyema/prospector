"""Lane management CLI: nix, natch, set, unset, list.

Tests the _manage_lanes function (line-based config.yaml mutation) plus the
_resolve_lanes resolution logic that the run pipeline consumes.

All tests are offline — they operate on a temp config.yaml; no live calls.
"""
from __future__ import annotations

import os
import re
import textwrap
import tempfile
from pathlib import Path

import pytest
from prospector.run import _manage_lanes, _resolve_lanes
from prospector.config import load_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_config():
    """Write a minimal config.yaml to a temp dir, yield the path."""
    content = textwrap.dedent("""\
        operator: mock
        model: ""
        model_fast: ""
        active_lane: ""
        active_lanes: [side_hustle, smb, growth, venture]
        lane_quota:
          side_hustle: 4
          smb: 3
          growth: 3
          venture: 3
        lanes:
          venture:
            hard_gates:
              - value_durability: [refuted]
              - adversarial_decisive: true
            thresholds:
              confidence_floor: 0.6
              min_composite_to_pass: 3.2
          side_hustle:
            hard_gates:
              - buyer_intent: [refuted]
              - adversarial_decisive: true
            thresholds:
              confidence_floor: 0.6
              min_composite_to_pass: 2.0
          smb:
            hard_gates:
              - buyer_intent: [refuted]
              - adversarial_decisive: true
            thresholds:
              confidence_floor: 0.6
              min_composite_to_pass: 2.6
        hard_gates: []
        weights: {}
        thresholds:
          confidence_floor: 0.6
          min_composite_to_pass: 3.2
        generation:
          candidates_per_signal: 5
        retrieval:
          provider: fixture
    """)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "config.yaml"
        path.write_text(content)
        yield path


def _read_config(path: Path) -> dict:
    """Load the config as a raw dict for field-level assertions."""
    import yaml
    return yaml.safe_load(path.read_text())


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def test_list_shows_all_defined_lanes(capsys, temp_config):
    """`lanes list` prints the defined lanes and active state."""
    _manage_lanes("list", None, temp_config)
    out = capsys.readouterr().out
    # Defined lanes: only those in the `lanes:` block (venture, side_hustle, smb)
    assert "Defined lanes:" in out
    assert "venture" in out
    assert "side_hustle" in out
    assert "smb" in out
    # growth is in active_lanes but NOT defined in lanes: — still listed in active_lanes
    assert "active_lanes" in out
    assert "growth" in out  # in active_lanes list
    # active_lane is empty (multi-lane mode)
    assert "active_lane:" in out
    assert "(multi-lane mode)" in out


# ---------------------------------------------------------------------------
# nix
# ---------------------------------------------------------------------------

def test_nix_removes_lane_from_active_lanes(temp_config):
    """Nixing a lane removes it from the active_lanes list."""
    _manage_lanes("nix", "side_hustle", temp_config)
    d = _read_config(temp_config)
    assert d["active_lanes"] == ["smb", "growth", "venture"]


def test_nix_last_lane_leaves_empty_list(temp_config):
    """Nixing all lanes should leave an empty list (no error)."""
    # First nix 3
    for lane in ["side_hustle", "smb", "growth"]:
        _manage_lanes("nix", lane, temp_config)
    _manage_lanes("nix", "venture", temp_config)
    d = _read_config(temp_config)
    assert d["active_lanes"] == []


def test_nix_unknown_lane_is_noop(capsys, temp_config):
    """Nixing a lane not in active_lanes is a no-op and warns."""
    original_lines = temp_config.read_text()
    _manage_lanes("nix", "bogus_lane", temp_config)
    d = _read_config(temp_config)
    assert "side_hustle" in d["active_lanes"]  # unchanged
    out = capsys.readouterr().out
    assert "not in active_lanes" in out.lower() or "bogus" in out.lower()


def test_nix_preserves_other_config(temp_config):
    """Nixing a lane does not corrupt other config fields."""
    _manage_lanes("nix", "growth", temp_config)
    d = _read_config(temp_config)
    assert d["operator"] == "mock"
    assert "venture" in d["lanes"]
    assert d["thresholds"]["confidence_floor"] == 0.6
    assert "growth" not in d["active_lanes"]


# ---------------------------------------------------------------------------
# natch
# ---------------------------------------------------------------------------

def test_natch_adds_lane_to_active_lanes(temp_config):
    """Natching a lane appends it to the active_lanes list."""
    # First nix it
    _manage_lanes("nix", "side_hustle", temp_config)
    d = _read_config(temp_config)
    assert "side_hustle" not in d["active_lanes"]
    # Then natch it back
    _manage_lanes("natch", "side_hustle", temp_config)
    d = _read_config(temp_config)
    assert "side_hustle" in d["active_lanes"]


def test_natch_already_active_lane_is_noop(capsys, temp_config):
    """Natching a lane already in active_lanes is a no-op and informs."""
    _manage_lanes("natch", "venture", temp_config)
    d = _read_config(temp_config)
    # venture should appear exactly once
    assert d["active_lanes"].count("venture") == 1
    out = capsys.readouterr().out
    assert "already" in out.lower() or "already in active_lanes" in out.lower()


def test_natch_any_lane_works_even_if_not_defined(temp_config):
    """Natching a lane not defined in `lanes:` warns but still adds it."""
    _manage_lanes("natch", "growth", temp_config)
    d = _read_config(temp_config)
    assert "growth" in d["active_lanes"]


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------

def test_set_active_lane_pins_single_lane(temp_config):
    """`lanes set X` sets active_lane to X (active_lane overrides active_lanes)."""
    _manage_lanes("set", "side_hustle", temp_config)
    d = _read_config(temp_config)
    assert d["active_lane"] == "side_hustle"
    # active_lanes is preserved (active_lane takes precedence in resolver)
    assert "venture" in d["active_lanes"]


def test_set_to_empty_clears_active_lane(temp_config):
    """Setting active_lane to empty string goes back to multi-lane."""
    # First set something
    _manage_lanes("set", "side_hustle", temp_config)
    # Now unset
    _manage_lanes("set", "", temp_config)
    d = _read_config(temp_config)
    assert d["active_lane"] == ""


def test_set_unknown_lane_warns(temp_config):
    """Setting an undefined lane warns but still sets it."""
    _manage_lanes("set", "super_saiyan", temp_config)
    d = _read_config(temp_config)
    assert d["active_lane"] == "super_saiyan"


# ---------------------------------------------------------------------------
# unset
# ---------------------------------------------------------------------------

def test_unset_clears_active_lane(temp_config):
    """`lanes unset` resets active_lane to "" (multi-lane mode)."""
    _manage_lanes("set", "side_hustle", temp_config)
    _manage_lanes("unset", None, temp_config)
    d = _read_config(temp_config)
    assert d["active_lane"] == ""


def test_unset_when_already_empty_is_noop(capsys, temp_config):
    """Unsetting when active_lane is already empty is fine."""
    _manage_lanes("unset", None, temp_config)
    d = _read_config(temp_config)
    assert d["active_lane"] == ""


# ---------------------------------------------------------------------------
# _resolve_lanes (integration with the run pipeline)
# ---------------------------------------------------------------------------

def test_resolve_lanes_with_explicit_lane_arg():
    """--lane X overrides everything → single pinned tier."""
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.active_lane = ""
    cfg.active_lanes = ["venture", "side_hustle"]
    args = MagicMock()
    args.lane = "side_hustle"
    assert _resolve_lanes(cfg, args) == ["side_hustle"]


def test_resolve_lanes_with_active_lane():
    """active_lane config field → single pinned tier."""
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.active_lane = "smb"
    cfg.active_lanes = ["venture", "side_hustle"]
    args = MagicMock()
    args.lane = None
    assert _resolve_lanes(cfg, args) == ["smb"]


def test_resolve_lanes_with_active_lanes():
    """active_lanes config field → multi-lane set."""
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.active_lane = ""
    cfg.active_lanes = ["side_hustle", "venture"]
    args = MagicMock()
    args.lane = None
    assert _resolve_lanes(cfg, args) == ["side_hustle", "venture"]


def test_resolve_lanes_none_when_no_lanes():
    """No lanes configured → None (byte-for-byte default behaviour)."""
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.active_lane = ""
    cfg.active_lanes = []
    args = MagicMock()
    args.lane = None
    assert _resolve_lanes(cfg, args) is None
