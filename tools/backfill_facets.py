#!/usr/bin/env python3
"""Tag already-published packs with discovery facets, so the filter bar can reach them.

The storefront's discovery system — facet sidebar, three-question Matchmaker, near-miss
state — is built and shipped, and under-fed. Measured on the live catalogue 2026-08-01:
`commitment` on 22/49 packs, `advantages` on 29/49, and **15 packs carrying no facets at
all**. By the null rule (`Store.Web/src/lib/facets.ts:18`) an untagged pack renders no chip
and appears only under "All" — invisible to every filter and to the Matchmaker. Those 15
are not broken, they are *absent*.

`store_platform/data/facets-backfill.json` was prepared with hand-reviewed evidence for 31
packs and never applied, because nothing existed to apply it. This is that tool.

**Authority order**, highest first — the whole design is in this list:

1. **The live pack.** A facet already set in production is never overwritten. This tool
   only ever fills holes. Correcting a wrong tag is a different job with a different blast
   radius, and doing both from one script is how a tagging run ends up rewriting something
   a human decided.
2. **`facets-backfill.json`** — hand-resolved with an `_evidence` block per field. Human
   judgement about who pays and what the buyer must already have.
3. **`prospector.facet_derive`** — mechanical derivation from the dossier's own fields, and
   only for the two facets where a dossier field means the same thing the facet means
   (`effort`, `mechanism`). It refuses everything else rather than guessing.

Anything none of the three can justify stays untagged. That is the point: a filter that
lies is worse than a filter that is thin, on a brand whose position is "every claim sourced".

Usage:
    python -m tools.backfill_facets                    # dry run (default)
    python -m tools.backfill_facets --apply            # write via PATCH .../facets
    python -m tools.backfill_facets --only 86a2b4eb9a66df28
    python -m tools.backfill_facets --evidence         # print the reasoning for each tag

`--apply` needs STORE_INTERNAL_API_KEY:
    set -a; source .env; set +a; .venv/bin/python -m tools.backfill_facets --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector import facet_derive, facets  # noqa: E402
from prospector.config import store_root  # noqa: E402

# Env-overridable so a backfill can be pointed at staging. This script PATCHes live
# catalogue rows; a hardcoded production constant means there is no way to rehearse
# one except against the real store.
DEFAULT_API_URL = os.environ.get("STORE_API_URL", "https://api.mumchimp.com")
HAND_RESOLVED = REPO_ROOT / "store_platform" / "data" / "facets-backfill.json"
DOSSIER_DIR = store_root() / "dossiers"

SINGLE = ("sector", "payer", "effort", "commitment", "mechanism")


def _load_hand_resolved() -> Dict[str, Dict[str, Any]]:
    if not HAND_RESOLVED.exists():
        return {}
    return json.loads(HAND_RESOLVED.read_text(encoding="utf-8"))


def _load_candidate(pack_id: str) -> Optional[Dict[str, Any]]:
    """The dossier's candidate block, or None when no dossier is on disk.

    Dossiers are named `<id>.pass.json` / `<id>.kill.json`, so this globs rather than
    guessing the verdict suffix — a published pack is a pass today, but reading the
    catalogue is what decides what to tag, not the filename.
    """
    matches = sorted(DOSSIER_DIR.glob(f"{pack_id}*.json"))
    if not matches:
        return None
    data = json.loads(matches[0].read_text(encoding="utf-8"))
    candidate = data.get("candidate")
    return candidate if isinstance(candidate, dict) else None


def _live_value(pack: Dict[str, Any], name: str) -> Any:
    """What production currently holds for `name`, normalised to None/[] when absent."""
    if name == "advantages":
        value = pack.get("advantages")
        return list(value) if isinstance(value, list) and value else []
    value = pack.get(name)
    return value if value else None


def _proposal(
    pack: Dict[str, Any],
    hand: Dict[str, Any],
    candidate: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Facets to send for this pack, plus the evidence behind each one.

    Only holes are filled. `hand` outranks derivation; derivation outranks nothing. Values
    are pushed through `facets.clean_one` / `clean_advantages` on the way out so a typo in
    the hand-resolved file is dropped here rather than 400-ing the whole request at the API
    (the door validates too — this is the cheaper of the two failures, not a replacement).
    """
    derived = facet_derive.derive(candidate) if candidate else {}
    send: Dict[str, Any] = {}
    why: Dict[str, str] = {}

    for name in SINGLE:
        if _live_value(pack, name) is not None:
            continue  # authority 1: never overwrite production
        raw = hand.get(name)
        cleaned = facets.clean_one(raw, getattr(facets, name.upper()))
        if cleaned:
            evidence = (hand.get("_evidence") or {}).get(name, "hand-resolved, no evidence recorded")
            send[name] = cleaned
            why[name] = f"[hand] {evidence}"
            continue
        if name in derived:
            send[name] = derived[name].value
            why[name] = f"[derived] {derived[name].evidence}"

    if not _live_value(pack, "advantages"):
        cleaned = facets.clean_advantages(hand.get("advantages"))
        if cleaned:
            evidence = (hand.get("_evidence") or {}).get("advantages", "hand-resolved, no evidence recorded")
            send["advantages"] = cleaned
            why["advantages"] = f"[hand] {evidence}"

    return send, why


