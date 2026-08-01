"""What `facet_derive` must and must not conclude from a dossier.

The point of most of these tests is the *refusals*. A derivation module on this codebase is
one bad mapping away from repeating the `category.ts` failure — a filter that confidently
files a metal-fabrication tool under gardening — so the cases that assert `None` carry more
weight than the cases that assert a value.
"""

from prospector import facet_derive


class TestEffortFromAutomatability:
    def test_fraction_bands(self):
        for value, expected in [
            (0.95, "automatable"),
            (0.75, "automatable"),  # floor is inclusive
            (0.74, "part_automatable"),
            (0.40, "part_automatable"),  # floor is inclusive
            (0.39, "hands_on"),
            (0.0, "hands_on"),
        ]:
            got = facet_derive.derive_effort({"automatability": value})
            assert got is not None, value
            assert got.value == expected, f"{value} -> {got.value}, wanted {expected}"

    def test_percentages_are_not_read_as_fractions(self):
        """The live data holds `0.7 … 0.95` AND `80` and `85` in the same field.

        Read naively, 80 clears the 0.75 floor by accident. This asserts the *reason*, not
        just the answer: 80 must be understood as 0.80, so a hypothetical 30 lands on
        hands_on rather than sailing over every band.
        """
        assert facet_derive.derive_effort({"automatability": 80}).value == "automatable"
        assert facet_derive.derive_effort({"automatability": 85}).value == "automatable"
        assert facet_derive.derive_effort({"automatability": 50}).value == "part_automatable"
        assert facet_derive.derive_effort({"automatability": 30}).value == "hands_on"

    def test_percent_string_from_live_dossier(self):
        raw = "85% – Ingestion of Tribunal decisions uses PDF scraping with some manual classification"
        got = facet_derive.derive_effort({"automatability": raw})
        assert got.value == "automatable"
        assert "85%" in got.evidence

    def test_leading_word_from_live_dossier(self):
        raw = "High — the tool is self-service; the solo operator maintains the question bank"
        got = facet_derive.derive_effort({"automatability": raw})
        assert got.value == "automatable"
        assert "opens with" in got.evidence

    def test_number_wins_over_surrounding_prose(self):
        """"0.5 — mostly manual" carries a measurement and a mood. The measurement rules."""
        got = facet_derive.derive_effort({"automatability": "0.5 — mostly manual work"})
        assert got.value == "part_automatable"

    def test_magnitude_word_must_open_the_string(self):
        """"a high volume of manual review" says the opposite of what a substring match claims."""
        assert facet_derive.derive_effort({"automatability": "a high volume of manual review"}) is None

    def test_refusals(self):
        for raw in [None, "", "   ", True, False, 150, -1, "unknown", {"x": 1}, []]:
            assert facet_derive.derive_effort({"automatability": raw}) is None, raw
        assert facet_derive.derive_effort({}) is None

    def test_effort_tag_is_never_a_source(self):
        """`facets.py` forbids deriving effort from the legacy low|medium|high effort_tag.

        A pack carrying only `effort_tag` must come back untagged, not banded — the two
        fields disagree, and honouring effort_tag here would reintroduce exactly the
        "guess wearing the costume of a migration" that docstring rules out.
        """
        assert facet_derive.derive_effort({"effort_tag": "high"}) is None


class TestMechanismFromStructuralForm:
    def test_in_vocabulary_passes_through(self):
        got = facet_derive.derive_mechanism({"structural_form": "vertical_tool"})
        assert got.value == "vertical_tool"
        assert "vertical_tool" in got.evidence

    def test_off_vocabulary_is_refused_not_coerced(self):
        """Both of these are live today. `vertical_saas` is one underscore from
        `vertical_tool` and must still be refused — nearness is not membership."""
        for raw in ["micro_ecommerce", "vertical_saas", "", None, "local_service_chain"]:
            assert facet_derive.derive_mechanism({"structural_form": raw}) is None, raw

    def test_case_and_whitespace_tolerated(self):
        assert facet_derive.derive_mechanism({"structural_form": " Vertical_Tool "}).value == "vertical_tool"


class TestDeriveContract:
    def test_only_defensible_facets_are_ever_returned(self):
        """sector/payer/commitment/advantages are judgement calls and must never appear."""
        candidate = {
            "automatability": 0.9,
            "structural_form": "vertical_tool",
            "one_liner": "a gardening tool for growing businesses that produces invoices",
            "who_pays": "Businesses paying GBP 80/month",
            "tags": {"gardening": True},
        }
        got = facet_derive.derive(candidate)
        assert set(got) == {"effort", "mechanism"}
        assert set(facet_derive.DERIVABLE) == {"effort", "mechanism"}

    def test_empty_candidate_yields_nothing(self):
        assert facet_derive.derive({}) == {}

    def test_every_derivation_carries_evidence(self):
        got = facet_derive.derive({"automatability": 0.9, "structural_form": "physical_ops"})
        for name, derived in got.items():
            assert derived.evidence.startswith("candidate."), name
