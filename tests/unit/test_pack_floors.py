"""Claim-safe pack floors — no invented numbers, listing never empty stub."""
from __future__ import annotations

import re

from prospector.models import Candidate, CheckResult, Verdict
from prospector.pack_floors import (
    claim_safe_marketing,
    ensure_marketing_floor,
    exec_summary_md,
    first_week_checklist_md,
)
from prospector.plain_text import publish_pass_document


def test_claim_safe_marketing_uses_only_dossier_fields():
    cand = Candidate(
        title="Shellfish Window",
        one_liner="Lease closure forecast for growers",
        who_pays="Independent shellfish farmers",
    )
    checks = [
        CheckResult("buyer_intent", Verdict.SUPPORTED, 0.9, "Search demand exists"),
        CheckResult("legality", Verdict.UNVERIFIABLE, 0.0, "silence"),
    ]
    m = claim_safe_marketing(cand, checks)
    assert m[0]["type"] == "listing_page"
    copy = m[0]["copy"]
    assert "Shellfish Window" in copy
    assert "Search demand exists" in copy
    assert "TAM" not in copy
    assert "£" not in copy or "£30" not in copy  # no invented price claims
    assert "silence" not in copy  # unverifiable rationale excluded


def test_ensure_marketing_floor_fills_empty():
    cand = Candidate(title="X", one_liner="Y")
    out = ensure_marketing_floor([], cand, [])
    assert any(p.get("type") == "listing_page" and p.get("copy") for p in out)


def test_ensure_marketing_floor_keeps_existing_listing():
    cand = Candidate(title="X", one_liner="Y")
    existing = [{"type": "listing_page", "copy": "Real listing copy from content_gen"}]
    out = ensure_marketing_floor(existing, cand, [])
    assert out[0]["copy"] == "Real listing copy from content_gen"


def test_exec_summary_and_checklist_non_empty():
    cand = Candidate(title="Pack", one_liner="One line", who_pays="SMEs")
    assert "Pack" in exec_summary_md(cand, [])
    assert "First-week" in first_week_checklist_md(cand)
    assert "SMEs" in first_week_checklist_md(cand)


