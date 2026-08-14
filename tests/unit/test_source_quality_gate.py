"""P3: the sourcing the pack invites you to check.

The pack's best paragraph is a loaded gun — "pick any claim marked SUPPORTED, click its
source, and if it doesn't say what we say it says, claim the refund." `8d5e24fbe6c1f5d3`
then cited `jeffreydachmd.com` ("Increasing Autism Rate is Caused by Environmental Toxin
Says RFK Jr") and `playproject.org` ("a 3000% increase!") for the 1-in-31 US autism
prevalence figure, in a pack sold to people who will market to autism parents — with CDC
pages already retrieved and sitting in the same source list.

The tier policy (§20) cleared them, correctly by its own terms: both are `other`. Hence a
second gate about the CLAIM rather than the domain.

Measured 2026-08-14 over `store/dossiers/*.json` (offline, zero LLM):
  * 6 of 3,476 ruled-and-cited checks demote under the health gate (0.17%);
  * 546 of 2,031 dossiers double-counted a URL in `all_sources`, inflating the corpus by
    922 phantom sources — `lulu.com/create/print-books` twice in the pack the founder read.
"""
from prospector import admissibility as adm
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict

AUTISM_RATE = "A 2025 report puts autism prevalence at 1 in 31 US children."


# --- the tier list has to contain the government --------------------------------------

def test_an_apex_government_domain_is_government():
    """`host.endswith(".gov.uk")` is False for `gov.uk` itself. Both are cited on disk, and
    the second was classified `other` — the government tier did not contain the government."""
    assert adm.tier("gov.uk") == "government"
    assert adm.tier("nhs.uk") == "government"
    assert adm.tier("www.gov.uk".removeprefix("www.")) == "government"


def test_a_subdomain_is_still_government():
    assert adm.tier("data.gov.uk") == "government"


def test_a_lookalike_is_not_promoted():
    """`_in_suffix_family` must not turn `notgov.uk` into the government."""
    assert adm.tier("notgov.uk") == "other"


# --- the health gate --------------------------------------------------------------------

def test_the_blog_that_shipped_is_refused_for_the_prevalence_figure():
    reason = adm.health_demotion_reason(
        AUTISM_RATE, ["https://jeffreydachmd.com/x", "https://playproject.org/y"])
    assert reason and "jeffreydachmd.com" in reason and "playproject.org" in reason


def test_one_primary_source_in_the_list_rescues_the_ruling():
    """Same "one good source is enough" rule as the tier policy: this gate demotes only a
    ruling with NOTHING primary behind it."""
    assert adm.health_demotion_reason(
        AUTISM_RATE, ["https://jeffreydachmd.com/x",
                      "https://www.cdc.gov/autism/data.html"]) is None


def test_a_medical_word_beside_a_price_is_not_a_health_statistic():
    """This gate is about epidemiological rates. A market fact about a health product is
    exactly the evidence the catalogue exists to find, and demoting it would be a bug."""
    assert not adm.is_health_statistic("Clinical customers pay £120 a session.")
    assert adm.health_demotion_reason(
        "Clinical customers pay £120 a session.", ["https://someshop.com/pricing"]) is None


def test_a_rate_with_no_medical_word_is_not_this_gates_business():
    assert not adm.is_health_statistic("Roughly 18% of fleets file the reclaim themselves.")


def test_the_gate_can_be_measured_against_being_off():
    assert adm.health_demotion_reason(
        AUTISM_RATE, ["https://jeffreydachmd.com/x"], enabled=False) is None


def test_a_ruling_with_no_citations_is_not_demoted_here():
    """`source_or_die` at verify.py owns the ungrounded case; two gates firing on one defect
    make the receipt unreadable."""
    assert adm.health_demotion_reason(AUTISM_RATE, []) is None


def test_the_config_carries_the_knob_and_rejects_a_non_boolean():
    import pytest

    from prospector.config import _validate_admissibility

    assert _validate_admissibility({"policy": "off"}).health_claims_need_primary is True
    assert _validate_admissibility(
        {"policy": "off", "health_claims_need_primary": False}
    ).health_claims_need_primary is False
    with pytest.raises(ValueError):
        _validate_admissibility({"health_claims_need_primary": "yes"})


