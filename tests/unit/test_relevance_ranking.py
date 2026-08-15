"""Search results must be RANKED before the verdict sees them.

THE DEFECT. Every provider in `prospector/retrieval.py` asked the search engine for
exactly `results_per_query` results and kept the engine's own first k (`raw[:k]`).
Relevance was therefore something this engine MEASURED at the verdict — as
`unverifiable` — and never once enforced where the sources are produced.

MEASURED 2026-08-14 over the 450 grounding passages written since the page-fetch fix
went live (`store/dossiers/*.json` -> `checks[].sources[]`):

    verdict         n     mean coverage of its own query's content words
    supported      74     42.8%
    refuted        18     36.0%
    unverifiable  358     25.1%   <- 47.2% of these matched under 20%

Half the fetched pages were off-topic outright: a `distribution` check grounded on
vk.com and fire.ca.gov, an `AATF WEEE resale` query grounded on
gamblingcommission.gov.uk. Re-running ten of those exact queries at max_results=10, the
first 3 average 25.9% coverage and the BEST 3 average 36.8% — the relevant pages were
already in the result list and were being discarded unread.

These tests pin the four properties that make the fix safe to run unattended: it picks
the best k, it costs no extra page fetch, it CANNOT starve a check (same count out), and
it is a byte-for-byte no-op when switched off.
"""
from __future__ import annotations

import threading

import pytest

from prospector.models import Source
from prospector.retrieval import (
    PageTextEnricher,
    RelevanceRankedProvider,
    SearchProvider,
    _resolve_urls,
    make_provider,
    relevance_score,
)

QUERY = "Illinois BIPA reform legislation per person violation"


def _src(url: str, text: str) -> Source:
    return Source.make(url=url, text=text, query=QUERY)


#: Ordered as DuckDuckGo actually ordered them — the junk first, the answer at #6.
#: `_ANSWER` is the page that would let a verdict rule; it is the one being thrown away.
_JUNK = [
    _src("https://www.fire.ca.gov/", "CAL FIRE is hiring forestry technicians this season"),
    _src("https://vk.com/video-204533316", "Смотрите онлайн видео без регистрации"),
    _src("https://en.wikipedia.org/wiki/Privacy", "Privacy is the ability of an individual"),
    _src("https://www.youtube.com/watch?v=x", "In this video I reveal the 4-stage system"),
    _src("https://praoto.baby/trending", "Download complete video now 0 views 0 likes"),
]
_ANSWER = _src("https://ilga.gov/bipa",
               "Illinois BIPA reform legislation caps per person violation damages")
_PARTIAL = _src("https://news.example/bipa",
                "Illinois legislation on biometric privacy reform advanced")


class _Fake(SearchProvider):
    """Records the k it was asked for, so over-fetch is provable, not asserted."""

    def __init__(self, results: list[Source]) -> None:
        self.results = results
        self.asked_k: list[int] = []

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        self.asked_k.append(k)
        return list(self.results[:k])


class TestTheScore:
    def test_it_measures_the_query_not_the_prose(self):
        assert relevance_score(QUERY, _ANSWER.text) == pytest.approx(1.0)
        assert relevance_score(QUERY, _JUNK[0].text) == 0.0

    def test_a_partial_match_ranks_between_the_two(self):
        assert 0.0 < relevance_score(QUERY, _PARTIAL.text) < 1.0

    def test_an_empty_query_scores_zero_rather_than_dividing_by_zero(self):
        assert relevance_score("", "anything at all") == 0.0
        assert relevance_score("of the a an", "anything at all") == 0.0


