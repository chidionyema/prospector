"""Founder archetypes — config validation + prompt injection (generation-only).

Archetypes reframe WHO can build the idea. They must never move gates/thresholds.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from prospector.config import UnknownArchetypeError, load_config
from prospector.generate import generate


def test_live_config_defines_three_archetypes():
    cfg = load_config()
    archetypes = cfg.generation.get("archetypes") or {}
    assert set(archetypes) >= {"solo_agent", "small_team", "startup"}
    for name in ("solo_agent", "small_team", "startup"):
        assert str(archetypes[name].get("binding", "")).strip()


def test_lane_defaults_pin_archetypes_without_touching_gates():
    cfg = load_config()
    smb_gates = {k for g in (cfg.lanes["smb"].get("hard_gates") or []) for k in g
                 if k != "adversarial_decisive"}
    assert "buyer_intent" in smb_gates

    assert cfg.for_lane("side_hustle").generation["operator_archetype"] == "solo_agent"
    assert cfg.for_lane("smb").generation["operator_archetype"] == "small_team"
    assert cfg.for_lane("growth").generation["operator_archetype"] == "startup"
    assert cfg.for_lane("venture").generation["operator_archetype"] == "startup"


def test_for_archetype_overrides_lane_default_and_reapplies_via_for_lane():
    cfg = load_config().for_archetype("startup")
    pinned = cfg.for_lane("side_hustle")
    assert pinned.generation["operator_archetype"] == "startup"
    assert pinned.active_archetype == "startup"
    # Moat bar for side_hustle still applies (buyer_intent), not venture gates.
    assert "buyer_intent" in pinned.gate_map()
    assert "value_durability" not in pinned.gate_map()


def test_unknown_archetype_raises():
    cfg = load_config()
    with pytest.raises(UnknownArchetypeError):
        cfg.for_archetype("mega_corp")


def test_load_rejects_unknown_operator_archetype(tmp_path: Path):
    data = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    data["generation"]["operator_archetype"] = "not_a_real_archetype"
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    with pytest.raises(UnknownArchetypeError):
        load_config(p)


def test_generate_prompt_injects_archetype_binding():
    """operator_constraints from the active archetype must reach the generate prompt."""
    base = load_config().for_lane("smb")
    binding = base.generation["archetypes"]["small_team"]["binding"]
    gen = {
        **base.generation,
        "structural_forms": ["vertical_tool"],
        "audience_forms": [],
        "max_per_call": 1,
        "max_rounds": 1,
        "candidates_per_signal": 1,
    }
    cfg = replace(base, generation=gen)

    class _Op:
        def complete(self, system, user, **kwargs):
            return "[]"

    with patch("prospector.generate.render") as mocked:
        mocked.return_value = ("system", "user")
        generate(_Op(), cfg, k=1, signal_text="test signal")
        assert mocked.called
        oc = mocked.call_args.kwargs.get("operator_constraints", "")
        assert binding[:48] in oc
        assert "SMALL-TEAM" in oc


def test_closed_market_stubs_exist_and_stay_closed():
    cfg = load_config()
    for code in ("africa", "nigeria", "europe", "asia", "us"):
        assert cfg.market_status(code) == "closed"
    assert cfg.market_status("uk") == "open"
