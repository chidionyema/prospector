"""Per-component model pins must ARRIVE, and a console knob must not be inert.

WHAT THIS FILE EXISTS TO STOP. Until 2026-08-19 the engine had two model-pin knobs, `model` and
`model_fast`, both editable from the ops console. Neither did anything. `_build_operator` decided
which provider a pin "belonged to" by matching a name prefix against a table
(`_PROVIDER_MODEL_PREFIX`); the value it computed was passed to exactly one construction site,
`ollama`, whose entry in that table was an empty tuple — so the match was always False and the
model always `None`. Setting `model:` to a MiniMax name, a Claude name or an Ollama name changed
the model of nothing. The console wrote the value, took a backup, recorded a history row and read
the new value back, and no call anywhere changed.

`tests/unit/test_model_config.py` was supposed to catch that and could not: its own class is
named `TestConfigOverridesHardcodedDefault` and its body branches on
`if kind in ("deepseek", "minimax")` — which is BOTH providers it parametrises — into an
assertion that the pin is ignored. The branch that tested the documented invariant was
unreachable. So the guard here is deliberately not "does the pin get read"; it is "does the pin
reach the built object", asked of the object.
"""
from __future__ import annotations

import copy

import pytest

from prospector.config import load_config
from prospector import operator as op
from prospector.ops import console_api as api


def _cfg():
    return load_config()


def _model_of(built) -> str:
    for attr in ("model", "_model", "_default_model", "_models"):
        v = getattr(built, attr, None)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, (list, tuple)) and v:
            return str(v[0])
    return ""


# --------------------------------------------------------------------------- resolution order

def test_a_component_pin_beats_the_provider_default():
    cfg = _cfg()
    baseline = _model_of(op._build_operator("minimax", cfg, fast=False, component="noncritical"))
    cfg.component_models = {"noncritical": {"minimax": "MiniMax-PINNED"}}
    assert _model_of(op._build_operator("minimax", cfg, fast=False,
                                        component="noncritical")) == "MiniMax-PINNED"
    assert baseline != "MiniMax-PINNED", "the fixture must differ from the default it overrides"


def test_a_pin_on_one_component_does_not_move_another():
    """The whole point of the field: the moat and the cheap tail are not coupled."""
    cfg = _cfg()
    moat_before = _model_of(op._build_operator("minimax", cfg, fast=False, component="moat"))
    cfg.component_models = {"noncritical": {"minimax": "MiniMax-PINNED"}}
    assert _model_of(op._build_operator("minimax", cfg, fast=False, component="moat")) == moat_before
    assert _model_of(op._build_operator("minimax", cfg, fast=False,
                                        component="noncritical")) == "MiniMax-PINNED"


def test_no_pin_is_exactly_the_old_behaviour():
    """An empty block must not change a single model, or this is a migration, not a feature."""
    cfg = _cfg()
    with_block = {k: _model_of(op._build_operator(k, cfg, fast=False, component="noncritical"))
                  for k in ("minimax", "minimax_m27", "deepseek", "ollama")}
    cfg.component_models = {}
    without = {k: _model_of(op._build_operator(k, cfg, fast=False, component=None))
               for k in ("minimax", "minimax_m27", "deepseek", "ollama")}
    assert with_block == without


def test_claude_cli_pin_layers_component_then_estate_then_cheapest():
    from prospector.claude_cli import CHEAPEST_CLAUDE_MODEL
    cfg = _cfg()
    cfg.claude_cli_model = ""
    cfg.component_models = {}
    assert _model_of(op._build_operator("claude_cli", cfg, fast=False,
                                        component="moat")) == CHEAPEST_CLAUDE_MODEL
    cfg.claude_cli_model = "claude-estate"
    assert _model_of(op._build_operator("claude_cli", cfg, fast=False,
                                        component="moat")) == "claude-estate"
    cfg.component_models = {"moat": {"claude_cli": "claude-moat-only"}}
    assert _model_of(op._build_operator("claude_cli", cfg, fast=False,
                                        component="moat")) == "claude-moat-only"
    assert _model_of(op._build_operator("claude_cli", cfg, fast=False,
                                        component="grounding")) == "claude-estate"


def test_component_pin_ignores_a_mock_config():
    """A MagicMock attribute is truthy. Treating one as a pin would hand every mocked test in the
    suite a model name that reads `<MagicMock id=...>` and fails somewhere else entirely."""
    from unittest.mock import MagicMock
    assert op.component_pin(MagicMock(), "moat", "minimax") == ""


# --------------------------------------------------------------------------- loud on a typo

@pytest.mark.parametrize("block, needle", [
    ({"markting": {"minimax": "x"}}, "unknown component"),
    ({"moat": {"minmax": "x"}}, "unknown provider"),
])
def test_an_unreadable_pin_raises_at_load(tmp_path, block, needle):
    """A name nothing reads is the defect this field replaced; it must not load quietly."""
    import yaml
    from prospector import config as C
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"operator": "mock", "component_models": block}))
    with pytest.raises(ValueError, match=needle):
        C.load_config(p)