class TestItPicksTheBest:
    def test_it_over_fetches(self):
        inner = _Fake(_JUNK + [_ANSWER, _PARTIAL])
        RelevanceRankedProvider(inner, overfetch=3).search(QUERY, k=3)
        assert inner.asked_k == [9], "asked for the same 3 it always did — nothing to rank"

    def test_the_answer_buried_at_result_six_is_what_the_verdict_gets(self):
        """The whole point: today this check rules `unverifiable` on CAL FIRE.

        The third slot is still junk, and that is correct — the ranker returns the COUNT
        it was asked for and never starves a check. What changed is that the statute is
        now IN the set and leads it, where the unranked first-3 excluded it entirely.
        """
        inner = _Fake(_JUNK + [_ANSWER, _PARTIAL])
        kept = RelevanceRankedProvider(inner, overfetch=3).search(QUERY, k=3)
        assert [s.url for s in kept][:2] == [_ANSWER.url, _PARTIAL.url]
        assert _ANSWER not in _JUNK[:3], "fixture is not reproducing the defect"

    def test_it_returns_exactly_the_count_it_was_asked_for(self):
        """It CANNOT starve a check: same count out, so `retrieval_failed`, the DEFER
        gate and every downstream count behave exactly as before."""
        inner = _Fake(_JUNK + [_ANSWER, _PARTIAL])
        assert len(RelevanceRankedProvider(inner, overfetch=3).search(QUERY, k=3)) == 3

    def test_a_thin_result_set_is_passed_through_whole(self):
        inner = _Fake([_ANSWER])
        assert RelevanceRankedProvider(inner, overfetch=3).search(QUERY, k=3) == [_ANSWER]

    def test_an_empty_result_stays_empty(self):
        """A legitimate empty result is evidence of nothing and must reach run_check
        unchanged — inventing a source here would manufacture grounding."""
        assert RelevanceRankedProvider(_Fake([]), overfetch=3).search(QUERY, k=3) == []

    def test_ties_keep_the_search_engines_own_order(self):
        same = [_src(f"https://e/{i}", "Illinois BIPA reform legislation per person violation")
                for i in range(6)]
        kept = RelevanceRankedProvider(_Fake(same), overfetch=3).search(QUERY, k=3)
        assert [s.url for s in kept] == [s.url for s in same[:3]]

    def test_a_provider_outage_still_raises(self):
        """`GroundingInfrastructureError` must reach run_check, which DEFERS. Swallowing
        it here would turn an outage into a reasoned kill — this repo has paid for that."""
        class _Dead(SearchProvider):
            def search(self, query, k=4, max_chars=1500):
                raise RuntimeError("all providers dead")

        with pytest.raises(RuntimeError):
            RelevanceRankedProvider(_Dead(), overfetch=3).search(QUERY, k=3)


class TestOffIsOff:
    def test_overfetch_one_is_a_byte_for_byte_no_op(self):
        inner = _Fake(_JUNK + [_ANSWER])
        kept = RelevanceRankedProvider(inner, overfetch=1).search(QUERY, k=3)
        assert inner.asked_k == [3], "widened the search while switched off"
        assert kept == _JUNK[:3], "re-ordered results while switched off"

    def test_the_shipped_default_is_off(self):
        """Fixtures, the golden set and any directly-constructed Retrieval() must keep
        their behaviour; only config.yaml turns this on."""
        from prospector.config import Retrieval
        assert Retrieval().relevance_overfetch == 1

    def test_the_shipped_config_turns_it_on(self):
        from prospector.config import load_config
        assert load_config("config.yaml").retrieval.relevance_overfetch > 1


