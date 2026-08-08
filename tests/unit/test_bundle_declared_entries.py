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
"""

import zipfile

import pytest

from prospector.bridge import (
    BUNDLE_BONUS_FILES,
    BUNDLE_FILES,
    audit_bundle,
    undeclared_bundle_entries,
)


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

    def test_reader_filename_is_declared(self):
        """`_create_bundle` writes the literal "index.html"; the registry must carry that literal."""
        assert "index.html" in BUNDLE_BONUS_FILES


class TestUndeclaredEntries:
    def test_a_complete_bundle_with_no_bonus_files_is_clean(self, tmp_path):
        path = _write_zip(tmp_path / "plain.zip", list(BUNDLE_FILES))
        assert undeclared_bundle_entries(path) == []

    def test_the_bonus_files_are_not_reported(self, tmp_path):
        """The real shape of a current bundle: eight deliverables plus both bonus files."""
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
