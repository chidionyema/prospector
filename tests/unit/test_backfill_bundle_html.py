"""The backfill's one transformation, proven on bytes.

Until 2026-08-15 the tool's promise was that a converted bundle differed from the original
ONLY in its generated index.html — every .md deliverable of record survived byte-identical,
and most of this file existed to hold that line. The history is kept because the reasoning was
right for its moment: you do not edit documents people have already paid for.

The founder's brief ("i dont like md files at all, we are not selling to developers") changed
what a pack IS, not that discipline. The .md entries are now the render INPUT: they are read,
patched, composed into index.html / Complete_Pack.pdf / First_Fortnight.html / Assumptions.csv
/ Marketing_Assets.txt, and then NOT carried into the output archive. Measured on pack
0bf4d472ef2b90ad's real R2 zip: 14 entries in, 6 out, no .md left, -40697 B (-15.4%).

So "byte-identical" moves down a level rather than being dropped. What is byte-identical now is
what goes INTO the render (`patched_md`), and the buyer-facing assertion is that every
document's content reaches the reader. Where a test's subject was the shipped .md itself, it is
re-pointed at the reader or at `patched_md`; two tests whose subject no longer exists at all
are deleted with a note.

CONVERSION IS ONE-WAY, and that is the hazard this file now guards hardest. A converted pack
has no .md left to render a reader FROM, so a second pass must return None rather than write an
empty index.html over a good pack. Two further no-op conditions exist: no .md in the source,
and `dossier is None` (no evidence record on disk means no manifest can be minted and no
First_Fortnight.html / Assumptions.csv can be derived, so converting would ship a pack that
fails `audit_bundle` and is held UNLISTED).

These tests also pin the READING ORDER, because this file previously pinned the opposite. The
old `test_entry_order_is_preserved_so_sections_keep_bundle_order` asserted the reader must
follow the zip's own entry order, on the belief that "bridge writes the .md files in a
deliberate reading order". It does not: the bundle is written 01, 02, 03, 04, QA, Marketing,
00, 05, so following write order opened the reader on the build spec, put the executive
summary seventh, and put the first-week checklist last. That test made the defect a
requirement — it would have failed the fix.
"""

import io
import zipfile

from prospector import pack_checklist
from prospector.bridge import (
    _SECTION_TITLES,
    BUNDLE_BONUS_FILES,
    BUNDLE_FILES,
    BUNDLE_READING_ORDER,
)
from prospector.pack_html import PackMeta
from tools.backfill_bundle_html import ordered_md_entries, patched_md, rebuild_zip_with_index

META = PackMeta(title="T", one_liner="o", verified_at="2026-07-31", source_count=3, pack_id="x")

# The order bridge wrote the legacy bundle in — deliberately not the reading order, and the
# order every already-sold pack is still stored in.
WRITE_ORDER = [
    "01_Blueprint_BuildSpec.md",
    "02_Marketing_Plan_GTM.md",
    "03_Operations_Plan.md",
    "04_Financial_Model.md",
    "QA_Report.md",
    "Marketing_Assets.md",
    "00_Executive_Summary.md",
    "05_First_Week_Checklist.md",
]

# The documents whose body text survives into the reader verbatim. The two exclusions are
# deliberate and each has its own test below: 05 is REWRITTEN by `pack_checklist.render`, and
# Evidence_and_Constraints.md is not in a legacy zip at all — it is rendered from the dossier.
BODY_BEARING = [n for n in BUNDLE_READING_ORDER
                if n in WRITE_ORDER and n != "05_First_Week_Checklist.md"]


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in entries:
            z.writestr(name, content)
    return buf.getvalue()


def _full_bundle(extra=()):
    """A bundle in bridge's real write order, each file naming itself."""
    return _zip([(n, f"# {n}\nbody of {n}") for n in WRITE_ORDER] + list(extra))


def _reader(zip_bytes):
    return zipfile.ZipFile(io.BytesIO(zip_bytes)).read("index.html").decode("utf-8")


