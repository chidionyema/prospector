"""D5: three pages from one site are one source.

`docs/RETRIEVAL_PROGRAM.md` §D5. Two adjudication gates already existed — what KIND of domain
(the tier policy) and what KIND of claim (the health gate). Neither asked how many publishers
actually said it, so 434 of 2,816 cited `supported` rulings (15.4%, measured 2026-08-14 by
`tools/experiments/d5_corroboration.py`) rested on a single registrable domain, under a pack
that tells the buyer to click any SUPPORTED claim and demand a refund if the source does not
say what we say it says.

Four properties matter more than the arithmetic, and all four are asserted below:
  * independence is judged at the REGISTRABLE domain, so a site cannot corroborate itself
    from a second subdomain — the exact failure the gate exists to reject;
  * a lone `government`/`academic` publisher is exempt, because demanding a blog agree with
    `legislation.gov.uk` makes the evidence worse (67 government rulings, and the measured
    PASS-flip count is 1 either way);
  * the demotion must NOT set `retrieval_failed` — that flag means "outage, come back later"
    and would turn a judged ruling into a DEFER (verify.py DEFER_GATE);
  * `corroboration_min_domains: 1` must reproduce pre-D5 behaviour exactly, so the change is
    reversible by config alone (the project's "deterministic on config" constraint).
"""
from __future__ import annotations

import pytest

from prospector.admissibility import (
    CORROBORATION_EXEMPT_TIERS,
    corroboration_reason,
    publishers,
    registrable,
)
from prospector.config import Admissibility, Config, _validate_admissibility
from prospector.models import Candidate, Source, Verdict
from prospector.operator import MockOperator
from prospector.verify import verdict_for

# --- the publisher, not the hostname ----------------------------------------------------


@pytest.mark.parametrize("host,expected", [
    ("assets.publishing.service.gov.uk", "gov.uk"),   # one state, one publisher
    ("www.gov.uk", "gov.uk"),
    ("gov.uk", "gov.uk"),
    ("data.nhs.uk", "nhs.uk"),
    ("ox.ac.uk", "ox.ac.uk"),              # NOT collapsed: two universities are two publishers
    ("cam.ac.uk", "cam.ac.uk"),
    ("blog.acme.com", "acme.com"),
    ("acme.com", "acme.com"),
    ("shop.acme.co.uk", "acme.co.uk"),
    ("acme.co.uk", "acme.co.uk"),
    ("news.bbc.co.uk", "bbc.co.uk"),
    ("localhost", "localhost"),
    ("", ""),
])
def test_registrable_collapses_subdomains_to_the_publisher(host, expected):
    assert registrable(host) == expected


def test_a_site_cannot_corroborate_itself_from_a_second_subdomain():
    """The whole point. Two hostnames, one publisher, so the ruling is not corroborated."""
    urls = ["https://www.siterecon.ai/blog/a", "https://help.siterecon.ai/guide/b"]
    assert publishers(urls) == {"siterecon.ai"}
    assert corroboration_reason("value_durability", urls) is not None


def test_two_real_publishers_stand():
    urls = ["https://siterecon.ai/blog/a", "https://landscapemanagement.net/b"]
    assert corroboration_reason("value_durability", urls) is None


def test_one_publisher_cited_many_times_is_still_one_publisher():
    urls = ["https://nhsleavecalculator.co.uk/"] * 4
    reason = corroboration_reason("value_durability", urls)
    assert reason and "nhsleavecalculator.co.uk" in reason and "one publisher" in reason


# --- the exemption ----------------------------------------------------------------------


def test_a_lone_government_source_needs_no_corroboration():
    """`legislation.gov.uk` IS the answer on legality; a blog agreeing adds nothing."""
    assert corroboration_reason(
        "legality", ["https://www.legislation.gov.uk/ukpga/2018/12"]) is None


def test_a_lone_academic_source_needs_no_corroboration():
    assert corroboration_reason("pain_reality", ["https://www.ox.ac.uk/research/x"]) is None


def test_one_exempt_source_rescues_a_single_publisher_set():
    """Mirrors the tier gate's `all()`: one good source rescues the ruling."""
    urls = ["https://facebook.com/groups/x", "https://www.gov.uk/guidance/y"]
    assert corroboration_reason("distribution", urls) is None


def test_a_lone_newspaper_is_not_exempt():
    """`media` is deliberately outside the exemption: one paper restating one press release
    is exactly the correlated evidence this gate exists to catch."""
    assert corroboration_reason("pain_reality", ["https://www.thetimes.co.uk/a"]) is not None
    assert "media" not in CORROBORATION_EXEMPT_TIERS


def test_a_lone_social_post_is_not_exempt():
    assert corroboration_reason("distribution", ["https://facebook.com/groups/x"]) is not None


# --- the off switch and the edges -------------------------------------------------------


def test_min_domains_one_disables_the_gate():
    urls = ["https://facebook.com/groups/x"]
    assert corroboration_reason("distribution", urls, min_domains=1) is None


def test_an_uncited_ruling_is_not_this_gates_business():
    """`source_or_die` already demotes a `supported` ruling with no citations."""
    assert corroboration_reason("legality", []) is None
    assert corroboration_reason("legality", ["", ""]) is None