class TestExecSummaryOpensInNewspaperOrder:
    """The first page is now genuinely first (bridge.py reads in BUNDLE_READING_ORDER; that
    constant was called BUNDLE_FILES until 2026-08-15, when the read order and the archive
    became two different lists), so what it opens with is a product decision rather than a
    cosmetic one.

    WHAT THIS CLASS USED TO PIN, AND WHY IT NO LONGER DOES
    -----------------------------------------------------
    It was `TestExecSummaryOpensWithSomethingToDo`, and it asserted three strings:
    "Somebody is already dealing with this", "## Why this is a business" and "## Before you
    go further". None of them is emitted any more, and their removal was the product decision,
    not a refactor — so pinning them was pinning a shape the founder had already rejected.
    A test that fails for that reason is stale, and updating it means pinning what replaced
    it, not deleting the assertion.

    Two of the three went for stated reasons, recorded in `pack_floors.exec_summary_md`:

      * "Somebody is already dealing with this:" was a demonstrative with no antecedent as the
        pack's first sentence — `this` pointed at the title three lines up. The one-liner is
        the standfirst now, so the lede has something to point at and names the person instead
        of announcing that a person exists.
      * "Before you go further" told the buyer to spend ten minutes opening our sources and
        checking the claims matched. The founder's reading, 2026-08-15: "we are asking the
        user to do our own work after purchasing". Verification is what the pack IS. The
        GUARANTEE survives — the refund sentence below is the one thing from that block that
        had to — but it is stated as our commitment rather than as their homework.

    So what is guarded here is the ORDER that replaced it, which is the newspaper order: what
    this is, then who is living with it, then what we found, then the housekeeping. Order is
    the assertion worth keeping because it is the thing that can silently regress — every
    individual sentence is visible in a diff, and their sequence is not.
    """

    def test_the_pack_says_what_it_is_before_it_says_anything_else(self):
        cand = Candidate(title="Pack", one_liner="One line", who_pays="SMEs")
        md = exec_summary_md(cand, [])
        standfirst = md.index("**One line**")
        lede = md.index("The person already paying for this problem")
        findings = md.index("## What we found")
        housekeeping = md.index("Every claim in this pack names the page it came from")
        assert standfirst < lede < findings < housekeeping, (
            "the newspaper order is the product decision here: a reader who has been told who "
            "is suffering, or handed the housekeeping, before being told what the business IS "
            "has been given a chore or a puzzle rather than a story")

    def test_the_buyer_is_no_longer_asked_to_do_our_verification_for_us(self):
        """The deleted block, pinned as deleted.

        It is not enough that the strings are gone: the reason they went is that the pack must
        not open by handing a paying reader a ten-minute audit task. A later edit that restores
        the block under a different heading would be the same defect, so this asserts the
        SHAPE — a first-person instruction to go and check our sources — rather than the exact
        wording it happened to use.
        """
        md = exec_summary_md(Candidate(title="Pack", one_liner="One", who_pays="SMEs"), [])
        assert "## Before you go further" not in md
        assert "Start here" not in md
        assert "the next ten minutes" not in md.lower()
        # The guarantee is the half that survived, and it survives as a promise we make.
        assert "that is a refund, not an argument" in md

    def test_it_points_at_somewhere_that_exists_in_what_the_buyer_downloaded(self):
        """Was `test_it_points_at_a_real_file_in_the_bundle`, and it guards the same thing it
        always did: a first instruction that sends the buyer to something the download does not
        contain is worse than no instruction at all. Only the definition of "exists" changed.

        This one caught a REAL defect on 2026-08-15 rather than going stale. The opening block
        said "1. Open **QA_Report.md**" and "**05_First_Week_Checklist.md** is what to do once
        it checks out" — and the archive stopped containing any `.md` at all that day, so the
        pack's very first page named two files the buyer does not have. `pack_floors.py` now
        interpolates SECTION titles (`QA_SECTION`, `CHECKLIST_SECTION`), which are headings in
        index.html and in the PDF, i.e. places that do exist.

        Those two constants are duplicated in `pack_floors` rather than imported from `bridge`,
        because `bridge` imports `pack_floors` and an import cycle on the money rail is not
        worth the DRY. Duplication is only safe while something holds the two copies equal, so
        that is asserted here first — this test is the reason the duplication is allowed.
        """
        import re

        from prospector import pack_floors
        from prospector.bridge import _SECTION_TITLES

        assert pack_floors.QA_SECTION == _SECTION_TITLES["QA_Report.md"]
        assert pack_floors.CHECKLIST_SECTION == _SECTION_TITLES["05_First_Week_Checklist.md"]

        md = exec_summary_md(Candidate(title="Pack", one_liner="One"), [])
        assert re.findall(r"\b[\w/]+\.md\b", md) == [], (
            "the first page named a markdown file; no .md reaches the buyer's zip any more")
        assert pack_floors.QA_SECTION in md
        assert pack_floors.CHECKLIST_SECTION in md

    def test_it_tells_the_buyer_to_refund_us_if_the_source_does_not_check_out(self):
        # The instruction has to survive somebody later deciding it is bad for conversion.
        # It is the reason the block is credible: an opening step that could only ever
        # flatter us would not be a check, it would be an onboarding flow.
        md = exec_summary_md(Candidate(title="Pack", one_liner="One"), [])
        assert "refund" in md.lower()

    def test_the_payer_line_appears_only_when_the_dossier_has_one(self):
        with_payer = exec_summary_md(
            Candidate(title="Pack", one_liner="One", who_pays="owner-operated oyster farms"), []
        )
        assert "owner-operated oyster farms" in with_payer

        without = exec_summary_md(Candidate(title="Pack", one_liner="One"), [])
        # Absent means absent — no generic "identify your customer" filler standing in for a
        # field the dossier never verified. The whole payer scaffolding goes with it, not just
        # the value: a lede that announces a person and then does not name one is worse than
        # no lede.
        assert "The person already paying for this problem" not in without
        assert "They are not waiting for a product" not in without
        # The rest of the document is still there, so this is an omission and not a collapse.
        assert "## What we found" in without
        assert "that is a refund, not an argument" in without

    def test_it_still_invents_nothing(self):
        md = exec_summary_md(Candidate(title="Pack", one_liner="One", who_pays="SMEs"), [])
        # Scoped to this DOCUMENT and deliberately not widened. The whole-pack version of this
        # assertion is the one to avoid: sections further down contain "TAM" and "guaranteed"
        # precisely because they are DISCLAIMING them — a standing reminder that a bare keyword
        # scan cannot tell a claim from its negation. The executive summary makes no such
        # disclaimer, so here the bare scan is sound and covers the whole file.
        for invented in ("guaranteed", "TAM", "you will earn", "risk-free", "proven to"):
            assert invented.lower() not in md.lower()


