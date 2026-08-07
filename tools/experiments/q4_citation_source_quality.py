#!/usr/bin/env python3
"""Q4 (source-quality probe) — what do our RULED verdicts actually rest on?

Founder observation 2026-08-07: `gitnux.org` (an AI-generated stats farm) appears twice as a
kill-log citation, and a raw `youtube.com/watch` link is used as evidence. The instinct is a
domain denylist in the grounding path. Programme §18 says do not: grounding already fails on
RELEVANCE, not availability, so blindly deleting domains can only starve checks further.

So this measures the blast radius BEFORE any policy exists. It is read-only, zero-LLM,
zero-network, and runs entirely off dossiers already on disk.

The population that matters is the CITED evidence, not the retrieved corpus. `check["citations"]`
holds `source_id` hashes; the URLs live in `check["sources"]`. Counting `sources` measures what
retrieval FETCHED; resolving the ids measures what the judge actually LEANED ON. Those are
different questions and only the second one can justify a denylist.

Two numbers decide the policy:

  (a) exposure  — ruled checks citing >=1 low-quality domain. How dirty the evidence base is.
  (b) blast radius — ruled checks whose citations are ENTIRELY low-quality. These are the
      verdicts a denylist would demote to `unverifiable`. This is the cost side, and §18 says
      it is the number that can make a denylist net-negative.

Tiers are declared explicitly below rather than inferred, so the policy argument is about a
visible list and not about a heuristic nobody can audit.

Usage:
    .venv/bin/python tools/experiments/q4_citation_source_quality.py [--current-moat]
"""

from __future__ import annotations

import collections
import glob
import json
import sys

DOSSIERS = "store/dossiers/*.json"
MOAT = {"claude_cli", "claude", "claude-cli/default"}
RULED = {"supported", "refuted"}

# --- tier definitions -------------------------------------------------------------------------
# MOVED to prospector/admissibility.py (2026-08-07) so the measurement and the SHIPPED gate
# share one definition. Two copies is how the gate and its receipts drift apart. This file's
# published receipts were produced with the identical lists; re-running reproduces them
# byte-for-byte, which is the proof the move changed nothing.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from prospector.admissibility import (  # noqa: E402
    LOW_TIERS,
    UGC_ADMISSIBLE,
    host_of,
    tier,
)


