"""The incumbency rationale has exactly one owner, and the pointer to it cannot dangle.

WHY THIS FILE EXISTS
--------------------
`pack_field.render` splits on the incumbency verdict (`pack_field.py`, the block above
`verdict_owned_here`): on `supported` it prints the rationale itself, and on `refuted` or
`unverifiable` it hands the paragraph to **What would sink this** and prints a pointer. The
split is what makes the same paragraph shipping in two documents impossible rather than
merely unlikely -- it was two of the six findings `pack_linter.check_repetition` blocked on.

Nothing pinned the other half of it. `bridge._create_bundle` guards each of the five late
renderers INDIVIDUALLY and on purpose (bridge.py:1789) -- "one that fails costs the pack that
section and nothing else" -- so `pack_bear_case.render` raising costs the pack the bear case
while `pack_field` has already shipped a pointer to it. Measured before the fix, with
`pack_bear_case.render` patched to raise: the pointer to 'What would sink this' is emitted and
the rationale is then published in NO section of the pack. The buyer is sent to a file that is
not in their zip, to read a paragraph nobody printed.

The two properties are pinned together on purpose. Either alone is satisfiable by a renderer
that is wrong in the other direction: always printing the rationale here kills the pointer and
restores the duplication, and never printing it keeps the pointer honest by losing the
paragraph. What must hold is that EXACTLY ONE of {rationale, pointer} is printed on every
path, and that the pointer is printed only when its target will be in the download.
"""
import pytest

from prospector import pack_bear_case, pack_field
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict

# The real citation id and source page from `store/dossiers/8d5e24fbe6c1f5d3.pass.json`, the
# same pack `tests/unit/test_pack_render_defects.py` draws its literals from.
CIT = "1e62e0c381e1c8d3"
URL = "https://www.socialstorytemplates.com/free"
PASSAGE = ("Over 100 free personalisable social stories are available to download, and the "
           "library is updated every month by the therapists who write them.")
# Distinctive enough that `in md` cannot pass on the section's boilerplate.
RATIONALE = "No incumbent was found selling personalised social stories to this segment."


def _dossier(verdict, rationale=RATIONALE, extra_checks=()):
    src = Source(source_id=CIT, url=URL, text=PASSAGE)
    checks = [CheckResult(check_name="incumbency", verdict=verdict, confidence=0.64,
                          rationale=rationale, citations=[CIT], sources=[src])]
    checks += list(extra_checks)
    return Dossier(
        candidate=Candidate(candidate_id="8d5e24fbe6c1f5d3", title="StorySprout",
                            one_liner="A picture book that stars one child"),
        checks=checks, decision=Decision.PASS, reason="Survived all gates.",
        model_version="minimax", created_at="2026-08-01T00:00:00Z")


def _pointer(md: str) -> bool:
    return pack_field.BEAR_CASE_SECTION in md


# --- the split itself ---------------------------------------------------------------------

def test_a_supported_verdict_prints_the_rationale_here_and_no_pointer():
    """`supported` rows are the ones the bear case never walks, so this section owns them."""
    md = pack_field.render(_dossier(Verdict.SUPPORTED))
    assert RATIONALE in md
    assert not _pointer(md)


@pytest.mark.parametrize("verdict", [Verdict.REFUTED, Verdict.UNVERIFIABLE])
def test_a_refuted_or_unproven_verdict_hands_over_and_prints_a_pointer(verdict):
    """The paragraph goes to the bear case; this section keeps the evidence and a signpost."""
    dossier = _dossier(verdict)
    assert pack_bear_case.render(dossier), "fixture precondition: the target section exists"
    md = pack_field.render(dossier)
    assert _pointer(md)
    assert RATIONALE not in md


@pytest.mark.parametrize("verdict", [Verdict.SUPPORTED, Verdict.REFUTED, Verdict.UNVERIFIABLE])
def test_the_rationale_and_the_pointer_are_never_both_printed(verdict):
    """The whole point of the split: the buyer pays once and must not read it twice.

    Asserted as an exclusive-or rather than as two independent membership checks, because
    "neither" is the other way to break this and passes both of those.
    """
    md = pack_field.render(_dossier(verdict))
    assert (RATIONALE in md) != _pointer(md)


def test_the_pointer_names_the_section_the_bear_case_actually_titles():
    """`BEAR_CASE_SECTION` is spelled out rather than imported (see the note on the constant).

    A duplicated string is only safe while something fails when the two drift, and the buyer
    is the one who finds out otherwise: the pointer names a heading that is not in the pack.
    """
    assert pack_field.BEAR_CASE_SECTION == pack_bear_case.TITLE
    md = pack_field.render(_dossier(Verdict.REFUTED))
    assert f"# {pack_bear_case.TITLE}" in pack_bear_case.render(_dossier(Verdict.REFUTED))
    assert pack_bear_case.TITLE in md


# --- the pointer may not outlive its target -----------------------------------------------

@pytest.mark.parametrize("verdict", [Verdict.REFUTED, Verdict.UNVERIFIABLE])
def test_no_pointer_is_printed_when_the_bear_case_cannot_render(verdict, monkeypatch):
    """The measured before-state: pointer shipped, target absent, rationale published nowhere.

    `bridge` catches the exception, logs "shipping the bundle without that section" and moves
    on, so this is not a hypothetical -- it is the documented behaviour of the guard.
    """
    def _boom(*a, **k):
        raise RuntimeError("bear case render failed")

    monkeypatch.setattr(pack_bear_case, "render", _boom)
    md = pack_field.render(_dossier(verdict))
    assert not _pointer(md), "the buyer is sent to a section that is not in their download"
    assert RATIONALE in md, "and the paragraph would then be published in no section at all"


@pytest.mark.parametrize("verdict", [Verdict.REFUTED, Verdict.UNVERIFIABLE])
def test_no_pointer_is_printed_when_the_bear_case_renders_nothing(verdict, monkeypatch):
    """"" is the other absence, and `bridge` treats it as "omit the section" by design.

    Distinct from the raise above: a renderer that returns "" is not failing, so nothing is
    logged and nothing looks wrong. That is the quieter of the two and needs its own pin.
    """
    monkeypatch.setattr(pack_bear_case, "render", lambda *a, **k: "")
    md = pack_field.render(_dossier(verdict))
    assert not _pointer(md)
    assert RATIONALE in md


def test_the_fallback_does_not_reintroduce_the_duplication_it_replaced():
    """The rationale is printed here ONLY when the bear case will not carry it.

    Guards the obvious wrong fix -- printing the paragraph in both places so the pointer is
    always honest -- which passes every "the rationale is somewhere" assertion above.
    """
    dossier = _dossier(Verdict.REFUTED)
    field_md = pack_field.render(dossier)
    bear_md = pack_bear_case.render(dossier)
    assert RATIONALE in bear_md
    assert RATIONALE not in field_md


def test_a_verdict_the_split_does_not_name_still_publishes_its_rationale():
    """A row whose verdict is neither supported, refuted nor unverifiable is carried by
    NEITHER section under a verdict-only split: the bear case walks refuted and unverifiable
    rows only, and the pre-fix `if` here required `supported`. Conditioning on the target
    rather than on the verdict list closes that hole as a side effect, and this pins it.
    """
    md = pack_field.render(_dossier(""))
    assert RATIONALE in md
    assert not _pointer(md)


def test_an_empty_rationale_prints_neither():
    """Nothing to hand over and nothing to print. The section still renders its evidence."""
    md = pack_field.render(_dossier(Verdict.SUPPORTED, rationale=""))
    assert not _pointer(md)
    assert URL in md, "the passages are why this section exists; they are unaffected"
