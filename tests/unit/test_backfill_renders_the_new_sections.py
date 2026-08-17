"""The five narrative sections, backfilled onto a pack somebody already owns.

The 2026-08-15 restructure turned the pack into a fourteen-section read, five of which are
rendered from the dossier with no model call: `The_Offer.md`, `The_Field.md`,
`What_Would_Sink_This.md`, `The_Toolkit.md` and `How_To_Know_In_30_Days.md`. The generator
writes them in `bridge._create_bundle`. Until this file existed, `tools/backfill_bundle_html.py`
re-rendered only `pack_reference` and `pack_checklist`, so the 145 bundles already on the shelf
would have kept the old shape forever and the restructure would have been a fix for FUTURE
buyers only.

What is pinned here is not "the sections appear" but the stronger property the backfill exists
for: A BACKFILLED PACK AND A GENERATED ONE ARE THE SAME DOCUMENT. The first test asserts that as
byte equality of the rendered reader against the sections composed the generator's way, which is
why it will fail if the backfill ever drops the prose pass, reorders the loop, or takes the bear
case's section title from a literal instead of `_SECTION_TITLES`.

The bear case is the reason order matters at all. It lifts two blocks out of the financial model
verbatim, and the model then has to hand them over and keep a pointer — otherwise the buyer
reads the same weakness text in two sections, which is the exact duplication this branch exists
to remove. So the absorb is tested in both directions: it happens when the bear case rendered,
and it does NOT happen when the bear case returned "" (nothing absorbed them, so the model keeps
its own).

Fixtures are imported from `test_backfill_bundle_html` rather than reinvented: the dossier, the
bundle in bridge's real write order and the reader accessor are that file's, and two divergent
fixtures for the same tool is how two tests come to disagree about what a pack looks like.

No network, no model calls: all five renderers are pure functions of the dossier, and
`plain_text.publish_pass_document` is pure Python. Nothing here touches `publish/` or `store/`;
`rebuild_zip_with_index` is called directly on in-memory bytes and `--apply` is never involved.
"""

import io
import sys
import zipfile
from pathlib import Path

from prospector import (
    pack_bear_case,
    pack_checklist,
    pack_field,
    pack_html,
    pack_kicker,
    pack_manifest,
    pack_offer,
    pack_reference,
    pack_toolkit,
    plain_text,
)
from prospector.bridge import _SECTION_TITLES, BUNDLE_READING_ORDER
from tools.backfill_bundle_html import rebuild_zip_with_index

sys.path.insert(0, str(Path(__file__).parent))

from test_backfill_bundle_html import (  # noqa: E402
    META,
    WRITE_ORDER,
    _dossier,
    _dossier_dict,
    _reader,
    _zip,
)

LATE_SECTIONS = (pack_offer, pack_field, pack_bear_case, pack_toolkit, pack_kicker)

#: A financial model carrying the two blocks the bear case absorbs, in the headings
#: `pack_bear_case._absorbed_blocks` looks for. The default fixture bundle has neither, which is
#: the thin case; this is the one where the duplication can actually happen.
WEAKNESS_LINE = "The CAC estimate is a guess and nobody has checked it against a real invoice."
FINANCIAL_WITH_WEAKNESSES = (
    "# 04_Financial_Model.md\n"
    "body of 04_Financial_Model.md\n\n"
    "### Where this is weakest\n\n"
    f"{WEAKNESS_LINE}\n\n"
    "### What we could not work out\n\n"
    "Churn past month three is unknown; no operator would give us a figure.\n"
)

#: The pointer sentence `financial_md_after_absorbing` leaves behind. Its presence is the tell
#: that the handover ran; its absence is the tell that it did not.
POINTER_HEADING = "Where these numbers are softest"


