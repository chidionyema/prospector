"""The reading order, its title map, and the seam that hands the assembled read to the gate.

Two registries in bridge.py describe one thing between them: `BUNDLE_READING_ORDER` is the
sequence a buyer reads in, `_SECTION_TITLES` is what each section is CALLED. A section added
to one and not the other fails silently in one of two ways — it renders untitled, or it
vanishes from the read entirely — and neither shows up as an exception anywhere.

The last class is the one that matters most. Five of the fourteen sections (`The_Offer.md`,
`The_Field.md`, `What_Would_Sink_This.md`, `The_Toolkit.md`, `How_To_Know_In_30_Days.md`) are
composed AFTER the four model-written artifacts, so the Q2 lint gate — handed `artifacts` —
graded 9 of 14 and reported the pack clean. `sections_out` is the repair: `_create_bundle`
fills it with the whole assembled read, and `publish_pass` forwards it to `lint_pack`. A test
that proves the registries agree but never proves the late sections ARRIVE would pass on the
broken code, so the fill is exercised against a real `_create_bundle` run.

Fixture pattern (the bridge fixture, the thin dossier, the four full artifacts) is lifted from
test_bundle_index_html.py — including `monkeypatch.chdir(tmp_path)`, which is not cosmetic:
`_create_bundle` writes `publish/bundles/<id>/` relative to the CURRENT WORKING DIRECTORY, and
`publish/` is tracked runtime state in this checkout.
"""
from __future__ import annotations

import pytest

from prospector import (
    pack_bear_case,
    pack_field,
    pack_kicker,
    pack_offer,
    pack_toolkit,
)
from prospector.bridge import (
    BUNDLE_READING_ORDER,
    EngineBridge,
    _SECTION_TITLES,
)
from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict

# The five composed after the four model-written artifacts — the population the Q2 gate could
# not see. Read from the modules rather than typed, so a renamed FILENAME moves this set with
# it instead of leaving a test that quietly checks nothing.
LATE_RENDERED = (
    pack_offer.FILENAME,
    pack_field.FILENAME,
    pack_bear_case.FILENAME,
    pack_toolkit.FILENAME,
    pack_kicker.FILENAME,
)


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class _Cfg:
        entitlements_api_key = ""
        store_payments = {"active_provider": "stripe"}

    return EngineBridge(_Cfg())


def _dossier():
    cand = Candidate(
        candidate_id="c" * 16,
        title="Shellfish Classification Aid",
        one_liner="Scheduling aid for UK oyster farms.",
        market="uk",
        who_pays="owner-operated shellfish farms",
        why_now="new sampling rules",
    )
    check = CheckResult(
        check_name="buyer_intent", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale="Growers search for closure guidance (SAGB, 2025).",
        citations=[], sources=[], queries=[],
    )
    return Dossier(candidate=cand, decision=Decision.PASS, checks=[check],
                   created_at="2026-07-31T00:00:00Z")


def _full_artifacts():
    body = ("## Section\n\nGrounded prose about the opportunity. " * 20)
    return {k: f"# {k}\n\n{body}" for k in
            ("build_spec", "gtm_plan", "ops_plan", "financial_model")}


class TestTheReadingOrderAndTheTitleMapAreOneContract:
    """Neither registry is meaningful alone: the order names files, the map names sections,
    and the pack is the join. Membership is asserted in BOTH directions because the two
    failure modes are different and only one of them is loud."""

    def test_every_section_in_the_reading_order_has_a_title(self):
        missing = [n for n in BUNDLE_READING_ORDER if n not in _SECTION_TITLES]
        assert not missing, (
            f"sections in the reading order with no buyer-visible title: {missing} — "
            "these render untitled in index.html and unnamed in any lint finding")

    def test_every_titled_section_is_in_the_reading_order(self):
        orphans = [n for n in _SECTION_TITLES if n not in BUNDLE_READING_ORDER]
        assert not orphans, (
            f"sections with a title but no place in the read: {orphans} — "
            "a titled section absent from the order silently vanishes from the pack")

    def test_the_two_registries_are_the_same_set(self):
        assert set(BUNDLE_READING_ORDER) == set(_SECTION_TITLES)

    def test_the_reading_order_has_no_duplicates(self):
        dupes = sorted({n for n in BUNDLE_READING_ORDER
                        if BUNDLE_READING_ORDER.count(n) > 1})
        assert not dupes, f"section printed twice in the read: {dupes}"
        assert len(BUNDLE_READING_ORDER) == len(set(BUNDLE_READING_ORDER))