def _coverage(packs: List[Dict[str, Any]]) -> str:
    lines = []
    for name in SINGLE + ("advantages",):
        n = sum(1 for p in packs if _live_value(p, name) not in (None, []))
        lines.append(f"  {name:12s} {n:2d}/{len(packs)}  {100 * n / len(packs):3.0f}%")
    zero = sum(
        1
        for p in packs
        if not any(_live_value(p, f) for f in SINGLE) and not _live_value(p, "advantages")
    )
    lines.append(f"  {'zero-facet':12s} {zero:2d}/{len(packs)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api-url", default=DEFAULT_API_URL)
    ap.add_argument("--apply", action="store_true",
                    help="PATCH the facets (default: dry-run report only)")
    ap.add_argument("--only", metavar="PACK_ID", action="append",
                    help="restrict to specific pack id(s); repeatable")
    ap.add_argument("--evidence", action="store_true",
                    help="print the justification for every proposed tag")
    args = ap.parse_args()

    import requests

    internal_key = os.environ.get("STORE_INTERNAL_API_KEY")
    if args.apply and not internal_key:
        print("--apply needs STORE_INTERNAL_API_KEY; refusing.", file=sys.stderr)
        return 2

    response = requests.get(f"{args.api_url}/catalog", timeout=20)
    response.raise_for_status()
    packs: List[Dict[str, Any]] = response.json()
    if args.only:
        wanted = set(args.only)
        packs = [p for p in packs if p.get("id") in wanted]
    if not packs:
        print("No packs matched.", file=sys.stderr)
        return 1

    hand_resolved = _load_hand_resolved()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: {len(packs)} pack(s) from {args.api_url}/catalog\n")
    print("Coverage before:")
    print(_coverage(packs))
    print()

    planned: List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]] = []
    no_source: List[Dict[str, Any]] = []

    for pack in packs:
        pack_id = pack.get("id", "")
        hand = hand_resolved.get(pack_id) or {}
        candidate = _load_candidate(pack_id)
        send, why = _proposal(pack, hand, candidate)
        holes = [f for f in SINGLE if _live_value(pack, f) is None]
        if not _live_value(pack, "advantages"):
            holes.append("advantages")
        if not holes:
            continue
        if send:
            planned.append((pack, send, why))
        else:
            no_source.append(pack)

    for pack, send, why in planned:
        print(f"  {pack['id']}  {pack.get('title', '')[:54]}")
        for name, value in sorted(send.items()):
            print(f"      + {name:12s} = {value}")
            if args.evidence:
                print(f"        {why[name][:200]}")
    if planned:
        print()

    if no_source:
        print(f"{len(no_source)} pack(s) still have holes with nothing to justify a tag "
              f"(stay untagged — this is the null rule working, not a bug):")
        for pack in no_source:
            missing = [f for f in SINGLE if _live_value(pack, f) is None]
            if not _live_value(pack, "advantages"):
                missing.append("advantages")
            print(f"  {pack['id']}  {pack.get('title', '')[:44]:46s} missing: {','.join(missing)}")
        print()

    total_tags = sum(len(s) for _, s, _ in planned)
    print(f"{len(planned)} pack(s) would gain {total_tags} tag(s).")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to perform it.")
        return 0

    ok = failed = 0
    for pack, send, _ in planned:
        result = requests.patch(
            f"{args.api_url}/internal/catalog/{pack['id']}/facets",
            headers={"X-Internal-Key": internal_key or "", "Content-Type": "application/json"},
            json=send,
            timeout=20,
        )
        if result.status_code == 200:
            ok += 1
        else:
            failed += 1
            print(f"  FAIL {pack['id']} -> {result.status_code} {result.text[:160]}", file=sys.stderr)

    print(f"\napplied: {ok} ok, {failed} failed")

    verify = requests.get(f"{args.api_url}/catalog", timeout=20)
    if verify.status_code == 200:
        print("\nCoverage after (read back from the API, not from what we sent):")
        print(_coverage(verify.json()))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
