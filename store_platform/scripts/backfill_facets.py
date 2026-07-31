#!/usr/bin/env python3
"""Propose discovery facets for already-published packs, from their dossiers.

The 15 packs live today were published before the facet vocabulary existed. This script
reads each one's dossier and proposes what it can DEFEND, writing a review file:

    store_platform/data/facets-backfill.json

It writes a file. It does not publish. A second invocation with ``--apply`` PATCHes the
reviewed file to ``PATCH /internal/catalog/{id}/facets``.

What it will and will not decide
--------------------------------
Two facets come from categorical dossier fields and are proposed mechanically:

* ``mechanism`` — from ``candidate.structural_form``, but ONLY when that value is already
  one of the canonical eight. Live dossiers have drifted (``niche_distribution``,
  ``specialist_agency``, ``local_service``, ``local_service_chain``, and one empty
  string), and there is deliberately no string table mapping those onto the canonical
  list: picking the "nearest" form is a guess, and spec 2.3 forbids exactly that.
* ``effort`` — from ``candidate.automatability``, which is the same quantity the facet
  describes (how much of delivery a machine can do). The field is type-mixed across the
  15 — floats, prose, bare words, and ``None`` — so the parse is defensive and the
  banding is stated in the evidence string rather than hidden in code.

The other four (``sector``, ``payer``, ``commitment``, ``advantages``) have NO
corresponding dossier field. Any value this script invented for them would be inference
from prose, which is precisely what the whole facet contract exists to stop. So it emits
them as ``null`` with an ``_unresolved`` note that quotes the dossier text a human needs
in order to decide, and the human resolves them in the review file.

An unresolved facet is a correct outcome, not a failure. The storefront lists an untagged
pack under "All" and says plainly that it is not tagged yet.

Usage
-----
    python3 store_platform/scripts/backfill_facets.py                  # propose (writes file)
    python3 store_platform/scripts/backfill_facets.py --apply          # PATCH the reviewed file
    python3 store_platform/scripts/backfill_facets.py --apply --dry-run

``--apply`` needs ``STORE_INTERNAL_API_KEY`` in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from prospector import facets as facet_vocab  # noqa: E402

DOSSIER_DIR = REPO_ROOT / "store" / "dossiers"
OUTPUT_PATH = REPO_ROOT / "store_platform" / "data" / "facets-backfill.json"
DEFAULT_CATALOG_URL = "https://prospector-store-api.fly.dev/catalog"

#: Facets with no dossier field of their own. Proposed as null, resolved by a human.
HUMAN_RESOLVED = ("sector", "payer", "commitment", "advantages")


# --------------------------------------------------------------------------------------
# effort — from candidate.automatability
# --------------------------------------------------------------------------------------

def propose_effort(automatability: Any) -> Tuple[Optional[str], str]:
    """Return ``(effort, evidence)`` from the type-mixed ``automatability`` field.

    Bands are stated here and echoed into the evidence string so a reviewer can see the
    rule that produced the value rather than having to trust it:

    * numeric  >= 0.75 -> automatable, 0.40-0.74 -> part_automatable, < 0.40 -> hands_on
    * prose beginning "high"/"highly automat" -> automatable
    * prose beginning "part"/"partial"/"medium"/"moderate" -> part_automatable
    * prose beginning "low"/"hands on"/"manual" -> hands_on
    * anything else, including None and the empty string -> undecidable
    """
    if automatability is None:
        return None, "candidate.automatability is null"

    if isinstance(automatability, bool):
        # A bare True/False says nothing about degree, and reading True as "automatable"
        # would be inventing a band the dossier never expressed.
        return None, f"candidate.automatability = {automatability!r} (boolean carries no degree)"

    if isinstance(automatability, (int, float)):
        value = float(automatability)
        if value >= 0.75:
            band = "automatable"
        elif value >= 0.40:
            band = "part_automatable"
        else:
            band = "hands_on"
        return band, f"candidate.automatability = {value} (band: >=0.75 automatable, >=0.40 part_automatable, else hands_on)"

    text = str(automatability).strip()
    if not text:
        return None, "candidate.automatability is empty"

    lowered = text.lower()
    quoted = text if len(text) <= 160 else text[:157] + "..."

    for prefix, band in (
        ("highly automat", "automatable"),
        ("high", "automatable"),
        ("part", "part_automatable"),
        ("medium", "part_automatable"),
        ("moderate", "part_automatable"),
        ("hands on", "hands_on"),
        ("hands-on", "hands_on"),
        ("manual", "hands_on"),
        ("low", "hands_on"),
    ):
        if lowered.startswith(prefix):
            return band, f'candidate.automatability = "{quoted}" (opens with "{prefix}")'

    return None, f'candidate.automatability = "{quoted}" (no decidable band)'


# --------------------------------------------------------------------------------------
# mechanism — from candidate.structural_form
# --------------------------------------------------------------------------------------

def propose_mechanism(structural_form: Any) -> Tuple[Optional[str], str]:
    """Return ``(mechanism, evidence)``. Canonical values only; drift is left unresolved."""
    text = str(structural_form or "").strip()
    if not text:
        return None, "candidate.structural_form is empty"
    if text in facet_vocab.MECHANISM:
        return text, f'candidate.structural_form = "{text}"'
    return None, (
        f'candidate.structural_form = "{text}" — not one of the canonical eight; '
        "resolve by hand, do NOT map to the nearest form"
    )


# --------------------------------------------------------------------------------------
# proposal
# --------------------------------------------------------------------------------------

def load_dossier(pack_id: str) -> Optional[Dict[str, Any]]:
    path = DOSSIER_DIR / f"{pack_id}.pass.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def propose(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Build one entry of the review file for a single listed pack."""
    pack_id = pack["id"]
    dossier = load_dossier(pack_id)
    if dossier is None:
        return {
            "_title": pack.get("title", ""),
            "sector": None, "payer": None, "effort": None,
            "commitment": None, "mechanism": None, "advantages": [],
            "_unresolved": {
                "all": f"no store/dossiers/{pack_id}.pass.json — nothing to read, tag by hand or leave untagged"
            },
        }

    candidate = dossier.get("candidate", {}) or {}
    entry: Dict[str, Any] = {"_title": pack.get("title", "")}
    evidence: Dict[str, str] = {}
    unresolved: Dict[str, str] = {}

    effort, effort_evidence = propose_effort(candidate.get("automatability"))
    entry["effort"] = effort
    (evidence if effort else unresolved)["effort"] = effort_evidence

    mechanism, mechanism_evidence = propose_mechanism(candidate.get("structural_form"))
    entry["mechanism"] = mechanism
    (evidence if mechanism else unresolved)["mechanism"] = mechanism_evidence

    # The four with no dossier field of their own. Quote what a human needs to decide.
    who_pays = str(candidate.get("who_pays") or "").strip()
    hypothesis = str(candidate.get("hypothesis") or "").strip()
    tags = candidate.get("tags") or {}
    tag_list = sorted(tags.keys()) if isinstance(tags, dict) else list(tags)

    entry["sector"] = None
    entry["payer"] = None
    entry["commitment"] = None
    entry["advantages"] = []

    unresolved["sector"] = (
        f"no dossier field; decide from candidate.tags = {tag_list[:12]} "
        f"and the title. Allowed: {list(facet_vocab.SECTOR)}"
    )
    unresolved["payer"] = (
        f'no dossier field; decide from candidate.who_pays = "{who_pays[:240]}". '
        f"Allowed: {list(facet_vocab.PAYER)}"
    )
    unresolved["commitment"] = (
        f'no dossier field; decide from candidate.hypothesis = "{hypothesis[:240]}". '
        f"Allowed: {list(facet_vocab.COMMITMENT)}"
    )
    unresolved["advantages"] = (
        "no dossier field; decide what the BUYER must already have from the hypothesis "
        f"and delivery description. Allowed: {list(facet_vocab.ADVANTAGE)} (0-3)"
    )

    if evidence:
        entry["_evidence"] = evidence
    if unresolved:
        entry["_unresolved"] = unresolved
    return entry


