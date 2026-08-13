"""`noncritical_operator` — the cheap chain became a config key, so pin what that key may do.

WHY THIS FILE EXISTS (2026-08-10)

The generation / prescreen / scoring chain was `_NONCRITICAL_ORDER`, a module constant in
`run.py`. Every other lever on that chain — batch size, cadence, the daily spend ceiling — is a
config line the operator can move without a deploy; the one knob whose entire subject is "what
does the ancillary work COST" was the only one needing a source edit and a daemon re-exec. Its
head changed three times in two weeks (deepseek -> claude_cli -> standardcompute), each time as
a code change written to express a billing fact.

WHAT IS PINNED, AND WHY EACH ONE

1. Absent, blank or unparseable => the historical constant, byte for byte. A config key that
   changes behaviour for configs which do not set it is a migration wearing a default's label.
2. A bare string is one tier, not N tiers of one character. `operator:` already accepts both
   shapes, so a reader that iterated the string would build a chain of single letters and fail
   with an unrecognisable provider name.
3. An all-blank list falls back rather than yielding an EMPTY chain. `_build_operator_chain(())`
   has no tiers, so generation would raise `ProviderExhaustedError` on every call — a daemon
   that looks dead, caused by a config key that looked set.
4. Order is preserved. A chain IS an order: tier 1 is what you pay for normally, the rest is
   failover, and a reader that sorted or de-duplicated would silently re-price every batch.
5. It does not touch `cfg.operator`. The verdict chain must stay led by a trusted brain, and
   that fence does not belong behind a key the operator can edit from a phone.
6. The value actually shipped in `config.yaml` resolves. A key documented on disk that the
   loader ignores is precisely the class of defect this change exists to remove.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from prospector.config import Config, load_config
from prospector.run import _NONCRITICAL_ORDER, _noncritical_order

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"


def test_dataclass_default_cannot_drift_from_the_module_constant():
    """Two spellings of the same default is how they diverge; bind them."""
    assert tuple(Config().noncritical_operator) == _NONCRITICAL_ORDER


@pytest.mark.parametrize(
    "raw",
    [None, [], (), "", "   ", ["", "  "], 0],
    ids=["none", "empty-list", "empty-tuple", "empty-str", "spaces", "blank-entries", "falsey"],
)
def test_blank_or_absent_falls_back_to_the_historical_default(raw):
    assert _noncritical_order(SimpleNamespace(noncritical_operator=raw)) == _NONCRITICAL_ORDER


def test_no_cfg_at_all_falls_back():
    assert _noncritical_order(None) == _NONCRITICAL_ORDER
    assert _noncritical_order(SimpleNamespace()) == _NONCRITICAL_ORDER


def test_bare_string_is_a_one_tier_chain_not_one_tier_per_character():
    assert _noncritical_order(SimpleNamespace(noncritical_operator="minimax")) == ("minimax",)


def test_entries_are_stripped_and_blanks_dropped():
    # NOT claude_cli: it is barred from this chain since 2026-08-14 and would be stripped,
    # which would make this test about the ban rather than about whitespace handling.
    cfg = SimpleNamespace(noncritical_operator=["  minimax ", "", "   ", "standardcompute"])
    assert _noncritical_order(cfg) == ("minimax", "standardcompute")


def test_order_is_preserved_because_a_chain_is_an_order():
    cfg = SimpleNamespace(noncritical_operator=["minimax", "deepseek", "standardcompute"])
    assert _noncritical_order(cfg) == ("minimax", "deepseek", "standardcompute")


def test_the_verdict_chain_is_not_reachable_from_this_key():
    base = Config()
    steered = replace(base, noncritical_operator=["minimax"])
    assert _noncritical_order(steered) == ("minimax",)
    assert steered.operator == base.operator


def test_shipped_config_yaml_resolves_to_a_usable_chain():
    order = _noncritical_order(load_config(str(REPO_CONFIG)))
    assert order, "config.yaml declares noncritical_operator; it must resolve to a non-empty chain"
    assert all(isinstance(k, str) and k.strip() for k in order)


def _load_with(tmp_path: Path, mutate) -> tuple[str, ...]:
    raw = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
    mutate(raw)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return _noncritical_order(load_config(str(p)))


def test_loader_omitting_the_key_is_byte_for_byte_the_old_behaviour(tmp_path):
    assert _load_with(tmp_path, lambda r: r.pop("noncritical_operator", None)) == _NONCRITICAL_ORDER


def test_loader_honours_a_declared_chain(tmp_path):
    got = _load_with(tmp_path, lambda r: r.update(noncritical_operator=["minimax", "deepseek"]))
    assert got == ("minimax", "deepseek")
