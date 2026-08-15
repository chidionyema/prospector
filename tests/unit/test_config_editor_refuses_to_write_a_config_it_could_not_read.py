"""A failed config read must not become a config wipe.

`config_editor.load_config_raw` degrades to `{}` when config.yaml cannot be parsed — it has
to, because the Parameters page stages its return value and a Streamlit page that raises is
a dead page.  But the editor then treats that `{}` as "the operator emptied the config"
(`pages/_parameters.py:28` stages it, `:365` diffs it, Save writes it), so one unparseable
config.yaml plus one click replaces the engine's entire configuration with an empty file.

The fence is at the actuator: `write_config` refuses an empty payload, and refuses to write
on top of a config.yaml it cannot itself read.  Either fence alone leaves the wipe reachable.
"""
from __future__ import annotations

import pytest

from prospector.control_center import config_editor as ce


@pytest.fixture()
def staged_config(tmp_path):
    """Point the editor at a throwaway config.yaml, restoring the module overrides."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "thresholds:\n  confidence_floor: 0.6\noperator:\n  - claude_cli\n",
        encoding="utf-8",
    )
    orig = (ce.CONFIG_PATH, ce._BACKUP_DIR, ce._CC_DIR)
    ce.CONFIG_PATH = cfg_path
    ce._BACKUP_DIR = tmp_path / "backups"
    ce._CC_DIR = tmp_path / "cc"
    try:
        yield cfg_path
    finally:
        ce.CONFIG_PATH, ce._BACKUP_DIR, ce._CC_DIR = orig


def test_an_empty_staged_config_is_refused(staged_config):
    before = staged_config.read_text(encoding="utf-8")

    ok, msg = ce.write_config({}, moat_affecting=False,
                              orig_mtime=ce.get_config_mtime())

    assert ok is False
    assert "empty" in msg.lower()
    assert staged_config.read_text(encoding="utf-8") == before


def test_a_config_that_cannot_be_parsed_is_never_overwritten(staged_config):
    # An operator opened Parameters while config.yaml was broken: the page staged `{}`,
    # then edited one threshold on top of it. The payload is non-empty and valid — the
    # only thing wrong with it is everything it silently dropped.
    staged_config.write_text("thresholds:\n  confidence_floor: [unclosed\n", encoding="utf-8")
    before = staged_config.read_text(encoding="utf-8")
    assert ce.load_config_raw() == {}, "precondition: the read degrades to empty"

    ok, msg = ce.write_config({"thresholds": {"confidence_floor": 0.7}},
                              moat_affecting=False,
                              orig_mtime=ce.get_config_mtime())

    assert ok is False
    assert "cannot be parsed" in msg
    assert staged_config.read_text(encoding="utf-8") == before


def test_a_real_edit_on_a_readable_config_still_writes(staged_config):
    """The fence must not block the ordinary path it sits in front of."""
    cfg = ce.load_config_raw()
    assert cfg, "precondition: the fixture config parses"
    cfg["thresholds"]["confidence_floor"] = 0.7

    ok, msg = ce.write_config(cfg, moat_affecting=False,
                              orig_mtime=ce.get_config_mtime())

    assert ok is True, msg
    assert ce.load_config_raw()["thresholds"]["confidence_floor"] == 0.7
