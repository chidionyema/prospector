"""The last paragraph of the product must not be a false claim.

`pack_kicker.render` writes the closing section of the pack, and one of its branches asserts:

    Every check in this pack came back supported.

That sentence was reached whenever `_pick` returned None — and `_pick` returns None for two
completely different reasons. One is that nothing is open. The other is that something IS open
but its name is absent from `_TESTS`, which carries seven checks while the engine runs more
(`hybrid_entity`, `buyer_intent`, `currency`, `route_to_market`, `claims_verifiable`). A dossier
whose only unverifiable check was `hybrid_entity` therefore closed with a sentence claiming
every check was supported, over a check that was not.

This repo's first rule is source-or-die, and the final paragraph of a paid document is the
worst place in it to break that rule: it is the sentence the reader leaves with. These tests
pin the claim to the one condition that makes it true and pin the alternatives that replaced
the fall-through.
"""
from __future__ import annotations

from types import SimpleNamespace

from prospector import pack_kicker

_ALL_SUPPORTED = "Every check in this pack came back supported."


def _check(name: str, verdict: str) -> SimpleNamespace:
    # Plain-string verdicts: the shape `pack_manifest.dossier_from_dict` builds when a pack is
    # re-rendered from its manifest, and the shape every `getattr` in the renderer must survive.
    return SimpleNamespace(check_name=name, verdict=verdict, rationale="Because of a passage.")


def _dossier(*checks: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        candidate=SimpleNamespace(title="Shellfish Window",
                                  one_liner="Lease closure forecast for growers",
                                  who_pays="Independent shellfish farmers"),
        checks=list(checks),
    )


class TestTheAllSupportedSentenceIsOnlyReachableWhenItIsTrue:

    def test_it_is_said_when_every_check_really_did_come_back_supported(self):
        md = pack_kicker.render(_dossier(
            _check("pain_reality", "supported"),
            _check("payer_solvency", "supported"),
            _check("legality", "supported")))
        assert _ALL_SUPPORTED in md
        # And it is still framed as a warning rather than as a clearance.
        assert "not permission to build" in md

    def test_an_open_check_outside_the_test_map_does_not_unlock_it(self):
        """The live defect, in the form it shipped.

        `hybrid_entity` is a real check name with no row in `_TESTS`, so `_pick` returns None
        for it exactly as it does for a clean dossier. Before 2026-08-15 the two were the same
        branch, and this dossier closed by telling the buyer everything was supported while
        holding a check that was unverifiable.
        """
        md = pack_kicker.render(_dossier(
            _check("pain_reality", "supported"),
            _check("hybrid_entity", "unverifiable")))
        assert _ALL_SUPPORTED not in md
        assert "Not every check in this pack came back supported" in md

    def test_it_names_the_check_it_could_not_turn_into_a_field_test(self):
        # Saying "something is open" and not saying what is the same evasion in a shorter
        # form. `check_label` is the buyer-facing question, so the reader gets the question
        # rather than the gate key.
        md = pack_kicker.render(_dossier(_check("buyer_intent", "unverifiable")))
        assert "Are people already looking for this?" in md

    def test_a_verdict_this_module_does_not_recognise_does_not_count_as_supported(self):
        """The negative form of the test would have let this through.

        Asking "is anything refuted or unverifiable?" reads an unknown verdict string as a
        pass, so the claim would be made about a check nobody ruled. The check is written as
        "does every verdict read supported?" for that reason, and this pins the difference.
        """
        md = pack_kicker.render(_dossier(
            _check("pain_reality", "supported"), _check("legality", "degraded")))
        assert _ALL_SUPPORTED not in md

    def test_a_dossier_with_no_checks_claims_nothing_about_checks(self):
        # Vacuous truth is still a false impression: "every check came back supported" over
        # zero checks tells a buyer seven things were verified when nothing was run.
        md = pack_kicker.render(_dossier())
        assert _ALL_SUPPORTED not in md
        assert "no check record" in md


class TestTheKickerStillResolvesThePiece:
    """Every branch has to end on one thing the reader can go and do.

    A correctness fix that left a branch with no test in it would trade a false claim for a
    kicker that summarises instead of resolving, which is the thing this module exists not to
    do (Bruce DeSilva's rule, module docstring).
    """

    def test_a_known_open_check_still_gets_its_derived_test(self):
        md = pack_kicker.render(_dossier(_check("payer_solvency", "unverifiable")))
        assert "The open question: Can the customer afford it?" in md
        assert "ask who signs off and which budget line it comes from" in md

    def test_a_refuted_check_is_worded_as_a_finding_to_overturn(self):
        md = pack_kicker.render(_dossier(_check("pain_reality", "refuted")))
        assert "argues AGAINST" in md
        assert "could not establish" not in md

    def test_every_branch_ends_on_a_thirty_day_test(self):
        for dossier in (_dossier(_check("payer_solvency", "unverifiable")),
                        _dossier(_check("hybrid_entity", "unverifiable")),
                        _dossier(_check("pain_reality", "supported")),
                        _dossier()):
            md = pack_kicker.render(dossier)
            assert "thirty-day test" in md or "**What to do.**" in md
            assert md.startswith(f"# {pack_kicker.TITLE}")
