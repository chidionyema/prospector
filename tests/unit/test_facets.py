"""The engine end of the discovery facet contract.

The rule these tests exist to hold: a facet the engine cannot justify is absent, never
defaulted and never coerced to the nearest vocabulary member. A coerced facet is a claim
nobody made, and the storefront routes real buyers on it.
"""

import json
from pathlib import Path

import pytest

from prospector import facets
from prospector.artifacts import _normalize_listing

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKFILL = REPO_ROOT / "store_platform" / "data" / "facets-backfill.json"


class TestCleanOne:
    def test_accepts_a_vocabulary_member(self):
        assert facets.clean_one("b2b", facets.PAYER) == "b2b"

    @pytest.mark.parametrize("raw", [" B2B ", "B2B", "b2b\n"])
    def test_tolerates_case_and_whitespace(self, raw):
        # No ambiguity to resolve: " B2B " unmistakably means b2b.
        assert facets.clean_one(raw, facets.PAYER) == "b2b"

    @pytest.mark.parametrize("raw", ["business", "b2x", "", None, 7, [], {}])
    def test_drops_anything_outside_the_vocabulary(self, raw):
        # "business" is not b2b, it is an unrecognised answer. Guessing which member it
        # meant is exactly the inference the contract forbids.
        assert facets.clean_one(raw, facets.PAYER) is None

    @pytest.mark.parametrize("legacy", ["low", "medium", "high", "Highly automatable"])
    def test_legacy_effort_tag_vocabulary_is_not_accepted_as_effort(self, legacy):
        # spec 2.3 — low|medium|high was never defined to mean machine-doability.
        assert facets.clean_one(legacy, facets.EFFORT) is None


class TestCleanAdvantages:
    def test_keeps_known_members_and_drops_the_rest(self):
        # Unlike the publish API (which rejects the whole request so a partial write is
        # impossible), generation-time cleaning keeps what was justified.
        assert facets.clean_advantages(["code", "telepathy", "sales"]) == ["code", "sales"]

    def test_deduplicates_and_caps_at_three(self):
        assert facets.clean_advantages(["code", "code", "sales", "ops", "audience"]) == [
            "code", "sales", "ops",
        ]

    @pytest.mark.parametrize("raw", [None, "code", 7, {}])
    def test_non_list_input_yields_empty(self, raw):
        assert facets.clean_advantages(raw) == []


class TestNormalize:
    def test_always_returns_all_six_keys(self):
        result = facets.normalize(None)
        assert set(result) == {"sector", "payer", "effort", "commitment", "mechanism", "advantages"}

    def test_absent_is_none_not_a_default(self):
        result = facets.normalize({})
        assert result["payer"] is None
        assert result["effort"] is None
        assert result["advantages"] == []

    def test_a_malformed_block_costs_the_tags_not_the_publish(self):
        # A model that returned a string where an object was asked for must not take the
        # whole listing down with it.
        assert facets.normalize("nonsense")["mechanism"] is None

    def test_a_good_block_survives_intact(self):
        result = facets.normalize({
            "payer": "b2b",
            "effort": "automatable",
            "commitment": "evenings",
            "mechanism": "vertical_tool",
            "sector": "pets_animals",
            "advantages": ["code"],
        })
        assert result == {
            "sector": "pets_animals",
            "payer": "b2b",
            "effort": "automatable",
            "commitment": "evenings",
            "mechanism": "vertical_tool",
            "advantages": ["code"],
        }

    def test_one_bad_facet_does_not_take_the_good_ones_with_it(self):
        result = facets.normalize({"payer": "b2b", "mechanism": "niche_distribution"})
        assert result["payer"] == "b2b"
        assert result["mechanism"] is None


class TestToWire:
    def test_drops_empties_so_a_republish_never_untags(self):
        # The Store API only overwrites the facets it was sent. Sending nulls would let a
        # facet-light republish wipe tags the backfill wrote.
        assert facets.to_wire(facets.normalize({"payer": "b2b"})) == {"payer": "b2b"}

    def test_sends_what_was_decided(self):
        wire = facets.to_wire(facets.normalize({
            "payer": "b2c", "effort": "hands_on", "advantages": ["ops", "sales"],
        }))
        assert wire == {"payer": "b2c", "effort": "hands_on", "advantages": ["ops", "sales"]}

    def test_empty_in_empty_out(self):
        assert facets.to_wire(facets.normalize({})) == {}


