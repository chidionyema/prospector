"""The storefront prose is assembled from the structured fields, not written separately.

`content_gen` asks the operator for `copy` as well as `headline`, `subhead`, `what_you_get`
and `proof_point` — and `copy` is defined in the prompt as "full prose version combining the
above". So the model is asked to concatenate four values it just produced, and `_derive_copy`
already does exactly that concatenation in code.

Preferring the model's version had a cost beyond the wasted tokens. The salvage path drops a
field whose claim failed the check, then re-derives; if the model's `copy` wins, the dropped
claim is still in the prose the storefront renders. `_derive_copy`'s own docstring names
re-derivation as "the only thing that keeps a discarded claim from reappearing".

The tolerance documented in `_normalize_listing` still holds: an operator that returns only
`copy` and no structured fields yields a valid piece.
"""

from prospector.artifacts import _derive_copy, _normalize_listing


class TestCopyIsDerivedFromTheStructuredFields:
    def test_derived_copy_wins_over_the_models_own_prose(self):
        out = _normalize_listing(
            {
                "type": "listing_page",
                "headline": "Cut refund disputes for independent letting agents",
                "subhead": "For agents running under 200 tenancies.",
                "what_you_get": ["A dispute log", "Three letter templates"],
                "proof_point": "42% of deposits are disputed, per TDS 2025.",
                "copy": "SOMETHING THE MODEL WROTE INSTEAD",
            }
        )
        assert out["copy"] == _derive_copy(
            "Cut refund disputes for independent letting agents",
            "For agents running under 200 tenancies.",
            ["A dispute log", "Three letter templates"],
            "42% of deposits are disputed, per TDS 2025.",
        )
        assert "SOMETHING THE MODEL WROTE INSTEAD" not in out["copy"]

    def test_a_claim_dropped_from_proof_point_does_not_survive_in_the_prose(self):
        # The regression this ordering exists to close. The salvage path has already removed
        # the unverified figure from `proof_point`; the model's prose still carries it.
        out = _normalize_listing(
            {
                "type": "listing_page",
                "headline": "Cut refund disputes for independent letting agents",
                "subhead": "For agents running under 200 tenancies.",
                "what_you_get": ["A dispute log"],
                "proof_point": "",
                "copy": "Agents recover 91% of disputed deposits within a week.",
            }
        )
        assert "91%" not in out["copy"]

    def test_an_operator_that_returns_only_copy_still_yields_a_valid_piece(self):
        # The tolerance path in `_normalize_listing`'s docstring. With no structured field to
        # derive from, the model's prose is the only thing there is, and it is kept.
        prose = "A plain prose listing with no structured fields at all."
        out = _normalize_listing({"type": "listing_page", "copy": prose})
        assert out["copy"] == prose

    def test_copy_is_always_set_so_the_completeness_gate_keeps_working(self):
        out = _normalize_listing({"type": "listing_page", "headline": "Only a headline"})
        assert out["copy"] == "Only a headline"
        assert _normalize_listing({})["copy"] == ""
