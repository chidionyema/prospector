"""Citation admissibility at RULING time (programme doc §20, the Q4 lever).

A supported/refuted ruling is demoted to `unverifiable` when EVERY one of its citations sits
in a tier that cannot establish THAT check. One good source rescues the ruling — which is why
the measured cost of the shipped policy is 12 verdicts in two months (0.47%) rather than the
484 rulings that merely TOUCH a low-tier domain.

Two properties matter more than the classification itself, and both are asserted below:
  * the demotion must NOT set `retrieval_failed` — that flag means "outage, come back later"
    and would turn a judged ruling into a DEFER (verify.py:693);
  * `policy: off` must reproduce pre-§20 behaviour exactly, so the change is reversible by
    config alone (the project's "deterministic on config" constraint).
"""
from __future__ import annotations

import pytest

from prospector.admissibility import (
    LOW_TIERS,
    POLICIES,
    UGC_ADMISSIBLE,
    demotion_reason,
    host_of,
    inadmissible_tiers,
    is_ruling_admissible,
    tier,
)
from prospector.config import Admissibility, Config
from prospector.models import Candidate, Source, Verdict
from prospector.operator import MockOperator
from prospector.verify import verdict_for

# ------------------------------------------------------------------------------- classifier

@pytest.mark.parametrize("host,expected", [
    ("gitnux.org", "stats_farm"),
    ("worldmetrics.org", "stats_farm"),
    ("thesaurus.com", "reference_noise"),
    ("youtube.com", "ugc_social"),
    ("reddit.com", "ugc_social"),
    ("legislation.gov.uk", "government"),
    ("hmrc.gov.uk", "government"),          # via GOV_SUFFIXES, not the explicit set
    ("ox.ac.uk", "academic"),               # via ACADEMIC_SUFFIXES
    ("bbc.co.uk", "media"),
    ("citizensadvice.org.uk", "established_org"),
    ("en.wikipedia.org", "wikipedia"),
    ("some-random-consultancy.co.uk", "other"),
])
def test_tier_classification(host, expected):
    assert tier(host) == expected


def test_host_of_strips_www_and_lowercases():
    assert host_of("https://WWW.Reddit.com/r/x?y=1") == "reddit.com"
    assert host_of("not a url") == ""


# ----------------------------------------------------------------------------- the policies

def test_p2_removes_farms_and_nothing_else():
    """The free floor: measured at 0 demoted verdicts in two months of history."""
    assert not is_ruling_admissible("legality", ["https://gitnux.org/a"], "P2_farm_only")
    assert not is_ruling_admissible("legality", ["https://thesaurus.com/a"], "P2_farm_only")
    # UGC is untouched by P2, on every check.
    assert is_ruling_admissible("legality", ["https://reddit.com/a"], "P2_farm_only")


def test_p1_is_check_aware_which_is_the_whole_point():
    """A Facebook group IS the channel for `distribution`; it cannot say what the law is."""
    ugc = ["https://facebook.com/groups/123"]
    assert is_ruling_admissible("distribution", ugc, "P1_check_aware")
    assert is_ruling_admissible("route_to_market", ugc, "P1_check_aware")
    assert not is_ruling_admissible("legality", ugc, "P1_check_aware")
    assert not is_ruling_admissible("payer_solvency", ugc, "P1_check_aware")


def test_p0_is_available_but_is_the_one_we_rejected():
    """Kept selectable so the §20.3 comparison stays runnable, not because it should ship."""
    assert not is_ruling_admissible("distribution", ["https://reddit.com/a"], "P0_global")
    assert inadmissible_tiers("distribution", "P0_global") == frozenset(LOW_TIERS)


def test_off_admits_everything():
    for check in ("legality", "distribution", "payer_solvency"):
        assert is_ruling_admissible(check, ["https://gitnux.org/a"], "off")


def test_one_good_source_rescues_the_ruling():
    """The `all()` in the gate is what keeps the measured cost at 0.47% instead of ~19%."""
    mixed = ["https://gitnux.org/stats", "https://legislation.gov.uk/ukpga/2018/12"]
    assert is_ruling_admissible("legality", mixed, "P1_check_aware")
    assert is_ruling_admissible("legality", mixed, "P0_global")


def test_no_citations_is_not_this_gates_business():
    """`source_or_die` (verify.py:427) already handles an uncited ruling."""
    assert is_ruling_admissible("legality", [], "P1_check_aware")


def test_every_declared_policy_is_handled():
    """A policy name that config accepts but the gate ignores is a silent no-op."""
    for p in POLICIES:
        assert isinstance(inadmissible_tiers("legality", p), frozenset)
    assert set(UGC_ADMISSIBLE) == {"distribution", "route_to_market", "buyer_intent",
                                   "pain_reality"}


def test_demotion_reason_names_the_domains_and_is_none_when_admissible():
    reason = demotion_reason("legality", ["https://gitnux.org/a"], "P1_check_aware")
    assert reason and "gitnux.org" in reason and "stats_farm" in reason
    assert demotion_reason("legality", ["https://bbc.co.uk/a"], "P1_check_aware") is None


# --------------------------------------------------------------- integration with verdict_for

def _ruling(policy: str, url: str, check: str = "legality", verdict: str = "refuted"):
    cfg = Config(admissibility=Admissibility(policy=policy))
    cand = Candidate(title="X", one_liner="y", hypothesis="z", who_pays="w")
    sources = [Source(source_id="s1", url=url, text="some passage text about the market")]
    op = MockOperator(router=lambda s, u: {"verdict": verdict, "citations": ["s1"],
                                           "rationale": "original reasoning"})
    return verdict_for(op, cand, check, sources, cfg)


def test_a_ruling_resting_only_on_a_stats_farm_is_demoted():
    res = _ruling("P1_check_aware", "https://gitnux.org/uk-market-statistics")
    assert res.verdict == Verdict.UNVERIFIABLE
    assert res.confidence == 0.0
    assert "gitnux.org" in res.rationale
    assert "original reasoning" in res.rationale, "the original must survive for the audit trail"


def test_the_demotion_is_not_an_outage_and_must_not_defer():
    """`retrieval_failed=True` would make this DEFER (verify.py:693). The evidence WAS
    fetched and judged; we are declining to trust it, which is a finding, not an outage."""
    res = _ruling("P1_check_aware", "https://gitnux.org/uk-market-statistics")
    assert getattr(res, "retrieval_failed", False) is False


def test_policy_off_reproduces_pre_section_20_behaviour(monkeypatch):
    """NON-VACUITY: the same ruling, same citation, stands when the gate is off."""
    res = _ruling("off", "https://gitnux.org/uk-market-statistics")
    assert res.verdict == Verdict.REFUTED
    assert res.confidence > 0.0


def test_check_awareness_survives_the_real_verdict_path():
    """The unit test above proves the predicate; this proves verify.py actually passes the
    check NAME through, which is the thing that would silently regress."""
    assert _ruling("P1_check_aware", "https://facebook.com/groups/1",
                   check="distribution").verdict == Verdict.REFUTED
    assert _ruling("P1_check_aware", "https://facebook.com/groups/1",
                   check="legality").verdict == Verdict.UNVERIFIABLE


def test_a_supported_ruling_is_demoted_too_not_just_a_kill():
    """Admissibility is not a pro-candidate lever: it demotes PASSES on bad evidence too."""
    res = _ruling("P1_check_aware", "https://gitnux.org/a", check="legality",
                  verdict="supported")
    assert res.verdict == Verdict.UNVERIFIABLE