def test_the_documents_are_rendered_into_the_reader_and_do_not_survive_as_entries():
    """Was `test_adds_index_html_and_keeps_every_entry_byte_identical`.

    The old assertion — the source entries survive, in their original order, before anything
    generated — is the exact thing that was reversed on 2026-08-15, so keeping it would pin the
    shape the founder rejected. What it was PROTECTING is kept: the tool must not lose content.
    That is now stated as "the documents' text reaches the reader", plus the new hard floor
    that no markdown reaches the buyer.
    """
    entries = [
        ("01_Blueprint_BuildSpec.md", "# One\n**bold** must survive the render"),
        ("QA_Report.md", "| a | b |\n|---|---|\n| 1 | 2 |"),
    ]
    out = rebuild_zip_with_index(_zip(entries), META, _dossier(), "x" * 16)
    assert out is not None

    src = zipfile.ZipFile(io.BytesIO(out))
    names = src.namelist()
    assert not [n for n in names if n.endswith(".md")], (
        f"markdown survived into the buyer's archive: {[n for n in names if n.endswith('.md')]}")
    # Asserted as a subset, not as a literal list: a pack that carries no Marketing_Assets.md
    # gets no Marketing_Assets.txt, and this test is about what may NOT appear.
    assert set(names) <= set(BUNDLE_FILES) | set(BUNDLE_BONUS_FILES), (
        f"undeclared entry written: {set(names) - set(BUNDLE_FILES) - set(BUNDLE_BONUS_FILES)}")
    assert "index.html" in names

    html = src.read("index.html").decode("utf-8")
    assert "<strong>bold</strong>" in html, "the document's content must reach the reader"
    assert _SECTION_TITLES["QA_Report.md"] in html


def test_a_converted_pack_is_a_no_op_and_never_gets_an_empty_reader_written_over_it():
    """Was `test_returns_none_only_when_the_existing_reader_is_already_correct`.

    Idempotence is still stated as a round trip rather than by hand-building the "already done"
    bundle — the hand-built version had to enumerate every generated entry, so it silently
    became a test that the tool adds EXACTLY index.html, and on 2026-08-14 it failed for the
    PDF, a file it was never about. Feeding the tool its own output cannot drift that way.

    What changed is WHY the second pass returns None, and it is now the most dangerous thing in
    this module rather than a tidiness property. Conversion is ONE-WAY: the reader is rendered
    from the .md entries and the .md entries are then dropped, so a converted pack has nothing
    left to render FROM. Without the `not documents` guard the second pass would render an
    EMPTY index.html and write it over a perfectly good, already-sold pack. The last assertion
    is that hazard made explicit — the render input really is empty, so None is the guard doing
    work rather than a coincidence.
    """
    once = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    assert once is not None
    assert rebuild_zip_with_index(once, META, _dossier(), "x" * 16) is None

    converted = zipfile.ZipFile(io.BytesIO(once))
    assert not [n for n in converted.namelist() if n.endswith(".md")]
    assert ordered_md_entries(converted) == [], (
        "precondition of the hazard: a converted pack has NO render input left, so anything "
        "that proceeded past the guard would write an empty reader")

    # The other half of "only": a legacy bundle whose reader is WRONG must still be rebuilt, or
    # the None above would be indistinguishable from a tool that never does anything.
    stale = _full_bundle(extra=[("index.html", "<p>old</p>")])
    assert rebuild_zip_with_index(stale, META, _dossier(), "x" * 16) is not None


def test_reading_order_follows_the_contract_not_the_zips_write_order():
    """The fix, stated as the property. This is the test the old suite had backwards.

    Re-pointed 2026-08-15 from `BUNDLE_FILES` to `BUNDLE_READING_ORDER`: those two were the
    same list while the archive WAS the documents, and are different lists now — one is what
    the pack says, the other is what the archive holds. The order a buyer reads in is the
    first of the two, and it is derived from `PACK_DOCUMENTS`, so this still tracks the single
    place the sequence is editable.
    """
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    html = _reader(out)

    positions = [html.index(f"body of {name}") for name in BODY_BEARING]
    assert positions == sorted(positions), (
        "index.html must read in BUNDLE_READING_ORDER; got "
        f"{[n for _, n in sorted(zip(positions, BODY_BEARING))]}"
    )

    # The two that motivated the fix, named explicitly so a regression says which.
    assert html.index("body of 00_Executive_Summary.md") < html.index("body of 01_Blueprint_BuildSpec.md")
    assert html.index("body of QA_Report.md") == max(positions)
    # The action document has no `body of` marker because it is rewritten (see below), so its
    # slot is asserted through the text the rewrite produces.
    assert (html.index("body of 04_Financial_Model.md")
            < html.index("Ten working days")
            < html.index("body of Marketing_Assets.md"))


