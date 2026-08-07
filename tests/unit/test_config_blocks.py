"""The commercial-readiness config blocks: they load, they land OFF, and a typo is loud.

Three separate incidents in this repo produced this file:

1. A block whose key was misspelled read as configured-on while being completely inert
   (`hybrid_entity_checks` returning `[]` for an unlisted check). So every block here has
   a STRICT key allowlist and `_validate_block` raises at config load, not at first use.
2. New arms have shipped switched on and changed the daemon's behaviour before anyone had
   measured them. So `test_new_arms_land_inert` asserts the default state of every
   experimental block is OFF, and names the one deliberate exception.
3. Defaults have drifted out of `config.yaml` into code, which is how a documented knob
   stops matching the running system. So the shipped `config.yaml` is asserted to declare
   every key the validator knows about — no key may exist only in Python.
"""

from __future__ import annotations

import pytest
import yaml

from prospector.config import _BLOCK_KEYS, _validate_block, load_config
from prospector.paths import repo_path

BLOCKS = sorted(_BLOCK_KEYS)


@pytest.fixture(scope="module")
def cfg():
    return load_config(str(repo_path("config.yaml")))


@pytest.fixture(scope="module")
def raw_yaml():
    return yaml.safe_load(repo_path("config.yaml").read_text())


@pytest.mark.parametrize("block", BLOCKS)
def test_block_is_present_on_the_config_object(cfg, block):
    """Every block resolves to a dict on Config — not a missing attribute."""
    assert isinstance(getattr(cfg, block), dict)


@pytest.mark.parametrize("block", BLOCKS)
def test_unknown_key_raises_at_load_not_at_first_use(block):
    """A typo must stop the process at startup.

    The failure this prevents: `shadow_mod: true` silently doing nothing, so the arm reads
    as configured-on in the file and is inert in the process.
    """
    with pytest.raises(ValueError) as exc:
        _validate_block(block, {"definitely_not_a_real_key": 1})
    assert "unknown key" in str(exc.value)
    assert block in str(exc.value)


@pytest.mark.parametrize("block", BLOCKS)
def test_absent_block_is_empty_not_an_error(block):
    """An unset block degrades to {} so `getattr(cfg, block, {})` readers see defaults."""
    assert _validate_block(block, None) == {}
    assert _validate_block(block, {}) == {}


@pytest.mark.parametrize("block", BLOCKS)
def test_config_yaml_declares_every_known_key(raw_yaml, block):
    """No key may live only in Python. A knob absent from config.yaml is undiscoverable."""
    declared = set(raw_yaml.get(block) or {})
    missing = _BLOCK_KEYS[block] - declared
    assert not missing, f"config.yaml `{block}` is missing key(s): {sorted(missing)}"


def test_new_arms_land_inert(cfg):
    """Experimental arms ship OFF. The daemon's behaviour must not change on merge.

    An arm leaves this list only by acquiring a named test below that states WHY it is on
    and pins whatever fence replaces `enabled: false`. Deleting a name from here without
    adding that test is the weakening this pair exists to prevent."""
    for block in ("coverage_sampler", "meta_shape_monitor"):
        assert getattr(cfg, block).get("enabled") is False, f"{block} shipped switched ON"


def test_claim_lock_is_on_because_it_is_a_correctness_rail(cfg):
    """R2 is a correctness rail, not an experiment: a double-paid re-vet is a real cost."""
    assert cfg.claim_lock.get("enabled") is True


def test_numeric_citation_is_on_but_fenced_by_shadow_mode(cfg):
    """Founder 2026-08-07: switched ON deliberately (config.yaml:1065).

    `enabled` is NOT the fence here — `shadow_mode` is. The arm extracts the figures from
    a rationale and records whether each one appears in the passage that rationale cites;
    in shadow mode it writes a log line and nothing else, never demoting a check to
    `unverifiable` and never striking a sentence. Both flags are pinned so that promoting
    the observer into an actor is an explicit edit to this test, not a one-word config
    change. The action variant is not built yet."""
    assert cfg.numeric_citation.get("enabled") is True
    assert cfg.numeric_citation.get("shadow_mode") is True


def test_pack_data_is_on_and_ships_only_the_exercised_formats(cfg):
    """Founder 2026-08-07: the deterministic data files now ship in the bundle.

    `pdf` stays out of `formats` on purpose: render_pdf shells out to headless Chrome
    (pack_data.py:642-677) with a polling timeout, which is a subprocess dependency on a
    GUI app inside a pack build. `xlsx` is out for the same not-yet-exercised reason."""
    assert cfg.pack_data.get("enabled") is True
    assert "pdf" not in (cfg.pack_data.get("formats") or [])
    assert "xlsx" not in (cfg.pack_data.get("formats") or [])


def test_numeric_citation_cannot_act_while_shadow(cfg):
    """§25.6 was a founder decision: SHADOW FIRST. Acting on it is a second decision."""
    assert cfg.numeric_citation.get("shadow_mode") is True


def test_coverage_sampler_axes_are_real_dossier_columns(cfg):
    """`sector` is unmeasurable — no column exists and generation never writes one.

    V2 was originally specified on (sector x persona x tier x market). Two of those are not
    columns. This asserts the axes stayed on the four that are, so the item cannot silently
    regress to sampling over a field that is always empty.
    """
    assert cfg.coverage_sampler["axes"] == [
        "ambition_tier", "structural_form", "audience", "market"]
    assert "sector" not in cfg.coverage_sampler["axes"]
