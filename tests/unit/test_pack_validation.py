"""Auto-verification gate: a pack may only be listed when its deliverable is complete."""
from __future__ import annotations

from prospector.pack_validation import (
    MIN_ARTIFACT_CHARS,
    REQUIRED_ARTIFACTS,
    validate_pack,
)


def _full_artifacts() -> dict:
    body = "x" * (MIN_ARTIFACT_CHARS + 50)
    return {name: body for name in REQUIRED_ARTIFACTS}


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