def test_three_publishers_needed_when_configured():
    urls = ["https://a.com/1", "https://b.com/2"]
    assert corroboration_reason("legality", urls, min_domains=3) is not None
    assert corroboration_reason("legality", urls, min_domains=2) is None


def test_an_unparseable_url_cannot_manufacture_a_publisher():
    urls = ["not a url", "https://acme.com/a"]
    assert publishers(urls) == {"acme.com"}
    assert corroboration_reason("legality", urls) is not None


# --- integration with the ruling seam ---------------------------------------------------


def _ruling(url_or_urls, check: str = "value_durability", verdict: str = "supported",
            **adm):
    """Exercises the seam with the gate ON, because it SHIPS OFF (`corroboration_min_domains:
    1`, config.yaml). The mechanism has to be tested at the value it will be enabled at, so
    the default here is 2 and `test_the_gate_is_reversible_by_config_alone` passes 1 to prove
    the off switch. Do not let this default track the shipped value — then no test covers the
    behaviour we intend to turn on."""
    urls = [url_or_urls] if isinstance(url_or_urls, str) else list(url_or_urls)
    adm.setdefault("corroboration_min_domains", 2)
    cfg = Config(admissibility=Admissibility(**adm))
    cand = Candidate(title="X", one_liner="y", hypothesis="z", who_pays="w")
    sources = [Source(source_id=f"s{i}", url=u, text="some passage text about the market")
               for i, u in enumerate(urls)]
    ids = [s.source_id for s in sources]
    op = MockOperator(router=lambda s, u: {"verdict": verdict, "citations": ids,
                                           "rationale": "original reasoning"})
    return verdict_for(op, cand, check, sources, cfg)


def test_a_single_publisher_supported_ruling_is_demoted_at_the_seam():
    r = _ruling(["https://nhsleavecalculator.co.uk/a", "https://nhsleavecalculator.co.uk/b"])
    assert r.verdict == Verdict.UNVERIFIABLE
    assert r.confidence == 0.0
    assert "one publisher" in r.rationale
    assert "original reasoning" in r.rationale        # the original argument is preserved


def test_the_demotion_is_not_an_outage():
    """`retrieval_failed` means DEFER. The evidence was fetched and judged, so this is a
    ruling we decline to trust, not something to come back to."""
    r = _ruling("https://sparkreceipt.com/blog/a")
    assert r.verdict == Verdict.UNVERIFIABLE
    assert r.retrieval_failed is False


def test_two_publishers_survive_the_seam():
    r = _ruling(["https://sparkreceipt.com/a", "https://xero.com/b"])
    assert r.verdict == Verdict.SUPPORTED


def test_a_refuted_ruling_is_never_demoted_for_lack_of_corroboration():
    """SUPPORTED-only by design: a refutation from one source still kills."""
    r = _ruling("https://sparkreceipt.com/blog/a", check="legality", verdict="refuted")
    assert r.verdict == Verdict.REFUTED


def test_the_gate_is_reversible_by_config_alone():
    r = _ruling("https://sparkreceipt.com/blog/a", corroboration_min_domains=1)
    assert r.verdict == Verdict.SUPPORTED


def test_the_lone_government_source_survives_the_seam():
    r = _ruling("https://www.legislation.gov.uk/ukpga/2018/12", check="legality")
    assert r.verdict == Verdict.SUPPORTED


# --- config validation ------------------------------------------------------------------


def test_config_defaults_match_the_dataclass():
    """ONE definition of what we ship: a caller passing no config gets the configured
    default, not a special case."""
    a = _validate_admissibility({})
    assert a.corroboration_min_domains == Admissibility().corroboration_min_domains == 1
    assert a.corroboration_exempt_tiers == CORROBORATION_EXEMPT_TIERS


def test_config_reads_the_keys():
    a = _validate_admissibility({"corroboration_min_domains": 3,
                                 "corroboration_exempt_tiers": ["government"]})
    assert a.corroboration_min_domains == 3
    assert a.corroboration_exempt_tiers == ("government",)


@pytest.mark.parametrize("raw", [
    {"corroboration_min_domains": True},      # bool is an int subclass: would silently be 1
    {"corroboration_min_domains": 0},
    {"corroboration_min_domains": "2"},
    {"corroboration_exempt_tiers": "government"},       # a bare string is not a list
    {"corroboration_exempt_tiers": ["goverment"]},      # typo'd tier => silent no-op
    {"corroboration_typo": 2},
])
def test_a_bad_config_stops_the_process(raw):
    """A typo must fail loudly at startup; the alternative is a gate that quietly does
    nothing while `config.yaml` reads as if it were on."""
    with pytest.raises(ValueError):
        _validate_admissibility(raw)


def test_the_floor_ships_off_until_the_fixtures_corroborate():
    """The mechanism is landed and tested; the SWITCH is off, and this pins that.

    At 2 the golden set scored 77.8% discrimination against the required 100% and the decay
    loop refreshed 0 dossiers, because the mock fixtures cite a single publisher per check.
    Flipping this to 2 without first giving those fixtures two publishers re-breaks both.
    """
    from prospector.config import load_config
    a = load_config("config.yaml").admissibility
    assert a.corroboration_min_domains == 1
    assert a.corroboration_exempt_tiers == ("government", "academic")