class TestItIsWiredWhereItCosts_Nothing:
    def _chain(self, provider):
        # DiskCache names its delegate `inner`; the wrappers name theirs `_inner`.
        out = []
        while provider is not None:
            out.append(type(provider).__name__)
            provider = getattr(provider, "_inner", None) or getattr(provider, "inner", None)
        return out

    def test_ranking_runs_before_the_page_fetch(self):
        """Order is the cost argument. Ranking on the free snippet and fetching only the
        survivors is why this adds no page fetches; invert the two and it triples them."""
        from prospector.config import load_config
        chain = self._chain(make_provider(load_config("config.yaml")))
        assert "RelevanceRankedProvider" in chain, "the ranker is not in the live chain"
        assert "PageTextEnricher" in chain
        assert chain.index("PageTextEnricher") < chain.index("RelevanceRankedProvider"), \
            "the enricher must WRAP the ranker, or every over-fetched result gets fetched"

    def test_the_enricher_only_ever_sees_the_survivors(self):
        inner = _Fake(_JUNK + [_ANSWER, _PARTIAL])
        fetched: list[str] = []

        enriched = PageTextEnricher(RelevanceRankedProvider(inner, overfetch=3))
        import prospector.retrieval as R
        orig = R.fetch_page_text
        try:
            R.fetch_page_text = lambda url, **kw: fetched.append(url) or None
            enriched.search(QUERY, k=3)
        finally:
            R.fetch_page_text = orig
        assert len(fetched) == 3, f"fetched {len(fetched)} pages to return 3 sources"

    def test_fixtures_never_get_the_ranker(self):
        """The golden set exists to attribute results to the BRAIN. Re-ordering its
        passages would move that baseline underneath every acceptance test."""
        from prospector.config import load_config
        cfg = load_config("config.yaml")
        assert "RelevanceRankedProvider" not in self._chain(make_provider(cfg, fixtures={}))


_NAV = "Skip navigation shop deals sign in help centre. " * 30
_ANSWER_TEXT = ("The FCC ruled in June 2024 that AI generated voice calls require prior "
                "express written consent under the TCPA. ")
_FOOTER = "Footer links about us careers press privacy cookies. " * 30
_PAGE = _NAV + _ANSWER_TEXT * 3 + _FOOTER
_PAGE_QUERY = "FCC June 2024 AI generated voice TCPA prior express written consent"