def test_the_archive_is_written_in_contract_order_not_the_sources():
    """Was `test_zip_entry_order_is_still_left_alone`, whose whole subject — the source zip's
    entry order, preserved as a matter of record — no longer exists: none of those entries
    survive the conversion.

    The property that replaces it is the one the write loop now guarantees, and it matters for
    the same reason the old one did (a stable archive is a diffable archive): entries are
    written in BUNDLE_FILES order, then BUNDLE_BONUS_FILES, then anything else, independent of
    whatever order the source happened to use.
    """
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    names = zipfile.ZipFile(io.BytesIO(out)).namelist()

    declared = [n for n in list(BUNDLE_FILES) + list(BUNDLE_BONUS_FILES) if n in names]
    assert names == declared, f"archive order drifted from the contract: {names}"
    assert not [n for n in names if n.endswith(".md")]


def test_titles_match_the_generator_not_the_filenames():
    src = zipfile.ZipFile(io.BytesIO(_full_bundle()))
    titles = [t for t, _ in ordered_md_entries(src)]
    assert titles[0] == "Executive Summary"
    assert "00_Executive_Summary" not in titles


def test_a_stale_reader_is_corrected_rather_than_skipped():
    """The idempotency change. Every pack listed today carries a write-order reader."""
    stale = _full_bundle(extra=[("index.html", "<p>old write-order reader</p>")])
    out = rebuild_zip_with_index(stale, META, _dossier(), "x" * 16)
    assert out is not None, "a wrong index.html must be corrected, not treated as already done"

    z = zipfile.ZipFile(io.BytesIO(out))
    assert z.namelist().count("index.html") == 1, "must never leave two readers in the zip"
    html = z.read("index.html").decode("utf-8")
    assert "old write-order reader" not in html
    assert html.index("body of 00_Executive_Summary.md") < html.index("body of 01_Blueprint_BuildSpec.md")


def test_an_unknown_md_is_rendered_at_the_end_never_dropped():
    out = rebuild_zip_with_index(
        _full_bundle(extra=[("99_Bonus.md", "# B\nbody of 99_Bonus.md")]),
        META, _dossier(), "x" * 16)
    html = _reader(out)
    # Still the tool's whole promise: it does not lose content. Since 2026-08-15 the unknown
    # file has nowhere ELSE to survive — it is not copied into the archive any more — so this
    # is the only thing standing between a legacy extra file and silent deletion.
    assert "body of 99_Bonus.md" in html
    assert html.index("body of 99_Bonus.md") > html.index("body of QA_Report.md")


# --- manifest.jsonld backfill -------------------------------------------------------------------
# The second generated file. index.html can be rebuilt from the zip alone; the manifest cannot,
# because the evidence it carries (checks, verdicts, cited passages) lives only in store/dossiers.
# That asymmetry is the whole reason these tests exist separately from the ones above — and since
# 2026-08-15 it is stronger still: with no dossier there is no conversion at all.

import json  # noqa: E402

from prospector import (
    pack_manifest,  # noqa: E402
    pack_reference,  # noqa: E402
)
from prospector.models import (  # noqa: E402
    Candidate,
    CheckResult,
    Decision,
    Dossier,
    Source,
    Verdict,
)
from tools.backfill_bundle_html import load_local_dossier  # noqa: E402