def test_the_shipped_config_has_the_gate_on():
    from prospector.config import load_config

    assert load_config().admissibility.health_claims_need_primary is True


# --- the source count the cover advertises ----------------------------------------------

def _dossier_with(sources_per_check):
    checks = [
        CheckResult(check_name=f"c{i}", verdict=Verdict.SUPPORTED, confidence=0.6,
                    rationale="ok", citations=[s.source_id for s in srcs], sources=list(srcs))
        for i, srcs in enumerate(sources_per_check)
    ]
    return Dossier(candidate=Candidate(title="x", one_liner="y"), checks=checks,
                   decision=Decision.PASS, reason="ok")


def test_the_same_page_retrieved_twice_is_one_source():
    """`source_id` is minted per retrieval, so the same URL fetched for two checks counted
    twice: "Grounded in 51 sources" with lulu.com listed twice."""
    url = "https://www.lulu.com/create/print-books"
    d = _dossier_with([
        [Source(source_id="aaaa", url=url, text="one")],
        [Source(source_id="bbbb", url=url, text="one")],
    ])
    assert len(d.all_sources) == 1


def test_a_trailing_slash_is_not_a_second_source():
    d = _dossier_with([
        [Source(source_id="aaaa", url="https://example.com/a", text="one")],
        [Source(source_id="bbbb", url="https://example.com/a/", text="one")],
    ])
    assert len(d.all_sources) == 1


def test_two_different_pages_are_still_two_sources():
    d = _dossier_with([
        [Source(source_id="aaaa", url="https://example.com/a", text="one"),
         Source(source_id="bbbb", url="https://example.com/b", text="two")],
    ])
    assert len(d.all_sources) == 2


def test_a_source_with_no_url_is_never_merged_into_another():
    """Keyed on the URL, so an empty URL would collapse every unlinked passage into one."""
    d = _dossier_with([
        [Source(source_id="aaaa", url="", text="one"),
         Source(source_id="bbbb", url="", text="two")],
    ])
    assert len(d.all_sources) == 2


def test_the_cover_counts_are_the_same_for_a_live_dossier_and_a_stored_one():
    """The generator counts a live `Dossier`; the backfill counts the SAME pack read back
    through `pack_manifest._ns`, a SimpleNamespace whose verdicts are plain strings. Two
    implementations is how a re-rendered cover would come to disagree with the original."""
    import json

    from prospector import models, pack_manifest

    d = _dossier_with([
        [Source(source_id="aaaa", url="https://a.example/x", text="one")],
        [Source(source_id="bbbb", url="https://a.example/x", text="one")],
        [Source(source_id="cccc", url="https://b.example/y", text="two")],
    ])
    stored = pack_manifest.dossier_from_dict(json.loads(d.to_json()))
    checks = stored.checks
    assert len(models.distinct_sources(checks)) == len(d.all_sources) == 2
    assert models.cited_claim_count(checks) == d.cited_claim_count == 3


def test_an_unverifiable_check_is_not_a_claim_the_pack_advertises():
    d = _dossier_with([[Source(source_id="aaaa", url="https://a.example/x", text="one")]])
    d.checks.append(CheckResult(check_name="u", verdict=Verdict.UNVERIFIABLE, confidence=0.0,
                                rationale="nothing found", citations=[], sources=[]))
    assert d.cited_claim_count == 1


def test_a_ruling_with_no_citation_is_not_counted_as_checkable():
    """The cover stat is the number the refund promise is written against, so it may only
    count claims a buyer can actually open."""
    d = _dossier_with([[]])
    assert d.cited_claim_count == 0


def test_citations_still_resolve_after_the_dedupe():
    """The dossier renderer resolves ids from the CHECKS, not from `all_sources` — a dedupe
    that broke that would blank the "Sources used" line the P2 work just fixed."""
    from prospector import dossier as dz

    url = "https://www.lulu.com/create/print-books"
    d = _dossier_with([
        [Source(source_id="aaaa", url=url, text="one")],
        [Source(source_id="bbbb", url=url, text="one")],
    ])
    md = dz.render_markdown(d)
    assert md.count("[lulu.com](") >= 1
