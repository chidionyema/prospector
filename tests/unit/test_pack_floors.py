"""Claim-safe pack floors — no invented numbers, listing never empty stub."""
from __future__ import annotations

from prospector.models import Candidate, CheckResult, Verdict
from prospector.pack_floors import (
    claim_safe_marketing,
    ensure_marketing_floor,
    exec_summary_md,
    first_week_checklist_md,
)


def test_claim_safe_marketing_uses_only_dossier_fields():
    cand = Candidate(
        title="Shellfish Window",
        one_liner="Lease closure forecast for growers",
        who_pays="Independent shellfish farmers",
    )
    checks = [
        CheckResult("buyer_intent", Verdict.SUPPORTED, 0.9, "Search demand exists"),
        CheckResult("legality", Verdict.UNVERIFIABLE, 0.0, "silence"),
    ]
    m = claim_safe_marketing(cand, checks)
    assert m[0]["type"] == "listing_page"
    copy = m[0]["copy"]
    assert "Shellfish Window" in copy
    assert "Search demand exists" in copy
    assert "TAM" not in copy
    assert "£" not in copy or "£30" not in copy  # no invented price claims
    assert "silence" not in copy  # unverifiable rationale excluded


def test_ensure_marketing_floor_fills_empty():
    cand = Candidate(title="X", one_liner="Y")
    out = ensure_marketing_floor([], cand, [])
    assert any(p.get("type") == "listing_page" and p.get("copy") for p in out)


def test_ensure_marketing_floor_keeps_existing_listing():
    cand = Candidate(title="X", one_liner="Y")
    existing = [{"type": "listing_page", "copy": "Real listing copy from content_gen"}]
    out = ensure_marketing_floor(existing, cand, [])
    assert out[0]["copy"] == "Real listing copy from content_gen"


def test_exec_summary_and_checklist_non_empty():
    cand = Candidate(title="Pack", one_liner="One line", who_pays="SMEs")
    assert "Pack" in exec_summary_md(cand, [])
    assert "First-week" in first_week_checklist_md(cand)
    assert "SMEs" in first_week_checklist_md(cand)
