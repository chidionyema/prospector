"""A result set that does not mention the query is a FAILURE, not an answer.

THE DEFECT. `FallbackSearchProvider` failed over on an exception and on nothing else, so
a provider that answered a precise question with the topic's head pages counted as a
success and ended the chain. Ranking (`RelevanceRankedProvider`) cannot repair that: it
picks the best of what arrived. The page fetch then reads the wrong page in full, and the
verdict correctly rules `unverifiable` on evidence that never addressed the check.

MEASURED 2026-08-14 over the 1,622 grounding passages written since the page-fetch fix
(`store/dossiers/*.json` -> `checks[].sources[]`):

    verdict         n     mean coverage of its own query's content words
    supported      61     0.488
    refuted         8     0.447
    unverifiable  202     0.300

and 183 passages (11.3%) share ZERO content words with their own query — `4A's ANA agency
members AI content guidelines California 2024 2025` grounded on fire.ca.gov (a CAL FIRE
hiring page), `insider risk detection startup funding round Series A 2026 offboarding` on
theins.press (a Russian politics magazine).

Paired replay of the 15 worst live queries through the identical stack (rank + page fetch,
cache off): ddg 0.359 -> exa 0.525 mean coverage, exa better on 12 of 15. `ddg` answered
`UK AI Bill parliamentary progress 2026 AISI evaluation publication ICO` with two Wikipedia
pages and visitbritain.com; `exa` returned bills.parliament.uk and aisi.gov.uk.

These tests pin the properties that make it safe to run unattended: it escalates only when
someone is left to escalate to, it keeps the BEST set rather than the last one, it never
returns fewer sources than the old code would have, and it is a no-op when switched off.
"""
from __future__ import annotations

import pytest

from prospector.config import Retrieval
from prospector.models import Source
from prospector.retrieval import FallbackSearchProvider, SearchProvider

QUERY = "Illinois BIPA reform legislation per person violation"

#: What DuckDuckGo actually returned for a query of this shape — the topic's head pages.
_OFF_TOPIC = [
    Source.make(url="https://www.fire.ca.gov/",
                text="CAL FIRE is hiring forestry technicians this season", query=QUERY),
    Source.make(url="https://en.wikipedia.org/wiki/Privacy",
                text="Privacy is the ability of an individual to seclude themselves",
                query=QUERY),
]
#: What the second provider returned for the same query.
_ON_TOPIC = [
    Source.make(url="https://ilga.gov/bipa",
                text="Illinois BIPA reform legislation caps per person violation damages",
                query=QUERY),
]


class _Fake(SearchProvider):
    def __init__(self, results: list[Source]) -> None:
        self.results = results
        self.calls = 0

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        self.calls += 1
        return list(self.results)


class _Boom(SearchProvider):
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        self.calls += 1
        raise RuntimeError("provider down")


class _NeverDead:
    """Health stub: nothing is dead-marked, and nothing is recorded."""

    def is_dead(self, name):        # noqa: D102
        return False

    def clear(self, name):          # noqa: D102
        pass

    def mark_exhausted(self, name, dead_for, error=""):   # noqa: D102
        pass


def _chain(pairs, *, min_relevance: float) -> FallbackSearchProvider:
    return FallbackSearchProvider(pairs, min_relevance=min_relevance,
                                  health=_NeverDead())


class TestItEscalatesOnIrrelevance:
    def test_an_off_topic_answer_falls_through_to_the_next_provider(self):
        a, b = _Fake(_OFF_TOPIC), _Fake(_ON_TOPIC)
        got = _chain([("ddg", a), ("exa", b)], min_relevance=0.35).search(QUERY)
        assert [s.url for s in got] == ["https://ilga.gov/bipa"]
        assert (a.calls, b.calls) == (1, 1)

    def test_a_relevant_answer_ends_the_chain_and_never_pays_for_the_next_one(self):
        a, b = _Fake(_ON_TOPIC), _Fake(_OFF_TOPIC)
        got = _chain([("ddg", a), ("exa", b)], min_relevance=0.35).search(QUERY)
        assert [s.url for s in got] == ["https://ilga.gov/bipa"]
        assert b.calls == 0, "escalated off a result set that already cleared the floor"

    def test_the_last_provider_is_never_escalated_off(self):
        """Nothing to escalate TO — returning junk beats raising an outage."""
        a = _Fake(_OFF_TOPIC)
        got = _chain([("ddg", a)], min_relevance=0.35).search(QUERY)
        assert [s.url for s in got] == [s.url for s in _OFF_TOPIC]

    def test_when_no_provider_clears_the_floor_the_best_set_is_kept(self):
        """The engine must not lose evidence for being imperfect."""
        worse = [Source.make(url="https://x.test/", text="unrelated prose", query=QUERY)]
        a, b = _Fake(_OFF_TOPIC), _Fake(worse)
        got = _chain([("ddg", a), ("exa", b)], min_relevance=0.9).search(QUERY)
        assert [s.url for s in got] == [s.url for s in _OFF_TOPIC], \
            "kept the LAST set rather than the best-covering one"

    def test_an_empty_result_is_still_real_evidence_of_nothing(self):
        """A working provider's [] short-circuits exactly as it did before."""
        a, b = _Fake([]), _Fake(_ON_TOPIC)
        got = _chain([("ddg", a), ("exa", b)], min_relevance=0.35).search(QUERY)
        assert got == []
        assert b.calls == 0


class TestItCannotMakeThingsWorse:
    def test_a_low_relevance_set_survives_a_failing_second_provider(self):
        """The escalation must not convert a usable answer into a DEFER."""
        a, b = _Fake(_OFF_TOPIC), _Boom()
        got = _chain([("ddg", a), ("exa", b)], min_relevance=0.35).search(QUERY)
        assert [s.url for s in got] == [s.url for s in _OFF_TOPIC]
        assert b.calls == 1

    def test_every_provider_dead_still_raises(self):
        from prospector.errors import GroundingInfrastructureError
        chain = _chain([("ddg", _Boom()), ("exa", _Boom())], min_relevance=0.35)
        with pytest.raises(GroundingInfrastructureError):
            chain.search(QUERY)

    def test_off_is_a_byte_for_byte_no_op(self):
        a, b = _Fake(_OFF_TOPIC), _Fake(_ON_TOPIC)
        got = _chain([("ddg", a), ("exa", b)], min_relevance=0.0).search(QUERY)
        assert [s.url for s in got] == [s.url for s in _OFF_TOPIC]
        assert b.calls == 0


class TestTheShippedConfig:
    def test_the_dataclass_default_is_off(self):
        assert Retrieval().min_relevance == 0.0

    def test_the_shipped_config_turns_it_on_between_the_measured_populations(self):
        from prospector.config import load_config
        floor = load_config("config.yaml").retrieval.min_relevance
        assert 0.298 < floor < 0.400, (
            f"floor {floor} is not between the measured unverifiable median (0.298) "
            "and supported p25 (0.400)")

    def test_make_provider_wires_the_floor_through(self):
        from prospector.config import load_config
        from prospector.retrieval import make_provider
        cfg = load_config("config.yaml")
        cfg.retrieval.cache = False
        cfg.retrieval.fetch_pages = False
        cfg.retrieval.relevance_overfetch = 1
        prov = make_provider(cfg)
        assert isinstance(prov, FallbackSearchProvider)
        assert prov.min_relevance == cfg.retrieval.min_relevance
