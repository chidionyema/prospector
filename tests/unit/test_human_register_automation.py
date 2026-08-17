"""The human-register coverage automation, driven against a store built in tmp_path.

Every `scan()` here joins the SHIPPED declaration onto tmp_path, so nothing reads the
operator's real store. The declaration is loaded rather than copied: a duplicated
`"store/dossiers"` literal reads to `test_suite_is_machine_independent.py` exactly like a test
that does read the real store, and it cannot tell the two apart. Loading also buys a second
thing — renaming a key in the yaml fails these tests instead of leaving them green against a
shape the automation no longer has.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.automations.human_register import (
    BLOCK_KEY,
    CannotEstablish,
    Declaration,
    load_declaration,
    scan,
)

DECL_PATH = (
    Path(__file__).resolve().parents[2] / "ops" / "config" / "human_register.yaml"
)

# Enough real sentences for the measures to mean something. Short strings make every metric
# degenerate, which would let a broken measurement pass as "no findings".
PROSE = (
    "The first job is to price the sign, not to design it. Ring three sign printers and "
    "ask for a quote on two hundred units of the same size. Write the three numbers down. "
    "The cheapest quote is your floor, and the sale price has to clear it twice over before "
    "the work is worth doing. Do this before you spend a penny on artwork. "
    "Councils publish their recycling rules on their own websites. Read four of them and "
    "note where the rules differ, because that difference is the whole product. A landlord "
    "with flats in two boroughs needs two signs, and nobody sells them the pair today. "
    "Start with one borough. Get ten orders. Then add the second."
)


def _decl(tmp_path: Path) -> Declaration:
    """The shipped declaration, pointed at a store built for this test."""
    decl = load_declaration(DECL_PATH)
    (tmp_path / decl.store_dir).mkdir(parents=True, exist_ok=True)
    return decl


def _write_pack(tmp_path: Path, decl: Declaration, pid: str, *, prose: bool = True,
                dossier: bool = True, block: dict | None = None) -> Path:
    store = tmp_path / decl.store_dir
    lint = store / f"{pid}.lint.json"
    report: dict = {"pack_id": pid, "findings": []}
    if block is not None:
        report[BLOCK_KEY] = block
    lint.write_text(json.dumps(report), encoding="utf-8")

    if dossier:
        arts = {t: PROSE for t in decl.prose_types} if prose else {}
        doc: dict = {}
        node = doc
        for key in decl.artifacts_path[:-1]:
            node[key] = {}
            node = node[key]
        node[decl.artifacts_path[-1]] = arts
        (store / f"{pid}{decl.dossier_suffixes[0]}").write_text(
            json.dumps(doc), encoding="utf-8")
    return lint


def test_fires_on_the_broken_state(tmp_path: Path) -> None:
    """A lint record with no block, and prose still on disk, is a finding."""
    decl = _decl(tmp_path)
    _write_pack(tmp_path, decl, "aaaa1111")

    result = scan(decl, tmp_path)

    assert len(result["findings"]) == 1
    assert result["findings"][0].where.endswith("aaaa1111.lint.json")
    assert BLOCK_KEY in result["findings"][0].what
    assert result["summary"]["carrying_the_block"] == 0
    assert result["summary"]["written"] == 0


def test_report_mode_writes_nothing(tmp_path: Path) -> None:
    decl = _decl(tmp_path)
    lint = _write_pack(tmp_path, decl, "aaaa1111")
    before = lint.read_text(encoding="utf-8")

    scan(decl, tmp_path)

    assert lint.read_text(encoding="utf-8") == before


def test_fix_writes_the_block_and_clears_the_finding(tmp_path: Path) -> None:
    decl = _decl(tmp_path)
    lint = _write_pack(tmp_path, decl, "aaaa1111")

    result = scan(decl, tmp_path, fix=True)

    assert result["findings"] == []
    assert result["summary"]["written"] == 1
    written = json.loads(lint.read_text(encoding="utf-8"))
    block = written[BLOCK_KEY]
    assert set(block) >= {"measures", "outside", "error", "backfilled", "corpus"}
    assert block["backfilled"] is True
    assert block["corpus"] == "prose_artifacts"
    assert isinstance(block["measures"], dict) and block["measures"]
    # The record it was written into survives intact.
    assert written["pack_id"] == "aaaa1111"

    # And a second pass is clean, so the automation is idempotent.
    again = scan(decl, tmp_path)
    assert again["findings"] == []
    assert again["summary"]["carrying_the_block"] == 1


def test_a_record_already_carrying_the_block_is_not_rewritten(tmp_path: Path) -> None:
    decl = _decl(tmp_path)
    lint = _write_pack(tmp_path, decl, "aaaa1111",
                       block={"measures": {"mattr": 0.5}, "outside": [], "error": None})

    result = scan(decl, tmp_path, fix=True)

    assert result["summary"]["written"] == 0
    assert json.loads(lint.read_text(encoding="utf-8"))[BLOCK_KEY]["measures"] == {"mattr": 0.5}


def test_missing_source_is_unmeasurable_not_a_finding(tmp_path: Path) -> None:
    """No dossier, or a dossier with no prose. Nothing can measure these, so a red line
    would be one nobody can act on."""
    decl = _decl(tmp_path)
    _write_pack(tmp_path, decl, "bbbb2222", dossier=False)
    _write_pack(tmp_path, decl, "cccc3333", prose=False)

    result = scan(decl, tmp_path, fix=True)

    assert result["findings"] == []
    assert len(result["unmeasurable"]) == 2
    assert result["summary"]["written"] == 0
    reasons = " ".join(f.what for f in result["unmeasurable"])
    assert "no dossier on disk" in reasons
    assert "no prose to measure" in reasons


def test_outside_the_range_is_counted_not_reported_as_a_finding(tmp_path: Path) -> None:
    decl = _decl(tmp_path)
    _write_pack(tmp_path, decl, "aaaa1111")

    result = scan(decl, tmp_path, fix=True)

    assert result["findings"] == []
    assert isinstance(result["summary"]["outside_the_human_range"], int)
    assert isinstance(result["summary"]["per_measure"], dict)


def test_a_missing_store_is_unknown_never_clean(tmp_path: Path) -> None:
    decl = load_declaration(DECL_PATH)
    with pytest.raises(CannotEstablish):
        scan(decl, tmp_path / "nowhere")


def test_the_shipped_declaration_loads(tmp_path: Path) -> None:
    decl = load_declaration(DECL_PATH)
    assert decl.store_dir
    assert decl.prose_types
    assert decl.dossier_suffixes
    assert decl.artifacts_path
