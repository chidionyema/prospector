"""The four rendering defects the founder found by reading a live pack (2026-08-14).

Every one of these shipped on the £49.99 product, in the documents whose entire job is to
show receipts, and each was invisible to the existing suite because the suite tested the
functions in isolation and nothing asserted on the rendered page a buyer sees.

Census across the 62 live packs on R2 (`tools/pack_defect_census.py`): blank pack id 62/62,
bare-comma sources 52/62, mid-word truncation 62/62, internal judge chain shown 52/62.

Source pack for every literal below: `store/dossiers/8d5e24fbe6c1f5d3.pass.json`
("StorySprout", £49.99, `side_hustle`, us, verified 2026-08-01).
"""
import re

import pytest

from prospector import dossier as dz
from prospector import plain_text as pt
from prospector import trimming
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict

# The two real citation ids from that dossier, verified on disk.
CIT_A, CIT_B = "1e62e0c381e1c8d3", "8299842c5162c176"


# --- (b)+(c) one bug: a deliberately quoted id was stripped as if it had leaked ----------

def test_a_quoted_id_survives_the_prose_id_stripper():
    """`_BARE_ID.sub(" ", "`<id>`")` used to return "` `" — an empty code span.

    Downstream that renders as nothing, which is why `Sources used:` printed bare commas
    and `Candidate ID:` printed blank on all 62 packs.
    """
    out = pt._strip_ids(f"**Sources used:** `{CIT_A}`, `{CIT_B}`")
    assert CIT_A in out and CIT_B in out
    assert "` `" not in out


def test_an_id_that_leaked_into_prose_is_still_stripped():
    """The exemption must be for QUOTED ids only, or the stripper stops doing its job."""
    assert CIT_A not in pt._strip_ids(f"The passages {CIT_A} directly show demand.")


def test_the_exemption_holds_through_the_whole_publish_pass():
    """`publish_pass` runs the register denylist and tidy after `_strip_ids`.

    Testing `_strip_ids` alone would let a later rule re-break it — which is exactly how
    this survived: the unit under test was never the string the buyer reads.
    """
    assert CIT_A in pt.publish_pass(f"Sources used: `{CIT_A}`")


# --- (a) truncation at an abbreviation ---------------------------------------------------

@pytest.mark.parametrize("abbrev", ["U.S.", "U.K.", "Inc.", "e.g.", "Dr.", "approx."])
def test_an_abbreviation_does_not_end_a_sentence(abbrev):
    text = f"A 2025 report puts autism at 1 in 31 {abbrev} children and rising. Next."
    ends = [m.start() for m in trimming._SENTENCE_END.finditer(text)]
    assert text.index(abbrev) + len(abbrev) - 1 not in ends, f"{abbrev} read as a full stop"


def test_the_exec_summary_line_the_founder_read_is_no_longer_cut_at_us():
    """Verbatim from the shipped pack: the sentence stopped dead at `U.S.`"""
    text = ("A 2025 report puts autism at 1 in 31 U.S. children, which the pack uses to "
            "size the market. That figure is prevalence, not demand.")
    assert not trimming.clip_to_sentence(text, 120).endswith("U.S.")


def test_a_real_sentence_end_still_cuts():
    """The guard must not disable the splitter — that would trade one defect for another.

    The first sentence has to occupy most of the budget: `_KEEP_RATIO` deliberately refuses
    a boundary that would throw away more than 40% of the allowance.
    """
    text = "The incumbent is entrenched and has been for a decade. " + "x" * 200
    assert trimming.clip_to_sentence(text, 70) == (
        "The incumbent is entrenched and has been for a decade.")


# --- fixtures for the rendered document --------------------------------------------------

def _check(name, verdict, citations=(), sources=()):
    return CheckResult(check_name=name, verdict=verdict, confidence=0.64,
                       rationale="The passages say so.", citations=list(citations),
                       sources=list(sources))


def _dossier(checks, decision=Decision.PASS, model_version="fallback(cursor_cli+minimax)"):
    return Dossier(
        candidate=Candidate(candidate_id="8d5e24fbe6c1f5d3", title="StorySprout",
                            one_liner="A picture book that stars one child"),
        checks=checks, decision=decision, reason="Survived all gates; composite 2.6500.",
        model_version=model_version, created_at="2026-08-01T00:00:00Z")


SRC = Source(source_id=CIT_A, url="https://www.socialstorytemplates.com/free",
             text="Over 100 free personalisable social stories.")


# --- P0(7) the banner claimed a pass the lane never granted ------------------------------

def test_the_banner_states_the_split_when_a_check_came_back_against_it():
    """`8d5e24fbe6c1f5d3` printed "This cleared every check we hold it to" three screens
    above "❌ Is the problem real? No — the sources contradict this"."""
    md = dz.render_markdown(_dossier([
        _check("pain_reality", Verdict.REFUTED),
        _check("buyer_intent", Verdict.SUPPORTED),
        _check("legality", Verdict.SUPPORTED),
    ]))
    assert "cleared every" not in md
    assert "Passed 2 of 3 checks" in md
    assert "came back against it" in md


