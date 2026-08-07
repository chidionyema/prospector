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

import re

# The slot value is an ENTITY, not the field it comes from. Measured on the whole corpus
# 2026-08-07 (1,600 dossiers, offline, zero LLM): `{payer}` is `who_pays` verbatim, which has a
# median of 29 words and a max of 136, so `payer_solvency` rendered search queries with a median
# of 38 words and **100% of 3,148 of them over 12 words**. The other three checks rendered 8-10.
# A 38-word query IS the product restatement this module's docstring says the arm exists to
# replace, so the flagship arm was quietly measuring the thing it was built to fix. The other
# slots need this too, cheaply: `{aud}` and `{market}` are already short, and a cap that never
# binds costs nothing.
#
# Whether the SHORTER query grounds better is E1's question and is deliberately not claimed
# here. What is claimed, and proved by tests/unit/test_e1_hybrid_queries.py, is only that the
# arm now emits something search-shaped.
MAX_ENTITY_WORDS = 8

# First clause: a sentence end, a spaced dash of any flavour, or a comma-led aside. `who_pays`
# is written as prose, and its first clause is reliably the payer; everything after it is
# pricing and justification, which belong in the check's reasoning and not in a search box.
_CLAUSE_BREAK = re.compile(r"[.;:!?]|\s[-‐-―]\s|,\s")
_LEADING_ARTICLE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def entity_phrase(raw: str, max_words: int = MAX_ENTITY_WORDS) -> str:
    """Reduce a candidate field to a searchable entity, or "" if nothing survives.

    Returning "" matters: `_entity_queries` SKIPS a template whose entity slot is blank rather
    than rendering a half-filled one, so an unreducible field falls through to the LLM arm
    instead of emitting a broken query under the treatment arm's name.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    head = _CLAUSE_BREAK.split(text, maxsplit=1)[0].strip()
    head = _LEADING_ARTICLE.sub("", head).strip(" \t\n\r-,;:")
    words = head.split()[:max_words]
    # A word cap cuts wherever the count runs out, and on this corpus that lands inside a
    # parenthetical often enough to matter: "Gen Z gig workers (rideshare" was a real rendered
    # query. Drop an opened-but-unclosed bracket and everything after it, then any punctuation
    # left dangling at the edge, so the cap never invents a token no page contains.
    out = " ".join(words)
    for opener, closer in (("(", ")"), ("[", "]"), ("“", "”")):
        if opener in out and closer not in out:
            out = out.split(opener)[0]
    return out.strip(" \t\n\r-,;:/&|(“")


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