def _dossier_dict(checks=True):
    cand = Candidate(candidate_id="x" * 16, title="T", one_liner="o", market="uk",
                     who_pays="operators", why_now="new rules")
    check = CheckResult(
        check_name="buyer_intent", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale="Growers search for closure guidance.",
        citations=["s1"],
        sources=[Source(source_id="s1", url="https://example.gov.uk/x", text="Notices are weekly.")],
    )
    return Dossier(candidate=cand, decision=Decision.PASS, checks=[check] if checks else [],
                   created_at="2026-07-31T00:00:00Z").to_dict()


def _dossier(checks=True):
    return pack_manifest.dossier_from_dict(_dossier_dict(checks))


def test_a_dossier_adds_a_manifest_whose_digests_match_the_shipped_bytes():
    """The manifest's digests must be of the bytes IN THE ZIP, not of a decode round-trip.

    The reader path decodes entries with errors="replace"; a digest taken over that string would
    differ from the file it describes on any byte the codec could not round-trip, turning the one
    file whose job is to be machine-checkable into the one file that fails its own check.

    The `promisedDeliverable is False` assertion on index.html was INVERTED on 2026-08-15 rather
    than dropped. It recorded that the reader was a bonus and must not be able to delist a pack.
    index.html is what the buyer opens now, so it is a promised deliverable — a pack without one
    has nothing readable in it and being held UNLISTED is the correct outcome.
    """
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    z = zipfile.ZipFile(io.BytesIO(out))
    doc = json.loads(z.read(pack_manifest.MANIFEST_FILENAME).decode("utf-8"))

    import hashlib
    docs = [n for n in doc["@graph"] if n.get("@type") == "DigitalDocument"]
    assert [n["contentUrl"] for n in docs if n.get("prospector:promisedDeliverable") is not False] \
        == list(BUNDLE_FILES)
    for node in docs:
        body = z.read(node["contentUrl"])
        assert node["prospector:sha256"] == hashlib.sha256(body).hexdigest(), node["contentUrl"]

    # index.html is regenerated in this same call, so the manifest must digest the NEW reader.
    reader = next(n for n in docs if n["contentUrl"] == "index.html")
    assert reader["prospector:sha256"] == hashlib.sha256(z.read("index.html")).hexdigest()
    assert reader.get("prospector:promisedDeliverable") is not False, (
        "the reader IS the pack now; marking it optional would let a bundle with no readable "
        "file in it pass audit_bundle and list")


def test_without_a_dossier_the_pack_is_left_exactly_as_it_is():
    """Was `test_without_a_dossier_no_manifest_is_invented`, and the rule it stated has been
    tightened rather than replaced.

    The original reasoning stands: an EMPTY evidence record reads, to an agent, as a pack that
    was never verified — strictly worse than no manifest, because absence is honest. What has
    changed is that "fix the reader anyway" is no longer safe. Converting without a dossier
    would ship a pack with no First_Fortnight.html and no Assumptions.csv, both of which are in
    BUNDLE_FILES now, so `audit_bundle` would report it short and the pack would be DELISTED —
    the tool would be taking packs that currently sell off the shelf. So a pack whose evidence
    record is off this disk is reported and left untouched, which is the honest outcome: it
    keeps selling in its old shape.
    """
    assert rebuild_zip_with_index(_full_bundle(), META) is None


def test_a_legacy_pack_that_already_has_a_correct_reader_still_converts():
    """Was `test_a_correct_reader_with_no_manifest_still_converts`; the guarantee is unchanged.

    The idempotency check is not a presence test on the generated files. Every pack listed
    before this feature has a reader and no manifest, and a presence test on index.html alone
    would skip all of them and the feature would reach nobody. The one that decides is whether
    there is anything left to render FROM.
    """
    converted = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    good_reader = zipfile.ZipFile(io.BytesIO(converted)).read("index.html")

    legacy_with_correct_reader = _full_bundle(extra=[("index.html", good_reader)])
    out = rebuild_zip_with_index(legacy_with_correct_reader, META, _dossier(), "x" * 16)
    assert out is not None
    assert pack_manifest.MANIFEST_FILENAME in zipfile.ZipFile(io.BytesIO(out)).namelist()


def test_rerunning_with_the_same_dossier_is_a_no_op():
    once = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    assert rebuild_zip_with_index(once, META, _dossier(), "x" * 16) is None


