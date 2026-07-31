"""The discovery facet vocabulary — the Python end of one closed contract.

The same six vocabularies exist in C# at
``store_platform/src/Store.Catalog/Domain/PackFacets.cs`` and in TypeScript at
``store_platform/src/Store.Web/src/lib/facets.ts``. Three copies is a deliberate cost: the
engine, the API, and the browser are three deploy units, and a shared runtime dependency
between them would be a worse coupling than three lists that a test can compare.

Two rules this module exists to enforce:

1. **Absent means absent.** A value the engine cannot justify is ``None``, never a default
   and never a guess. ``normalize`` drops anything outside the vocabulary rather than
   coercing it to the nearest member — a coerced facet is a claim nobody made, and the
   buyer would filter on it believing it came from the dossier.

2. **The legacy ``effort_tag`` is not a source for ``effort``.** ``low | medium | high``
   was never defined to mean "how much of delivery is machine-doable"; mapping ``high`` to
   ``hands_on`` is a guess wearing the costume of a migration. See spec 2.3.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

#: What the buyer already has. Multi-valued (0-3) — the primary router input.
ADVANTAGE = ("code", "nocode", "sales", "ops", "audience")

#: Who signs the cheque.
PAYER = ("b2b", "b2c", "b2g")

#: How much of delivery is machine-doable.
EFFORT = ("automatable", "part_automatable", "hands_on")

#: Hours needed to RUN it — deliberately separate from EFFORT.
COMMITMENT = ("evenings", "part_time", "full_time")

#: How it makes money. Mirrors config.yaml:595-603 (``generation.structural_forms``).
MECHANISM = (
    "productized_service",
    "vertical_tool",
    "transaction_broker",
    "risk_financing",
    "physical_ops",
    "audience_media",
    "picks_and_shovels",
    "data_intelligence",
)

#: Display and exclusion only ("anything but vets") — never the primary filter.
SECTOR = (
    "licensing_admin",
    "employment_pay",
    "housing_rental",
    "care_benefits",
    "trades_construction",
    "pets_animals",
    "creative_rights",
    "property_probate",
    "energy_planning",
    "retail_inventory",
    "professional_services",
    "other",
)

#: Single-valued facets and their vocabularies, in the order they appear on the wire.
SINGLE_VALUED = {
    "sector": SECTOR,
    "payer": PAYER,
    "effort": EFFORT,
    "commitment": COMMITMENT,
    "mechanism": MECHANISM,
}

MAX_ADVANTAGES = 3


def clean_one(value: Any, allowed: Iterable[str]) -> Optional[str]:
    """Return ``value`` if it is in ``allowed``, else ``None``.

    Case- and whitespace-tolerant on the way in, because an operator returning
    ``" B2B "`` meant ``b2b`` and there is no ambiguity to resolve. Everything else is
    dropped: ``"business"`` is not ``b2b``, it is an unrecognised answer, and guessing
    which member it meant is exactly the inference this contract forbids.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    return text if text in tuple(allowed) else None


def clean_advantages(values: Any) -> List[str]:
    """Normalise the multi-valued advantage list, de-duplicated and capped.

    Unknown members are dropped individually rather than failing the list: unlike the
    publish API — which rejects the whole request so a partial write cannot happen — this
    runs at generation time, where keeping the two advantages the model justified is
    strictly better than discarding all three because it invented a fourth.
    """
    if not isinstance(values, (list, tuple, set)):
        return []
    out: List[str] = []
    for v in values:
        cleaned = clean_one(v, ADVANTAGE)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out[:MAX_ADVANTAGES]


def normalize(raw: Any) -> Dict[str, Any]:
    """Coerce a model-supplied ``facets`` object into the contract.

    Always returns all six keys. Single-valued facets are ``None`` when absent or
    unrecognised; ``advantages`` is ``[]``. Never raises: a malformed facets block must
    cost the listing its tags, not the whole publish.
    """
    if not isinstance(raw, dict):
        raw = {}

    facets: Dict[str, Any] = {
        name: clean_one(raw.get(name), allowed)
        for name, allowed in SINGLE_VALUED.items()
    }
    facets["advantages"] = clean_advantages(raw.get("advantages"))
    return facets


def to_wire(facets: Dict[str, Any]) -> Dict[str, Any]:
    """Map the snake_case engine facets onto the camelCase publish payload.

    Empty values are dropped so the Store API's only-overwrite-when-sent rule applies: a
    facet-light republish must never silently untag a pack the backfill tagged.
    """
    # The Store API binds JSON property names case-insensitively, so these lower-case
    # names land on PublishRequest.Sector/Payer/… Spelled out rather than derived, so a
    # rename on either side breaks visibly here instead of silently dropping a facet.
    wire: Dict[str, Any] = {}
    for name in ("sector", "payer", "effort", "commitment", "mechanism"):
        value = facets.get(name)
        if value:
            wire[name] = value
    advantages = facets.get("advantages") or []
    if advantages:
        wire["advantages"] = list(advantages)
    return wire
