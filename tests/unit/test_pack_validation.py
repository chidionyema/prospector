"""Auto-verification gate: a pack may only be listed when its deliverable is complete."""
from __future__ import annotations

from prospector.pack_validation import (
    MIN_ARTIFACT_CHARS,
    PROSE_ARTIFACTS,
    REQUIRED_ARTIFACTS,
    validate_pack,
)


def _prose_body() -> str:
    """A genuine prose artifact: several titled sections, well over the substance floor."""
    para = "x" * 220
    return f"## Overview\n\n{para}\n\n## Plan\n\n{para}\n\n## Risks\n\n{para}"


def _full_artifacts() -> dict:
    # Prose artifacts must be substantial + multi-section; financial_model (Python-rendered)
    # only needs to clear the basic floor.
    arts = {name: _prose_body() for name in PROSE_ARTIFACTS}
    arts["financial_model"] = "x" * (MIN_ARTIFACT_CHARS + 50)
    return arts


def _listing() -> list:
    return [{"type": "listing_page", "copy": "y" * 200}]


def test_complete_pack_passes():
    ok, problems = validate_pack(_full_artifacts(), _listing())
    assert ok, problems
    assert problems == []


def test_empty_artifact_fails():
    arts = _full_artifacts()
    arts["ops_plan"] = ""
    ok, problems = validate_pack(arts, _listing())
    assert not ok
    assert any("ops_plan" in p for p in problems)


def test_stub_artifact_fails():
    """The exact flakiness mode: a tier returns a tiny stub instead of real content."""
    arts = _full_artifacts()
    arts["gtm_plan"] = "TODO"
    ok, problems = validate_pack(arts, _listing())
    assert not ok
    assert any("gtm_plan" in p for p in problems)


def test_missing_artifact_key_fails():
    arts = _full_artifacts()
    del arts["financial_model"]
    ok, problems = validate_pack(arts, _listing())
    assert not ok
    assert any("financial_model" in p for p in problems)


def test_missing_listing_page_fails():
    ok, problems = validate_pack(_full_artifacts(), [])
    assert not ok
    assert any("listing_page" in p for p in problems)


def test_thin_long_blob_fails():
    """A long-but-hollow artifact: clears the 200-char floor but is one undifferentiated
    block under the substance bar. This is the boilerplate-blob case the gate now catches."""
    arts = _full_artifacts()
    arts["build_spec"] = "x" * 250  # > MIN_ARTIFACT_CHARS, but 1 block and < 600 chars
    ok, problems = validate_pack(arts, _listing())
    assert not ok
    assert any("build_spec" in p and "thin" in p for p in problems)


def test_three_empty_one_good_fails():
    """The luck case that motivated the gate: only 1/4 artifacts generated."""
    arts = {
        "build_spec": "",
        "gtm_plan": "",
        "ops_plan": "",
        "financial_model": "x" * 2000,
    }
    ok, problems = validate_pack(arts, _listing())
    assert not ok
    assert len(problems) >= 3