class TestEveryTitleIsSomethingABuyerWouldRead:
    """A title is the only part of a pack everyone reads. The failure this guards is a
    filename leaking through as a title — which is exactly what `_SECTION_TITLES.get(name,
    name)` does by design when a section is missing from the map, so the assertion above and
    this one close the same hole from both ends."""

    def test_titles_are_non_empty_strings(self):
        bad = [k for k, v in _SECTION_TITLES.items()
               if not isinstance(v, str) or not v.strip()]
        assert not bad, f"sections with an empty or non-string title: {bad}"

    def test_no_title_is_a_filename(self):
        leaked = [v for v in _SECTION_TITLES.values()
                  if v.strip().lower().endswith((".md", ".html", ".pdf", ".csv", ".json"))]
        assert not leaked, f"a filename leaked through as a section title: {leaked}"

    def test_no_title_is_just_its_own_filename(self):
        same = [k for k, v in _SECTION_TITLES.items() if v.strip() == k]
        assert not same, f"section titled after its file rather than its content: {same}"

    def test_titles_are_distinct(self):
        """Two sections under one heading is a pack that reads as though it repeats itself,
        and a repetition finding that cannot say which section it came from."""
        titles = list(_SECTION_TITLES.values())
        dupes = sorted({t for t in titles if titles.count(t) > 1})
        assert not dupes, f"two sections share a title: {dupes}"


class TestCreateBundleHandsBackTheAssembledRead:
    """THE WIRING ITSELF — the half a registry test cannot reach.

    `sections_out` is filled after all fourteen sections are composed and after the bear case
    has absorbed the financial model's weakness blocks, i.e. at the last moment the pack
    exists as a whole document rather than as files in a zip. The final test is the point of
    the fix: if the late-rendered sections are absent from the fill, the gate is still
    grading nine of fourteen and every other assertion here passes anyway.
    """

    def test_sections_out_is_filled(self, bridge):
        sections: dict = {}
        bridge._create_bundle(_dossier(), _full_artifacts(), [], sections_out=sections)
        assert sections, "_create_bundle returned the pack but graded nothing"

    def test_it_is_optional_and_the_bundle_still_builds_without_it(self, bridge):
        """The pre-wiring call shape. Every existing caller passes three positionals."""
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        assert path is not None and path.exists()

    def test_every_key_is_a_buyer_visible_title(self, bridge):
        sections: dict = {}
        bridge._create_bundle(_dossier(), _full_artifacts(), [], sections_out=sections)
        stray = sorted(set(sections) - set(_SECTION_TITLES.values()))
        assert not stray, (
            f"the read was graded under keys that are not section titles: {stray} — "
            "a filename fell through `_SECTION_TITLES.get(name, name)`")

    def test_every_section_carries_text(self, bridge):
        sections: dict = {}
        bridge._create_bundle(_dossier(), _full_artifacts(), [], sections_out=sections)
        empty = sorted(k for k, v in sections.items() if not (v or "").strip())
        assert not empty, f"empty sections handed to the linter as graded: {empty}"

    def test_the_keys_are_in_the_reading_order(self, bridge):
        """Same order the buyer gets, so a lint finding names sections in the sequence they
        were read in. Absent sections are skipped, never reordered."""
        sections: dict = {}
        bridge._create_bundle(_dossier(), _full_artifacts(), [], sections_out=sections)
        expected = [_SECTION_TITLES[n] for n in BUNDLE_READING_ORDER
                    if _SECTION_TITLES[n] in sections]
        assert list(sections) == expected

    def test_the_late_rendered_sections_reach_the_gate(self, bridge):
        """THE WHOLE POINT. These five are composed after the four model-written artifacts;
        before 2026-08-15 nothing in pack_linter had ever seen them. A pass here without at
        least one of them present would be worthless, so the assertion names the population
        and fails with the names.

        A thin dossier legitimately omits some of them (`pack_field` and `pack_bear_case`
        return "" with no incumbency sources and nothing refuted), which is why the floor is
        "at least one" rather than all five — the property under test is that the fill
        reaches PAST the four artifacts at all.
        """
        sections: dict = {}
        bridge._create_bundle(_dossier(), _full_artifacts(), [], sections_out=sections)
        late_titles = {_SECTION_TITLES[f] for f in LATE_RENDERED}
        arrived = sorted(late_titles & set(sections))
        assert arrived, (
            "not one of the five late-rendered sections reached the linter's corpus "
            f"(expected any of {sorted(late_titles)}, graded {sorted(sections)}) — "
            "the Q2 gate is still grading 9 of 14")

    def test_the_fill_is_not_just_the_four_model_written_artifacts(self, bridge):
        """The regression stated as a count: the gate used to see the four documents. The
        assembled read is strictly larger."""
        sections: dict = {}
        bridge._create_bundle(_dossier(), _full_artifacts(), [], sections_out=sections)
        assert len(sections) > 4

    def test_a_prefilled_mapping_is_replaced_not_appended_to(self, bridge):
        """`_create_bundle` clears before it fills, so a reused dict cannot smuggle a stale
        section into the corpus of the next pack."""
        sections = {"Stale section from a previous pack": "text that is not in this pack"}
        bridge._create_bundle(_dossier(), _full_artifacts(), [], sections_out=sections)
        assert "Stale section from a previous pack" not in sections
