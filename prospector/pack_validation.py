"""Pack completeness gate — auto-verification before a pack may be listed for sale.

Generation is non-critical and flaky by nature (a tier can return empty/unparseable
output without raising, or hit a quota wall mid-batch). Without a gate, a half-empty
pack still zips, uploads, and lists — we'd be selling a deliverable that isn't there.

This module is the single source of truth for "is this pack actually sellable?". Both
the publish path (EngineBridge, as a hard backstop) and the batch driver (as a retry
trigger) call `validate_pack`. A pack may only be listed when this returns ok=True.

The bar is deliberately generous on size (it only needs to catch empty/stub output,
never reject a genuine artifact) and strict on presence (every required artifact must
exist and be non-trivial).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# The four £30-pack artifacts. All must be present and non-trivial — these ARE the
# deliverable. financial_model is Python-rendered, so even a sparse one clears the floor;
# the others are LLM prose that comes back at 1500+ chars when generation succeeds and
# exactly 0 when a tier silently fails. A 200-char floor cleanly separates the two.
REQUIRED_ARTIFACTS = ("build_spec", "gtm_plan", "ops_plan", "financial_model")
MIN_ARTIFACT_CHARS = 200

# Marketing pieces can be legitimately dropped when they fail claim-check (by design),
# so we don't require all four. But the listing page is the storefront copy itself — a
# pack with no listing_page has nothing to show a buyer, so it's required.
REQUIRED_MARKETING = ("listing_page",)
MIN_MARKETING_CHARS = 80


def validate_pack(
    artifacts: Dict[str, str],
    marketing: List[Dict[str, str]],
) -> Tuple[bool, List[str]]:
    """Return (ok, problems). ok=True only when the pack is complete enough to sell.

    `problems` is a human-readable list of every gap, so callers can log exactly why a
    pack was held back (and the driver can decide whether a regeneration is worth it).
    """
    problems: List[str] = []

    for name in REQUIRED_ARTIFACTS:
        content = (artifacts or {}).get(name) or ""
        size = len(content.strip())
        if size == 0:
            problems.append(f"artifact '{name}' is empty (generation produced nothing)")
        elif size < MIN_ARTIFACT_CHARS:
            problems.append(
                f"artifact '{name}' is only {size} chars (<{MIN_ARTIFACT_CHARS}; looks like a stub)"
            )

    by_type = {m.get("type"): (m.get("copy") or "") for m in (marketing or [])}
    for name in REQUIRED_MARKETING:
        copy = by_type.get(name, "")
        size = len(copy.strip())
        if size == 0:
            problems.append(f"marketing '{name}' is missing or empty")
        elif size < MIN_MARKETING_CHARS:
            problems.append(
                f"marketing '{name}' is only {size} chars (<{MIN_MARKETING_CHARS})"
            )

    return (not problems, problems)
