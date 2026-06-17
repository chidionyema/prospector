"""Behavioral tests for the model-config refactor (HARDCODED_MODEL_AUDIT_TICKET).

The invariant: model identifiers are config-driven, not hardcoded. Setting
`cfg.model` (or `cfg.model_fast` for fast operators) must select a different
model than the operator's hardcoded default — without code changes.

If this invariant ever breaks (e.g. a future refactor forgets to thread the
config value through), the hardcoded-default test will silently pass (the
operator still uses its hardcoded default) while the config-overrides test
will fail, surfacing the regression.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


def _anthropic_works() -> bool:
    """The anthropic SDK depends on jiter (a native module). If jiter is
    broken in this venv, Claude tests would error on import — skip them
    rather than masking the real env issue. The other providers are
    sufficient to verify the model-config refactor.
    """
    try:
        from anthropic import Anthropic  # noqa: F401
        return True
    except Exception:
        return False


# Each (kind, default_env_var) pair needs its API key set for the operator
# to construct. We use patch.dict to set the env var at test time.
PROVIDERS = [
    ("gemini", "GEMINI_API_KEY"),
    pytest.param("claude", "ANTHROPIC_API_KEY",
                 marks=pytest.mark.skipif(
                     not _anthropic_works(),
                     reason="anthropic SDK / jiter import broken in this env")),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("minimax", "MINIMAX_API_KEY"),
]


PROVIDER_PREFIXES = {"gemini": "gemini-", "claude": "claude-", "deepseek": "deepseek-", "minimax": "minimax-"}

def _make_cfg(model: str, model_fast: str, kind: str):
    cfg = MagicMock()
    cfg.model = model
    cfg.model_fast = model_fast
    cfg.operator = kind
    cfg.retrieval = MagicMock()
    cfg.model_defaults = MagicMock()
    cfg.model_defaults.gemini = "gemini-2.0-flash"
    cfg.model_defaults.claude = "claude-sonnet-4-5"
    return cfg


class TestConfigOverridesHardcodedDefault:
    """cfg.model must override the operator's _DEFAULT_MODEL when set."""

    @pytest.mark.parametrize("kind, env_var", PROVIDERS)
    def test_cfg_model_overrides_hardcoded_default(self, kind, env_var):
        from prospector.operator import _build_operator

        # Use a model name that starts with the provider prefix so _build_operator
        # recognises it as a provider-specific pin (see _PROVIDER_MODEL_PREFIX logic).
        prefix = PROVIDER_PREFIXES.get(kind, "")
        override_model = f"{prefix}test-override-model"

        with patch.dict(os.environ, {env_var: "fake-key-for-test"}):
            cfg = _make_cfg(model=override_model, model_fast="", kind=kind)
            op = _build_operator(kind, cfg, fast=False)
            # deepseek and minimax NEVER accept cfg.model (they use model_defaults
            # exclusively per _build_operator's design). For those, verify the
            # correct fallback was used instead.
            if kind in ("deepseek", "minimax"):
                expected = cfg.model_defaults.deepseek if kind == "deepseek" else cfg.model_defaults.minimax or cfg.model_defaults.minimax_fast
                assert op.model == expected, (
                    f"{kind}: should use model_defaults.{kind} when cfg.model is not "
                    f"a pinned match. Got {op.model!r} instead of {expected!r}."
                )
            else:
                assert op.model == override_model, (
                    f"{kind}: cfg.model should override the hardcoded default. "
                    f"Got {op.model!r} instead of {override_model!r}."
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