def test_an_unverifiable_check_is_not_counted_as_a_pass():
    md = dz.render_markdown(_dossier([
        _check("pain_reality", Verdict.SUPPORTED),
        _check("claim_check", Verdict.UNVERIFIABLE),
    ]))
    assert "Passed 1 of 2 checks" in md
    assert "could not be settled either way" in md


def test_a_clean_sweep_may_still_say_so():
    """The fix is truth, not blanket hedging: a pack that really did clear everything
    must not be made to sound worse than it is."""
    md = dz.render_markdown(_dossier([_check("legality", Verdict.SUPPORTED)]))
    assert "cleared every one of the 1 checks" in md


def test_the_banner_survives_the_loader_that_leaves_verdicts_as_strings():
    """Two loader shapes reach this renderer; a banner that counts zero on one of them
    would silently print the old lie on that path."""
    d = _dossier([_check("pain_reality", Verdict.REFUTED),
                  _check("legality", Verdict.SUPPORTED)])
    for chk in d.checks:
        chk.verdict = chk.verdict.value  # the `pack_manifest` shape
    assert "Passed 1 of 2 checks" in dz.render_markdown(d)


# --- (b) sources must be openable, (d) the judge chain must not be shown ------------------

def test_sources_used_renders_a_link_the_buyer_can_open():
    md = dz.render_markdown(_dossier([
        _check("pain_reality", Verdict.SUPPORTED, [CIT_A], [SRC])]))
    assert "[socialstorytemplates.com](https://www.socialstorytemplates.com/free)" in md
    assert CIT_A not in md.split("## Run details")[0], "a raw passage id is not a receipt"


def test_no_sources_line_is_ever_only_separators():
    """The exact defect string: `Sources used: , , , , , ,`"""
    md = dz.render_markdown(_dossier([
        _check("pain_reality", Verdict.SUPPORTED, [CIT_A, CIT_B], [SRC])]))
    for line in md.splitlines():
        if line.startswith("**Sources used:**"):
            assert line.replace("**Sources used:**", "").strip(" ,")


def test_an_unresolvable_citation_keeps_its_id_rather_than_vanishing():
    """This is an audit document. An ugly pointer beats a missing one."""
    md = dz.render_markdown(_dossier([
        _check("pain_reality", Verdict.SUPPORTED, ["deadbeefdeadbeef"], [])]))
    assert "deadbeefdeadbeef" in md


def test_the_same_url_cited_twice_is_listed_once():
    dup = Source(source_id=CIT_B, url="https://www.socialstorytemplates.com/free", text="x")
    md = dz.render_markdown(_dossier([
        _check("pain_reality", Verdict.SUPPORTED, [CIT_A, CIT_B], [SRC, dup])]))
    line = next(x for x in md.splitlines() if x.startswith("**Sources used:**"))
    # Count links, not domain mentions: the host appears in BOTH the label and the href of a
    # single markdown link, so a substring count reads 2 for one correctly-deduped entry.
    assert line.count("](") == 1


def test_the_source_appendix_is_headed_by_the_site_not_our_internal_key():
    """It read `### Source [1e62e0c381e1c8d3]` — our database key, printed as if it were a
    citation, in the section titled "Every source we used"."""
    md = dz.render_markdown(_dossier([
        _check("pain_reality", Verdict.SUPPORTED, [CIT_A], [SRC])]))
    assert "### 1. socialstorytemplates.com" in md
    assert f"Source [{CIT_A}]" not in md


def test_a_quote_that_was_never_truncated_is_not_marked_as_truncated():
    """The appendix appended `...` unconditionally to a 500-char slice, so a complete
    47-character quote shipped as `social stories....` — four dots and a false claim."""
    md = dz.render_markdown(_dossier([
        _check("pain_reality", Verdict.SUPPORTED, [CIT_A], [SRC])]))
    assert "> Over 100 free personalisable social stories." in md
    assert "stories...." not in md


def test_the_buyer_is_never_shown_the_internal_operator_chain():
    """Shipped on 52 of 62 packs: `Judged by: fallback(cursor_cli+claude_cli+minimax)` —
    naming a failover chain, calling it a fallback, and citing an operator deleted from
    this repo on 2026-08-06."""
    md = dz.render_markdown(_dossier([_check("legality", Verdict.SUPPORTED)]))
    assert "Judged by" not in md
    assert "fallback(" not in md
    assert "cursor_cli" not in md and "minimax" not in md


def test_the_pack_reference_is_present_and_populated():
    """It rendered as `Candidate ID:` followed by nothing on all 62 packs."""
    md = dz.render_markdown(_dossier([_check("legality", Verdict.SUPPORTED)]))
    assert re.search(r"\*\*Pack reference:\*\*\s+`8d5e24fbe6c1f5d3`", md)
