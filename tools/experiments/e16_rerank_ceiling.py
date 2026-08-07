#!/usr/bin/env python3
"""E16 (ceiling probe) — is there headroom for reranking the passages we ALREADY stored?

Programme doc §14 registers E16 as "bge-rerank the stored passages of bucket-D checks — does
better evidence selection move unverifiable->ruled?". Running the real reranker needs a ~2GB
torch+transformers install. This probe answers the PRIOR question for free, in pure Python:

    Is the probative passage even IN the retrieved set?

Because the two candidate explanations for §18's finding (35.8% of August kills lost to grounding
QUALITY, on candidates carrying a mean 21.4 citations) make opposite predictions:

  * SELECTION failure (§10 R2, "templated suffixes on keyword salad") — a good passage was
    retrieved but buried among junk. Reranking recovers it. Headroom is REAL.
  * AVAILABILITY failure (§10 R1, "the question class is unanswerable in principle") — the open
    web never published a passage that answers this claim. Reranking cannot invent one. Headroom
    is ZERO and the fix is E13's claim reframe instead.

Method, stratified by check_name so we never compare an easy check against a hard one:
  For each check we have `queries` (verify.py:481-493) and `sources[].text`. We score every stored
  passage by lexical overlap with the CANDIDATE-SPECIFIC query terms — after stripping the fixed
  template operator suffixes (_DISCONFIRM/_CONFIRM boilerplate), which are identical across every
  candidate and would otherwise manufacture overlap that carries no information.

  Then, per check_name, compare:
    A. supported checks     -> distribution of their BEST passage's overlap  (what "enough
                              evidence to rule" actually looked like)
    B. bucket-D checks      -> distribution of their BEST passage's overlap
  If B's best passages reach A's typical best, the evidence was present and unused -> rerank.
  If B's best passages sit far below, the evidence was absent -> reframe the claim.

  We also measure the junk floor (non-Latin boilerplate, navigation chrome, stubs), because a
  passage set that is mostly junk is direct evidence for the selection story.

Read-only. Zero LLM. Zero network. Writes e16_rerank_ceiling_receipts.json next to this file.
"""
from __future__ import annotations

import json
import glob
import os
import re
import sys
import unicodedata
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DOSSIERS = os.path.join(ROOT, "store", "dossiers", "*.json")

# The fixed template tails from verify.py _DISCONFIRM_TEMPLATES / _CONFIRM_TEMPLATES. These are
# byte-identical across every candidate, so counting them as query terms would inflate overlap
# uniformly and destroy the contrast this probe exists to measure.
_TEMPLATE_TAIL_TERMS = {
    "obsolete", "commoditised", "commoditized", "replaced", "free", "alternative",
    "regulation", "licence", "license", "required", "banned", "illegal",
    "incumbent", "market", "leader", "dominant", "competitor",
    "budget", "cuts", "cannot", "afford", "insolvency",
    "customer", "acquisition", "channel", "saturated", "expensive",
    "not", "real", "problem", "existing", "workaround",
    "durable", "moat", "barrier", "defensibility",
    "legal", "framework", "compliance", "pathway",
    "gap", "underserved", "segment",
    "willingness", "pay", "roi", "case", "study",
    "acute", "testimonial", "evidence",
    "or", "and",
}
_STOP = {
    "the", "a", "an", "of", "for", "to", "in", "on", "by", "with", "is", "are", "was", "were",
    "be", "been", "this", "that", "these", "those", "it", "its", "as", "at", "from", "how",
    "what", "who", "which", "do", "does", "did", "can", "will", "would", "there", "their",
    "you", "your", "we", "our", "they", "them", "he", "she", "his", "her", "have", "has",
}


def _terms(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z][a-z0-9-]{2,}", (text or "").lower())
        if w not in _STOP
    }


def query_terms(queries: list[str]) -> set[str]:
    """Candidate-specific query vocabulary: query terms minus the shared template boilerplate."""
    out: set[str] = set()
    for q in queries or []:
        out |= _terms(q)
    return out - _TEMPLATE_TAIL_TERMS


def latin_ratio(text: str) -> float:
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    return latin / len(letters)


_JUNK_MARKERS = (
    "cookie", "sign in", "log in", "subscribe to", "all rights reserved", "privacy policy",
    "terms of service", "javascript", "enable javascript", "404", "page not found",
    "skip to content", "browse by", "shopping cart", "add to basket",
)


def is_junk(text: str) -> tuple[bool, str]:
    """Cheap, conservative junk classifier. Only flags what is unambiguously not evidence."""
    t = (text or "").strip()
    if len(t) < 120:
        return True, "stub"
    if latin_ratio(t) < 0.55:
        return True, "non_latin"
    low = t.lower()
    hits = sum(1 for m in _JUNK_MARKERS if m in low)
    if hits >= 2 and len(t) < 900:
        return True, "chrome"
    return False, ""


def overlap(passage: str, qterms: set[str]) -> float:
    """Fraction of the candidate-specific query vocabulary that the passage actually contains."""
    if not qterms:
        return 0.0
    return len(_terms(passage) & qterms) / len(qterms)


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[i]


