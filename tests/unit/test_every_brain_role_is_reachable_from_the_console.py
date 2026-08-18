"""The console must be able to change the brain for EVERY role, and the model each brain runs.

The founder's ask was plain: swapping a role's brain, or pointing a brain at a different model
version, must be a console edit. Before 2026-08-18 the page reached three of five chains and
none of the model pins, so changing the brain that writes what a buyer reads meant editing
config.yaml on the Fly machine — the one thing this page exists to remove.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from prospector.operator import BUILDABLE_TIERS, _build_operator, _coerce_moat_primary
from prospector.ops.config_editor import validate_config
from prospector.ops.console_api import KNOBS_BY_KEY, _coerce, _dig

CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"

# Every role that routes work to a brain. `moat_primary` is not a chain that runs, it is the
# roster that may rule finally, and it is a role decision like the rest.
ROLE_KEYS = ("operator", "moat_primary", "noncritical_operator",
             "artifact_operator", "marketing_operator")
MODEL_PINS = ("model", "model_fast", "model_defaults.minimax",
              "model_defaults.minimax_fast", "model_defaults.minimax_m27",
              "model_defaults.deepseek", "model_defaults.ollama")


def _raw() -> dict:
    return yaml.safe_load(CONFIG.read_text())


@pytest.mark.parametrize("key", ROLE_KEYS + MODEL_PINS)
def test_the_console_can_reach_every_brain_role(key):
    assert key in KNOBS_BY_KEY, (
        f"{key} routes work to a brain but no console knob sets it, so changing it means "
        f"editing config.yaml on the box. Known knobs: {sorted(KNOBS_BY_KEY)}")
    assert KNOBS_BY_KEY[key]["group"] == "brains"


def test_no_operator_chain_in_config_is_unreachable_from_the_console():
    """A drift guard: a chain key added to config.yaml later must land on this page too."""
    raw = _raw()
    chains = [k for k in raw if k.endswith("_operator") or k == "operator"]
    unreachable = [k for k in chains if k not in KNOBS_BY_KEY]
    assert not unreachable, (
        f"config.yaml declares {unreachable} but the console cannot set them")


@pytest.mark.parametrize("key", ROLE_KEYS + MODEL_PINS)
def test_the_console_accepts_the_value_already_on_disk(key):
    """The lowest bar there is: a page that cannot re-save the live config is not an editor.

    `noncritical_operator: [minimax, minimax_m27]` failed exactly this before the fix, because
    the moat kept a SECOND hand-maintained list of buildable tiers that never learned m27.
    """
    spec = KNOBS_BY_KEY[key]
    current = _dig(_raw(), tuple(spec["path"]))
    assert current is not None, f"{key} is absent from config.yaml; the rewriter never adds keys"
    assert _coerce(spec, current) == current


def test_there_is_one_list_of_buildable_tiers_and_the_moat_reads_it():
    """`minimax_m27` was buildable and ran in production while the moat called it a typo."""
    for tier in BUILDABLE_TIERS:
        assert _coerce_moat_primary([tier], source="test") == {tier}


def test_every_buildable_tier_can_actually_be_built(monkeypatch):
    """The other half: a name on the allow-list that no adapter serves is a worse lie.

    Credentials are stubbed. What is being proven is that an ADAPTER exists for every name the
    console offers, not that this machine holds a key for it — CI holds none, and a test that
    demanded them would pass on a laptop and fail in CI for a reason unrelated to the claim.
    """
    from prospector.config import load_config

    for var in ("MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(var, "test-key-not-a-credential")

    cfg = load_config(str(CONFIG))
    for tier in BUILDABLE_TIERS:
        _build_operator(tier, cfg, fast=False)  # raises if the adapter is gone


def test_a_brain_name_no_adapter_serves_is_refused_at_save_time():
    """Refused by the knob AND by the validator, so a caller skipping the page meets it too."""
    with pytest.raises(ValueError, match="not allowed here"):
        _coerce(KNOBS_BY_KEY["operator"], "gemini")
    for field in ROLE_KEYS:
        raw = _raw()
        raw[field] = ["gemini"]
        ok, errors = validate_config(raw)
        assert not ok and any(field in e for e in errors), (
            f"{field} accepted an unbuildable brain: {errors}")


def test_a_model_pin_stays_text():
    """`model: "3"` fell through to parseFloat in the browser and to passthrough in Python."""
    spec = KNOBS_BY_KEY["model_defaults.minimax"]
    assert _coerce(spec, "3") == "3"
    assert _coerce(spec, "  MiniMax-M3  ") == "MiniMax-M3"
    for junk in ({"model": "x"}, ["MiniMax-M3"], True):
        with pytest.raises(ValueError):
            _coerce(spec, junk)


def test_the_ui_offers_the_roster_rather_than_asking_the_operator_to_recall_it():
    for key in ROLE_KEYS:
        assert KNOBS_BY_KEY[key].get("choices") == list(BUILDABLE_TIERS), (
            f"{key} has no allow-list, so the page cannot tell an operator which brains exist")


def test_changing_who_rules_still_needs_the_extra_acknowledgement():
    """Widening the page must not widen it past the fence."""
    for key in ROLE_KEYS:
        assert KNOBS_BY_KEY[key].get("high_blast") is True, key
