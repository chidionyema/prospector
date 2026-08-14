#!/usr/bin/env python3
"""D5 measurement: how many `supported` rulings rest on ONE publisher?

Programme doc `docs/RETRIEVAL_PROGRAM.md` §D5 proposed two fixes. The FIRST one — a
source-authority floor — is already on disk and running: `prospector/admissibility.py`
+ the ruling-time demotion at `prospector/verify.py:511-537` (policy `P1_check_aware`,
`config.yaml:325`). So D5 reduces to its SECOND half: nothing requires a `supported`
verdict to rest on more than one INDEPENDENT publisher. Three pages from one site count
as three sources.

This script is read-only and offline (no model calls). It measures the cost of the gate
BEFORE the gate exists, which is the whole point: a corroboration requirement that would
demote half the supported rulings in the catalogue is a different decision from one that
demotes 3%.

Independence is measured at the REGISTRABLE domain, not the hostname: `www.gov.uk` and
`assets.publishing.service.gov.uk` are one publisher, and counting them as two would let
the gate pass on exactly the correlated evidence it exists to reject.

Usage:  .venv/bin/python tools/experiments/d5_corroboration.py [--since YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ONE definition of "publisher", shared with the gate itself — a measurement that classifies
# domains differently from the code it prices is not a measurement of that code.
from prospector.admissibility import host_of, registrable, tier  # noqa: E402


def _dossier_date(js: dict, path: str) -> str:
    for k in ("verified_at", "created_at", "checked_at", "generated_at"):
        v = js.get(k)
        if isinstance(v, str) and len(v) >= 10:
            return v[:10]
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="YYYY-MM-DD, inclusive")
    ap.add_argument("--min-domains", type=int, default=2,
                    help="corroboration floor to price (default 2)")
    a = ap.parse_args()

    paths = sorted(glob.glob("store/dossiers/*.json"))
    if not paths:
        print("no dossiers found (run from the repo root)")
        return 1

    n_dossiers = 0
    # supported+cited rulings, bucketed by how many independent publishers back them
    by_ndom: Counter[int] = Counter()
    # per-gate breakdown of the ones the floor would demote
    demoted_by_check: Counter[str] = Counter()
    total_by_check: Counter[str] = Counter()
    # the single publishers most relied on, and their tier
    sole_publisher: Counter[str] = Counter()
    sole_tier: Counter[str] = Counter()
    # decision-level blast radius
    dossiers_with_demotion: Counter[str] = Counter()
    dossiers_by_decision: Counter[str] = Counter()
    # a supported ruling can also be single-CITATION; that is a stricter subset
    single_citation = 0
    supported_cited = 0

    for p in paths:
        try:
            with open(p) as fh:
                js = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        checks = js.get("checks")
        if not isinstance(checks, list) or not checks:
            continue  # lint/QA records live in the same directory and have no `checks`
        if a.since and _dossier_date(js, p) < a.since:
            continue
        n_dossiers += 1
        decision = str(js.get("decision") or js.get("verdict") or
                       ("KILL" if p.endswith(".kill.json") else "?")).upper()
        dossiers_by_decision[decision] += 1
        hit = False

        for ck in checks:
            if not isinstance(ck, dict):
                continue
            name = str(ck.get("check_name") or ck.get("name") or "?")
            if str(ck.get("verdict") or "").lower() != "supported":
                continue
            cited = {str(c) for c in (ck.get("citations") or [])}
            srcs = [s for s in (ck.get("sources") or []) if isinstance(s, dict)]
            urls = [s.get("url") or "" for s in srcs
                    if not cited or str(s.get("source_id") or "") in cited]
            urls = [u for u in urls if u]
            if not urls:
                continue  # source_or_die already handles uncited `supported`
            supported_cited += 1
            total_by_check[name] += 1
            if len(urls) == 1:
                single_citation += 1
            doms = {registrable(host_of(u)) for u in urls}
            doms.discard("")
            n = len(doms)
            by_ndom[n] += 1
            if n < a.min_domains:
                demoted_by_check[name] += 1
                hit = True
                if n == 1:
                    d = next(iter(doms))
                    sole_publisher[d] += 1
                    sole_tier[tier(host_of(urls[0]))] += 1
        if hit:
            dossiers_with_demotion[decision] += 1

    if not supported_cited:
        print("no `supported` rulings with citations in range")
        return 0

    print(f"dossiers with checks: {n_dossiers}"
          + (f"   since: {a.since}" if a.since else "   (all time)"))
    print(f"`supported` rulings with >=1 cited source: {supported_cited}")
    print(f"  of which exactly ONE citation: {single_citation} "
          f"({100 * single_citation / supported_cited:.1f}%)\n")

    print("independent publishers backing a `supported` ruling")
    print(f"{'publishers':>10} {'rulings':>8} {'share':>7}")
    for n in sorted(by_ndom):
        c = by_ndom[n]
        print(f"{n:>10} {c:>8} {100 * c / supported_cited:>6.1f}%")

    demoted = sum(demoted_by_check.values())
    print(f"\nfloor min_domains={a.min_domains} would demote "
          f"{demoted}/{supported_cited} supported rulings "
          f"({100 * demoted / supported_cited:.1f}%)\n")

    print(f"{'check':<22} {'supported':>10} {'demoted':>8} {'share':>7}")
    for name, tot in total_by_check.most_common():
        d = demoted_by_check.get(name, 0)
        print(f"{name:<22} {tot:>10} {d:>8} {100 * d / tot:>6.1f}%")

    print("\ntier of the sole publisher (single-domain rulings only)")
    for t, c in sole_tier.most_common():
        print(f"  {t:<18} {c:>6}")

    print("\ntop sole publishers")
    for d, c in sole_publisher.most_common(15):
        print(f"  {d:<34} {c:>5}")

    print("\nblast radius by dossier decision (dossiers with >=1 demoted ruling)")
    for dec, tot in dossiers_by_decision.most_common():
        h = dossiers_with_demotion.get(dec, 0)
        print(f"  {dec:<12} {h:>5} / {tot:<5} ({100 * h / tot if tot else 0:.1f}%)")

    flip_report(paths, a.since)
    return 0


# ---------------------------------------------------------------------------
# Would the floor have cost us shipped inventory?
#
# The PASS boundary does NOT depend on the composite here: `dossier.py:187-199` rules PASS on
# `grounded_support(checks, cfg)` — (n_supported >= min_supported_to_pass) AND
# (moat_grounded >= 1). The composite is scored from the candidate NARRATIVE and a verdict
# demotion cannot move it. So the flip is exactly computable offline, with no model call, by
# demoting the affected checks and re-running the real `grounded_support` under the real
# per-lane config. This is the E11 replay pattern; unlike E11 it is not limited to hard gates,
# because the PASS side is decided by one function rather than by `apply_gates`.
# ---------------------------------------------------------------------------

#: Tiers whose SINGLE publisher is the authority on the question, so corroboration by a second
#: publisher adds nothing. `legislation.gov.uk` alone IS the answer on legality; demanding a
#: blog agree with it makes the evidence worse, not better.
_AUTHORITATIVE = ("government", "academic")
_AUTHORITATIVE_WIDE = ("government", "academic", "media", "established_org")

VARIANTS = (
    ("A blanket        ", ()),
    ("B gov/academic ok", _AUTHORITATIVE),
    ("C + media/orgs ok", _AUTHORITATIVE_WIDE),
)


def _cited_urls(ck: dict) -> list[str]:
    cited = {str(c) for c in (ck.get("citations") or [])}
    srcs = [s for s in (ck.get("sources") or []) if isinstance(s, dict)]
    urls = [s.get("url") or "" for s in srcs
            if not cited or str(s.get("source_id") or "") in cited]
    return [u for u in urls if u]


def _would_demote(ck: dict, exempt: tuple[str, ...], min_domains: int) -> bool:
    if str(ck.get("verdict") or "").lower() != "supported":
        return False
    urls = _cited_urls(ck)
    if not urls:
        return False
    doms = {registrable(host_of(u)) for u in urls}
    doms.discard("")
    if len(doms) >= min_domains:
        return False
    return not any(tier(host_of(u)) in exempt for u in urls)


def flip_report(paths: list[str], since: str) -> None:
    from prospector.config import load_config
    from prospector.dossier import grounded_support
    from prospector.models import CheckResult, Verdict

    base = load_config("config.yaml")
    lanes: dict = {}

    def cfg_for(t):
        if t not in lanes:
            try:
                lanes[t] = base.for_lane(t)
            except Exception:  # noqa: BLE001
                lanes[t] = base
        return lanes[t]

    passes = []
    for p in paths:
        if p.endswith(".kill.json"):
            continue
        try:
            with open(p) as fh:
                js = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(js.get("checks"), list) or not js["checks"]:
            continue
        if str(js.get("decision") or "").upper() != "PASS":
            continue
        if since and _dossier_date(js, p) < since:
            continue
        passes.append((os.path.basename(p), js))

    print(f"\nPASS dossiers replayed: {len(passes)}")
    if not passes:
        return

    for label, exempt in VARIANTS:
        flipped: list[tuple[str, str]] = []
        touched = 0
        for name, js in passes:
            tier_name = js.get("ambition_tier")
            cfg = cfg_for(tier_name)
            rebuilt, hit = [], False
            for ck in js["checks"]:
                if not isinstance(ck, dict):
                    continue
                v = str(ck.get("verdict") or "unverifiable")
                if _would_demote(ck, exempt, 2):
                    v, hit = "unverifiable", True
                try:
                    verdict = Verdict(v)
                except ValueError:
                    verdict = Verdict.UNVERIFIABLE
                rebuilt.append(CheckResult(
                    check_name=str(ck.get("check_name") or ""),
                    verdict=verdict,
                    confidence=float(ck.get("confidence") or 0.0),
                    rationale="", citations=[], sources=[]))
            if hit:
                touched += 1
            n_sup, moat, moat_checks = grounded_support(rebuilt, cfg)
            min_sup = getattr(cfg.thresholds, "min_supported_to_pass", 1)
            if n_sup < min_sup or moat < 1:
                why = "moat_ungrounded" if moat < 1 else "source_or_die"
                flipped.append((name, f"{why} (lane={tier_name}, moat={','.join(moat_checks)})"))
        print(f"  {label}: {touched:>3}/{len(passes)} passes touched, "
              f"{len(flipped):>3} FLIP to KILL")
        for name, why in flipped[:10]:
            print(f"      {name}  {why}")


if __name__ == "__main__":
    raise SystemExit(main())
