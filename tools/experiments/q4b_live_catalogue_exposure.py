#!/usr/bin/env python3
"""Q4b — what does the LIVE, SELLING catalogue rest on, and what does the shipped gate reach?

§20 measured citation source quality across the whole dossier corpus and §21.2 shipped
`P1_check_aware` admissibility. Both are corpus-wide. This probe asks the commercial question that
neither answers: **of the products a buyer can actually purchase right now, how many rest on
low-quality evidence, and how much of that does the shipped gate remove?**

The two are very different populations. The corpus is two months of every candidate ever vetted,
mostly kills. The catalogue is the ~56 that passed and shipped. A source-quality problem that is
rare in the corpus can be common in the catalogue, or the reverse, and only the catalogue number
describes what a customer receives.

THE DENOMINATOR IS THE HARD PART, and getting it wrong is the whole risk in this probe:

  * `store/listings/*.json` is NOT the catalogue. It is a local receipt.
    `prospector/decay.py:52-56` records the incident: four candidates re-vetted to KILL "kept
    selling live on mumchimp.com because store/listings/{cid}.json and Store.Api's IsListed both
    outlive the kill". Receipts outlive listings, and (measured 2026-08-07) 21 of 77 receipt files
    have no live listing at all — including two mock fixtures (§23.3).
  * `store_platform/src/Store.Api/store.db` is NOT the catalogue either. It is a DEV database
    holding 13 packs including `demo-pack-001`/`demo-pack-002`. Querying it says a live, selling
    product is absent — which nearly produced a retraction of a correct finding.
  * The catalogue is the production API. `GET https://api.mumchimp.com/catalog`.

So this probe reads the production catalogue over the network by default, and tiers its evidence
through `prospector.admissibility` — the SAME module the shipped gate uses, never a second copy, so
this cannot disagree with the gate about what a `stats_farm` is.

Read-only. Zero LLM. One HTTP GET (or `--catalogue <file>` for an offline replay).

Usage:
    .venv/bin/python tools/experiments/q4b_live_catalogue_exposure.py
    .venv/bin/python tools/experiments/q4b_live_catalogue_exposure.py --catalogue /tmp/cat.json
    .venv/bin/python tools/experiments/q4b_live_catalogue_exposure.py --policy P0_global
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from prospector.config import store_root  # noqa: E402
from prospector.admissibility import (  # noqa: E402
    LOW_TIERS,
    host_of,
    is_ruling_admissible,
    tier,
)

CATALOGUE_URL = "https://api.mumchimp.com/catalog"
RULED = {"supported", "refuted"}
HERE = os.path.dirname(os.path.abspath(__file__))
RECEIPTS = os.path.join(HERE, "q4b_live_catalogue_exposure_receipts.json")


def load_catalogue(argv: list[str]) -> tuple[set[str], str]:
    for i, a in enumerate(argv):
        if a == "--catalogue" and i + 1 < len(argv):
            with open(argv[i + 1]) as fh:
                return _ids(json.load(fh)), f"file:{argv[i + 1]}"
    with urllib.request.urlopen(CATALOGUE_URL, timeout=30) as r:
        return _ids(json.loads(r.read().decode())), CATALOGUE_URL


def _ids(doc) -> set[str]:
    items = doc if isinstance(doc, list) else (doc.get("items") or doc.get("packs")
                                               or doc.get("data") or [])
    return {str(i.get("id") or i.get("Id")) for i in items if isinstance(i, dict)}


def main() -> int:
    policy = "P1_check_aware"
    for i, a in enumerate(sys.argv):
        if a == "--policy" and i + 1 < len(sys.argv):
            policy = sys.argv[i + 1]
    live, origin = load_catalogue(sys.argv)

    tiers: collections.Counter = collections.Counter()
    per_check_low: collections.Counter = collections.Counter()
    items_low, items_demoted, items_residual, items_nodossier = set(), set(), set(), set()
    residual_domains: collections.Counter = collections.Counter()
    ruled = low = demoted = 0

    for key in sorted(live):
        paths = glob.glob(str(store_root() / "dossiers" / (key + "*.json")))
        if not paths:
            items_nodossier.add(key)
            continue
        with open(paths[0]) as fh:
            dossier = json.load(fh)
        for chk in dossier.get("checks") or []:
            if chk.get("verdict") not in RULED:
                continue
            by_id = {s.get("source_id"): s.get("url") or ""
                     for s in (chk.get("sources") or []) if isinstance(s, dict)}
            urls = [by_id[c] for c in (chk.get("citations") or []) if c in by_id]
            if not urls:
                continue
            ruled += 1
            name = chk.get("check_name") or "?"
            ts = [tier(host_of(u)) for u in urls]
            tiers.update(ts)
            if not any(t in LOW_TIERS for t in ts):
                continue
            low += 1
            per_check_low[name] += 1
            items_low.add(key)
            if is_ruling_admissible(name, urls, policy):
                items_residual.add(key)
                for u, t in zip(urls, ts):
                    if t in LOW_TIERS:
                        residual_domains[host_of(u)] += 1
            else:
                demoted += 1
                items_demoted.add(key)

    n = len(live)
    tot = sum(tiers.values()) or 1
    print(f"Q4b live-catalogue exposure — policy {policy}")
    print(f"catalogue origin: {origin}")
    print(f"live items: {n}   with a dossier: {n - len(items_nodossier)}   "
          f"ruled checks: {ruled}   cited urls: {tot}")
    if items_nodossier:
        print(f"  NO DOSSIER (cannot be audited): {sorted(items_nodossier)}")
    print("\ncited evidence by tier:")
    for t, c in tiers.most_common():
        print(f"  {c:6d} {c / tot:6.1%}  {t}{'   <-- LOW' if t in LOW_TIERS else ''}")

    print(f"\nruled checks touching a LOW tier   : {low} of {ruled} "
          f"({low / ruled if ruled else 0:.1%})")
    print(f"  demoted by {policy:<18}: {demoted}")
    print(f"  LEFT STANDING (residual)         : {low - demoted}")
    print(f"\nlive items with a low-tier citation: {len(items_low)}/{n} "
          f"({len(items_low) / n if n else 0:.0%})")
    print(f"  a check demoted by the gate      : {len(items_demoted)} {sorted(items_demoted)}")
    print(f"  residual low-tier evidence       : {len(items_residual)}/{n} "
          f"({len(items_residual) / n if n else 0:.0%})")
    print("\nresidual low-quality domains still behind a STANDING ruling:")
    for h, c in residual_domains.most_common(15):
        print(f"  {c:5d}  {tier(h):14s} {h}")
    print("\nlow-tier-touching ruled checks by check_name:")
    for name, c in per_check_low.most_common():
        print(f"  {c:5d}  {name}")

    with open(RECEIPTS, "w") as fh:
        json.dump({
            "policy": policy, "origin": origin, "live_items": n,
            "items_without_dossier": sorted(items_nodossier),
            "ruled_checks": ruled, "cited_urls": tot, "tiers": dict(tiers),
            "checks_touching_low": low, "checks_demoted": demoted,
            "checks_residual": low - demoted,
            "items_with_low": sorted(items_low), "items_demoted": sorted(items_demoted),
            "items_residual": sorted(items_residual),
            "residual_domains": residual_domains.most_common(),
            "low_by_check": dict(per_check_low),
        }, fh, indent=2, sort_keys=True)
    print(f"\nreceipts -> {os.path.relpath(RECEIPTS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
