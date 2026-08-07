"""E1 hybrid arm: query templates that NAME the concrete entity a check turns on.

Leaf module by design — it imports nothing from the package. `config.py` validates
`retrieval.hybrid_entity_checks` against `ENTITY_TEMPLATES` at load time, and `verify.py`
consumes it at query time. If this dict lived in `verify.py` (as it did), that validation
would force `config.load_config()` to import `verify`, which imports `operator`, `prompts`
and `retrieval` — any of which loading config mid-import would see a half-initialised
`verify` and fail on a missing name. Keeping the data in a leaf breaks that cycle.

Why the arm exists (docs/COMMERCIAL_READINESS_PROGRAM.md §3 E1): generic keyword queries
restate the product pitch, and the open web has no page about a product restatement. It
does have pages about NAMED entities — what a `local council` budgets, how you reach
`independent pharmacies`, what `uk` licensing demands. Programme doc §8 measured the cost
of getting this wrong: 771 vs 145 unverifiable:supported on kills.
"""
from __future__ import annotations

# Slots are filled from candidate fields: {payer}=who_pays, {aud}=tags.audience,
# {market}=market, {base}=extracted keywords. A template whose ENTITY slot is blank is
# skipped rather than rendered — a half-filled template degenerates into exactly the
# product-shaped query this arm replaces. {base} is not an entity slot and never skips.
ENTITY_TEMPLATES: dict[str, list[str]] = {
    "payer_solvency": [
        "{payer} budget spending on {base}",
        "how much do {payer} pay for {base}",
    ],
    "distribution": [
        "how to reach {aud} marketing channels {base}",
        "{aud} customer acquisition cost by channel",
    ],
    # Added 2026-08-07. UNMEASURED: the arm ships OFF (`hybrid_entity_checks: []`), so
    # these two are arm CONTENT awaiting E1's own measurement, not a proven improvement.
    # They are here so a config that lists `incumbency` or `legality` is a live experiment
    # rather than a silent no-op — which is the defect the validation below closes.
    "incumbency": [
        "who already sells {base} to {aud}",
        "{aud} existing vendors alternatives {base}",
    ],
    "legality": [
        "{market} regulation licensing requirements {base}",
        "is {base} legal in {market}",
    ],
}

# Which slot each template's skip-if-blank rule turns on. Kept next to the templates so
# adding a new slot cannot silently bypass the blank check in `_entity_queries`.
ENTITY_SLOTS: tuple[str, ...] = ("{payer}", "{aud}", "{market}")


def checks_with_entity_templates() -> frozenset[str]:
    """The only check names `retrieval.hybrid_entity_checks` may legally contain."""
    return frozenset(ENTITY_TEMPLATES)
