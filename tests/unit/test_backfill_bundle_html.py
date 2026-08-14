"""The backfill's one transformation, proven on bytes.

The tool's promise to buyers and to the catalogue is that a converted bundle differs from the
original only in its generated index.html — every .md deliverable of record survives
byte-identical. Everything else in tools/backfill_bundle_html.py is plumbing around this.

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
from prospector.bridge import _SECTION_TITLES, BUNDLE_BONUS_FILES, BUNDLE_FILES
from prospector.pack_html import PackMeta
from tools.backfill_bundle_html import ordered_md_entries, rebuild_zip_with_index

META = PackMeta(title="T", one_liner="o", verified_at="2026-07-31", source_count=3, pack_id="x")

# The order bridge actually writes the bundle in — deliberately not the reading order.
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


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in entries:
            z.writestr(name, content)
    return buf.getvalue()


def _full_bundle(extra=()):
    """A bundle in bridge's real write order, each file naming itself."""
    return _zip([(n, f"# {n}\nbody of {n}") for n in WRITE_ORDER] + list(extra))


def test_adds_index_html_and_keeps_every_entry_byte_identical():
    entries = [
        ("01_Playbook.md", "# One\n**bold** stays *markdown* in the .md"),
        ("QA_Report.md", "| a | b |\n|---|---|\n| 1 | 2 |"),
    ]
    out = rebuild_zip_with_index(_zip(entries), META)

    src = zipfile.ZipFile(io.BytesIO(out))
    names = src.namelist()
    # The originals, in their original order, before anything generated. Asserted as a prefix
    # rather than as the whole list: what the tool ADDS grows with BUNDLE_BONUS_FILES (index.html
    # in 2026-07, four more by 2026-08), and a literal here fails on the day a bonus file ships
    # rather than on the day a deliverable is disturbed — which is the only event it exists for.
    assert names[:len(entries)] == [n for n, _ in entries]
    for name, content in entries:
        assert src.read(name) == content.encode("utf-8")
    added = names[len(entries):]
    assert "index.html" in added
    assert set(added) <= set(BUNDLE_BONUS_FILES), f"undeclared entry added: {added}"
    html = src.read("index.html").decode("utf-8")
    assert "<strong>bold</strong>" in html


def test_returns_none_only_when_the_existing_reader_is_already_correct():
    """Idempotence, stated as a round trip rather than by hand-building the "already correct"
    bundle. The hand-built version had to enumerate every generated entry, so it silently became
    a test that the tool adds EXACTLY index.html — and on 2026-08-14 it failed for the PDF, a
    file it was never about. Feeding the tool its own output cannot drift that way.
    """
    once = rebuild_zip_with_index(_full_bundle(), META)
    assert once is not None
    assert rebuild_zip_with_index(once, META) is None

    # The other half of "only": a bundle whose reader is WRONG must still be rebuilt, or the
    # None above would be indistinguishable from a tool that never does anything.
    stale = _zip([(n, f"# {n}\nbody of {n}") for n in WRITE_ORDER] + [("index.html", "<p>old</p>")])
    assert rebuild_zip_with_index(stale, META) is not None


def test_reading_order_follows_the_contract_not_the_zips_write_order():
    """The fix, stated as the property. This is the test the old suite had backwards."""
    out = rebuild_zip_with_index(_full_bundle(), META)
    html = zipfile.ZipFile(io.BytesIO(out)).read("index.html").decode("utf-8")

    positions = [html.index(f"body of {name}") for name in BUNDLE_FILES]
    assert positions == sorted(positions), (
        "index.html must read in BUNDLE_FILES order; got "
        f"{[n for _, n in sorted(zip(positions, BUNDLE_FILES))]}"
    )

    # The two that motivated the fix, named explicitly so a regression says which.
    assert html.index("body of 00_Executive_Summary.md") < html.index("body of 01_Blueprint_BuildSpec.md")
    assert html.index("body of 05_First_Week_Checklist.md") > html.index("body of 04_Financial_Model.md")
    assert html.index("body of QA_Report.md") == max(positions)


def test_zip_entry_order_is_still_left_alone():
    """Reading order changed; the archive did not. The .md bytes AND their order are of record."""
    out = rebuild_zip_with_index(_full_bundle(), META)
    names = zipfile.ZipFile(io.BytesIO(out)).namelist()
    assert names[:len(WRITE_ORDER)] == WRITE_ORDER
    assert set(names[len(WRITE_ORDER):]) <= set(BUNDLE_BONUS_FILES)