class TestTheHeadingCountsTheBulletsTheBuyerCanSee:
    """"## What we found — N things that hold up", and then the buyer counts them.

    The number interpolated the count of SUPPORTED CHECKS while the list under it was capped
    at four, so six supported checks printed a promise of six over four bullets. That is the
    pack miscounting itself on the first page a buyer opens, in the five minutes when a refund
    gets decided, and it is the kind of defect a reader finds instantly and we never would.

    The second source of the same drift is invisible in this file's own output: every pack
    document is run through `plain_text.publish_pass_document` in `bridge._create_bundle`, and
    that pass DELETES any line it empties out. A rationale written as one 681-character
    sentence used to be clipped to an ellipsis here, counted by the heading, and then deleted
    by the publish pass — "2 things that hold up" above one bullet, with nothing in this
    module's output to show for it. So the assertions below are made against the PUBLISHED
    document as well as the raw one; the raw-only version of this test passes on the bug.
    """

    @staticmethod
    def _counted_and_printed(md: str) -> tuple:
        """`(number in the heading, bullets actually under it)`, either as None/0 if absent."""
        promised = None
        printed = 0
        for line in md.splitlines():
            match = re.match(r"^## What we found — (\d+) thing", line)
            if match:
                promised = int(match.group(1))
            elif line.startswith("- **"):
                # `- **<question>** <finding>`. The "could not settle" list below is `- <q>`
                # with no bold, so it cannot be counted here by accident.
                printed += 1
        return promised, printed

    def test_six_supported_checks_do_not_promise_more_bullets_than_the_cap_prints(self):
        checks = [CheckResult(name, Verdict.SUPPORTED, 0.9, f"Finding {i} holds.")
                  for i, name in enumerate(("pain_reality", "value_durability", "incumbency",
                                            "payer_solvency", "distribution", "legality"))]
        md = exec_summary_md(Candidate(title="Pack", one_liner="One"), checks)
        promised, printed = self._counted_and_printed(md)
        assert promised == printed == 4, (
            "the cap is a product choice and may move; the heading agreeing with it is not")

    def test_a_rationale_the_publish_pass_deletes_is_not_counted(self):
        """The 681-character single sentence, which is what the live defect was.

        `_whole_sentences` used to hand it to `clip_to_sentence`, which marks the cut with an
        ellipsis; `publish_pass` then finds no sentence terminator inside the line and returns
        "", so `publish_pass_document` drops the whole bullet. The count was taken before
        that happened.
        """
        long_sentence = "The market for " + "shellfish lease closure forecasting " * 20 + "is it"
        assert len(long_sentence) > 600 and "." not in long_sentence
        checks = [
            CheckResult("pain_reality", Verdict.SUPPORTED, 0.9, long_sentence),
            CheckResult("legality", Verdict.SUPPORTED, 0.9, "Nothing bars the sale."),
        ]
        md = exec_summary_md(Candidate(title="Pack", one_liner="One"), checks)
        assert self._counted_and_printed(md) == (1, 1)
        # And the same after the pass that actually reaches the buyer.
        assert self._counted_and_printed(publish_pass_document(md)) == (1, 1)
        assert "shellfish lease closure forecasting" not in md

    def test_one_finding_is_not_announced_as_one_things(self):
        md = exec_summary_md(
            Candidate(title="Pack", one_liner="One"),
            [CheckResult("legality", Verdict.SUPPORTED, 0.9, "Nothing bars the sale.")])
        assert "## What we found — 1 thing that holds up" in md

    def test_supported_checks_with_nothing_quotable_are_not_called_unconfirmed(self):
        """The branch that replaced the arithmetic, and the reason it is not one line.

        Making the heading count the bullets is trivial; the honest handling of "there were
        supported checks but none of them is printable" is not. Falling through to the
        no-evidence copy would tell the buyer nothing came back confirmed when six things did,
        which on a source-or-die storefront is the worse of the two defects.
        """
        checks = [CheckResult("pain_reality", Verdict.SUPPORTED, 0.9, ""),
                  CheckResult("legality", Verdict.SUPPORTED, 0.9, "")]
        md = exec_summary_md(Candidate(title="Pack", one_liner="One"), checks)
        assert "Nothing here came back confirmed" not in md
        assert "2 of the checks behind this pack came back supported" in md
        assert self._counted_and_printed(md) == (None, 0)
