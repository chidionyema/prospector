"""A dictionary entry is not evidence that a buyer pays for something.

MEASURED 2026-08-17 over three days of kill dossiers: 39.7% of the source slots under an
`unverifiable` check came from encyclopedia, dictionary and atlas hosts, against 6.6% under
`supported` and 1.2% on the packs that actually passed. The receipts name the mechanism. A
`payer_solvency` check searched "venture financing closing delay cap table conflict
anti-dilution litigation dispute investor risk" and was handed Merriam-Webster's definition
of the word "venture". A legality check searched "Illinois Supreme Court Rule practice of law
software document analysis exception unauthorized" and was handed Wikipedia and World Atlas
on the STATE of Illinois.

`relevance_score` is the fraction of the query's content words a passage contains, so a
state's encyclopedia entry scores well on a query naming that state repeatedly. Coverage
cannot tell "about Illinois" from "about the law in Illinois". The host can.

These pages are DEMOTED, never dropped. `RelevanceRankedProvider` returns the same count it
was asked for, which is what keeps `retrieval_failed`, the DEFER gate and every downstream
count untouched. That property must survive this change, so it is pinned below.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from prospector.models import Source
from prospector.retrieval import RelevanceRankedProvider, is_reference_page


def _src(url: str, text: str) -> Source:
    return Source.make(url=url, text=text, query="q")


class TestIsReferencePage(unittest.TestCase):
    def test_the_hosts_that_produced_the_measured_junk(self):
        for url in (
            "https://en.wikipedia.org/wiki/Illinois",
            "https://www.worldatlas.com/maps/united-states/illinois",
            "https://www.britannica.com/place/Illinois-state",
            "https://dictionary.cambridge.org/dictionary/english/venture",
            "https://www.merriam-webster.com/dictionary/venture",
        ):
            self.assertTrue(is_reference_page(url), url)

    def test_a_locale_subdomain_of_the_same_encyclopedia_is_caught(self):
        """Without parent-domain matching this needs one entry per language."""
        self.assertTrue(is_reference_page("https://fr.wikipedia.org/wiki/Illinois"))
        self.assertTrue(is_reference_page("https://de.wiktionary.org/wiki/Wagnis"))

    def test_real_evidence_hosts_are_untouched(self):
        for url in (
            "https://www.gov.uk/guidance/tenant-fees-act-2019-guidance-for-tenants",
            "https://ico.org.uk/for-organisations/",
            "https://iq.govwin.com/neo/marketAnalysis",
            "https://www.fca.org.uk/firms",
            "https://www.linkedin.com/company/x",
        ):
            self.assertFalse(is_reference_page(url), url)

    def test_junk_input_is_not_a_reference_page_and_does_not_raise(self):
        for url in ("", "   ", "notaurl", "ftp://en.wikipedia.org/x", None):
            self.assertFalse(is_reference_page(url))  # type: ignore[arg-type]

    def test_a_host_that_merely_ends_in_a_listed_word_is_not_matched(self):
        """Substring matching would bench a real site. `notwikipedia.org` is not the
        encyclopedia, and `mydictionary.com` is not Cambridge."""
        self.assertFalse(is_reference_page("https://notwikipedia.org/x"))
        self.assertFalse(is_reference_page("https://mydictionary.com/x"))


class TestTheRankerDemotesButNeverStarves(unittest.TestCase):
    def _provider(self, results):
        inner = MagicMock()
        inner.search.return_value = results
        return RelevanceRankedProvider(inner, overfetch=3)

    def test_a_real_page_beats_an_encyclopedia_page_that_scores_higher_on_words(self):
        """The measured case. The Wikipedia page repeats 'Illinois' and outscores the trade
        page on raw content-word coverage; it must still lose."""
        query = "Illinois Supreme Court Rule practice of law software document unauthorized"
        wiki = _src("https://en.wikipedia.org/wiki/Illinois",
                    "Illinois Illinois Supreme Court Illinois practice Illinois law "
                    "Illinois software Illinois document Illinois unauthorized rule")
        real = _src("https://www.isba.org/advisoryopinions/2024",
                    "Illinois State Bar advisory opinion on document software")
        kept = self._provider([wiki, real, wiki, real]).search(query, k=2)

        self.assertEqual(kept[0].url, real.url,
                         "an encyclopedia page outranked the page that answers the question")

    def test_the_count_returned_is_unchanged(self):
        """The no-starvation property. Downstream counts, retrieval_failed and the DEFER
        gate all depend on this."""
        query = "anything at all"
        results = [_src(f"https://en.wikipedia.org/wiki/{i}", "text") for i in range(6)]
        self.assertEqual(len(self._provider(results).search(query, k=3)), 3)

    def test_all_reference_results_are_returned_unchanged(self):
        """When every candidate is a reference page there is nothing to demote it below, so
        the list must come back exactly as the ranking would otherwise have left it."""
        query = "venture financing cap table dispute"
        results = [
            _src("https://en.wikipedia.org/wiki/Venture", "venture financing cap table dispute"),
            _src("https://www.merriam-webster.com/dictionary/venture", "venture"),
            _src("https://dictionary.cambridge.org/dictionary/english/venture", "venture"),
            _src("https://www.britannica.com/money/venture-capital", "venture financing"),
        ]
        kept = self._provider(results).search(query, k=2)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0].url, "https://en.wikipedia.org/wiki/Venture",
                         "with nothing to demote below, the best-covering page must still win")

    def test_overfetch_of_one_is_still_a_byte_for_byte_passthrough(self):
        """The documented no-op guarantee predates this change and must survive it."""
        inner = MagicMock()
        results = [_src("https://en.wikipedia.org/wiki/Illinois", "Illinois")]
        inner.search.return_value = results
        self.assertEqual(RelevanceRankedProvider(inner, overfetch=1).search("q", k=4), results)


if __name__ == "__main__":
    unittest.main()