def main() -> int:
    current_moat_only = "--current-moat" in sys.argv
    MOAT = {"claude_cli", "claude"}

    # per check_name -> {"supported": [best_overlap...], "bucketD": [...]}
    best_by = defaultdict(lambda: defaultdict(list))
    # bucket-D rank analysis: where does the best passage sit in the stored order?
    best_rank = defaultdict(int)
    junk_counts = defaultdict(int)
    junk_reasons = defaultdict(int)
    passages_seen = 0
    checks_seen = 0
    skipped_no_qterms = 0

    for path in glob.glob(DOSSIERS):
        try:
            with open(path) as fh:
                dossier = json.load(fh)
        except Exception:
            continue
        for chk in dossier.get("checks") or []:
            verdict = chk.get("verdict")
            srcs = chk.get("sources") or []
            if not srcs or chk.get("retrieval_failed"):
                continue
            if current_moat_only and (chk.get("provider") or "") not in MOAT:
                continue
            if verdict == "unverifiable":
                arm = "bucketD"
            elif verdict == "supported":
                arm = "supported"
            else:
                continue  # refuted is a ruled verdict but a different evidence shape

            qt = query_terms(chk.get("queries") or [])
            if not qt:
                skipped_no_qterms += 1
                continue

            checks_seen += 1
            name = chk.get("check_name") or "?"
            scores = []
            for rank, s in enumerate(srcs):
                text = s.get("text") or ""
                passages_seen += 1
                junk, why = is_junk(text)
                if junk:
                    junk_counts[arm] += 1
                    junk_reasons[why] += 1
                scores.append((overlap(text, qt), rank, junk))

            top = max(scores, key=lambda x: x[0])
            best_by[name][arm].append(top[0])
            if arm == "bucketD":
                best_rank[top[1]] += 1

    if not checks_seen:
        print("no checks matched — is store/dossiers populated?")
        return 1

    scope = "CURRENT MOAT ONLY (claude_cli/claude)" if current_moat_only else "ALL PROVIDER ERAS"
    print(f"E16 ceiling probe — {scope}")
    print(f"checks analysed: {checks_seen}   passages scored: {passages_seen}   "
          f"skipped (no candidate-specific query terms): {skipped_no_qterms}")
    print()
    print("Best-passage query-term coverage, by check. 'reachable' = share of bucket-D checks whose")
    print("BEST stored passage already meets the MEDIAN best of that check's supported rulings.")
    print()
    hdr = f"{'check':<20} {'n_sup':>6} {'n_D':>6} {'sup med':>8} {'D med':>7} {'D p90':>7} {'reachable':>10}"
    print(hdr)
    print("-" * len(hdr))

    rows = []
    tot_D = 0
    tot_reach = 0
    for name in sorted(best_by, key=lambda n: -len(best_by[n]["bucketD"])):
        sup = best_by[name]["supported"]
        bad = best_by[name]["bucketD"]
        if not sup or not bad:
            continue
        bar = pct(sup, 50)
        reach = sum(1 for v in bad if v >= bar)
        tot_D += len(bad)
        tot_reach += reach
        rows.append({
            "check": name, "n_supported": len(sup), "n_bucketD": len(bad),
            "supported_median_best": round(bar, 3),
            "bucketD_median_best": round(pct(bad, 50), 3),
            "bucketD_p90_best": round(pct(bad, 90), 3),
            "reachable_share": round(reach / len(bad), 3),
        })
        print(f"{name:<20} {len(sup):>6} {len(bad):>6} {bar:>8.3f} "
              f"{pct(bad,50):>7.3f} {pct(bad,90):>7.3f} {reach/len(bad):>9.1%}")

    overall = (tot_reach / tot_D) if tot_D else 0.0
    print("-" * len(hdr))
    print(f"{'OVERALL':<20} {'':>6} {tot_D:>6} {'':>8} {'':>7} {'':>7} {overall:>9.1%}")

    print()
    tot_junk = sum(junk_counts.values())
    print(f"Junk passages: {tot_junk}/{passages_seen} = {tot_junk/passages_seen:.1%} of everything "
          f"we stored as evidence")
    for why, n in sorted(junk_reasons.items(), key=lambda kv: -kv[1]):
        print(f"    {why:<10} {n:>6}")

    print()
    print("Where the best bucket-D passage sits in stored order (rerank only helps if it is NOT")
    print("already first — a best-passage-at-rank-0 set is one the judge already saw on top):")
    tot_rank = sum(best_rank.values()) or 1
    for r in sorted(best_rank)[:8]:
        print(f"    rank {r}: {best_rank[r]:>6}  ({best_rank[r]/tot_rank:5.1%})")
    not_first = tot_rank - best_rank.get(0, 0)
    print(f"    -> best passage was NOT already on top in {not_first}/{tot_rank} = "
          f"{not_first/tot_rank:.1%} of bucket-D checks")

    print()
    print("READING")
    if overall >= 0.5:
        print(f"  SELECTION story favoured: {overall:.1%} of bucket-D checks already hold a passage")
        print("  as query-relevant as the median SUPPORTED ruling. The evidence was retrieved and")
        print("  not used. E16's reranker has real headroom — proceed to the torch install.")
    elif overall >= 0.25:
        print(f"  MIXED: {overall:.1%} reachable. Reranking addresses a real but partial slice;")
        print("  the remainder needs §10's E13 claim reframe. Do both, reframe first.")
    else:
        print(f"  AVAILABILITY story favoured: only {overall:.1%} of bucket-D checks hold a passage")
        print("  matching what a supported ruling looked like. Reranking cannot invent evidence.")
        print("  §10 R1 stands: fix the CLAIM (E13), do not buy a reranker yet.")

    out = {
        "scope": scope,
        "checks_analysed": checks_seen,
        "passages_scored": passages_seen,
        "overall_reachable_share": round(overall, 4),
        "junk_share": round(tot_junk / passages_seen, 4) if passages_seen else 0.0,
        "junk_reasons": dict(junk_reasons),
        "best_passage_rank_histogram": {str(k): v for k, v in sorted(best_rank.items())},
        "per_check": rows,
    }
    dest = os.path.join(HERE, "e16_rerank_ceiling_receipts.json")
    with open(dest, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nreceipts -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
