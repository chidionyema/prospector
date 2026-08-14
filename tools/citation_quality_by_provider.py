#!/usr/bin/env python3
"""What kind of evidence is each search provider actually giving us?

THE READER FOR `Source.retrieved_by`. A field nobody reads is a field nobody maintains, and
this repo has paid for write-only state before. `retrieval.ProviderStamped` records which
engine supplied each passage; this is the report that turns those stamps into the decision
they exist for — which provider to lead the chain with, and which to demote.

WHAT PROMPTED IT (2026-08-14, 13,479 citations from dossiers written 8-14 Aug):

    en.wikipedia.org 970 · gov.uk 455 · youtube.com 318 · linkedin.com 262
    merriam-webster.com 128 · tiktok.com 72 · facebook.com 66 · dictionary.cambridge.org 42
    primary-source share of ALL citations: 8.9%

Two dictionaries supplied 170 citations of evidence about whether business problems are
real — and the stored source carried no provider, so none of it could be attributed without
replaying queries live. See `docs/RETRIEVAL_PROGRAM.md` §D3, §D8.

READ-ONLY. Opens the catalogue with `mode=ro` and never writes. Safe to run against a live
daemon.

    .venv/bin/python tools/citation_quality_by_provider.py
    .venv/bin/python tools/citation_quality_by_provider.py --since 2026-08-15
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

#: Sources whose authority comes from being the record itself: statute, regulator,
#: legislature, court, national statistics, academic. Deliberately a SUFFIX/substring rule
#: over the registrable domain, not a curated allow-list — a list would silently rot, and the
#: question here is "is this an official record", which the TLD structure already answers for
#: the jurisdictions the engine works in. A citation that is primary but not matched here is
#: undercounted, which biases this report AGAINST the conclusion it is used to argue.
_PRIMARY = (".gov", ".gov.uk", ".mil", ".edu", ".ac.uk", ".parliament.uk", ".nhs.uk",
            "europa.eu", "who.int", "oecd.org", "imf.org", "worldbank.org", "un.org")

#: Domains that answer a keyword, not a question. Cited as evidence, each of these is a
#: retrieval failure that the verdict layer then has to rule `unverifiable` around.
_LOW_AUTHORITY = ("wikipedia.org", "merriam-webster.com", "dictionary.cambridge.org",
                  "youtube.com", "tiktok.com", "facebook.com", "instagram.com",
                  "pinterest.com", "worldatlas.com", "investopedia.com", "quora.com",
                  "dictionary.com", "britannica.com", "imdb.com")

UNATTRIBUTED = "unattributed (written before 2026-08-14)"


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().removeprefix("www.")
    except Exception:                                   # noqa: BLE001 — a probe never dies
        return ""


def _is(domain: str, needles: tuple[str, ...]) -> bool:
    return any(domain.endswith(n) or ("." + n) in domain or domain == n.lstrip(".")
               for n in needles)


def _dossier_paths(repo: str, since: str | None) -> list[str]:
    uri = f"file:{repo}/store/prospector.db?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10.0) as conn:
        has_tomb = any(r[1] == "tombstone" for r in conn.execute("PRAGMA table_info(dossiers)"))
        where = " WHERE 1=1" + (" AND tombstone IS NULL" if has_tomb else "")
        args: list[str] = []
        if since:
            where += " AND created_at >= ?"
            args.append(since)
        rows = conn.execute(f"SELECT candidate_id, path FROM dossiers{where}", args).fetchall()
    out = []
    for cid, path in rows:
        for cand in ([path] if path else []) + [f"{repo}/store/dossiers/{cid}.kill.json",
                                                f"{repo}/store/dossiers/{cid}.json"]:
            if cand and os.path.exists(cand):
                out.append(cand)
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="ISO date; only dossiers created on/after it")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--top", type=int, default=8, help="domains to list per provider")
    a = ap.parse_args()

    paths = _dossier_paths(a.repo, a.since)
    if not paths:
        print("no dossiers in range")
        return 0

    cites: Counter[str] = Counter()
    prim: Counter[str] = Counter()
    low: Counter[str] = Counter()
    doms: dict[str, Counter[str]] = defaultdict(Counter)
    verdicts: dict[str, Counter[str]] = defaultdict(Counter)

    for p in paths:
        try:
            with open(p) as fh:
                js = json.load(fh)
        except Exception:                               # noqa: BLE001
            continue
        for ck in (js.get("checks") or []):
            v = str(ck.get("verdict") or "?")
            for s in (ck.get("sources") or []):
                if not isinstance(s, dict):
                    continue
                who = s.get("retrieved_by") or UNATTRIBUTED
                d = _domain(s.get("url") or "")
                cites[who] += 1
                verdicts[who][v] += 1
                if d:
                    doms[who][d] += 1
                    if _is(d, _PRIMARY):
                        prim[who] += 1
                    elif _is(d, _LOW_AUTHORITY):
                        low[who] += 1

    total = sum(cites.values())
    print(f"dossiers read: {len(paths)}   citations: {total}"
          + (f"   since: {a.since}" if a.since else ""))
    if not total:
        return 0

    attributed = total - cites.get(UNATTRIBUTED, 0)
    print(f"attributed to a provider: {attributed}/{total} "
          f"({100 * attributed / total:.1f}%)\n")

    hdr = f"{'provider':<38} {'cites':>7} {'primary':>9} {'low-auth':>9}   verdict mix of the checks fed"
    print(hdr)
    print("-" * len(hdr))
    for who, n in cites.most_common():
        vv = verdicts[who]
        tv = sum(vv.values()) or 1
        mix = "  ".join(f"{k[:5]} {100 * vv[k] / tv:.0f}%"
                        for k in ("supported", "unverifiable", "refuted") if vv.get(k))
        print(f"{who:<38} {n:>7} {100 * prim[who] / n:>8.1f}% {100 * low[who] / n:>8.1f}%   {mix}")

    print()
    for who, _ in cites.most_common():
        top = "  ".join(f"{d} {c}" for d, c in doms[who].most_common(a.top))
        print(f"  {who}: {top}")

    if cites.get(UNATTRIBUTED) == total:
        print("\nNOTE: nothing is attributed yet. `Source.retrieved_by` stamps forward only —"
              "\n      run a fresh batch, then re-run this. Backfill is impossible: the"
              "\n      provider that supplied an existing citation was never recorded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
