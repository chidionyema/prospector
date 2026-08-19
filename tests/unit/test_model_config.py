"""Behavioral tests for the model-config refactor (HARDCODED_MODEL_AUDIT_TICKET).

The invariant: model identifiers are config-driven, not hardcoded. Setting
`component_models.<component>.<provider>`, or `model_defaults.<provider>`, must
select a different model than the operator's hardcoded default, without code changes.

Rewritten 2026-08-20. Until then this file tested `cfg.model`, a key that reached
exactly one construction site behind an empty prefix table and therefore selected
nothing anywhere. `TestConfigOverridesHardcodedDefault` branched on
`if kind in ("deepseek", "minimax")` — both of its own parameters — into an assertion
that the pin was IGNORED, so the branch testing the documented invariant was
unreachable and the suite was green while pinning did nothing.
See docs/MODEL_PINNING_PROGRAM.md.

If this invariant ever breaks (e.g. a future refactor forgets to thread the
config value through), the hardcoded-default test will silently pass (the
operator still uses its hardcoded default) while the config-overrides test
will fail, surfacing the regression.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# Each (kind, default_env_var) pair needs its API key set for the operator
# to construct. We use patch.dict to set the env var at test time.
#
# `claude` (the paid Anthropic API tier) was removed here on 2026-08-15 with the tier itself:
# `_build_operator("claude")` raises by design (operator.py:1346), so the parameter tested a
# deleted branch. It survived because its `skipif(not _anthropic_works())` guard fires on any
# machine without a working anthropic/jiter install — this laptop skipped it, CI has the SDK
# and ran it, which is why the suite was green locally and red on the PR.
PROVIDERS = [
    # ("claude", "ANTHROPIC_API_KEY") removed 2026-08-15 with the paid Anthropic API tier's
    # adapter; `_build_operator("claude", ...)` now raises ValueError by design.
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("minimax", "MINIMAX_API_KEY"),
]



def _make_cfg(model: str, model_fast: str, kind: str):
    cfg = MagicMock()
    cfg.model = model
    cfg.model_fast = model_fast
    cfg.operator = kind
    cfg.retrieval = MagicMock()
    cfg.model_defaults = MagicMock()
    cfg.component_models = {}
    cfg.claude_cli_model = ""
    return cfg


class TestComponentPinOverridesProviderDefault:
    """A per-component pin must beat model_defaults for that component only."""

    @pytest.mark.parametrize("kind, env_var", PROVIDERS)
    def test_component_pin_wins(self, kind, env_var):
        from prospector.operator import _build_operator

        with patch.dict(os.environ, {env_var: "fake-key-for-test"}):
            cfg = _make_cfg(model="", model_fast="", kind=kind)
            setattr(cfg.model_defaults, kind, "the-provider-default")
            cfg.component_models = {"noncritical": {kind: "the-component-pin"}}

            pinned = _build_operator(kind, cfg, fast=False, component="noncritical")
            assert pinned.model == "the-component-pin", (
                f"{kind}: component_models.noncritical.{kind} must select the model. "
                f"Got {pinned.model!r}."
            )

    @pytest.mark.parametrize("kind, env_var", PROVIDERS)
    def test_a_pin_on_one_component_does_not_move_another(self, kind, env_var):
        from prospector.operator import _build_operator

        with patch.dict(os.environ, {env_var: "fake-key-for-test"}):
            cfg = _make_cfg(model="", model_fast="", kind=kind)
            setattr(cfg.model_defaults, kind, "the-provider-default")
            cfg.component_models = {"noncritical": {kind: "the-component-pin"}}

            other = _build_operator(kind, cfg, fast=False, component="moat")
            assert other.model == "the-provider-default", (
                f"{kind}: pinning noncritical moved moat too. Got {other.model!r}. "
                "The decoupling is the whole point of component_models."
            )


class TestEmptyConfigFallsBackToHardcoded:
    """When cfg.model is empty, the operator's own default must apply."""

    @pytest.mark.parametrize("kind, env_var", PROVIDERS)
    def test_empty_cfg_uses_hardcoded_default(self, kind, env_var):
        from prospector.operator import _build_operator

        with patch.dict(os.environ, {env_var: "fake-key-for-test"}):
            cfg = _make_cfg(model="", model_fast="", kind=kind)
            op = _build_operator(kind, fast=False, cfg=cfg)
            # Must be a non-empty string (the operator's hardcoded default)
            assert op.model, (
                f"{kind}: empty cfg.model should fall back to a hardcoded default, "
                f"not silently become empty/None."
            )
            assert op.model != "", f"{kind}: model is empty string"


class TestModelFastForFastOperators:
    """For minimax (the only operator that currently uses fast differently),
    cfg.model_fast must select a different model than cfg.model."""

    def test_minimax_fast_uses_model_fast(self):
        from prospector.operator import _build_operator

        with patch.dict(os.environ, {"MINIMAX_API_KEY": "fake-key-for-test"}):
            cfg = _make_cfg(
                model="minimax-m3-full",
                model_fast="minimax-m2.7-fast",
                kind="minimax",
            )
            # minimax NEVER accepts cfg.model/cfg.model_fast per _build_operator's
            # design — it uses model_defaults exclusively. Set model_defaults so
            # the test can verify the fast/slow distinction via config.
            cfg.model_defaults.minimax = "minimax-m3-full"
            cfg.model_defaults.minimax_fast = "minimax-m2.7-fast"
            op_full = _build_operator("minimax", cfg, fast=False)
            op_fast = _build_operator("minimax", cfg, fast=True)
            assert op_full.model == "minimax-m3-full"
            assert op_fast.model == "minimax-m2.7-fast"
            assert op_full.model != op_fast.model


class TestOneLineMigration:
    """The deepseek-chat deprecation (2026-07-24) must be a 1-line config change.

    Today: cfg.model = "deepseek-chat" (or default fallback). After the change:
    cfg.model = "deepseek-v4-pro" (whatever succeeds it). The operator picks up
    the new model automatically — no code change, no operator class edit.
    """

    def test_deepseek_model_is_config_driven(self):
        """The whole point: changing model_defaults.deepseek = a different string
        causes a different model to be used, without touching operator.py."""
        from prospector.operator import _build_operator

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key-for-test"}):
            for test_model in ("deepseek-chat", "deepseek-v4-pro",
                              "deepseek-v4-flash", "anything-else"):
                cfg = _make_cfg(model="", model_fast="", kind="deepseek")
                cfg.model_defaults.deepseek = test_model
                op = _build_operator("deepseek", cfg, fast=False)
                assert op.model == test_model, (
                    f"DeepSeek should use {test_model!r} when set in model_defaults; "
                    f"got {op.model!r}"
                )
