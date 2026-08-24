"""The config parser stays the fast one, and stays a SAFE one.

Measured 2026-08-21: `config.yaml` is 194 KB, and PyYAML's pure-Python `safe_load` spent 0.79s
on it on the laptop and 2.49s in the engine container. `config.load_config` is uncached and one
ops-console page load calls it twice, so that parse was ~5s of a 13.76s console read.

Two things must hold from here, and neither is provable by reading the diff a year from now:
the fast loader must answer identically to the one it replaced, and nobody must quietly put
`yaml.safe_load` back into the config path while chasing something else.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from prospector import yaml_fast

REPO = Path(__file__).resolve().parents[2]


def test_the_fast_loader_parses_the_real_config_identically():
    """The only comparison that matters: our actual config, both ways, same object."""
    src = (REPO / "config.yaml").read_text(encoding="utf-8")
    assert yaml_fast.safe_load(src) == yaml.safe_load(src)


@pytest.mark.parametrize("doc", [
    "", "a: 1", "a: [1, 2, 3]", "a:\n  b:\n    c: null",
    "a: yes\nb: no\nc: 'yes'", "a: 2026-08-21", "a: 1.5e3", "a: |\n  line\n  line",
    "a: &x {b: 1}\nc: *x", "a: \"\\u00e9\\u4e2d\"", "a: ~", "[]", "{}",
])
def test_the_fast_loader_agrees_with_safe_load_on_yaml_corners(doc):
    assert yaml_fast.safe_load(doc) == yaml.safe_load(doc)


def test_a_malformed_document_still_raises_yamlerror():
    """The fallback and the fast path must fail the same way — callers catch `yaml.YAMLError`."""
    with pytest.raises(yaml.YAMLError):
        yaml_fast.safe_load("a: [1, 2\nb: }")


def test_the_fast_loader_will_not_construct_arbitrary_objects():
    """`safe` is the load-bearing half of the name. config.yaml is editable from the portal."""
    with pytest.raises(yaml.YAMLError):
        yaml_fast.safe_load("!!python/object/apply:os.system ['echo pwned']")


def test_config_does_not_parse_config_yaml_with_the_slow_loader():
    """A source check, because a timing assertion on shared CI is a flake, not a guard.

    This fails if anyone reintroduces `yaml.safe_load` or `yaml.load(..., SafeLoader)` into
    `config.load_config`. The fast path is worth ~2.3s of every console page load in
    production; losing it again would be invisible except as "the dashboard feels slow".
    """
    src = (REPO / "prospector" / "config.py").read_text(encoding="utf-8")
    body = src[src.index("def load_config("):]
    body = body[: body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    offenders = re.findall(r"yaml\.safe_load\s*\(|yaml\.load\s*\([^)]*SafeLoader", body)
    assert not offenders, (
        f"load_config parses YAML with the pure-Python loader again: {offenders}. "
        "Use prospector.yaml_fast.safe_load — see that module for the measurement."
    )
