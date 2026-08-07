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

from prospector.bridge import BUNDLE_FILES
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
    assert src.namelist() == ["01_Playbook.md", "QA_Report.md", "index.html"]
    for name, content in entries:
        assert src.read(name) == content.encode("utf-8")
    html = src.read("index.html").decode("utf-8")
    assert "<strong>bold</strong>" in html


def test_returns_none_only_when_the_existing_reader_is_already_correct():
    bundle = _full_bundle()
    correct = zipfile.ZipFile(io.BytesIO(rebuild_zip_with_index(bundle, META))).read("index.html")
    already = _zip([(n, f"# {n}\nbody of {n}") for n in WRITE_ORDER] + [("index.html", correct)])
    assert rebuild_zip_with_index(already, META) is None


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
    assert names == WRITE_ORDER + ["index.html"]


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

from prospector import pack_manifest  # noqa: E402
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
