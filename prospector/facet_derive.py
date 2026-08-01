"""Derive discovery facets from a dossier's own evidence — only where the mapping is defensible.

This module exists because 28 of 49 live packs were published before the facet vocabulary
existed, and the storefront's null rule (``facets.ts:18``) makes an untagged pack reachable
only under "All" — invisible to every filter and to the Matchmaker. The fix is to tag them.
The fix is *not* to loosen the null rule, and it is *not* to guess.

**What this module will and will not do.**

It derives exactly two facets, because exactly two have a dossier field that means the same
thing the facet means:

- ``mechanism`` from ``candidate.structural_form`` — the same taxonomy under a different
  name. ``MECHANISM`` mirrors ``config.yaml`` ``generation.structural_forms``
  (``facets.py:39``), so this is a vocabulary check, not an inference.
- ``effort`` from ``candidate.automatability`` — the field is *defined* as how much of
  delivery is machine-doable, which is what ``effort`` asks.

It refuses ``sector``, ``payer``, ``commitment`` and ``advantages``. Those need a judgement
about what a buyer must already have, or who signs the cheque, and the last time this
codebase inferred one of them from pack text it published a metal-fabrication quoting engine
as a *gardening* business and a dog-walking tool as *gardening* too (the deleted
``lib/category.ts``; see ``specs/discovery-ux-2026-07-30.md`` Part 0). On a storefront whose
whole position is "every claim sourced", a filter that lies costs more than a filter that is
thin. Those four are resolved by hand with evidence in
``store_platform/data/facets-backfill.json``.

**The distinction this module must not blur.** ``facets.py``'s docstring forbids deriving
``effort`` from the legacy ``effort_tag`` (``low | medium | high``), because that field was
never defined to mean machine-doability — mapping it would be "a guess wearing the costume of
a migration". ``automatability`` is a different field with a different definition, and it is
the source the hand-resolved entries in ``facets-backfill.json`` already cite for ``effort``.
This module reads ``automatability`` and never ``effort_tag``; the two must not be conflated
because they disagree (a hands-on service can be *high* value and *low* automatability).

Every derivation returns its evidence string alongside the value so the backfill can write an
auditable ``_evidence`` block, exactly like the hand-resolved entries. A tag whose reasoning
cannot be printed back is not shippable on this brand.
"""

from __future__ import annotations

import re
from typing import Any, Dict, NamedTuple, Optional

from . import facets


class Derived(NamedTuple):
    """A facet value with the evidence sentence that justifies it."""

    value: str
    evidence: str


#: Automatability bands, as already documented in the hand-resolved backfill entries
#: ("candidate.automatability = 0.5 (band: >=0.75 automatable, >=0.40 part_automatable,
#: else hands_on)"). Kept identical so machine-derived and hand-resolved tags cannot
#: disagree about the same number.
_AUTOMATABLE_FLOOR = 0.75
_PART_AUTOMATABLE_FLOOR = 0.40

#: Leading-word forms seen in the live dossiers ("High — the tool is self-service…").
#: Deliberately does NOT include a bare "medium"→"part_automatable" guess for values that
#: arrive with no supporting text; see `_band_from_word`.
_WORD_BANDS = {
    "high": "automatable",
    "medium": "part_automatable",
    "moderate": "part_automatable",
    "low": "hands_on",
}


def _as_fraction(raw: Any) -> Optional[float]:
    """Coerce an automatability reading to a 0–1 fraction, or None if it is not a number.

    Units are explicit here because the live data carries both conventions in the same
    field: the 28 packs needing backfill hold ``0.7 … 0.95`` *and* ``80`` and ``85``. Read
    naively as fractions, ``80`` and ``85`` clear every band by accident rather than by
    meaning — right answer, wrong reason, and the reason is what breaks silently the first
    time a pack lands on ``0.8`` versus ``8``. Anything above 100 or below 0 is refused
    rather than clamped: a value outside both conventions is a field this module does not
    understand, and the null rule says absent beats invented.
    """
    if isinstance(raw, bool):  # bool is an int subclass; never an automatability reading
        return None
    if isinstance(raw, (int, float)):
        number = float(raw)
    elif isinstance(raw, str):
        match = re.match(r"\s*(\d+(?:\.\d+)?)\s*%?", raw)
        if not match:
            return None
        number = float(match.group(1))
        # "85% – Ingestion of Tribunal decisions…" is a percentage whatever its magnitude.
        if "%" in raw[: match.end() + 1]:
            return number / 100.0 if 0.0 <= number <= 100.0 else None
    else:
        return None

    if 0.0 <= number <= 1.0:
        return number
    if 1.0 < number <= 100.0:
        return number / 100.0
    return None


def _band_from_fraction(fraction: float) -> str:
    if fraction >= _AUTOMATABLE_FLOOR:
        return "automatable"
    if fraction >= _PART_AUTOMATABLE_FLOOR:
        return "part_automatable"
    return "hands_on"


def _band_from_word(text: str) -> Optional[str]:
    """Band a free-text automatability that opens with a magnitude word.

    Only the opening word counts. Scanning the whole sentence for "high" would match "a high
    volume of manual review", which says the opposite of what the match would claim.
    """
    match = re.match(r"\s*([A-Za-z]+)", text)
    if not match:
        return None
    return _WORD_BANDS.get(match.group(1).lower())


def derive_effort(candidate: Dict[str, Any]) -> Optional[Derived]:
    """``effort`` from ``candidate.automatability``, or None when it cannot be read.

    Numbers are tried before words because a string like "0.5 — mostly manual" carries both,
    and the number is the measured claim while the prose around it is commentary.
    """
    raw = candidate.get("automatability")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None

    fraction = _as_fraction(raw)
    if fraction is not None:
        value = _band_from_fraction(fraction)
        shown = str(raw)[:120]
        return Derived(
            value,
            f'candidate.automatability = "{shown}" -> {fraction:.2f} '
            f"(band: >={_AUTOMATABLE_FLOOR} automatable, "
            f">={_PART_AUTOMATABLE_FLOOR} part_automatable, else hands_on)",
        )

    if isinstance(raw, str):
        value = _band_from_word(raw)
        if value:
            return Derived(
                value,
                f'candidate.automatability = "{raw[:120]}" (opens with '
                f'"{raw.strip().split()[0]}")',
            )
    return None


def derive_mechanism(candidate: Dict[str, Any]) -> Optional[Derived]:
    """``mechanism`` from ``candidate.structural_form``, or None when it is off-vocabulary.

    ``clean_one`` does the membership check, so an unrecognised form (``micro_ecommerce``,
    ``vertical_saas`` — both live today) yields None rather than being coerced to the nearest
    member. Coercion is the specific failure ``facets.clean_one`` was written to prevent:
    "business" is not ``b2b``, it is an unrecognised answer.
    """
    raw = candidate.get("structural_form")
    value = facets.clean_one(raw, facets.MECHANISM)
    if not value:
        return None
    return Derived(value, f'candidate.structural_form = "{raw}"')


#: The facets this module is willing to derive. `sector`, `payer`, `commitment` and
#: `advantages` are absent on purpose — see the module docstring.
DERIVABLE = ("effort", "mechanism")


def derive(candidate: Dict[str, Any]) -> Dict[str, Derived]:
    """Every facet derivable from this candidate's evidence. Missing keys mean "cannot say"."""
    out: Dict[str, Derived] = {}
    for name, fn in (("effort", derive_effort), ("mechanism", derive_mechanism)):
        result = fn(candidate)
        if result is not None:
            out[name] = result
    return out