def main() -> int:
    current_moat_only = "--current-moat" in sys.argv

    cited_tier = collections.Counter()
    cited_domain = collections.Counter()
    low_domain_ruled = collections.Counter()
    per_check = collections.Counter()          # ruled checks by check_name
    exposed = collections.Counter()            # ruled checks citing >=1 low-quality
    only_low = collections.Counter()           # ruled checks citing ONLY low-quality
    gate_blast = collections.Counter()         # dossier gate_fired for only-low kills
    ruled_checks = 0
    uncited = 0
    unresolved_ids = 0
    dossiers = 0

    for path in glob.glob(DOSSIERS):
        try:
            with open(path) as fh:
                dossier = json.load(fh)
        except Exception:
            continue
        if not dossier.get("checks"):
            continue
        dossiers += 1
        gate = dossier.get("gate_fired") or "-"

        for chk in dossier["checks"]:
            if chk.get("verdict") not in RULED:
                continue
            if current_moat_only and (chk.get("provider") or "") not in MOAT:
                continue

            by_id = {
                s.get("source_id"): s.get("url") or ""
                for s in (chk.get("sources") or [])
                if isinstance(s, dict)
            }
            cids = chk.get("citations") or []
            urls = []
            for cid in cids:
                if isinstance(cid, str) and cid in by_id:
                    urls.append(by_id[cid])
                elif isinstance(cid, str) and cid.startswith("http"):
                    urls.append(cid)          # tolerate a raw-URL citation shape
                else:
                    unresolved_ids += 1

            name = chk.get("check_name") or "?"
            ruled_checks += 1
            per_check[name] += 1

            hosts = [h for h in (host_of(u) for u in urls) if h]
            if not hosts:
                uncited += 1
                continue

            tiers = []
            for h in hosts:
                t = tier(h)
                tiers.append(t)
                cited_tier[t] += 1
                cited_domain[h] += 1
                if t in LOW_TIERS:
                    low_domain_ruled[h] += 1

            if any(t in LOW_TIERS for t in tiers):
                exposed[name] += 1
            if all(t in LOW_TIERS for t in tiers):
                only_low[name] += 1
                gate_blast[gate] += 1

    scope = "current moat only" if current_moat_only else "all provider eras"
    tot_cites = sum(cited_tier.values())
    tot_exposed = sum(exposed.values())
    tot_only = sum(only_low.values())

    print(f"Q4 citation source quality — {scope}")
    print(f"dossiers={dossiers}  ruled checks={ruled_checks}  "
          f"resolved citation urls={tot_cites}  ruled-but-uncited checks={uncited}  "
          f"unresolved citation ids={unresolved_ids}")
    print()
    print("--- cited evidence by tier (what ruled verdicts actually lean on) ---")
    for t, n in cited_tier.most_common():
        flag = "  <-- LOW" if t in LOW_TIERS else ""
        print(f"  {n:6d}  {n / tot_cites:6.1%}  {t}{flag}")
    print()
    print("--- exposure vs blast radius (the two policy numbers) ---")
    denom = ruled_checks - uncited
    print(f"  ruled checks with >=1 low-quality citation : {tot_exposed:5d} / {denom} = "
          f"{(tot_exposed / denom if denom else 0):.1%}   (exposure)")
    print(f"  ruled checks resting ONLY on low-quality   : {tot_only:5d} / {denom} = "
          f"{(tot_only / denom if denom else 0):.1%}   (denylist blast radius)")
    print()
    print("--- blast radius by check ---")
    for name in sorted(per_check, key=lambda k: -only_low[k]):
        print(f"  {name:20s} ruled={per_check[name]:5d}  exposed={exposed[name]:5d}  "
              f"only-low={only_low[name]:4d}")
    print()
    print("--- kill gates that would be disturbed (dossier gate_fired of only-low checks) ---")
    for g, n in gate_blast.most_common(8):
        print(f"  {n:5d}  {g}")
    print()
    print("--- top low-quality domains behind RULED verdicts ---")
    for h, n in low_domain_ruled.most_common(20):
        print(f"  {n:5d}  {tier(h):16s} {h}")

    # --- policy simulation --------------------------------------------------------------------
    # A blanket denylist is not the only option, and choosing between options is itself a claim
    # that has to be measured. UGC is not uniformly unprobative: for `distribution` and
    # `route_to_market` a Facebook group with 12k members IS the channel being evidenced, whereas
    # for `legality` or `payer_solvency` a TikTok cannot establish what the law says or what
    # buyers pay. So admissibility is scored per check, not per domain.
    # UGC_ADMISSIBLE now comes from prospector.admissibility (imported above) — same value,
    # one definition, so the simulation cannot drift from the gate it is simulating.

    def demoted_under(policy: str, name: str, tiers: list[str]) -> bool:
        if policy == "P0_global":
            bad = LOW_TIERS
        elif policy == "P2_farm_only":
            bad = {"stats_farm", "reference_noise"}
        else:  # P1_check_aware
            bad = {"stats_farm", "reference_noise"}
            if name not in UGC_ADMISSIBLE:
                bad = bad | {"ugc_social"}
        return bool(tiers) and all(t in bad for t in tiers)

    sim = {p: collections.Counter() for p in ("P0_global", "P1_check_aware", "P2_farm_only")}
    for path in glob.glob(DOSSIERS):
        try:
            with open(path) as fh:
                dossier = json.load(fh)
        except Exception:
            continue
        for chk in dossier.get("checks") or []:
            if chk.get("verdict") not in RULED:
                continue
            if current_moat_only and (chk.get("provider") or "") not in MOAT:
                continue
            by_id = {s.get("source_id"): s.get("url") or ""
                     for s in (chk.get("sources") or []) if isinstance(s, dict)}
            hosts = [host_of(by_id.get(c, c if isinstance(c, str) and c.startswith("http") else ""))
                     for c in (chk.get("citations") or [])]
            hosts = [h for h in hosts if h]
            if not hosts:
                continue
            name = chk.get("check_name") or "?"
            tiers = [tier(h) for h in hosts]
            for p in sim:
                if demoted_under(p, name, tiers):
                    sim[p][name] += 1

    print()
    print("--- POLICY SIMULATION: ruled verdicts demoted to `unverifiable` ---")
    for p in ("P0_global", "P1_check_aware", "P2_farm_only"):
        n = sum(sim[p].values())
        print(f"  {p:16s} {n:5d} / {denom} = {(n / denom if denom else 0):6.2%}   "
              f"top: {', '.join(f'{k}={v}' for k, v in sim[p].most_common(3)) or '-'}")

    receipts = {
        "policy_simulation": {p: {"total": sum(sim[p].values()), "by_check": dict(sim[p])}
                              for p in sim},
        "ugc_admissible_checks": sorted(UGC_ADMISSIBLE),
        "scope": scope,
        "dossiers": dossiers,
        "ruled_checks": ruled_checks,
        "ruled_uncited": uncited,
        "resolved_citation_urls": tot_cites,
        "tier_counts": dict(cited_tier),
        "exposure_checks": tot_exposed,
        "exposure_share": round(tot_exposed / denom, 4) if denom else 0.0,
        "blast_radius_checks": tot_only,
        "blast_radius_share": round(tot_only / denom, 4) if denom else 0.0,
        "by_check": {
            k: {"ruled": per_check[k], "exposed": exposed[k], "only_low": only_low[k]}
            for k in per_check
        },
        "gate_blast": dict(gate_blast),
        "top_low_domains": low_domain_ruled.most_common(30),
    }
    out = ("tools/experiments/q4_citation_source_quality_receipts"
           + ("_current_moat" if current_moat_only else "") + ".json")
    with open(out, "w") as fh:
        json.dump(receipts, fh, indent=2)
    print(f"\nreceipts -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
