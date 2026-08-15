"""The trust fence is DECLARED, not welded (2026-08-15).

`MOAT_PRIMARY` was a bare `frozenset({"claude_cli"})` in `operator.py` with no config key. It was
the only tier knob in the engine that required a source edit and a daemon re-exec to move, while
`operator:`, `noncritical_operator:`, `artifact_operator:` and `marketing_operator:` beside it were
all config lines — a breach of this repo's own constraint ("Deterministic on config. Swapping
operators requires no code change, only `config.yaml`").

It cost throughput, not just tidiness: with the trusted set welded to `claude_cli`, MiniMax's
concurrency was unusable at ANY width, because everything it ruled was stamped `provisional`
(`run.py` refuses to publish those) and had to be re-vetted by claude_cli anyway.

What these tests pin, in the order the defects would appear:
  1. absent key => the default, byte for byte (no behaviour change on today's config);
  2. a declared key actually MOVES the fence — `is_provisional_provider` is the reader, so this is
     the publishability of a ruling, not a cosmetic field;
  3. a later load with no key RESETS to the default — a process global written by `load_config` is
     otherwise a poisoning hazard between one config and the next;
  4. an unbuildable name RAISES at load. This is the one that matters most: a typo in this key
     fails silently in the worst direction — every ruling stamped `provisional`, nothing ever
     published, and an engine that looks merely unproductive rather than misconfigured.
"""
from __future__ import annotations

import pytest
import yaml

import prospector.operator as OP
from prospector.config import load_config
from prospector.operator import (
    MOAT_PRIMARY_DEFAULT,
    MOAT_PRIMARY_ENV,
    is_provisional_provider,
    moat_primary,
    set_moat_primary,
)


@pytest.fixture(autouse=True)
def _restore_process_fence(monkeypatch):
    """`load_config` writes a PROCESS global, so every test here must hand it back untouched —
    otherwise this file silently re-fences the rest of the suite."""
    monkeypatch.delenv(MOAT_PRIMARY_ENV, raising=False)
    before = OP._MOAT_PRIMARY
    yield
    OP._MOAT_PRIMARY = before


def _write_cfg(tmp_path, **keys) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"operator": ["claude_cli", "minimax"], **keys}))
    return str(p)


# ---------------------------------------------------------------- 1. no behaviour change

def test_an_absent_key_leaves_the_historical_default_byte_for_byte(tmp_path):
    load_config(_write_cfg(tmp_path))
    assert moat_primary() == MOAT_PRIMARY_DEFAULT
    assert MOAT_PRIMARY_DEFAULT, "the code default must never be empty"
    for name in MOAT_PRIMARY_DEFAULT:
        assert is_provisional_provider(name) is False


def test_the_shipped_config_declares_a_fence_that_leads_its_own_verdict_chain():
    """Deliberately does NOT pin WHICH brains are trusted — that is a config decision, and a test
    that names them re-welds the key one layer up. What must hold whatever is declared: the set is
    non-empty, every name is buildable, and the head of `operator:` is in it (a chain led by a
    brain that cannot rule finally makes every normal verdict provisional and stops the catalogue
    publishing entirely)."""
    cfg = load_config()
    declared = moat_primary()
    assert declared, "the trusted set must never be empty"
    ops = cfg.operator if isinstance(cfg.operator, list) else [cfg.operator]
    assert ops[0] in declared, (
        f"the verdict chain is led by {ops[0]!r}, which is not in the trusted set {sorted(declared)}")


# ---------------------------------------------------------------- 2. the key MOVES the fence

def test_declaring_a_brain_makes_its_rulings_publishable(tmp_path):
    """The whole point: promoting a brain is a config line, not a patch. `run.py` gates
    publication on `is_provisional_provider`, so this assertion IS the sellability change."""
    load_config(_write_cfg(tmp_path, moat_primary=["claude_cli"]))
    assert is_provisional_provider("minimax") is True, "precondition: fenced when not declared"
    load_config(_write_cfg(tmp_path, moat_primary=["claude_cli", "minimax"]))
    assert moat_primary() == frozenset({"claude_cli", "minimax"})
    assert is_provisional_provider("minimax") is False


def test_a_scalar_or_comma_string_is_accepted_like_every_other_chain_key(tmp_path):
    load_config(_write_cfg(tmp_path, moat_primary="claude_cli, minimax"))
    assert moat_primary() == frozenset({"claude_cli", "minimax"})


def test_dropping_a_brain_from_the_set_fences_it_even_while_it_leads_the_chain(tmp_path):
    """`operator:` and `moat_primary:` are independent: a brain can run first and still be
    unable to rule finally. Without this the two keys would only ever be read as one."""
    load_config(_write_cfg(tmp_path, operator=["minimax"], moat_primary=["claude_cli"]))
    assert is_provisional_provider("minimax") is True


# ---------------------------------------------------------------- 3. no cross-config poisoning

def test_a_later_config_with_no_key_resets_to_the_default(tmp_path):
    load_config(_write_cfg(tmp_path, moat_primary=["claude_cli", "minimax"]))
    assert is_provisional_provider("minimax") is False
    load_config(_write_cfg(tmp_path))          # same path, key removed
    assert moat_primary() == MOAT_PRIMARY_DEFAULT, (
        "an absent key left the PREVIOUS config's fence installed; one process loading a "
        "fixture config would silently re-fence every later load")


def test_the_env_override_wins_over_the_config(tmp_path, monkeypatch):
    """Ops override, matching `PROSPECTOR_VET_WORKERS`: run one experiment on a different fence
    without editing the file the daemon reads."""
    load_config(_write_cfg(tmp_path))
    monkeypatch.setenv(MOAT_PRIMARY_ENV, "minimax")
    assert moat_primary() == frozenset({"minimax"})
    assert is_provisional_provider("minimax") is False
    assert is_provisional_provider("claude_cli") is True
    monkeypatch.delenv(MOAT_PRIMARY_ENV)
    assert moat_primary() == MOAT_PRIMARY_DEFAULT


# ---------------------------------------------------------------- 4. a typo must be LOUD

def test_an_unbuildable_tier_name_raises_at_load(tmp_path):
    """`claude-cli` (hyphen) is the exact typo this guard exists for: no tier ever serves that
    name, so without the raise EVERY ruling would be stamped provisional and nothing would
    publish — while the config file reads as though claude_cli were trusted."""
    with pytest.raises(ValueError, match="unbuildable operator tier"):
        load_config(_write_cfg(tmp_path, moat_primary=["claude-cli"]))


def test_an_empty_declared_set_raises_rather_than_fencing_everything():
    with pytest.raises(ValueError, match="EMPTY trusted verdict set"):
        set_moat_primary(",")


def test_an_empty_env_value_is_treated_as_unset_not_as_an_empty_set(tmp_path, monkeypatch):
    load_config(_write_cfg(tmp_path))
    monkeypatch.setenv(MOAT_PRIMARY_ENV, "   ")
    assert moat_primary() == MOAT_PRIMARY_DEFAULT


# ---------------------------------------------------------------- the reader is the only reader

def test_the_constant_is_gone_so_a_stale_import_cannot_read_a_pre_override_set():
    """`MOAT_PRIMARY` was deliberately RENAMED, not aliased. An alias kept for compatibility is
    exactly the redundant mechanism that makes a test pin the wrong thing: a module-level
    `from prospector.operator import MOAT_PRIMARY` would keep answering the pre-config default
    forever, and the reader would never know."""
    assert not hasattr(OP, "MOAT_PRIMARY")
