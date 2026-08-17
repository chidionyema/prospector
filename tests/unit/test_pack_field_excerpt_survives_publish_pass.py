"""A quoted passage must survive the pass that runs over it, or it is not published at all.

WHY THIS FILE EXISTS
--------------------
`pack_field._readable_excerpt` clips an over-long passage and marks the cut with an ellipsis;
`pack_field._passage_block` emits it as `> {quote}`; and since 2026-08-15
`bridge._create_bundle` runs all five late sections through `plain_text.publish_pass_document`
(bridge.py, the `prose_pass_document(body)` line in block 8b-2). That pass treats a trailing
ellipsis as truncation, cuts back to the last sentence terminator inside the line, and returns
"" when there is none -- and a retrieved passage is frequently ONE long sentence.

Measured before the fix, on the 449-character fixture in `test_pack_render_defects.py`:

    len(_readable_excerpt(CUT_PASSAGE)) == 420
    tail                                == 'etitor in this space quietly makes most...'
    publish_pass_document('> ' + quote) == ''

The citation and its link still published, with no passage under them, on a source-or-die
storefront. `test_pack_render_defects.py` pins that a complete quote carries no marker and a
cut one carries exactly one; neither notices that the marked line is then deleted, because
both assert on `pack_field.render` and the deletion happens one call later. This file asserts
on the string the buyer actually reads.
"""
from prospector import pack_field
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict
from prospector.plain_text import publish_pass_document

CIT = "1e62e0c381e1c8d3"
URL = "https://www.socialstorytemplates.com/free"

# One sentence, no internal terminator, over `_MAX_EXCERPT_CHARS` (420). The shape that has no
# earlier sentence end for the publish pass to fall back to -- which is what made the deletion
# total rather than partial.
CUT_PASSAGE = (
    "The catalogue lists printable visual timetables for classrooms and picture cards that "
    "teachers cut out and laminate, alongside a subscription tier that adds a printing "
    "service for schools which want the packs delivered already bound, plus a small "
    "consultancy arm that visits a school for a day and writes the stories with the staff "
    "who will read them, which is the part every competitor in this space quietly makes "
    "most of its money from in practice")
WHOLE_PASSAGE = ("Over 100 free personalisable social stories are available to download, and "
                 "the library is updated every month by the therapists who write them.")
# The same defect arriving from upstream: a passage that reached us already truncated.
PRE_TRUNCATED = (
    "Schools buy the printed packs a term at a time and the therapists who write them say "
    "the classroom sets outsell everything else in the catalogue by a wide margin...")


def _dossier(text):
    src = Source(source_id=CIT, url=URL, text=text)
    chk = CheckResult(check_name="incumbency", verdict=Verdict.SUPPORTED, confidence=0.64,
                      rationale="The passages name three sellers.", citations=[CIT],
                      sources=[src])
    return Dossier(
        candidate=Candidate(candidate_id="8d5e24fbe6c1f5d3", title="StorySprout",
                            one_liner="A picture book that stars one child"),
        checks=[chk], decision=Decision.PASS, reason="Survived all gates.",
        model_version="minimax", created_at="2026-08-01T00:00:00Z")


def _quotes(md: str):
    return [ln for ln in md.splitlines() if ln.lstrip().startswith(">")]


def test_a_cut_excerpt_is_not_deleted_by_the_publish_pass():
    """The whole defect in one assertion: rendered, then gone."""
    quote = pack_field._readable_excerpt(CUT_PASSAGE)
    assert quote
    assert publish_pass_document(f"> {quote}")


def test_the_cut_quote_still_reaches_the_buyer_through_the_rendered_document():
    """Asserted on the document, not on the helper: the pass runs on whole documents, and a
    line that survives in isolation can still be removed in context."""
    published = publish_pass_document(pack_field.render(_dossier(CUT_PASSAGE)))
    assert len(_quotes(published)) == 1
    assert CUT_PASSAGE[:80] in published
    assert URL in published, "a citation with no passage under it is the shipped defect"


def test_the_cut_is_still_declared_after_it_survives():
    """Surviving by dropping the marker would trade a false "truncated" for a false
    "complete" -- the worse lie in a document made of receipts. One ellipsis CHARACTER,
    never the four dots an unconditional slice produces, and the tail is genuinely gone.
    """
    published = publish_pass_document(pack_field.render(_dossier(CUT_PASSAGE)))
    assert published.count("…") == 1
    assert "...." not in published
    assert CUT_PASSAGE[-40:] not in published


def test_a_complete_quote_carries_no_marker_and_is_untouched():
    """The paired case. A quote that was never cut must not claim it was."""
    published = publish_pass_document(pack_field.render(_dossier(WHOLE_PASSAGE)))
    assert f"> {WHOLE_PASSAGE}" in published
    assert "…" not in published and "..." not in published


def test_a_passage_that_arrived_truncated_is_repaired_not_deleted():
    """The same shape from upstream. It is under `_MAX_EXCERPT_CHARS`, so the clip never
    fires and the ellipsis is the source's own -- and it reaches the publish pass identically.
    """
    quote = pack_field._readable_excerpt(PRE_TRUNCATED)
    assert quote and len(quote) < pack_field._MAX_EXCERPT_CHARS + len(quote)
    published = publish_pass_document(f"> {quote}")
    assert published
    assert published.count("…") == 1
    assert "..." not in published, "normalised to one character, whatever shape it arrived in"


def test_the_publish_pass_is_idempotent_over_the_marked_quote():
    """`publish_pass` is idempotent by construction (`tests/unit/test_publish_pass.py`), and a
    backfill re-renders packs already sold: the second pass must produce the identical bytes.
    """
    once = publish_pass_document(pack_field.render(_dossier(CUT_PASSAGE)))
    assert publish_pass_document(once) == once