def test_a_shipped_manifest_is_never_dropped_because_the_dossier_went_missing():
    """Deleting evidence a buyer already has, because a local file moved, is data loss wearing a
    no-op's clothes.

    The tool used to satisfy this by carrying the shipped manifest forward when it rebuilt
    without a dossier. Since 2026-08-15 it cannot: a carried-forward manifest would assert a
    sha256 for eight .md entries the same run just removed, and a manifest listing an entry the
    zip lacks is the ONE failure mode manifest.jsonld exists to make impossible. So the
    guarantee is met by refusing to convert at all — which also covers the original loss (the
    buyer's manifest is still there, in the untouched pack).
    """
    once = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    shipped_manifest = zipfile.ZipFile(io.BytesIO(once)).read(pack_manifest.MANIFEST_FILENAME)

    # A legacy pack that already carries a manifest, whose reader is stale, whose dossier is
    # gone. The tempting thing here is a partial rebuild; the correct thing is to do nothing.
    legacy = _full_bundle(extra=[(pack_manifest.MANIFEST_FILENAME, shipped_manifest),
                                 ("index.html", b"<p>stale</p>")])
    assert rebuild_zip_with_index(legacy, META) is None
    assert zipfile.ZipFile(io.BytesIO(legacy)).read(pack_manifest.MANIFEST_FILENAME) \
        == shipped_manifest


def test_load_local_dossier_is_none_when_the_record_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.backfill_bundle_html.DOSSIER_DIR", tmp_path)
    assert load_local_dossier("nosuchpack") is None
    (tmp_path / "p1.pass.json").write_text(json.dumps(_dossier_dict()))
    assert load_local_dossier("p1").candidate.title == "T"
    (tmp_path / "p2.pass.json").write_text("{not json")
    assert load_local_dossier("p2") is None, "a corrupt record is a skip, never a wrong manifest"


# --- P7: the shelf-life line already sold to 62 buyers ---------------------------------------
#
# Censused 2026-08-14 against R2 (the live objects the listings point at, not publish/bundles):
# 62 of 62 live packs carry `- **Evidence goes stale after:** <ISO stamp>` in QA_Report.md,
# verbatim — the prose pass never rewrote it. That is what makes a one-line rewrite of an
# already-sold deliverable safe to do deterministically, with no model call.
#
# Since 2026-08-15 the rewritten QA_Report.md is not itself shipped: it is the input the reader
# and the PDF are composed from. So these tests moved down one level, to `patched_md` (the
# function that actually performs the rewrite) and up one level, to index.html (what the buyer
# actually reads). The middle level they used to sit at — the .md entry in the zip — is gone.

LEGACY = "- **Evidence goes stale after:** 2026-09-12T12:46:19.062428+00:00"


def _bundle_with_legacy_footer():
    return _zip([
        (n, f"# {n}\nbody of {n}" + (f"\n\n## Run details\n\n{LEGACY}\n" if n == "QA_Report.md" else ""))
        for n in WRITE_ORDER
    ])


def test_the_retired_expiry_line_is_rewritten_in_the_document_the_pack_is_rendered_from():
    """Was `..._in_the_shipped_deliverable`; the deliverable is no longer shipped, so the
    assertion is made against `patched_md`, which is the function that does the rewrite and is
    the input to every rendered file in the archive.

    The wording is the point, not just the deletion: `reverify_due_at` is an internal scheduling
    field (`run.py:813`), and printed as "Evidence goes stale after" it reads to a buyer as a
    warranty with a cliff — bought on day 28, the document says three days left.
    """
    src = zipfile.ZipFile(io.BytesIO(_bundle_with_legacy_footer()))
    qa = patched_md("QA_Report.md", src.read("QA_Report.md")).decode("utf-8")
    assert "goes stale after" not in qa
    assert "- **Next evidence check:** 2026-09-12" in qa
    assert "we take the pack off sale" in qa