def _rich_dossier():
    """The shared fixture dossier, given the two fields the thinnest sections need.

    Derived from `_dossier_dict()` rather than written out again: `pack_offer` renders only when
    the candidate carries a `hypothesis` or a `structural_form` (it guards on the fields it
    actually prints), and `pack_field` renders only when an incumbency or price_comparables
    check retrieved a passage. On the bare fixture both correctly return "" — which is the
    subject of a test below, not something to paper over here.
    """
    d = _dossier_dict()
    d["candidate"]["hypothesis"] = (
        "Growers will pay for a weekly closure digest because the notices are scattered.")
    d["candidate"]["structural_form"] = "productised service"
    d["checks"].append({
        "check_name": "incumbency",
        "verdict": "supported",
        "confidence": 0.7,
        "rationale": "Two established players publish something adjacent.",
        "citations": ["s2"],
        "sources": [{
            "source_id": "s2",
            "url": "https://example.com/rival",
            "text": ("Fieldline publishes a weekly closure bulletin for growers across the "
                     "eastern counties and charges ninety pounds a year for it."),
        }],
    })
    return pack_manifest.dossier_from_dict(d)


def _bundle(financial_md=None):
    """The shared write-order bundle, optionally with a richer financial model."""
    bodies = {n: f"# {n}\nbody of {n}" for n in WRITE_ORDER}
    if financial_md is not None:
        bodies["04_Financial_Model.md"] = financial_md
    return _zip([(n, bodies[n]) for n in WRITE_ORDER])


def _generated_reader(dossier, financial_md=None):
    """The reader the GENERATOR would produce for the same dossier and the same documents.

    Composed the way `bridge._create_bundle` composes it — reference, checklist, then the five
    sections in the generator's own order, each through `publish_pass_document`, with the bear
    case's absorb applied to the financial model afterwards — and then handed to the same
    `render_pack_html` the tool calls. This is the reference implementation the backfill is
    asserted equal to, so a drift in ORDER, in the prose pass or in the absorb shows up as a
    byte difference rather than as a section that happens to be present.
    """
    written = {n: f"# {n}\nbody of {n}" for n in WRITE_ORDER}
    if financial_md is not None:
        written["04_Financial_Model.md"] = financial_md

    reference_md = pack_reference.render(dossier)
    if reference_md:
        written[pack_reference.FILENAME] = reference_md
    checklist_md = pack_checklist.render(dossier, dict(written))
    if checklist_md:
        written[pack_checklist.FILENAME] = checklist_md

    for module in LATE_SECTIONS:
        kwargs = ({"financial_md": written.get("04_Financial_Model.md", "")}
                  if module is pack_bear_case else {})
        body = module.render(dossier, **kwargs)
        if not body:
            continue
        written[module.FILENAME] = plain_text.publish_pass_document(body)
        if module is pack_bear_case and written.get("04_Financial_Model.md"):
            written["04_Financial_Model.md"] = module.financial_md_after_absorbing(
                written["04_Financial_Model.md"],
                _SECTION_TITLES.get(module.FILENAME, "the bear case"))

    entries = [(_SECTION_TITLES[n], written[n])
               for n in BUNDLE_READING_ORDER if written.get(n)]
    return pack_html.render_pack_html(entries, META)


def _section(html, filename):
    """The BODY of one section of the reader, sliced on `<section id=...>`.

    The reader is one document, so "the weakness text is in the bear case and not in the
    numbers" cannot be asserted by a substring test over the whole page. Sliced on the section
    element and NOT on the first occurrence of the title: `render_pack_html` opens with a
    contents list that prints every title once, so a title-index slice returns a fragment of the
    table of contents and every content assertion inside it fails for the wrong reason.
    """
    marker = f'<h2 class="section-title">{_SECTION_TITLES[filename]}</h2>'
    blocks = [b for b in html.split('<section id="') if marker in b]
    assert blocks, f"{filename} is not a section of this reader"
    return blocks[0]