class TestNormalizeListing:
    def test_listing_carries_a_facets_block(self):
        piece = _normalize_listing({"copy": "x", "facets": {"payer": "b2b"}})
        assert piece["facets"]["payer"] == "b2b"

    def test_listing_without_facets_still_normalises(self):
        # Back-compat: an operator that predates the facets block must keep working.
        piece = _normalize_listing({"copy": "x", "effort_tag": "high"})
        assert piece["effort_tag"] == "high"          # legacy field kept for one release
        assert piece["facets"]["effort"] is None      # and NOT mapped into the new enum

    def test_invented_facet_values_are_dropped_at_the_boundary(self):
        piece = _normalize_listing({"copy": "x", "facets": {"mechanism": "vibes"}})
        assert piece["facets"]["mechanism"] is None


class TestVocabularyMatchesTheOtherTwoCopies:
    """The C# and TypeScript copies must agree with this one, member for member."""

    def test_mechanism_matches_the_engines_structural_forms(self):
        # config.yaml:595-603 is where these come from; a drift between them would mean
        # the engine generates forms the storefront cannot route on.
        import yaml
        config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
        forms = config["generation"]["structural_forms"]
        assert set(forms) == set(facets.MECHANISM)

    def test_csharp_vocabulary_matches(self):
        source = (REPO_ROOT / "store_platform" / "src" / "Store.Catalog" / "Domain"
                  / "PackFacets.cs").read_text(encoding="utf-8")
        for value in facets.ADVANTAGE + facets.PAYER + facets.EFFORT + facets.COMMITMENT \
                + facets.MECHANISM + facets.SECTOR:
            assert f'"{value}"' in source, f"{value} missing from PackFacets.cs"


class TestBackfillFile:
    """AC-4 — the reviewed backfill covers every live pack and never guesses."""

    @pytest.fixture(scope="class")
    def data(self):
        return json.loads(BACKFILL.read_text(encoding="utf-8"))

    def test_every_entry_is_a_pack_that_was_actually_published(self, data):
        # Deliberately NOT `len(data) == 15`, and deliberately not the other direction
        # either. The engine publishes unattended, so "every live pack has an entry" is a
        # moving target: asserting it here would turn a successful PASS into a red suite
        # and a blocked commit. That coverage check belongs where it can be acted on -
        # backfill_facets.py reads the LIVE catalogue on every run and re-proposes anything
        # new, so re-running it is the fix, and its printed `packs=` line is the report.
        #
        # What is stable, and what this guards, is the reverse: no entry may name a pack
        # that was never published. That catches a mistyped or stale id, which would
        # otherwise fail silently as a 404 halfway through --apply.
        # Keyed on store/dossiers/, not store/listings/: the dossier is what the proposer
        # actually read to justify each value, and it is the only local record that is
        # complete. store/listings/ has drifted from the deployed catalogue (checked
        # 2026-07-31: 20 packs live, 11 of them with no listings/ file), so using it here
        # would fail on packs that are demonstrably published.
        known = {p.name.split(".")[0] for p in (REPO_ROOT / "store" / "dossiers").glob("*.json")}
        assert known, "no dossiers on disk - the assertion below would prove nothing"
        phantom = sorted(set(data) - known)
        assert not phantom, f"backfill entries with no dossier to justify them: {phantom}"

    def test_every_non_null_value_is_in_the_vocabulary(self, data):
        for pack_id, entry in data.items():
            for name, vocabulary in facets.SINGLE_VALUED.items():
                value = entry.get(name)
                assert value is None or value in vocabulary, f"{pack_id}.{name} = {value!r}"
            for advantage in entry.get("advantages") or []:
                assert advantage in facets.ADVANTAGE, f"{pack_id}.advantages {advantage!r}"

    def test_every_non_null_value_quotes_its_dossier_evidence(self, data):
        for pack_id, entry in data.items():
            evidence = entry.get("_evidence", {})
            for name in list(facets.SINGLE_VALUED) + ["advantages"]:
                if entry.get(name):
                    assert evidence.get(name), f"{pack_id}.{name} has a value but no _evidence"

    def test_undecidable_facets_are_null_with_a_reason(self, data):
        for pack_id, entry in data.items():
            for name, reason in entry.get("_unresolved", {}).items():
                assert not entry.get(name), f"{pack_id}.{name} is both resolved and unresolved"
                assert reason.strip(), f"{pack_id}.{name} unresolved with no reason"

    def test_no_facet_is_defaulted_across_the_whole_catalogue(self, data):
        # The ship criterion from spec Part 13: every facet carries at least one real
        # value, and no facet is the same value on every pack (which would mean it was
        # defaulted rather than decided).
        for name in facets.SINGLE_VALUED:
            values = [e.get(name) for e in data.values() if e.get(name)]
            assert values, f"{name} has no real value anywhere"
            assert len(set(values)) > 1, f"{name} is the same value on every pack - defaulted?"
