"""Claim-safe pack floors (Epic C lite) — fill empty stubs without inventing facts.

When content_gen returns empty marketing / thin prose, published zips used to ship
23-byte Marketing_Assets stubs. These helpers synthesise buyer-facing text ONLY from
fields already on the dossier/candidate (title, one-liner, supported rationales).
No numbers, no unsourced claims — silence stays silence.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .plain_text import to_plain_text


def _supported_bullets(checks: Sequence[Any], *, limit: int = 5) -> List[str]:
    out: List[str] = []
    for c in checks or []:
        verdict = getattr(getattr(c, "verdict", None), "value", None) or getattr(c, "verdict", "")
        if str(verdict).lower() != "supported":
            continue
        rationale = (getattr(c, "rationale", None) or "").strip()
        name = (getattr(c, "check_name", None) or "check").replace("_", " ")
        if rationale:
            out.append(f"- **{name}:** {rationale[:280]}")
        if len(out) >= limit:
            break
    return out


def claim_safe_marketing(
    candidate: Any,
    checks: Sequence[Any] = (),
) -> List[Dict[str, str]]:
    """Deterministic listing_page (+ light ancillary) from grounded fields only."""
    title = (getattr(candidate, "title", None) or "Opportunity pack").strip()
    one = (getattr(candidate, "one_liner", None) or "").strip()
    why = (getattr(candidate, "why_now", None) or "").strip()
    who = (getattr(candidate, "who_pays", None) or "").strip()
    bullets = _supported_bullets(checks)

    body_parts = [
        f"# {title}",
        "",
        one or "Evidence-grounded opportunity pack.",
        "",
    ]
    if who:
        body_parts += [f"**Who pays:** {who}", ""]
    if why:
        body_parts += [f"**Why now:** {why}", ""]
    if bullets:
        body_parts += ["## What the evidence supports", ""] + bullets + [""]
    else:
        body_parts += [
            "## What the evidence supports",
            "",
            "_No additional supported check rationales were attached to this pack._",
            "",
        ]
    body_parts += [
        "## Honesty note",
        "",
        "Every factual claim in the full pack must cite a retrieved source or is "
        "marked unverifiable. This summary only restates fields already on the "
        "verified dossier — it does not add market sizes, revenue figures, or "
        "unverified promises.",
        "",
    ]
    copy = "\n".join(body_parts).strip()
    return [
        {
            "type": "listing_page",
            "headline": title[:140],
            "subhead": (one or title)[:280],
            "copy": copy,
            "what_you_get": [
                "Blueprint / build spec",
                "Go-to-market plan",
                "Operations plan",
                "Financial model (Python-computed from verified inputs)",
            ],
            # `bullets` are markdown list items (`- **buyer intent:** ...`). proof_point is
            # rendered by the storefront as literal text, so the markup has to come off here
            # or the buyer reads the asterisks. Words are preserved verbatim.
            "proof_point": to_plain_text(
                bullets[0] if bullets else one, collapse=True
            )[:240],
            "who_pays": who,
            "effort_tag": "solo_operator",
            "time_to_first_revenue": "",
        }
    ]


def exec_summary_md(candidate: Any, checks: Sequence[Any] = ()) -> str:
    title = (getattr(candidate, "title", None) or "Opportunity").strip()
    one = (getattr(candidate, "one_liner", None) or "").strip()
    bullets = _supported_bullets(checks, limit=4)
    lines = [
        f"# Executive summary — {title}",
        "",
        one or "_No one-liner on dossier._",
        "",
        "## Grounded signals",
        "",
    ]
    lines += bullets or ["_None attached._"]
    lines += [
        "",
        "## What this pack does not claim",
        "",
        "No unsourced TAM/SAM figures, guaranteed revenue, or legality shortcuts. "
        "If a check was unverifiable, it is absent here on purpose.",
        "",
    ]
    return "\n".join(lines)


def first_week_checklist_md(candidate: Any) -> str:
    title = (getattr(candidate, "title", None) or "this opportunity").strip()
    who = (getattr(candidate, "who_pays", None) or "the stated buyer").strip()
    return "\n".join([
        f"# First-week checklist — {title}",
        "",
        "Claim-safe starter steps. Adapt only where your own evidence supports it.",
        "",
        "1. Re-read the QA report kill/pass gates and list every SUPPORTED citation URL.",
        "2. Confirm the buyer (`who_pays`) matches reality for your market — dossier says: "
        f"{who}.",
        "3. Sketch the smallest paid offer described in the build spec (no scope creep).",
        "4. Pick one distribution channel from the GTM plan; ignore the rest for week one.",
        "5. Write the first outreach / listing using only claims that survived claim-check.",
        "6. Log what you could not verify; do not invent substitutes.",
        "",
    ])


def ensure_marketing_floor(
    marketing: List[Dict[str, Any]] | None,
    candidate: Any,
    checks: Sequence[Any] = (),
) -> List[Dict[str, Any]]:
    """Return marketing list with at least a claim-safe listing_page."""
    pieces = list(marketing or [])
    has_listing = any(
        (m.get("type") == "listing_page" and (m.get("copy") or "").strip())
        for m in pieces
    )
    if not has_listing:
        pieces = claim_safe_marketing(candidate, checks) + [
            m for m in pieces if m.get("type") != "listing_page"
        ]
    return pieces