class TestTheBackfillCarriesTheSameSectionsTheGeneratorDoes:

    def test_a_backfilled_pack_gains_the_late_sections_a_generated_one_would_have(self):
        dossier = _rich_dossier()
        for module in LATE_SECTIONS:
            kwargs = {"financial_md": FINANCIAL_WITH_WEAKNESSES} \
                if module is pack_bear_case else {}
            assert module.render(dossier, **kwargs), (
                f"precondition: this dossier gives {module.FILENAME} something to say")

        out = rebuild_zip_with_index(
            _bundle(FINANCIAL_WITH_WEAKNESSES), META, dossier, "x" * 16)
        assert out is not None
        html = _reader(out)

        for module in LATE_SECTIONS:
            assert _SECTION_TITLES[module.FILENAME] in html, (
                f"{module.FILENAME} never reached the reader; a backfilled pack is still the "
                "old fourteen-section-minus-five shape")

    def test_the_backfilled_reader_is_the_generated_reader_byte_for_byte(self):
        """The property the whole block exists for, stated as equality rather than presence.

        Presence would pass a backfill that skipped the prose pass, ran the five in a different
        order, or took the bear case's pointer title from a literal. Each of those makes a pack
        bought in June a different document from the same pack published today, which is the
        drift `pack_reference` and `pack_checklist` are both written to avoid.
        """
        dossier = _rich_dossier()
        out = rebuild_zip_with_index(
            _bundle(FINANCIAL_WITH_WEAKNESSES), META, dossier, "x" * 16)
        assert _reader(out) == _generated_reader(dossier, FINANCIAL_WITH_WEAKNESSES)

    def test_the_sections_are_documents_in_the_read_not_entries_in_the_archive(self):
        """They go through `payload`, so the reader and the PDF pick them up in reading order —
        and no markdown reaches the buyer's archive, which is the floor the conversion set."""
        out = rebuild_zip_with_index(
            _bundle(FINANCIAL_WITH_WEAKNESSES), META, _rich_dossier(), "x" * 16)
        names = zipfile.ZipFile(io.BytesIO(out)).namelist()
        assert not [n for n in names if n.endswith(".md")], names

        html = _reader(out)
        markers = {n: f'<h2 class="section-title">{_SECTION_TITLES[n]}</h2>'
                   for n in BUNDLE_READING_ORDER}
        positions = [html.index(m) for m in markers.values() if m in html]
        assert positions == sorted(positions), (
            "the late sections were appended rather than read in contract order")


class TestTheBearCaseAbsorbsTheFinancialModelsWeaknesses:

    def test_the_weakness_text_is_in_exactly_one_of_the_two_documents(self):
        out = rebuild_zip_with_index(
            _bundle(FINANCIAL_WITH_WEAKNESSES), META, _rich_dossier(), "x" * 16)
        html = _reader(out)

        assert html.count(WEAKNESS_LINE) == 1, (
            f"the buyer reads the same weakness {html.count(WEAKNESS_LINE)} times; "
            "1 is the only correct answer — 2 is the duplication this branch removes, "
            "0 is content lost in the handover")
        assert WEAKNESS_LINE in _section(html, pack_bear_case.FILENAME)
        assert WEAKNESS_LINE not in _section(html, "04_Financial_Model.md")

    def test_the_numbers_section_keeps_a_pointer_rather_than_a_silent_deletion(self):
        out = rebuild_zip_with_index(
            _bundle(FINANCIAL_WITH_WEAKNESSES), META, _rich_dossier(), "x" * 16)
        numbers = _section(_reader(out), "04_Financial_Model.md")
        assert POINTER_HEADING in numbers
        assert _SECTION_TITLES[pack_bear_case.FILENAME] in numbers, (
            "the pointer must name the section by its `_SECTION_TITLES` title, never a literal")

    def test_nothing_absorbed_them_when_the_bear_case_declined_to_render(self, monkeypatch):
        """The other direction, and the one a naive implementation gets wrong: absorb only on
        success. A bear case that returned "" took nothing, so deleting the model's weaknesses
        would delete them from the pack entirely."""
        monkeypatch.setattr(pack_bear_case, "render", lambda *a, **k: "")
        out = rebuild_zip_with_index(
            _bundle(FINANCIAL_WITH_WEAKNESSES), META, _rich_dossier(), "x" * 16)
        html = _reader(out)

        assert _SECTION_TITLES[pack_bear_case.FILENAME] not in html
        assert html.count(WEAKNESS_LINE) == 1, "the weaknesses were lost with nothing to hold them"
        assert WEAKNESS_LINE in _section(html, "04_Financial_Model.md")
        assert POINTER_HEADING not in html, "a pointer at a section that was never rendered"

    def test_a_thin_dossier_leaves_the_financial_model_exactly_as_it_was(self):
        """The shipped fixture: one supported check and a financial model with nothing to lift,
        so `render` returns "" for real rather than by monkeypatch."""
        dossier = _dossier()
        plain_financial = "# 04_Financial_Model.md\nbody of 04_Financial_Model.md"
        assert pack_bear_case.render(dossier, financial_md=plain_financial) == "", (
            "precondition: this dossier refutes nothing and leaves nothing unproven")

        html = _reader(rebuild_zip_with_index(_bundle(), META, dossier, "x" * 16))
        assert _SECTION_TITLES[pack_bear_case.FILENAME] not in html
        assert POINTER_HEADING not in html
        assert "body of 04_Financial_Model.md" in _section(html, "04_Financial_Model.md")