def test_titles_match_the_generator_not_the_filenames():
    src = zipfile.ZipFile(io.BytesIO(_full_bundle()))
    titles = [t for t, _ in ordered_md_entries(src)]
    assert titles[0] == "Executive Summary"
    assert "00_Executive_Summary" not in titles


def test_a_stale_reader_is_corrected_rather_than_skipped():
    """The idempotency change. Every pack listed today carries a write-order reader."""
    stale = _full_bundle(extra=[("index.html", "<p>old write-order reader</p>")])
    out = rebuild_zip_with_index(stale, META)
    assert out is not None, "a wrong index.html must be corrected, not treated as already done"

    z = zipfile.ZipFile(io.BytesIO(out))
    assert z.namelist().count("index.html") == 1, "must never leave two readers in the zip"
    html = z.read("index.html").decode("utf-8")
    assert "old write-order reader" not in html
    assert html.index("body of 00_Executive_Summary.md") < html.index("body of 01_Blueprint_BuildSpec.md")


def test_rerunning_on_a_corrected_bundle_is_a_no_op():
    once = rebuild_zip_with_index(_full_bundle(), META)
    assert rebuild_zip_with_index(once, META) is None


def test_an_unknown_md_is_rendered_at_the_end_never_dropped():
    out = rebuild_zip_with_index(_full_bundle(extra=[("99_Bonus.md", "# B\nbody of 99_Bonus.md")]), META)
    html = zipfile.ZipFile(io.BytesIO(out)).read("index.html").decode("utf-8")
    assert "body of 99_Bonus.md" in html
    assert html.index("body of 99_Bonus.md") > html.index("body of QA_Report.md")


# --- manifest.jsonld backfill -------------------------------------------------------------------
# The second generated file. index.html can be rebuilt from the zip alone; the manifest cannot,
# because the evidence it carries (checks, verdicts, cited passages) lives only in store/dossiers.
# That asymmetry is the whole reason these tests exist separately from the ones above.

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


def _dossier_dict():
    cand = Candidate(candidate_id="x" * 16, title="T", one_liner="o", market="uk",
                     who_pays="operators", why_now="new rules")
    check = CheckResult(
        check_name="buyer_intent", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale="Growers search for closure guidance.",
        citations=["s1"],
        sources=[Source(source_id="s1", url="https://example.gov.uk/x", text="Notices are weekly.")],
    )
    return Dossier(candidate=cand, decision=Decision.PASS, checks=[check],
                   created_at="2026-07-31T00:00:00Z").to_dict()


def _dossier():
    return pack_manifest.dossier_from_dict(_dossier_dict())


def test_a_dossier_adds_a_manifest_whose_digests_match_the_shipped_bytes():
    """The manifest's digests must be of the bytes IN THE ZIP, not of a decode round-trip.

    The reader path decodes entries with errors="replace"; a digest taken over that string would
    differ from the file it describes on any byte the codec could not round-trip, turning the one
    file whose job is to be machine-checkable into the one file that fails its own check.
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
    assert reader["prospector:promisedDeliverable"] is False


def test_without_a_dossier_no_manifest_is_invented():
    """An EMPTY evidence record reads, to an agent, as a pack that was never verified — strictly
    worse than no manifest, because absence is honest. A pack whose dossier is gone still gets its
    reader fixed."""
    out = rebuild_zip_with_index(_full_bundle(), META)
    names = zipfile.ZipFile(io.BytesIO(out)).namelist()
    assert pack_manifest.MANIFEST_FILENAME not in names
    assert "index.html" in names


def test_a_correct_reader_with_no_manifest_still_converts():
    """The idempotency check is an AND. Every pack listed today has a reader and no manifest; a
    presence test on index.html alone would skip all of them and the feature would reach nobody."""
    once = rebuild_zip_with_index(_full_bundle(), META)
    assert rebuild_zip_with_index(once, META) is None, "precondition: reader already correct"
    out = rebuild_zip_with_index(once, META, _dossier(), "x" * 16)
    assert out is not None
    assert pack_manifest.MANIFEST_FILENAME in zipfile.ZipFile(io.BytesIO(out)).namelist()


def test_rerunning_with_the_same_dossier_is_a_no_op():
    once = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    assert rebuild_zip_with_index(once, META, _dossier(), "x" * 16) is None


def test_a_shipped_manifest_is_never_dropped_because_the_dossier_went_missing():
    """Deleting evidence a buyer already has, because a local file moved, is data loss wearing a
    no-op's clothes."""
    once = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    stale = zipfile.ZipFile(io.BytesIO(once))
    kept = stale.read(pack_manifest.MANIFEST_FILENAME)
    # Force a rebuild with no dossier by breaking the reader.
    broken = _zip([(n, stale.read(n)) for n in stale.namelist() if n != "index.html"]
                  + [("index.html", b"<p>stale</p>")])
    out = rebuild_zip_with_index(broken, META)
    z = zipfile.ZipFile(io.BytesIO(out))
    assert z.read(pack_manifest.MANIFEST_FILENAME) == kept
    assert z.namelist().count(pack_manifest.MANIFEST_FILENAME) == 1


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