def test_the_rewrite_touches_one_line_in_one_document_and_nothing_else():
    """Was `test_every_other_deliverable_is_still_byte_identical`, asserted over the output zip.
    No deliverable is shipped as itself any more, so the same property is asserted where the
    rewrite actually happens.

    The exception is one line in one file. A rewrite that touched anything else would be editing
    documents people paid for — and that is still true even though the edit now reaches them
    through the reader rather than as bytes they can diff.
    """
    src = zipfile.ZipFile(io.BytesIO(_bundle_with_legacy_footer()))
    for name in src.namelist():
        raw = src.read(name)
        if name == "QA_Report.md":
            assert patched_md(name, raw) != raw, "precondition: this is the file that changes"
            continue
        assert patched_md(name, raw) == raw, name


def test_the_reader_shows_the_rewritten_text_not_the_original():
    """index.html is rendered FROM the deliverables, so a fix applied to the .md and not to the
    reader would leave the retired promise on the page most buyers actually open. Since
    2026-08-15 the reader is the ONLY place a buyer meets this text, so this test carries the
    whole guarantee rather than half of it."""
    out = rebuild_zip_with_index(_bundle_with_legacy_footer(), META, _dossier(), "x" * 16)
    html = _reader(out)
    assert "goes stale after" not in html
    assert "Next evidence check" in html
    assert "we take the pack off sale" in html


def test_a_pack_needing_only_the_rewrite_is_not_reported_already_correct():
    """The trap this pins: a pack backfilled last week has a correct reader and a correct
    manifest, so a check on the two GENERATED files alone returns None and the buyer's own
    document keeps saying its evidence expires."""
    src = _bundle_with_legacy_footer()
    corrected = rebuild_zip_with_index(src, META, _dossier(), "x" * 16)
    # Put the current reader back beside the ORIGINAL, unrewritten deliverables.
    z = zipfile.ZipFile(io.BytesIO(corrected))
    old = zipfile.ZipFile(io.BytesIO(src))
    reader_ok_but_stale_md = _zip(
        [(n, old.read(n)) for n in old.namelist()] + [("index.html", z.read("index.html"))])
    out = rebuild_zip_with_index(reader_ok_but_stale_md, META, _dossier(), "x" * 16)
    assert out is not None
    assert "goes stale after" not in _reader(out)


def test_rerunning_over_a_converted_legacy_footer_pack_is_a_no_op():
    """Was `test_rerunning_the_rewrite_is_a_no_op`. The name is now honest about what makes it a
    no-op: not that the rewrite declines to fire twice (it is idempotent by construction — see
    `test_a_bundle_without_the_line_is_untouched_by_it`), but that the converted pack has no .md
    for it to fire ON."""
    once = rebuild_zip_with_index(_bundle_with_legacy_footer(), META, _dossier(), "x" * 16)
    assert once is not None
    assert rebuild_zip_with_index(once, META, _dossier(), "x" * 16) is None


def test_a_bundle_without_the_line_is_untouched_by_it():
    from prospector import dossier as dz
    assert dz.rewrite_legacy_shelf_life("# nothing to see\n") is None


# ------------------------------------------------------------------------------------ P4
# `Evidence_and_Constraints.md` — the evidence stated once, added to packs already sold.
# It is rendered from the DOSSIER, which is the same reason the manifest is: the evidence
# lives in store/dossiers, never in the shipped zip. So the rule is the manifest's rule —
# with a dossier the evidence is added, without one it is not invented.
#
# Since 2026-08-15 it is a SECTION rather than an entry: composed into the reading order and
# delivered through index.html and the PDF, in NEITHER BUNDLE_FILES nor BUNDLE_BONUS_FILES.

def test_a_dossier_adds_the_consolidated_evidence_section():
    """Was `test_a_dossier_adds_the_consolidated_evidence_document`, which read the file out of
    the zip. The document is still rendered by the shared `pack_reference` module — so a
    backfilled pack and a fresh one carry identical text — but it reaches the buyer as a
    section of the reader, and is not an archive entry at all."""
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    z = zipfile.ZipFile(io.BytesIO(out))
    html = z.read("index.html").decode("utf-8")

    assert pack_reference.FILENAME not in z.namelist()
    assert _SECTION_TITLES[pack_reference.FILENAME] in html
    assert "https://example.gov.uk/x" in html, "the cited source must reach the buyer"