class TestAnEmptyOrFailedSectionCostsThatSectionAndNothingElse:

    def test_an_empty_render_omits_the_section_and_is_not_a_failure(self):
        """`pack_field` returns "" on a dossier whose incumbency check fetched nothing, and a
        section headed "who is already there" followed by nothing states that nobody is. A pack
        that omits it is correct, and the rest of the pack still converts."""
        dossier = _dossier()
        assert pack_field.render(dossier) == "", "precondition: nothing retrieved about the field"

        out = rebuild_zip_with_index(_bundle(), META, dossier, "x" * 16)
        assert out is not None, "an omitted section must never fail the conversion"
        html = _reader(out)
        assert _SECTION_TITLES[pack_field.FILENAME] not in html
        assert _SECTION_TITLES[pack_toolkit.FILENAME] in html

    def test_one_section_raising_costs_that_section_only(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("renderer blew up")

        monkeypatch.setattr(pack_toolkit, "render", boom)
        out = rebuild_zip_with_index(
            _bundle(FINANCIAL_WITH_WEAKNESSES), META, _rich_dossier(), "x" * 16)
        assert out is not None, (
            "one section failing took the whole pack down; on the --apply path that is an "
            "exception instead of a converted bundle")

        html = _reader(out)
        assert _SECTION_TITLES[pack_toolkit.FILENAME] not in html
        for module in (pack_offer, pack_field, pack_bear_case, pack_kicker):
            assert _SECTION_TITLES[module.FILENAME] in html, module.FILENAME

    def test_the_prose_pass_runs_on_every_late_section(self):
        """Skipping it is invisible in a presence test and is exactly what would make a
        backfilled pack differ from a generated one. Asserted on a section whose raw render the
        pass demonstrably changes, so the test cannot pass vacuously."""
        dossier = _rich_dossier()
        changed = [m for m in LATE_SECTIONS
                   if (raw := m.render(dossier, **({"financial_md": FINANCIAL_WITH_WEAKNESSES}
                                                   if m is pack_bear_case else {})))
                   and plain_text.publish_pass_document(raw) != raw]
        if not changed:
            # Nothing to distinguish on this fixture; the byte-equality test above still holds
            # the property. Stated rather than silently passing.
            import pytest
            pytest.skip("no late section's raw render differs from its passed form here")

        html = _reader(rebuild_zip_with_index(
            _bundle(FINANCIAL_WITH_WEAKNESSES), META, dossier, "x" * 16))
        for module in changed:
            kwargs = {"financial_md": FINANCIAL_WITH_WEAKNESSES} \
                if module is pack_bear_case else {}
            passed = plain_text.publish_pass_document(module.render(dossier, **kwargs))
            marker = next((ln.strip() for ln in passed.split("\n")
                           if len(ln.strip()) > 40 and not ln.startswith("#")), "")
            assert marker and marker in _section(html, module.FILENAME).replace("&#39;", "'")