LEGACY = "- **Evidence goes stale after:** 2026-09-12T12:46:19.062428+00:00"


def _bundle_with_legacy_footer():
    return _zip([
        (n, f"# {n}\nbody of {n}" + (f"\n\n## Run details\n\n{LEGACY}\n" if n == "QA_Report.md" else ""))
        for n in WRITE_ORDER
    ])


def test_the_retired_expiry_line_is_rewritten_in_the_shipped_deliverable():
    out = rebuild_zip_with_index(_bundle_with_legacy_footer(), META)
    qa = zipfile.ZipFile(io.BytesIO(out)).read("QA_Report.md").decode("utf-8")
    assert "goes stale after" not in qa
    assert "- **Next evidence check:** 2026-09-12" in qa
    assert "we take the pack off sale" in qa


def test_every_other_deliverable_is_still_byte_identical():
    """The exception is one line in one file. A rewrite that touched anything else would be
    editing documents people paid for."""
    src = _bundle_with_legacy_footer()
    before = zipfile.ZipFile(io.BytesIO(src))
    after = zipfile.ZipFile(io.BytesIO(rebuild_zip_with_index(src, META)))
    for n in before.namelist():
        if n == "QA_Report.md":
            continue
        assert after.read(n) == before.read(n), n


def test_the_reader_shows_the_rewritten_text_not_the_original():
    """index.html is rendered FROM the deliverables, so a fix applied to the .md and not to the
    reader would leave the retired promise on the page most buyers actually open."""
    out = rebuild_zip_with_index(_bundle_with_legacy_footer(), META)
    html = zipfile.ZipFile(io.BytesIO(out)).read("index.html").decode("utf-8")
    assert "goes stale after" not in html
    assert "Next evidence check" in html


def test_a_pack_needing_only_the_rewrite_is_not_reported_already_correct():
    """The trap this pins: a pack backfilled last week has a correct reader and a correct
    manifest, so a check on the two GENERATED files alone returns None and the buyer's own
    document keeps saying its evidence expires."""
    src = _bundle_with_legacy_footer()
    corrected = rebuild_zip_with_index(src, META)
    # Put the current reader back beside the ORIGINAL, unrewritten deliverables.
    z = zipfile.ZipFile(io.BytesIO(corrected))
    old = zipfile.ZipFile(io.BytesIO(src))
    reader_ok_but_stale_md = _zip(
        [(n, old.read(n)) for n in old.namelist()] + [("index.html", z.read("index.html"))])
    out = rebuild_zip_with_index(reader_ok_but_stale_md, META)
    assert out is not None
    assert "goes stale after" not in zipfile.ZipFile(io.BytesIO(out)).read("QA_Report.md").decode()


def test_rerunning_the_rewrite_is_a_no_op():
    once = rebuild_zip_with_index(_bundle_with_legacy_footer(), META)
    assert rebuild_zip_with_index(once, META) is None


def test_a_bundle_without_the_line_is_untouched_by_it():
    from prospector import dossier as dz
    assert dz.rewrite_legacy_shelf_life("# nothing to see\n") is None


# ------------------------------------------------------------------------------------ P4
# `Evidence_and_Constraints.md` — the evidence stated once, added to packs already sold.
# It is rendered from the DOSSIER, which is the same reason the manifest is: the evidence
# lives in store/dossiers, never in the shipped zip. So the rule is the manifest's rule —
# with a dossier the file is added, without one it is not invented.

