"""P5: the machine-readable table — `Assumptions.csv`.

The programme doc asks for "one machine-readable table (assumption, cost to confirm, test, cost
of test)". Three of those four are on disk. The money is not: nothing the engine retrieved
prices what a test costs, so a `cost_to_confirm` column would be a number we invented, in the
one file a buyer is most likely to paste into a spreadsheet and total. `source-or-die` forbids
it, and the first test class below is what keeps it forbidden when somebody re-reads the
programme doc and wonders why a column is missing.

Everything else here pins the two ways a generated CSV goes wrong in a buyer's hands: a
rationale containing a comma, a quote or a newline that shifts their columns, and a `0.00`
printed where the engine actually had no opinion.
"""
from __future__ import annotations

import csv
import io
from types import SimpleNamespace

import pytest

from prospector import pack_manifest, pack_table
from prospector.dossier import check_label
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict

_MESSY = ('The council said "we cut hours, not care", which is a distinction, not a policy.\n'
          'Two providers, both London-based, disagree.')


def _src(sid: str, url: str) -> Source:
    return Source(source_id=sid, url=url, text="A retrieved passage.", query="q",
                  fetched_at="2026-07-31T00:00:00Z")


def _dossier(checks=None) -> Dossier:
    cand = Candidate(candidate_id="c" * 16, title="Care Hours Appeal Pack", one_liner="x",
                     market="uk", who_pays="Unpaid family carers.", why_now="y")
    return Dossier(candidate=cand, decision=Decision.PASS,
                   checks=checks if checks is not None else _checks(),
                   created_at="2026-07-31T00:00:00Z", provider_chain="claude-cli/default")


def _checks():
    shared = _src("a" * 16, "https://example.gov.uk/care")
    return [
        CheckResult(check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.83,
                    rationale=_MESSY, citations=["a" * 16],
                    # The same page fetched twice under two ids — the shape that made one URL
                    # appear twice in the evidence document before it was deduped.
                    sources=[shared, _src("b" * 16, "https://example.gov.uk/care")],
                    queries=["council care hours cut appeal"]),
        CheckResult(check_name="incumbency", verdict=Verdict.REFUTED, confidence=0.7,
                    rationale="Two incumbents already ship this.", citations=["b" * 16],
                    sources=[_src("d" * 16, "https://example.com/rival")]),
        CheckResult(check_name="payer_solvency", verdict=Verdict.UNVERIFIABLE, confidence=0.2,
                    rationale="No passage states what a carer can afford.",
                    queries=["unpaid carer household income uk", "carers allowance rate"]),
    ]


@pytest.fixture
def rows():
    return list(csv.reader(io.StringIO(pack_table.render(_dossier()))))


class TestTheColumnWeRefusedToInvent:
    def test_there_is_no_cost_column(self):
        """`source-or-die`. Nothing on disk prices a test, so a cost column would be a made-up
        number in the file a buyer is most likely to total in a spreadsheet."""
        assert not [c for c in pack_table.HEADER if "cost" in c or "price" in c]

    def test_what_replaces_it_is_the_searches_actually_run(self, rows):
        settle = rows[0].index("how_to_settle")
        assert rows[3][settle] == "unpaid carer household income uk | carers allowance rate"

    def test_a_check_with_no_recorded_searches_leaves_the_cell_empty_not_invented(self, rows):
        settle = rows[0].index("how_to_settle")
        assert rows[2][settle] == ""


class TestOneRowPerCheck:
    def test_the_header_is_the_declared_header(self, rows):
        assert tuple(rows[0]) == pack_table.HEADER

    def test_every_check_gets_a_row_named_in_the_buyers_words(self, rows):
        assert [r[0] for r in rows[1:]] == [
            check_label("pain_reality"), check_label("incumbency"),
            check_label("payer_solvency")]

    def test_the_verdict_is_translated_out_of_the_engines_vocabulary(self, rows):
        """A buyer sorting this column should not have to learn what "unverifiable" means."""
        assert [r[1] for r in rows[1:]] == ["proven", "disproven", "assumption"]

    def test_a_scored_check_prints_the_score_the_brain_gave_it(self, rows):
        assert rows[1][rows[0].index("confidence")] == "0.83"

    def test_an_unscored_check_prints_no_confidence_rather_than_zero(self):
        """`0.00` and "we did not score this" are different facts, and printing the first for
        the second tells the buyer the engine had no confidence when it had no opinion. A live
        `CheckResult` always carries a score; the replayed `SimpleNamespace` the backfill builds
        from an older `store/dossiers/<id>.json` need not, which is the shape tested here."""
        assert pack_table._confidence(SimpleNamespace(confidence=None)) == ""
        assert pack_table._confidence(SimpleNamespace()) == ""
        assert pack_table._confidence(SimpleNamespace(confidence=0.0)) == "0.00"


class TestABuyersSpreadsheetSurvivesIt:
    def test_a_rationale_full_of_commas_and_quotes_round_trips(self, rows):
        found = rows[1][rows[0].index("what_we_found")]
        assert 'said "we cut hours, not care"' in found
        assert len(rows[1]) == len(pack_table.HEADER), "the columns must not shift"

    def test_a_newline_inside_a_rationale_is_collapsed_not_embedded(self):
        """Quoting makes an embedded newline legal CSV and still breaks every buyer who opens
        the file in a text editor or pipes it through `cut`."""
        out = pack_table.render(_dossier())
        assert len(out.rstrip("\r\n").split("\r\n")) == 4
        assert "\n" not in out.replace("\r\n", "")

    def test_it_is_written_with_the_line_ending_every_spreadsheet_expects(self):
        assert pack_table.render(_dossier()).endswith("\r\n")

    def test_each_page_is_listed_once_however_many_times_it_was_fetched(self, rows):
        srcs = rows[1][rows[0].index("sources")]
        assert srcs.split() == ["https://example.gov.uk/care"]


class TestItRefusesToShipAnEmptyTable:
    def test_no_checks_means_no_file(self):
        """A header row with nothing under it, in a file called `Assumptions.csv`, reads as
        "we checked nothing" — the same trap the empty manifest is guarded against."""
        assert pack_table.render(_dossier([])) == ""


class TestItReadsBothRecordShapes:
    def test_a_replayed_dossier_renders_the_identical_table(self):
        """The backfill rebuilds a `SimpleNamespace` tree from `store/dossiers/<id>.json` whose
        verdicts are plain strings. Every read is duck-typed for that reason."""
        live = _dossier()
        replayed = pack_manifest.dossier_from_dict(live.to_dict())
        assert pack_table.render(replayed) == pack_table.render(live)
