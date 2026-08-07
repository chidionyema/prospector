"""E1: a `hybrid_entity_checks` entry with no template must fail at LOAD, not go inert.

The defect. `_entity_queries` returns [] for a check with no entity template, and the
caller falls through to the ordinary LLM/template chain. That fallthrough is correct and
is asserted by tests/unit/test_e1_hybrid_queries.py — a missing template must never crash
a verdict mid-run. But it meant `hybrid_entity_checks: [incumbency]` did not enable the
arm for `incumbency`; it did nothing at all, while config.yaml read as though the arm was
on. The experiment would have reported a null result for a condition that never ran.

So the fix cannot live in `_entity_queries` (whose empty-return contract is deliberate and
locked by an existing test). It lives at config load, the same place `_validate_admissibility`
catches a typo'd policy and `_build_operator` rejects the removed `cursor_cli`.
"""
from __future__ import annotations

import pytest
import yaml

from prospector.config import load_config
from prospector.entity_templates import (
    ENTITY_SLOTS,
    ENTITY_TEMPLATES,
    checks_with_entity_templates,
)
from prospector.models import Candidate
from prospector.verify import _ENTITY_TEMPLATES, _entity_queries


def _write_cfg(tmp_path, retrieval: dict):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"retrieval": retrieval}), encoding="utf-8")
    return p


class TestLoadTimeValidation:
    def test_an_unbacked_check_raises_at_load(self, tmp_path):
        cfg_path = _write_cfg(tmp_path, {"hybrid_entity_checks": ["pain_reality"]})
        with pytest.raises(ValueError) as exc:
            load_config(cfg_path)
        msg = str(exc.value)
        assert "pain_reality" in msg
        assert "no entity template" in msg
        assert "silently disables" in msg, "the message must say what goes wrong, not just that it did"

    def test_a_typo_raises_rather_than_running_nothing(self, tmp_path):
        cfg_path = _write_cfg(tmp_path, {"hybrid_entity_checks": ["payer_solvancy"]})
        with pytest.raises(ValueError, match="payer_solvancy"):
            load_config(cfg_path)

    def test_a_backed_check_loads(self, tmp_path):
        cfg_path = _write_cfg(tmp_path, {"hybrid_entity_checks": ["payer_solvency"]})
        cfg = load_config(cfg_path)
        assert cfg.retrieval.hybrid_entity_checks == ["payer_solvency"]

    def test_every_backed_check_is_accepted(self, tmp_path):
        """Whatever ships in ENTITY_TEMPLATES must be loadable — else the arm cannot be run."""
        cfg_path = _write_cfg(tmp_path, {"hybrid_entity_checks": sorted(ENTITY_TEMPLATES)})
        cfg = load_config(cfg_path)
        assert sorted(cfg.retrieval.hybrid_entity_checks) == sorted(ENTITY_TEMPLATES)

    def test_empty_is_the_shipped_default_and_still_loads(self, tmp_path):
        cfg = load_config(_write_cfg(tmp_path, {"hybrid_entity_checks": []}))
        assert cfg.retrieval.hybrid_entity_checks == []

    def test_a_string_is_rejected_not_iterated_per_character(self, tmp_path):
        """`hybrid_entity_checks: payer_solvency` would otherwise iterate as characters."""
        cfg_path = _write_cfg(tmp_path, {"hybrid_entity_checks": "payer_solvency"})
        with pytest.raises(ValueError, match="must be a list"):
            load_config(cfg_path)

    def test_the_repo_config_itself_loads(self):
        """The shipped config.yaml must satisfy its own validator."""
        assert load_config() is not None


class TestTheTemplatesThemselves:
    def test_verify_reexports_the_same_object(self):
        """verify._ENTITY_TEMPLATES is the binding the arm's other tests use."""
        assert _ENTITY_TEMPLATES is ENTITY_TEMPLATES

    def test_every_slot_used_is_declared_in_ENTITY_SLOTS(self):
        """The skip-if-blank guard iterates ENTITY_SLOTS.

        A new slot added to a template but not to ENTITY_SLOTS would render blank instead
        of skipping — producing exactly the product-shaped query the arm exists to avoid,
        and doing it silently.
        """
        import re

        declared = {s.strip("{}") for s in ENTITY_SLOTS} | {"base"}
        for check, tpls in ENTITY_TEMPLATES.items():
            for t in tpls:
                used = set(re.findall(r"\{(\w+)\}", t))
                assert used <= declared, f"{check}: undeclared slot(s) {used - declared} in {t!r}"

    def test_every_check_names_an_entity_in_at_least_one_template(self):
        """A templates-list of pure {base} would be a product restatement wearing the arm's name."""
        for check, tpls in ENTITY_TEMPLATES.items():
            assert any(any(s in t for s in ENTITY_SLOTS) for t in tpls), check

    def test_checks_with_entity_templates_matches_the_dict(self):
        assert checks_with_entity_templates() == frozenset(ENTITY_TEMPLATES)


class TestTheNewChecks:
    """incumbency and legality, added 2026-08-07. The arm ships OFF, so these are
    unmeasured arm CONTENT; what is proven here is the slotting, not any yield claim."""

    def _cand(self, **kw):
        base = dict(
            title="Rota cover for independent pharmacies",
            one_liner="Fills last-minute locum shifts",
            who_pays="independent pharmacy owners",
            market="uk",
            tags={"audience": "independent_pharmacies"},
        )
        base.update(kw)
        return Candidate(**base)

    def test_legality_slots_the_market(self):
        qs = _entity_queries(self._cand(), "legality", n=2)
        assert qs, "legality must now produce entity queries"
        assert all("uk" in q for q in qs), qs

    def test_legality_skips_when_market_is_blank(self):
        """A blank market would render 'is X legal in ' — worse than falling through."""
        assert _entity_queries(self._cand(market=""), "legality", n=2) == []

    def test_incumbency_slots_the_audience_with_underscores_expanded(self):
        qs = _entity_queries(self._cand(), "incumbency", n=2)
        assert qs
        assert all("independent pharmacies" in q for q in qs), qs

    def test_incumbency_skips_when_audience_is_blank(self):
        assert _entity_queries(self._cand(tags={}), "incumbency", n=2) == []

    def test_an_unknown_check_still_returns_empty(self):
        """The contract test_e1_hybrid_queries.py locks — unchanged by this work."""
        assert _entity_queries(self._cand(), "pain_reality", n=2) == []
