"""The engine's own filing system, and how it gets out of the buyer's zip.

FOUNDER, 2026-08-15, on a pack downloaded from the live storefront: "it has engine ifo like
conposite score etc and even ai judge info". Three separate leaks were found behind that one
sentence, in three different files, and this module pins all three together because they are
one defect — our grade of the idea, and the identity of the model that graded it, shipped to
the person who bought the idea.

  1. `pack_data`      scorecard.json / scorecard.csv / scorecard_radar.svg — our six-axis
                      grading, with weights and weighted contributions, as data files.
  2. `pack_manifest`  prospector:compositeScore, prospector:scores, prospector:providerChain,
                      prospector:provisional, prospector:ruledBy — in manifest.jsonld.
                      Pinned in `test_pack_manifest.py`, next to the flags that STAY.
  3. `pack_linter`    the engine quoting its own scoresheet in the prose, which no check had
                      ever read: `INTERNAL_VOCAB` grades six shelf lines and stops there.

WHY THE SCOPE OF (3) IS THE INTERESTING PART. The obvious fix — grade the body against the
shelf's word list — was measured first and rejected on the numbers. Across 296 live buyer
documents (427,687 words) a loose list scored 461 hits for "composite/score" alone, and the
first five examples were all false positives: "aluminum composite" in a signage build spec, a
council "pre-screening addresses", "adversarial" describing a marketing tone, "churn signal",
"no grounding in specific search volume". The narrow list in `BODY_ENGINE_TOKENS` scores 18 on
the same corpus with no false positive, so the tests below assert the false positives stay
quiet as hard as they assert the real ones fire.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from prospector import dossier as dz
from prospector import pack_data
from prospector.models import (
    Candidate,
    CheckResult,
    Decision,
    Dossier,
    ScoreResult,
    Source,
    Verdict,
)
from prospector.pack_linter import (
    BODY_ENGINE_PHRASES,
    BODY_ENGINE_TOKENS,
    INTERNAL_VOCAB,
    check_engine_leak,
)

REPO = Path(__file__).resolve().parents[2]


def _severities(problems):
    return {p["severity"] for p in problems}


class TestTheEngineQuotingItsOwnScoresheet:
    """The 18 real hits on the live corpus all have one shape: a check name and its
    confidence number, printed in a document written for a buyer."""

    # Verbatim from store/dossiers/0c6c74267f7485a3.pass.json :: financial_model.
    LIVE_LEAK = (
        "The margin is not proven, and no verified claim speaks to it. The confidence "
        "scores on the supporting checks are low (value_durability 0.438, distribution "
        "0.430), and nothing retrieved demonstrates that spill events plus rainfall "
        "predict the outcome."
    )

    def test_the_live_leak_is_caught(self):
        problems = check_engine_leak({"financial_model": self.LIVE_LEAK})
        assert problems, "the exact sentence this check was written for went unreported"
        assert any("value_durability" in p["detail"] for p in problems)

    def test_it_names_the_document_the_buyer_opens(self):
        """A finding a reviewer cannot act on is a finding they will not act on: the pack has
        fourteen sections and 'somewhere in the pack' is not a location."""
        problems = check_engine_leak({"The numbers": self.LIVE_LEAK})
        assert [p["where"] for p in problems] == ["The numbers"]

    @pytest.mark.parametrize("text", [
        "Sources: verified claim value_durability — Street Trading Act 1982.",
        "The payer_solvency check itself returned nothing on unpaid carers.",
        "Our composite score for this idea sits mid-table.",
        "It was cleared by an AI judge before publication.",
        "The provider chain ran minimax first.",
        "This one is a hard fail on the second gate.",
        "Ruled unverifiable, so treat the figure as indicative.",
    ])
    def test_every_shape_of_the_leak(self, text):
        assert check_engine_leak({"gtm_plan": text}), text


class TestTheFalsePositivesThatKilledTheLooseList:
    """Each string below is verbatim from a live pack and is CORRECT English about a real
    business. A check that flagged these would be switched off within a week, and the
    threshold it was measuring would never be set."""

    @pytest.mark.parametrize("text", [
        "Material: exterior-grade aluminum composite or acrylic for outdoor signs.",
        "A council simplifies its process or starts pre-screening addresses.",
        'Not "catch your ex hiding money" (adversarial, promises an outcome we cannot '
        "guarantee) but a process the buyer controls.",
        "You need churn signal to know whether the forecast is real.",
        "Customer ramp has no grounding in specific search volume or conversion data.",
        "The verdict that determines whether stock is sellable arrives after the sample "
        "is tested.",
        "Kill-or-continue gate: if the historical relationship does not hold, stop.",
        "BadgeBack builds that second-look case: a short, referenced dossier.",
        "Social-media distribution to the target audience is feasible and cheap.",
        "A risk score, a recommended action, and a frozen snapshot of every input.",
        "The table carries a travel_time_hours_estimate and a confidence enum.",
    ])
    def test_ordinary_business_english_is_left_alone(self, text):
        assert check_engine_leak({"build_spec": text}) == [], text

    def test_the_two_lists_are_deliberately_different(self):
        """If the body list ever becomes the shelf list, this check starts crying wolf at
        roughly 25x its true rate and the measured baseline stops meaning anything."""
        assert BODY_ENGINE_TOKENS != INTERNAL_VOCAB
        for loose in ("candidate", "candidates", "signal", "gate", "check", "moat",
                      "wedge", "lens", "score", "composite", "distribution",
                      "incumbency", "legality", "grounding", "dossier"):
            assert loose not in BODY_ENGINE_TOKENS, (
                f"{loose!r} is an ordinary word in 5,800 words of business prose")

    def test_every_phrase_is_multi_word_on_purpose(self):
        """Each phrase exists because its individual words are innocent — 'composite' is a
        material, 'chain' is a chain of shops, 'judge' is a person, 'fail' is a test."""
        for phrase in BODY_ENGINE_PHRASES:
            assert " " in phrase or "-" in phrase, phrase


class TestTheActuatorIsShadowFirst:
    """Same convention as every other rate check here, and for one extra reason: this check
    is new, so its false-positive rate is known from one corpus and nothing else."""

    def test_it_only_warns_by_default(self):
        problems = check_engine_leak(
            {"financial_model": TestTheEngineQuotingItsOwnScoresheet.LIVE_LEAK})
        assert _severities(problems) == {"warning"}

    def test_it_blocks_when_told_to(self):
        problems = check_engine_leak(
            {"financial_model": TestTheEngineQuotingItsOwnScoresheet.LIVE_LEAK},
            block=True)
        assert _severities(problems) == {"error"}

    def test_a_zero_ceiling_measures_and_never_fires(self):
        """0.0 is 'measure only', not 'block everything above zero'. Getting this backwards
        is how a shadow-first knob unlists a catalogue on the day it ships."""
        text = " ".join(["word"] * 400) + " value_durability 0.4"
        rate_findings = [p for p in check_engine_leak({"x": text}, max_per_1k=0.0)
                         if p["where"] == "pack"]
        assert rate_findings == []

    def test_the_rate_fires_once_a_ceiling_exists(self):
        text = " ".join(["word"] * 100) + " value_durability 0.4"
        rate_findings = [p for p in check_engine_leak({"x": text}, max_per_1k=1.0)
                         if p["where"] == "pack"]
        assert len(rate_findings) == 1
        assert "per 1,000 words" in rate_findings[0]["detail"]

    def test_an_empty_corpus_is_not_a_pass(self):
        assert check_engine_leak(None) == []
        assert check_engine_leak({}) == []


class TestOurGradeStaysOutOfTheZip:
    """`scorecard.json` was the single biggest leak measured: 325 engine-vocabulary hits
    across 74 live PASS dossiers, more than every prose document in the pack combined."""

    @staticmethod
    def _cfg(**pack_data_overrides):
        block = {"enabled": True, "formats": ["json", "csv", "svg"]}
        block.update(pack_data_overrides)
        return SimpleNamespace(pack_data=block, weights={})

    @staticmethod
    def _dossier():
        candidate = SimpleNamespace(title="A pack", tags={}, one_liner="")
        return SimpleNamespace(candidate=candidate, score=None, sources=[])

    def test_the_scorecard_files_do_not_ship(self):
        out = pack_data.build_text_artifacts(self._dossier(), self._cfg())
        assert pack_data.SCORECARD_JSON not in out
        assert pack_data.SCORECARD_CSV not in out
        assert pack_data.RADAR_SVG not in out

    def test_what_the_buyer_paid_for_still_ships(self):
        """The rule is not 'data files are bad'. The financial model is the buyer's own
        model and the comparables are what other people already charge: both are the
        product. Our ranking of their purchase is not."""
        out = pack_data.build_text_artifacts(self._dossier(), self._cfg())
        assert pack_data.FINANCIAL_JSON in out
        assert pack_data.FINANCIAL_CSV in out
        assert pack_data.COMPARABLES_JSON in out
        assert pack_data.COMPARABLES_CSV in out

    def test_it_is_a_knob_and_not_a_deletion(self):
        out = pack_data.build_text_artifacts(
            self._dossier(), self._cfg(include_scorecard=True))
        assert pack_data.SCORECARD_JSON in out
        assert pack_data.RADAR_SVG in out

    def test_the_default_is_off_even_with_no_config_at_all(self):
        """A stale config must behave as 'do not ship our grade', not as the old behaviour.
        The whole defect was that the old behaviour looked deliberate."""
        assert pack_data.settings(None)["include_scorecard"] is False
        assert pack_data.DEFAULT_INCLUDE_SCORECARD is False


class TestOurScoresheetStaysOutOfTheQaReport:
    """The FOURTH leak, and the largest of the four in words on the page.

    `bridge.py:1795` renders `dossier.render_markdown(dossier)` straight into `QA_Report.md`
    inside the pack zip. That document carried a `## How it scored` table — our composite to
    four decimal places, then six internal axis names with weighted marks out of five — and a
    `## Why this passed` block that reprinted `Survived all gates; composite 3.6500; ...`.
    Both are our ranking of the idea against candidates the buyer will never see, on a scale
    nobody explained to them. The evidence (checks, verdicts, confidences, every source)
    stays: the store's proposition is that the checks are real and published.
    """

    @staticmethod
    def _dossier(decision=Decision.PASS, reason="Survived all gates; composite 3.6500; "
                                                "5 grounded-supported check(s) "
                                                "(moat grounded: 2)."):
        checks = [CheckResult(
            check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.7,
            rationale="Fleets file the reclaim by hand.", citations=["s1"],
            sources=[Source(source_id="s1", url="https://www.gov.uk/x", text="p")],
        )]
        return Dossier(
            candidate=Candidate(title="A thing", one_liner="It does a thing."),
            checks=checks, decision=decision, reason=reason,
            score=ScoreResult(
                scores={"pain_acuity": 4, "value_durability": 3},
                justification={"pain_acuity": "It hurts weekly."},
                composite=3.6500),
            created_at="2026-08-01T00:00:00+00:00",
        )

    def test_the_scores_table_is_gone_from_the_buyers_copy(self):
        md = dz.render_markdown(self._dossier())
        assert "How it scored" not in md
        assert "3.6500" not in md
        assert "/5" not in md

    def test_the_internal_axis_names_go_with_it(self):
        """The table was also the only place `value_durability` reached a buyer as a label
        rather than as prose, which is why `check_engine_leak` alone would not have caught
        it: the linter reads the assembled SECTIONS, and QA_Report.md is not one of them."""
        md = dz.render_markdown(self._dossier())
        assert "value_durability" not in md

    def test_the_pass_reason_keeps_its_sentence_and_loses_the_number(self):
        md = dz.render_markdown(self._dossier())
        assert "Why this passed" in md
        assert "grounded-supported check(s)" in md, "the scrub ate the whole sentence"
        assert "composite" not in md.lower()

    def test_a_kill_reason_that_opens_on_the_number_still_reads_as_english(self):
        """The KILL forms START with it: 'Composite 2.9500 cleared the bar but ...'. A scrub
        that only deleted would ship a sentence beginning mid-word."""
        md = dz.render_markdown(self._dossier(
            decision=Decision.KILL,
            reason="Composite 2.9500 cleared the bar but no publish-critical check was "
                   "grounded-supported."))
        assert "Cleared the bar but no publish-critical" in md
        assert "2.9500" not in md

    def test_the_operator_still_sees_everything(self):
        """`vet --show` is the command you run to decide whether the engine ruled sensibly.
        Hiding the composite THERE would be hiding it from the only person it is for."""
        md = dz.render_markdown(self._dossier(), include_our_grade=True)
        assert "How it scored" in md
        assert "3.6500" in md

    def test_the_evidence_is_not_what_we_removed(self):
        """If this ever fails, the fix went too far: we sell the checks.

        What the report prints per check is the verdict, the confidence, the sources and the
        passages we quoted from them — not the model's `rationale` string, which has never
        been rendered here and is not what this commit touched.
        """
        md = dz.render_markdown(self._dossier())
        assert "Is the problem real?" in md          # the check, by its buyer-facing name
        assert "Confidence 0.70" in md               # the number that IS about the evidence
        assert "https://www.gov.uk/x" in md          # the source, followable
        assert "Every source we used" in md          # and the full appendix

    def test_the_buyers_caller_takes_the_default(self):
        """A default that has to be remembered is how this shipped to 145 live products."""
        src = (REPO / "prospector" / "bridge.py").read_text()
        assert "render_markdown(dossier), keep_confidence_figures=True" in src, (
            "bridge.py now passes something to render_markdown — check it is not "
            "include_our_grade=True")


class TestTheDecisionIsDeclaredInConfig:
    """Founder directive: params live in config, not in a source edit. A reader who wants to
    know whether a buyer sees our score reads config.yaml, not two Python modules."""

    @staticmethod
    def _cfg():
        return yaml.safe_load((REPO / "config.yaml").read_text())

    def test_the_scorecard_is_switched_off_on_disk(self):
        assert self._cfg()["pack_data"]["include_scorecard"] is False

    def test_the_new_lint_knobs_are_declared_and_shadow_first(self):
        listing = self._cfg()["listing"]
        assert listing["engine_leak_block"] is False
        assert float(listing["max_engine_leak_per_1k"]) == 0.0
