"""Every entry a bundle ships is declared somewhere.

The defect this pins: the storefront advertised "8 files" while the archive held nine or ten
entries (measured 2026-08-08 across the 45 packs then live: 33 carried index.html, 19 carried
manifest.jsonld, entry counts 8/9/10 = 12/14/19 packs). Two mechanisms were in place and NEITHER
could see it:

  * `packContents.test.ts` compares `PACK_CONTENTS` to `BUNDLE_FILES` — two lists of INTENT, in
    source. It never opens a zip.
  * `audit_bundle` opens the zip, but iterates BUNDLE_FILES asking "did it arrive?". An entry in
    no list is invisible to it by construction, and `test_bundle_index_html.py` asserts exactly
    that blindness on purpose, because a bonus file must never read as a completeness failure.

So the pair covered "is every promised file present" and left "is anything else present" to
nobody. `BUNDLE_BONUS_FILES` + `undeclared_bundle_entries` close that side, and these tests are
what make the registry load-bearing rather than a comment.

2026-08-15: the archive stopped being markdown. `BUNDLE_FILES` is now the rendered pack
(index.html, Complete_Pack.pdf, First_Fortnight.html, Assumptions.csv, Marketing_Assets.txt)
and `PACK_DOCUMENTS` is the render input, which reaches the buyer only through those files.
`TestNoMarkdownReachesTheBuyer` at the bottom is the regression guard for that whole change —
the founder's requirement was one sentence ("i dont like md files at all, we are not selling to
developers") and it is one assertion.
"""

import zipfile

import pytest

from prospector.bridge import (
    BUNDLE_BONUS_FILES,
    BUNDLE_FILES,
    PACK_DOCUMENTS,
    EngineBridge,
    audit_bundle,
    undeclared_bundle_entries,
)
from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict


def _write_zip(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            # Comfortably over _MIN_BUNDLE_ENTRY_BYTES so nothing here reads as a stub.
            z.writestr(name, "x" * 400)
    return str(path)


class TestBonusRegistry:
    def test_bonus_files_are_not_also_deliverables(self):
        """The two lists must be disjoint or the count they support is ambiguous."""
        assert not set(BUNDLE_FILES) & set(BUNDLE_BONUS_FILES)

    def test_manifest_filename_matches_pack_manifest(self):
        """The registry duplicates this string rather than importing it (flat import graph).

        A duplicate that nothing checks is how the original drift happened, so check it.
        """
        from prospector import pack_manifest

        assert pack_manifest.MANIFEST_FILENAME in BUNDLE_BONUS_FILES

    def test_the_reader_is_a_promised_deliverable_not_a_bonus(self):
        """Renamed and inverted 2026-08-15 (was `test_reader_filename_is_declared`, which
        asserted `"index.html" in BUNDLE_BONUS_FILES`).

        index.html was a bonus while the renderer was new and unproven: a fault in it must not
        be able to delist a pack whose eight markdown deliverables had all arrived. It is not
        unproven now (all 59 live packs carry it, measured against the objects R2 serves), and
        it is no longer additive — it is the pack. So the consequence is inverted on purpose:
        a bundle without a reader has nothing readable in it at all, and `audit_bundle` must
        hold it UNLISTED rather than wave it through.

        `_create_bundle` still writes the literal "index.html"; the contract carries that
        literal, which is what this test checks.
        """
        assert "index.html" in BUNDLE_FILES
        assert "index.html" not in BUNDLE_BONUS_FILES


class TestUndeclaredEntries:
    def test_a_complete_bundle_with_no_bonus_files_is_clean(self, tmp_path):
        path = _write_zip(tmp_path / "plain.zip", list(BUNDLE_FILES))
        assert undeclared_bundle_entries(path) == []

    def test_the_bonus_files_are_not_reported(self, tmp_path):
        """The real shape of a current bundle: every contract file plus every declared bonus."""
        path = _write_zip(tmp_path / "full.zip", list(BUNDLE_FILES) + list(BUNDLE_BONUS_FILES))
        assert undeclared_bundle_entries(path) == []

    def test_an_undeclared_entry_is_named(self, tmp_path):
        """The assertion that would have caught the "8 files" claim."""
        path = _write_zip(tmp_path / "extra.zip", list(BUNDLE_FILES) + ["BONUS_Offer.pdf"])
        assert undeclared_bundle_entries(path) == ["BONUS_Offer.pdf"]

    def test_several_undeclared_entries_come_back_sorted(self, tmp_path):
        path = _write_zip(tmp_path / "many.zip", list(BUNDLE_FILES) + ["z.txt", "a.txt"])
        assert undeclared_bundle_entries(path) == ["a.txt", "z.txt"]

    def test_a_missing_zip_yields_no_findings_rather_than_raising(self, tmp_path):
        """This runs on the register-unlisted retry path; a diagnostic that throws kills it.

        "The zip is missing" is `audit_bundle`'s answer to give, and it gives it.
        """
        missing = str(tmp_path / "nope.zip")
        assert undeclared_bundle_entries(missing) == []
        assert audit_bundle(missing) == (list(BUNDLE_FILES), [])

    def test_an_unreadable_zip_yields_no_findings_rather_than_raising(self, tmp_path):
        corrupt = tmp_path / "corrupt.zip"
        corrupt.write_bytes(b"not a zip at all")
        assert undeclared_bundle_entries(str(corrupt)) == []


class TestTheTwoAuditsAreComplementary:
    """Neither function alone answers "does the archive match what the shop claims"."""

    @pytest.fixture
    def bundle_with_a_stray_file(self, tmp_path):
        return _write_zip(tmp_path / "stray.zip", list(BUNDLE_FILES) + ["stray.bin"])

    def test_audit_bundle_is_blind_to_a_stray_file(self, bundle_with_a_stray_file):
        """Documents the blindness rather than fixing it: a surplus file is not incompleteness,
        and making it one would delist complete packs. This is why the second function exists."""
        assert audit_bundle(bundle_with_a_stray_file) == ([], [])

    def test_undeclared_entries_sees_it(self, bundle_with_a_stray_file):
        assert undeclared_bundle_entries(bundle_with_a_stray_file) == ["stray.bin"]


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    """_create_bundle writes to a relative publish/bundles path — keep it out of the repo."""
    monkeypatch.chdir(tmp_path)

    class _Cfg:
        entitlements_api_key = ""
        store_payments = {"active_provider": "stripe"}

    return EngineBridge(_Cfg())


def _dossier():
    cand = Candidate(
        candidate_id="d" * 16,
        title="Classification scheduling for UK oyster farms",
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


class TestNoMarkdownReachesTheBuyer:
    """THE REGRESSION GUARD for the 2026-08-15 change, stated as the founder stated it.

    "i dont like md files at all, we are not selling to developers." Everything else about that
    change — five contract files instead of eight, `PACK_DOCUMENTS` as render input, the reading
    order derived from it, `Marketing_Assets.txt` as the one editable concession — is machinery
    in service of this one observable property, so it gets its own assertion rather than being
    implied by a set comparison somewhere else.

    Asserted on a bundle the engine actually BUILT, not on the tuples: the tuples are intent in
    source (that is exactly what `packContents.test.ts` already checks and what let the "8 files"
    claim drift), and only the written archive can answer what a buyer receives.
    """

    def test_a_freshly_built_bundle_contains_no_markdown_entry_whatsoever(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        with zipfile.ZipFile(path) as zf:
            entries = zf.namelist()

        assert not [n for n in entries if n.endswith(".md")], (
            f"markdown reached the buyer's zip: {[n for n in entries if n.endswith('.md')]}")
        # The documents still exist — as the render input. None of them is an archive entry,
        # and the second half of that sentence is the half a buyer can observe.
        assert not (set(PACK_DOCUMENTS) & set(entries))
        # And nothing was quietly substituted in their place: the archive is exactly what the
        # two registries declare, no more and no less.
        assert set(entries) == set(BUNDLE_FILES) | set(BUNDLE_BONUS_FILES)