def test_the_new_document_is_read_before_the_qa_report_not_appended_last():
    """A file appended to the end of a zip lands at the end of the read. The reader order comes
    from BUNDLE_READING_ORDER, so the evidence arrives immediately before the report that
    scores it — which is the whole point of consolidating it."""
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    html = zipfile.ZipFile(io.BytesIO(out)).read("index.html").decode("utf-8")
    assert html.index("Evidence and Constraints") < html.index(_SECTION_TITLES["QA_Report.md"])


def test_with_nothing_proven_the_evidence_section_is_not_invented():
    """Was `test_without_a_dossier_the_document_is_not_invented`. "Without a dossier" is now the
    whole-pack no-op (`test_without_a_dossier_the_pack_is_left_exactly_as_it_is`), so this test
    would have become a duplicate of it.

    The rule it actually carried survives one level in, and is the more interesting half: an
    evidence document with no evidence in it is worse than no document. A dossier with no checks
    renders "" from `pack_reference`, and the section is then absent from the reader — the pack
    still converts, it just does not claim to have evidence it has not got.
    """
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(checks=False), "x" * 16)
    assert out is not None, "a pack with a thin record still gets converted"
    html = _reader(out)
    assert _SECTION_TITLES[pack_reference.FILENAME] not in html


def test_every_other_document_still_reaches_the_reader_beside_it():
    """Was `test_the_promised_deliverables_are_still_byte_identical_beside_it`, over the eight
    .md entries in the output zip. Adding a section is not licence to disturb the documents that
    were sold; the bytes are no longer shipped, so the assertion is that every document's text
    still arrives, unaltered, in what the buyer reads.

    One document is a declared exception and is asserted separately below: the action document,
    which every bundle on disk shipped as the same six-line template.
    """
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    html = _reader(out)
    for name in BODY_BEARING:
        assert f"body of {name}" in html, name
        assert _SECTION_TITLES[name] in html, name


def test_the_action_document_is_rewritten_rather_than_copied():
    """The one deliverable this tool rewrites. Measured 2026-08-13, 127 of 127 bundles on disk
    carried the identical six-line template (`pack_floors.first_week_checklist_md`), addressed
    to somebody auditing the engine rather than to the buyer. Copying it byte-identical would
    have meant the fix reached new packs only.

    Re-pointed 2026-08-15 from the zip entry to the reader. The equality against
    `pack_checklist.render` is kept in the same spirit it was written in — it must be the module
    the generator calls, so a backfilled pack and a fresh one carry the identical document — by
    asserting the rendered body reaches index.html and the original template's does not.
    """
    src = _full_bundle()
    out = rebuild_zip_with_index(src, META, _dossier(), "x" * 16)
    html = _reader(out)

    docs = {n: f"# {n}\nbody of {n}" for n in WRITE_ORDER}
    rendered = pack_checklist.render(_dossier(), docs)
    assert rendered, "precondition: this pack gives the checklist something to point at"

    assert "body of 05_First_Week_Checklist.md" not in html, (
        "the original template was copied through instead of being rewritten")
    assert "Ten working days" in rendered and "Ten working days" in html
    assert "QA report" not in rendered


def test_the_checklist_is_rendered_from_the_documents_not_guessed():
    """Was `test_without_a_dossier_the_action_document_is_left_alone`. "Without a dossier" now
    means the pack is not converted at all, so that setup can no longer distinguish anything —
    the assertion would have been about a zip that does not exist.

    The property underneath it was that the derivation NEEDS the record and never guesses: the
    checklist points at what this pack actually contains. That is asserted directly, on the
    renderer, where it is now observable — the same shared module the generator calls.
    """
    docs = {n: f"# {n}\nbody of {n}" for n in WRITE_ORDER}
    rendered = pack_checklist.render(_dossier(), docs)
    assert rendered.startswith("# Your first fortnight")
    assert "T" in rendered, "the pack's own title, from the record, not a template"


def test_rerunning_with_the_document_already_present_is_a_no_op():
    once = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    assert rebuild_zip_with_index(once, META, _dossier(), "x" * 16) is None