def fetch_catalog(url: str) -> list:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - operator-supplied URL
        return json.loads(response.read().decode("utf-8"))


# --------------------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------------------

def apply_backfill(api_base: str, api_key: str, dry_run: bool) -> int:
    """PATCH the reviewed file to the store. Skips entries with nothing decided."""
    if not OUTPUT_PATH.exists():
        print(f"error: {OUTPUT_PATH} does not exist — run without --apply first", file=sys.stderr)
        return 1

    with OUTPUT_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)

    applied = skipped = failed = 0
    for pack_id, entry in sorted(data.items()):
        if pack_id.startswith("_"):
            continue

        payload = {}
        for name in ("sector", "payer", "effort", "commitment", "mechanism"):
            value = entry.get(name)
            if value:
                payload[name] = value
        advantages = entry.get("advantages") or []
        if advantages:
            payload["advantages"] = advantages

        if not payload:
            print(f"skip   {pack_id}  (nothing decided — stays untagged, which is a valid state)")
            skipped += 1
            continue

        # Validate against the same closed vocabulary the API enforces, so a typo in the
        # reviewed file is caught here rather than as a 400 halfway through the run.
        cleaned = facet_vocab.normalize(payload)
        for name in ("sector", "payer", "effort", "commitment", "mechanism"):
            if payload.get(name) and not cleaned.get(name):
                print(f"ERROR  {pack_id}  {name}={payload[name]!r} is not in the vocabulary", file=sys.stderr)
                failed += 1
                payload = {}
                break
        if not payload:
            continue

        if dry_run:
            print(f"would  {pack_id}  {json.dumps(payload, sort_keys=True)}")
            applied += 1
            continue

        request = urllib.request.Request(
            f"{api_base.rstrip('/')}/internal/catalog/{pack_id}/facets",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Internal-Key": api_key},
            method="PATCH",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                body = response.read().decode("utf-8")
            print(f"ok     {pack_id}  {body}")
            applied += 1
        except urllib.error.HTTPError as exc:
            print(f"FAIL   {pack_id}  HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
            failed += 1
        except urllib.error.URLError as exc:
            print(f"FAIL   {pack_id}  {exc}", file=sys.stderr)
            failed += 1

    print(f"\napplied={applied} skipped={skipped} failed={failed}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-url", default=DEFAULT_CATALOG_URL,
                        help="where to read the list of currently-listed packs")
    parser.add_argument("--api-base", default="https://prospector-store-api.fly.dev",
                        help="store API base for --apply")
    parser.add_argument("--apply", action="store_true",
                        help="PATCH the reviewed file to the store instead of proposing")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --apply, print what would be sent and send nothing")
    args = parser.parse_args()

    if args.apply:
        api_key = os.environ.get("STORE_INTERNAL_API_KEY", "")
        if not api_key and not args.dry_run:
            print("error: STORE_INTERNAL_API_KEY is not set", file=sys.stderr)
            return 1
        return apply_backfill(args.api_base, api_key, args.dry_run)

    try:
        catalog = fetch_catalog(args.catalog_url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"error: could not read {args.catalog_url}: {exc}", file=sys.stderr)
        return 1

    # Preserve any human resolutions already in the file: re-running the proposer must
    # never silently overwrite a decision a person made. Only fields still null are
    # refreshed from the dossier.
    existing: Dict[str, Any] = {}
    if OUTPUT_PATH.exists():
        with OUTPUT_PATH.open(encoding="utf-8") as handle:
            existing = json.load(handle)

    out: Dict[str, Any] = {}
    for pack in catalog:
        pack_id = pack["id"]
        proposed = propose(pack)
        prior = existing.get(pack_id) or {}
        for name in ("sector", "payer", "effort", "commitment", "mechanism"):
            if prior.get(name):
                proposed[name] = prior[name]
                proposed.setdefault("_evidence", {})[name] = (
                    prior.get("_evidence", {}).get(name) or "resolved by hand"
                )
                proposed.get("_unresolved", {}).pop(name, None)
        if prior.get("advantages"):
            proposed["advantages"] = prior["advantages"]
            proposed.setdefault("_evidence", {})["advantages"] = (
                prior.get("_evidence", {}).get("advantages") or "resolved by hand"
            )
            proposed.get("_unresolved", {}).pop("advantages", None)
        if not proposed.get("_unresolved"):
            proposed.pop("_unresolved", None)
        out[pack_id] = proposed

    # Keep entries for packs that have left the live catalogue. /catalog serves listed packs
    # only, so a pack withdrawn by PATCH /internal/catalog/{id}/listing disappears from the
    # loop above — and rebuilding the file purely from what is live would delete the record
    # of WHY it was withdrawn, which for the three quarantined on 2026-07-31 is the entire
    # value of the entry. The row is still needed too: a re-listed pack must come back tagged,
    # not silently untagged. Phantom ids cannot accumulate here because
    # test_every_entry_is_a_pack_that_was_actually_published rejects any entry with no dossier.
    for pack_id, prior in existing.items():
        if pack_id not in out:
            out[pack_id] = prior

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")

    decided = sum(
        1 for entry in out.values()
        for name in ("sector", "payer", "effort", "commitment", "mechanism")
        if entry.get(name)
    )
    unresolved = sum(len(entry.get("_unresolved", {})) for entry in out.values())
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(f"packs={len(out)} facet_values_decided={decided} facets_awaiting_review={unresolved}")
    print("\nThis file is a PROPOSAL. Review it, resolve the _unresolved entries by reading")
    print("the quoted dossier text, then re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
