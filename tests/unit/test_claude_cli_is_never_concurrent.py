"""One claude subprocess at a time, machine-wide, whatever anyone asks for.

Founder directive 2026-08-21, given more than once and finally as "for the last fuckinng tine":
"i dont want consurreny onclaude code", "its too expencice".

This is a test and not a note because the number kept drifting back up on its own — it was 2,
then `config.yaml` raised it to 4, and both were reached by editing a default rather than by
anyone deciding to spend more. A default can drift. A clamp with a test on it cannot.

What is pinned here is the CEILING, not the brand and not the config key. If the config key is
renamed or the adapter is replaced, these tests should be rewritten to point at whatever the new
governor is, never deleted.
"""
import pathlib

import yaml

from prospector import claude_cli


def test_the_ceiling_is_one():
    assert claude_cli._CLAUDE_MAX_EVER == 1
    assert claude_cli._MAX_CLI == 1


def test_asking_for_more_gets_one():
    original = claude_cli._MAX_CLI
    try:
        for asked in (2, 4, 8, 64):
            claude_cli.configure_concurrency(asked)
            assert claude_cli._MAX_CLI == 1, f"configure_concurrency({asked}) raised the ceiling"
    finally:
        claude_cli.configure_concurrency(original)


def test_asking_for_less_than_one_still_gets_one():
    original = claude_cli._MAX_CLI
    try:
        for asked in (0, -1):
            claude_cli.configure_concurrency(asked)
            assert claude_cli._MAX_CLI == 1, f"configure_concurrency({asked}) went below one"
    finally:
        claude_cli.configure_concurrency(original)


def test_the_env_override_cannot_raise_it_either():
    """PROSPECTOR_CLAUDE_CONCURRENCY pins the value, so it must not be able to pin a high one.

    The module reads the env var at import, so this asserts the import-time expression is the
    clamp rather than the env value. Re-importing under a patched environ is the only honest way
    to grade a module-level constant.
    """
    import importlib
    import os

    original = os.environ.get("PROSPECTOR_CLAUDE_CONCURRENCY")
    try:
        os.environ["PROSPECTOR_CLAUDE_CONCURRENCY"] = "16"
        reloaded = importlib.reload(claude_cli)
        assert reloaded._MAX_CLI == 1
    finally:
        if original is None:
            os.environ.pop("PROSPECTOR_CLAUDE_CONCURRENCY", None)
        else:
            os.environ["PROSPECTOR_CLAUDE_CONCURRENCY"] = original
        importlib.reload(claude_cli)


def test_the_config_key_agrees_with_the_clamp():
    """A config that says 4 while the code allows 1 is a lie an operator will act on."""
    root = pathlib.Path(__file__).resolve().parents[2]
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    assert int(cfg["retrieval"]["claude_concurrency"]) == 1
