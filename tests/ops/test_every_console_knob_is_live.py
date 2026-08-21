"""Every control the portal draws must move something the engine reads.

THE CLASS, and it has bitten this console three times. `model` and `model_fast` wrote a config
key whose only construction site had an empty prefix table. `retrieval.claude_concurrency`
offered 16 against a code clamp of 1. Both moved config.yaml, both printed a receipt, and both
changed nothing the engine does -- which is worse than a missing control, because the operator
believes they turned it down.

Three tests already close that class one GROUP at a time:
`test_component_models.py::test_no_model_knob_is_inert` for the model pins,
`test_cadence_is_configurable.py::test_every_new_knob_resolves_against_the_real_config` for the
schedule keys, and `test_the_console_cannot_offer_a_dead_concurrency_knob.py` for the one pinned
knob. Each is stronger than what is here, and each covers roughly a fifth of the list. This file
is the floor UNDER all of them: it grades every knob in `KNOBS`, including ones added tomorrow,
on the four things that can be checked without knowing what the key means.

What it deliberately does NOT claim: that a knob CHANGES A CALL. Only the per-group tests above
can prove that, and a knob whose group has no such test is carried here on the weaker evidence.
The list `_NO_READER_OUTSIDE_CONSOLE` is where that gap is written down rather than hidden.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache

import pytest
import yaml

from prospector.config import REPO_ROOT, load_config
from prospector.ops import config_editor as ce
from prospector.ops import console_api as api

sys.path.insert(0, str(REPO_ROOT / "tests" / "unit"))

from repo_files import repo_files  # noqa: E402


@lru_cache(maxsize=1)
def _searchable() -> tuple[tuple[str, str], ...]:
    """(relative path, text) for everything under prospector/ and scripts/ worth grepping.

    This used to shell out to `rg` once per knob. That passed on the founder's laptop and failed
    61 times on the Fly CI runners, whose image has no ripgrep: `FileNotFoundError: [Errno 2] No
    such file or directory: 'rg'` (run 32444675763, job 96665192946, 2026-08-21). A test may only
    depend on tools the runner actually has, and the local gate cannot catch the difference,
    because the laptop has them.

    Read once and cached, so this is also 61 fewer processes than the version it replaces.
    """
    out = []
    for path in repo_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if not (rel.startswith("prospector/") or rel.startswith("scripts/")):
            continue
        if rel.endswith(".md") or rel == "prospector/ops/console_api.py":
            continue
        if rel.startswith(("store/", "storage/")) or "/node_modules/" in rel:
            continue
        try:
            out.append((rel, path.read_text(errors="ignore")))
        except OSError:
            continue
    return tuple(out)

_RAW = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
_CFG = load_config()

#: Knobs whose leaf name is not greppable outside the console, WITH the reason. A name here is a
#: knob nothing in this file can vouch for -- it is not a waiver, it is a debt.
_NO_READER_OUTSIDE_CONSOLE: dict[str, str] = {}


def _key(knob: dict) -> str:
    return ".".join(knob["path"])


def _knobs() -> list[dict]:
    """Every knob the console actually serves, generated ones included."""
    return list(api.KNOBS)


def _resolve(root, path: list[str]):
    """Walk a dotted path through dicts AND dataclasses. Returns (found, value)."""
    node = root
    for part in path:
        if isinstance(node, dict):
            if part not in node:
                return False, None
            node = node[part]
        elif hasattr(node, part):
            node = getattr(node, part)
        else:
            return False, None
    return True, node


@pytest.mark.parametrize("knob", _knobs(), ids=_key)
def test_the_knob_names_a_key_that_exists_in_config_yaml(knob):
    """`_act_config_set` refuses a key the rewriter cannot find, so a knob whose path is absent
    from the file is a control that always errors. Catch it here, not on the operator."""
    found, _ = _resolve(_RAW, knob["path"])
    assert found, f"{_key(knob)} is a console knob with no line in config.yaml"


@pytest.mark.parametrize("knob", _knobs(), ids=_key)
def test_the_key_survives_the_loader(knob):
    """A line in config.yaml that `load_config` drops on the floor reaches no reader at all.
    The file is where the console WRITES; the loaded config is what the engine READS, and only
    the second one decides whether the knob did anything."""
    found, _ = _resolve(_CFG, knob["path"])
    assert found, (
        f"{_key(knob)} is in config.yaml but not on the object load_config() returns, so nothing "
        f"in the engine can see a change to it")


@pytest.mark.parametrize("knob", [k for k in _knobs() if "min" in k or "max" in k], ids=_key)
def test_the_declared_bounds_contain_the_value_already_on_disk(knob):
    """A bound that excludes the live setting is a control that refuses the status quo. The
    operator opens the page, changes nothing, saves, and is told the current config is invalid."""
    found, value = _resolve(_RAW, knob["path"])
    assert found
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        pytest.skip(f"{_key(knob)} is not numeric on disk")
    lo, hi = knob.get("min"), knob.get("max")
    if lo is not None:
        assert value >= lo, f"{_key(knob)} is {value} on disk, below the console minimum {lo}"
    if hi is not None:
        assert value <= hi, f"{_key(knob)} is {value} on disk, above the console maximum {hi}"


@pytest.mark.parametrize("knob", _knobs(), ids=_key)
def test_something_outside_the_console_names_this_key(knob):
    """The floor, and it is a WEAK check said out loud: it proves the name appears in a module
    that is not the console, never that reading it changes an answer. It is still the check that
    would have caught `retrieval.cli_timeout`, which is in config.yaml, survives the loader, and
    is named by nothing but its own dataclass field."""
    key = _key(knob)
    if key in _NO_READER_OUTSIDE_CONSOLE:
        pytest.skip(_NO_READER_OUTSIDE_CONSOLE[key])
    names = [knob["path"][-1], knob["path"][0]]
    for name in names:
        word = re.compile(rf"\b{re.escape(name)}\b")
        if any(word.search(text) for _, text in _searchable()):
            return
    pytest.fail(
        f"{key}: nothing under prospector/ or scripts/ outside the console names either "
        f"{names[0]!r} or {names[1]!r}. Either it is inert, or it is read some way this check "
        f"cannot see -- in which case add it to _NO_READER_OUTSIDE_CONSOLE with the reason.")


# --------------------------------------------------------------------------------------------
# The bar knobs, whose bounds are enforced twice and must agree
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key,path", [
    ("thresholds.min_composite_to_pass", ["thresholds", "min_composite_to_pass"]),
    ("thresholds.confidence_floor", ["thresholds", "confidence_floor"]),
])
def test_the_console_bound_is_the_bound_the_validator_enforces(key, path):
    """Not "is 20.0" -- is the SAME EDGE. Asked of the validator rather than restated, so the
    two cannot drift into a portal that offers a value the save then refuses."""
    knob = api.KNOBS_BY_KEY[key]
    leaf = path[-1]
    at_max = {"thresholds": {leaf: knob["max"]}}
    over_max = {"thresholds": {leaf: knob["max"] + 0.1}}
    at_min = {"thresholds": {leaf: knob["min"]}}
    under_min = {"thresholds": {leaf: knob["min"] - 0.1}}

    ok, errs = ce.validate_config(at_max)
    assert ok, f"the console offers {knob['max']} for {key} but the validator refuses it: {errs}"
    ok, _ = ce.validate_config(at_min)
    assert ok, f"the console offers {knob['min']} for {key} but the validator refuses it"

    ok, _ = ce.validate_config(over_max)
    assert not ok, (
        f"the validator accepts {knob['max'] + 0.1} for {key}, which the console will not offer "
        f"-- the console bound is tighter than the real one and is hiding a legal setting")
    ok, _ = ce.validate_config(under_min)
    assert not ok, f"the validator accepts {knob['min'] - 0.1} for {key}; the console bound is tighter"


def test_both_bar_knobs_are_inside_the_moat_fence():
    """Changing what may be SOLD must drop the certification. `("thresholds",)` is already in
    MOAT_AFFECTING_KEYS; this fails if someone narrows that set and leaves the knobs behind."""
    for leaf in ("min_composite_to_pass", "confidence_floor"):
        old = {"thresholds": {leaf: 0.4}}
        new = {"thresholds": {leaf: 0.5}}
        assert ce.is_moat_affecting(old, new), (
            f"moving thresholds.{leaf} from the console would not drop the certification")


def test_the_dead_timeout_field_is_not_offered():
    """`retrieval.cli_timeout` and `cli_timeout_max` are in config.yaml and on the loaded config,
    and the ONLY place either name appears is the dataclass field that declares it
    (prospector/config.py:225-226). Nothing reads them. Measured 2026-08-21; if that changes,
    delete this test and add the knob."""
    keys = {".".join(k["path"]) for k in api.KNOBS}
    assert "retrieval.cli_timeout" not in keys
    assert "retrieval.cli_timeout_max" not in keys


def test_every_group_a_knob_claims_can_be_ordered():
    """`_read_config` sorts groups with `GROUP_ORDER.index(...)`, which RAISES on an unknown
    group -- so a knob in a new group takes the whole config page down rather than rendering
    it last."""
    missing = sorted({k["group"] for k in api.KNOBS} - set(api.GROUP_ORDER))
    assert not missing, f"these knob groups are not in GROUP_ORDER: {missing}"


def test_every_group_has_a_blurb():
    missing = sorted({k["group"] for k in api.KNOBS} - set(api.GROUP_BLURBS))
    assert not missing, f"these knob groups render with no explanation: {missing}"
