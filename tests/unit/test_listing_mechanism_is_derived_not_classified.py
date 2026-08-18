"""The `mechanism` facet comes from the candidate's own declared form, not a model tag.

`facets.MECHANISM` mirrors `config.yaml generation.structural_forms`, so `candidate
.structural_form` and the `mechanism` facet are the same taxonomy under two names
(`facet_derive.py:13-15`). Generation already declares the form. Asking the model to tag it
again on the listing page is asking a second answer to a question the engine has already
answered, and a second answer can only agree or disagree.

Measured over the 89 pass dossiers on disk that carry a listing_page
(`docs/TEMPLATE_FIRST_COPY.md`): the deriver and the model both answer on 65 packs and agree
on 62 (95%), the deriver fills 2 the model left blank, and `structural_form` is non-empty on
89 of 89 candidates.

The ordering is the one `_derive_copy` already established: build it deterministically, and
let the model's answer stand ONLY where the builder has nothing to say. Here that is the 20
packs whose form is outside the facet vocabulary (`micro_ecommerce`, `vertical_saas`,
`api_product` ...). `facets.clean_one` refuses to coerce those to the nearest member, and
that refusal is load-bearing: the last time this codebase inferred a facet from pack text it
published a metal-fabrication quoting engine as a gardening business
(`facet_derive.py:19-26`).

`effort` is deliberately NOT derived, though `facet_derive` can derive it. On the same corpus
it agrees with the model on 26 of 84 packs (31%), because `candidate.automatability` is
written at generation time, when nothing is judged, and the model answers after verification.
The last test here pins that, so a later "while we are in here" change has to argue with a
number instead of with a hunch.
"""

from types import SimpleNamespace

from prospector.artifacts import _derive_mechanism, _normalize_listing


def _candidate(form, **kw):
    return SimpleNamespace(structural_form=form, **kw)


class TestMechanismComesFromTheCandidatesDeclaredForm:
    def test_the_declared_form_wins_over_the_models_own_tag(self):
        out = _normalize_listing(
            {"type": "listing_page", "facets": {"mechanism": "productized_service"}},
            _candidate("vertical_tool"),
        )
        assert out["facets"]["mechanism"] == "vertical_tool"

    def test_it_fills_a_facet_the_model_left_blank(self):
        # 2 of the 89 packs on disk. An untagged pack is reachable only under "All", so a
        # blank facet costs the pack every filter and the Matchmaker.
        out = _normalize_listing(
            {"type": "listing_page", "facets": {}}, _candidate("transaction_broker")
        )
        assert out["facets"]["mechanism"] == "transaction_broker"

    def test_an_off_vocabulary_form_leaves_the_models_tag_alone(self):
        # `micro_ecommerce` is live on 6 candidates today and is not a MECHANISM member.
        # Coercing it to the nearest member is the failure mode this refusal prevents, so
        # the builder returns nothing and the model's answer is kept.
        out = _normalize_listing(
            {"type": "listing_page", "facets": {"mechanism": "physical_ops"}},
            _candidate("micro_ecommerce"),
        )
        assert out["facets"]["mechanism"] == "physical_ops"

    def test_no_candidate_means_byte_for_byte_prior_behaviour(self):
        # Every caller that does not pass a candidate — the backfill tools, the salvage
        # path's re-normalisation — must see exactly what it saw before.
        payload = {"type": "listing_page", "facets": {"mechanism": "audience_media"}}
        assert _normalize_listing(payload) == _normalize_listing(payload, None)
        assert _normalize_listing(payload)["facets"]["mechanism"] == "audience_media"

    def test_the_other_five_facets_are_untouched(self):
        # This change is one facet wide. `sector`, `payer`, `commitment` and `advantages` are
        # refused by `facet_derive` on a documented incident; `effort` is refused on the 31%
        # measurement above. A regression here would be a filter that lies.
        out = _normalize_listing(
            {
                "type": "listing_page",
                "facets": {
                    "mechanism": "productized_service",
                    "sector": "care_benefits",
                    "payer": "b2c",
                    "effort": "part_automatable",
                    "commitment": "evenings",
                    "advantages": ["sales"],
                },
            },
            _candidate("vertical_tool", automatability=0.95),
        )
        assert out["facets"]["sector"] == "care_benefits"
        assert out["facets"]["payer"] == "b2c"
        assert out["facets"]["commitment"] == "evenings"
        assert out["facets"]["advantages"] == ["sales"]

    def test_effort_is_not_derived_from_automatability(self):
        # automatability 0.95 bands to `automatable` in `facet_derive.derive_effort`. The
        # model said `part_automatable` after reading the verified dossier, and it keeps the
        # field. 48 of the 89 live packs are exactly this disagreement.
        out = _normalize_listing(
            {"type": "listing_page", "facets": {"effort": "part_automatable"}},
            _candidate("vertical_tool", automatability=0.95),
        )
        assert out["facets"]["effort"] == "part_automatable"


class TestTheBuilderItself:
    def test_a_dict_candidate_works_as_well_as_the_dataclass(self):
        # The backfill paths carry the dossier as raw JSON, never as a Candidate.
        assert _derive_mechanism({"structural_form": "risk_financing"}) == "risk_financing"

    def test_a_missing_or_empty_form_returns_nothing_rather_than_guessing(self):
        assert _derive_mechanism(None) == ""
        assert _derive_mechanism({}) == ""
        assert _derive_mechanism(_candidate("")) == ""
        assert _derive_mechanism(_candidate(None)) == ""