def test_a_dossier_adds_the_consolidated_evidence_document():
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    z = zipfile.ZipFile(io.BytesIO(out))
    body = z.read(pack_reference.FILENAME).decode("utf-8")
    assert body == pack_reference.render(_dossier()), "must be the shared renderer, not a copy"
    assert "https://example.gov.uk/x" in body


def test_the_new_document_is_read_before_the_qa_report_not_appended_last():
    """A file appended to the end of a zip lands at the end of the read. The reader order comes
    from BUNDLE_READING_ORDER, so the evidence arrives immediately before the report that
    scores it — which is the whole point of consolidating it."""
    out = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    html = zipfile.ZipFile(io.BytesIO(out)).read("index.html").decode("utf-8")
    assert html.index("Evidence and Constraints") < html.index(_SECTION_TITLES["QA_Report.md"])


def test_without_a_dossier_the_document_is_not_invented():
    """Same rule as the manifest: an evidence document with no evidence in it is worse than no
    document. A pack whose record is off disk still gets its reader and its footer fixed."""
    out = rebuild_zip_with_index(_full_bundle(), META)
    assert pack_reference.FILENAME not in zipfile.ZipFile(io.BytesIO(out)).namelist()


def test_the_promised_deliverables_are_still_byte_identical_beside_it():
    """Adding a file is not licence to touch the eight that were sold.

    One deliverable is a declared exception and is asserted separately below: the action
    document, which every bundle on disk shipped as the same six-line template.
    """
    src = _full_bundle()
    out = rebuild_zip_with_index(src, META, _dossier(), "x" * 16)
    old, new = zipfile.ZipFile(io.BytesIO(src)), zipfile.ZipFile(io.BytesIO(out))
    for name in BUNDLE_FILES:
        if name == pack_checklist.FILENAME:
            continue
        assert new.read(name) == old.read(name), name


def test_the_action_document_is_rewritten_rather_than_copied():
    """The one deliverable this tool rewrites. Measured 2026-08-13, 127 of 127 bundles on disk
    carried the identical six-line template (`pack_floors.first_week_checklist_md`), addressed
    to somebody auditing the engine rather than to the buyer. Copying it byte-identical would
    have meant the fix reached new packs only."""
    src = _full_bundle()
    out = rebuild_zip_with_index(src, META, _dossier(), "x" * 16)
    z = zipfile.ZipFile(io.BytesIO(out))
    body = z.read(pack_checklist.FILENAME).decode("utf-8")
    docs = {n: z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".md")}
    assert body == pack_checklist.render(_dossier(), docs), (
        "must be the module the generator calls, so a backfilled pack and a fresh one carry "
        "the identical document")
    assert "QA report" not in body


def test_without_a_dossier_the_action_document_is_left_alone():
    """Same rule as the evidence document and the manifest: the derivation needs the record.
    With no record the original ships untouched rather than a guess replacing it."""
    src = _full_bundle()
    out = rebuild_zip_with_index(src, META)
    old, new = zipfile.ZipFile(io.BytesIO(src)), zipfile.ZipFile(io.BytesIO(out))
    assert new.read(pack_checklist.FILENAME) == old.read(pack_checklist.FILENAME)


def test_rerunning_with_the_document_already_present_is_a_no_op():
    once = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    assert rebuild_zip_with_index(once, META, _dossier(), "x" * 16) is None


def test_a_pack_needing_only_the_evidence_document_is_not_reported_already_correct():
    """The presence trap again, one layer down: a pack backfilled BEFORE P4 has a correct reader
    and a correct manifest, so a check on the two generated files alone returns None and the
    buyer never receives the document. Idempotency is by CONTENT of everything shipped."""
    once = rebuild_zip_with_index(_full_bundle(), META, _dossier(), "x" * 16)
    z = zipfile.ZipFile(io.BytesIO(once))
    without = _zip([(n, z.read(n)) for n in z.namelist() if n != pack_reference.FILENAME])
    out = rebuild_zip_with_index(without, META, _dossier(), "x" * 16)
    assert out is not None
    assert pack_reference.FILENAME in zipfile.ZipFile(io.BytesIO(out)).namelist()