# --------------------------------------------------------------------------- openrouter

def test_openrouter_is_constructible():
    """It was ~300 lines of adapter with no branch in `_build_operator` and no other call site
    in the repo, so every roster naming it raised `unknown operator`."""
    import os
    from unittest.mock import patch
    assert "openrouter" in op.BUILDABLE_TIERS
    cfg = _cfg()
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-key-for-test"}):
        built = op._build_operator("openrouter", cfg, fast=False, component="noncritical")
    assert isinstance(built, op.OpenRouterOperator)
    assert built.available_models, "the priority list must come from model_defaults.openrouter"


def test_openrouter_default_models_come_from_config():
    import os
    from unittest.mock import patch
    cfg = _cfg()
    cfg.model_defaults.openrouter = ["vendor/model-a:free", "vendor/model-b:free"]
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-key-for-test"}):
        built = op._build_operator("openrouter", cfg, fast=False, component="noncritical")
    assert set(built.available_models) == {"vendor/model-a:free", "vendor/model-b:free"}


# --------------------------------------------------------------------------- the console guard

def _model_knobs():
    return [k for k in api.KNOBS if k.get("group") == "models"]


def test_the_console_offers_a_pin_for_every_component():
    keys = {".".join(k["path"]) for k in _model_knobs()}
    for comp in op.COMPONENTS:
        assert any(k.startswith(f"component_models.{comp}.") for k in keys), (
            f"{comp} has no editable model pin — the console cannot set what config.yaml can")


def test_every_model_knob_names_a_key_that_exists_in_config_yaml():
    """`_act_config_set` refuses a key the rewriter cannot find, so a knob whose path is absent
    from the file is a control that always errors. This catches it before an operator does."""
    import yaml
    from prospector.config import REPO_ROOT
    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    for knob in _model_knobs():
        node = raw
        for part in knob["path"]:
            assert isinstance(node, dict) and part in node, (
                f"{'.'.join(knob['path'])} is a console knob with no line in config.yaml")
            node = node[part]


def test_no_model_knob_is_inert():
    """THE GUARD THAT WOULD HAVE CAUGHT `model` AND `model_fast`.

    Every knob in the models group must change what an operator is built with. A knob that
    writes a config key no builder reads is worse than a missing feature: it reports success.
    """
    import os
    from unittest.mock import patch
    env = {"MINIMAX_API_KEY": "k", "DEEPSEEK_API_KEY": "k", "OPENROUTER_API_KEY": "k"}
    inert: list[str] = []
    unknown: list[str] = []
    for knob in _model_knobs():
        path = knob["path"]
        cfg = _cfg()
        if path[0] == "component_models":
            _, comp, prov = path
            before_cfg, after_cfg = _cfg(), _cfg()
            after_cfg.component_models = copy.deepcopy(after_cfg.component_models)
            after_cfg.component_models.setdefault(comp, {})[prov] = "SENTINEL-MODEL"
            kind, component = prov, comp
        elif len(path) == 2 and path[0] == "model_defaults":
            _, prov = path
            before_cfg, after_cfg = _cfg(), _cfg()
            setattr(after_cfg.model_defaults, prov, "SENTINEL-MODEL")
            # minimax_fast only shows up on a fast build; minimax_m27 is its own tier name.
            kind = {"minimax_fast": "minimax", "minimax_m27": "minimax_m27"}.get(prov, prov)
            component = None
        else:
            unknown.append(".".join(path))
            continue
        fast = path[-1] == "minimax_fast"
        with patch.dict(os.environ, env):
            try:
                a = _model_of(op._build_operator(kind, before_cfg, fast=fast, component=component))
                b = _model_of(op._build_operator(kind, after_cfg, fast=fast, component=component))
            except RuntimeError:
                continue  # no credential on this machine — not an inertness signal
        if a == b:
            inert.append(".".join(path))
    assert not unknown, (
        "this test does not know how to prove these knobs arrive at a built operator, so it "
        "cannot vouch for them. A new model knob ships with the proof that setting it changes "
        f"a call, or it is another `model`/`model_fast`: {unknown}")
    assert not inert, (
        "these console knobs write a config key that changes no call — the exact defect "
        f"`model`/`model_fast` were: {inert}")


def test_the_two_knobs_that_did_nothing_are_gone():
    keys = {".".join(k["path"]) for k in api.KNOBS}
    assert "model" not in keys and "model_fast" not in keys, (
        "`model`/`model_fast` reached one construction site whose prefix table was empty, so "
        "they selected a model for nothing. Do not re-add them without a test that a pin arrives.")