class TestSelectingThePassage:
    """`fetch_page_text` returned the TOP of the page and the verdict read the first 600
    chars of that. On a median 6,334-char page that is the masthead — which is why the
    page-fetch fix bought real page text and no yield. Measured over 61 live pages, what
    the verdict reads went from 26.9% to 40.3% query coverage when anchored."""

    def test_it_skips_the_masthead_and_lands_on_the_evidence(self):
        from prospector.retrieval import select_passage
        out = select_passage(_PAGE, 300, query=_PAGE_QUERY)
        assert "prior express written consent" in out
        assert "Skip navigation" not in out, "returned the nav bar, as today"

    def test_no_query_is_the_old_head_slice_byte_for_byte(self):
        from prospector.retrieval import select_passage
        assert select_passage(_PAGE, 300) == _PAGE[:300]

    def test_text_shorter_than_the_budget_is_untouched(self):
        from prospector.retrieval import select_passage
        assert select_passage("short passage", 300, query=_PAGE_QUERY) == "short passage"

    def test_a_page_with_no_query_terms_keeps_the_head(self):
        """No match is not a licence to pick an arbitrary window — that would silently
        move evidence for no reason and make a diff impossible to reason about."""
        from prospector.retrieval import select_passage
        assert select_passage(_NAV + _FOOTER, 300, query="zzzz yyyy xxxx") == (_NAV + _FOOTER)[:300]

    def test_it_never_returns_more_than_the_budget(self):
        from prospector.retrieval import select_passage
        assert len(select_passage(_PAGE, 300, query=_PAGE_QUERY)) <= 300

    def test_a_passage_never_opens_mid_word(self):
        from prospector.retrieval import select_passage
        out = select_passage(_PAGE, 300, query=_PAGE_QUERY)
        assert _PAGE[_PAGE.index(out) - 1] in " " if _PAGE.index(out) else True

    def test_the_tail_of_a_page_is_reachable(self):
        """The window may not run off the end — clamping to len-max_chars is what lets
        evidence in the last paragraph be selected at all."""
        from prospector.retrieval import select_passage
        page = _NAV * 2 + _ANSWER_TEXT
        out = select_passage(page, 300, query=_PAGE_QUERY)
        assert "prior express written consent" in out
        assert len(out) == 300

    def test_the_anchor_matches_the_verdicts_own_budget(self):
        """One discipline, one number. Anchoring on 1500 instead and slicing its head made
        what the verdict reads WORSE by 3.5 points (n=26 live pages, 2026-08-14)."""
        from prospector.retrieval import PASSAGE_ANCHOR_CHARS
        from prospector.verify import VERDICT_PASSAGE_TRUNCATE
        assert PASSAGE_ANCHOR_CHARS == VERDICT_PASSAGE_TRUNCATE

    def test_the_enricher_hands_the_query_down(self):
        """Without the query the selector is inert — the defect would look fixed and the
        verdict would still read the masthead."""
        import prospector.retrieval as R
        seen: dict = {}
        inner = _Fake([_src("https://e/1", "snippet")])
        orig = R.fetch_page_text
        try:
            R.fetch_page_text = lambda url, **kw: seen.update(kw) or None
            PageTextEnricher(inner).search(QUERY, k=1)
        finally:
            R.fetch_page_text = orig
        assert seen.get("query") == QUERY, f"query never reached the fetch: {seen}"

    def test_a_huge_page_is_selected_in_reasonable_time(self):
        """Scanning every offset of a 400,000-char page and re-tokenising a 600-char slice
        at each is seconds of CPU per source, on the grounding path."""
        import time

        from prospector.retrieval import select_passage
        huge = (_NAV * 200) + _ANSWER_TEXT + (_FOOTER * 200)
        # CPU time, not wall clock, and a budget with room in it. Measured 2026-08-15 on this
        # 606,111-char input, inside pytest, warm: wall 0.476-0.503s, CPU 0.371-0.391s.
        #
        # The old assertion was `monotonic() < 0.5` — a 22% margin over a 0.39s cost, on the
        # WALL clock. That is not a regression detector, it is a load detector, and it had two
        # ways to go red on unchanged code: run this test ALONE and the first call pays warmup
        # nothing has amortised (it fails); run the suite at `-n auto` and 12-way memory
        # contention inflates the cost past the margin (it fails). Both happened on 2026-08-15.
        # It only ever looked stable because it ran mid-file on an idle machine.
        #
        # So: `process_time`, because the claim in the docstring is about WORK and wall clock
        # cannot measure work; and 2.0s, because the defect this guards is "seconds of CPU per
        # source" — an O(n^2) window scan re-tokenising at every offset, which regresses by
        # multiples, not by 25%. A budget that trips on a busy machine trains people to rerun
        # the suite until it is green, which is how a real regression gets waved through.
        t0 = time.process_time()
        out = select_passage(huge, 1500, query=_PAGE_QUERY)
        cpu = time.process_time() - t0
        assert cpu < 2.0, (
            f"window scan took {cpu:.2f}s CPU on {len(huge):,} chars; the grounding path pays "
            "this per source. Baseline is ~0.39s — this is a multiple, not measurement noise")
        assert "prior express written consent" in out


class TestResolvingManyUrls:
    def test_order_is_preserved(self, monkeypatch):
        import prospector.retrieval as R
        monkeypatch.setattr(R, "_resolve", lambda u, t=None: None if "dead" in u else u)
        urls = ["https://a", "https://dead", "https://c"]
        assert _resolve_urls(urls) == ["https://a", None, "https://c"]

    def test_it_survives_genuine_concurrency(self, monkeypatch):
        """One `copy_context()` PER WORKER, never one shared. `Context.run()` raises when
        the same Context is entered concurrently — the defect that made `resolve_sources`
        raise 20/20 on 3 URLs from 2026-06-15 until 2026-08-13. A stub that returns
        instantly never overlaps, so the Barrier forces the overlap that finds it."""
        import prospector.retrieval as R
        barrier = threading.Barrier(4, timeout=10)
        monkeypatch.setattr(R, "_resolve", lambda u, t=None: (barrier.wait(), u)[1])
        urls = [f"https://h{i}" for i in range(4)]
        assert _resolve_urls(urls) == urls
