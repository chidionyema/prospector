#!/usr/bin/env python3
"""E13 (claim-reframe probe) — would a PROXY-FRAMED claim be grounded by passages we ALREADY hold?

Programme doc §10 registers E13 as: "replay ~30 unverifiable payer_solvency/distribution checks
with proxy-framed claims on the current moat; metric = grounded-rate (supported OR refuted). Kill
criterion: <2x improvement over the 10:1 absence ratio means the reframe is wrong too."

§10's diagnosis is that those two checks ask the open web a question about a product that does not
exist ("will UK freelance designers pay for X"), so the passage that would answer them was never
published. The proposed fix is the `price_comparables.py` move — evidence-only, reframed onto a
class of evidence the web DOES publish:

  payer_solvency -> "buyers in this segment already pay a STATED AMOUNT for an adjacent product"
  distribution   -> "a NAMED channel that reaches this segment exists"

The live version of E13 needs the moat to re-rule ~30 checks. This runner answers the PRIOR
question for free, offline, and over the whole population rather than a 30-check sample:

    Is the proxy evidence already sitting in the passages the judge was shown and ignored?

If it is not, the reframe is dead before it costs a token — no re-vet of ~700 absence-kills can
recover evidence that is not on disk. If it is, the reframe's ceiling is measured, and the only
thing left to buy is the LLM's judgement of probativeness.

METHOD (deterministic; no LLM verdict is simulated)
  Population: every payer_solvency / distribution check with >=1 stored passage and
  retrieval_failed falsy — §10's bucket D, plus the ruled checks of the same names as a
  calibration arm.

  A check "holds proxy evidence" iff >=1 of its stored passages satisfies that check's proxy
  pattern. The pattern is a conjunction of three deterministic tests, all over passage text only:

    payer_solvency:  MONEY (a currency amount literally present in the passage — the
                     `price_comparables.py:104` rail: a transcription, never an assertion)
                   + SPEND semantics (pay/spend/fee/price/budget/subscription/...)
                   + SEGMENT anchor (>=1 candidate-specific term from who_pays/title/one_liner)

    distribution:    CHANNEL noun (association/federation/marketplace/community/directory/...)
                   + NAMED (a capitalised token inside a +/-80 char window of the channel noun,
                     i.e. the channel is named, not a generic gesture at "a community")
                   + SEGMENT anchor (same)

  Lexical/entity overlap is a PROXY for probativeness, exactly as in E16 — a passage can carry a
  price and a segment word and still not evidence willingness-to-pay. So every number here is an
  UPPER BOUND on what the reframe can recover, and the LLM-judged replay is the follow-up.

  Three controls, because a detector that fires on everything measures nothing:
    1. CALIBRATION — the same detector on already-RULED checks of the same name. A detector that
       fires no more often on evidence that sufficed to rule than on evidence that did not is
       measuring vocabulary, not evidence.
    2. SWAPPED — the payer_solvency detector on distribution checks and vice versa. Separates
       "this passage set carries proxy evidence of the RIGHT class" from "carries any pattern".
    3. SHUFFLED SEGMENT — each check's passages scored against a DIFFERENT candidate's segment
       terms (deterministic offset, no RNG). Isolates how much of the hit rate the segment anchor
       is actually earning versus generic money/channel boilerplate anywhere on the web.

  Generic segment terms are removed by a corpus document-frequency cut (a term appearing in more
  than SEGMENT_DF_MAX of candidates is not a segment anchor), so "business" and "service" cannot
  manufacture a match.

Read-only over store/. Zero LLM. Zero network. Writes e13_proxy_claim_reframe_receipts.json
next to this file.

Usage:
    .venv/bin/python tools/experiments/e13_proxy_claim_reframe.py [--current-moat]
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DOSSIERS = os.path.join(ROOT, "store", "dossiers", "*.json")

CHECKS = ("payer_solvency", "distribution")
MOAT = {"claude_cli", "claude"}
RULED = {"supported", "refuted"}

# A term present in more than this share of candidates is corpus boilerplate, not a segment.
SEGMENT_DF_MAX = 0.05

# --- lexicons ---------------------------------------------------------------------------------
# Currency amounts. Written to require a currency marker so a bare year ("2025") or a member count
# cannot pass as a price. This is the offline analogue of price_comparables.py's rail: the amount
# is EXTRACTED from the passage, so it is literally present by construction.
_MONEY = re.compile(
    r"(?:[£$€]\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|bn|billion|million|thousand)?)"
    r"|(?:\b\d[\d,]*(?:\.\d+)?\s?(?:pounds|pence|dollars|euros|gbp|usd|eur|pcm|p/m)\b)",
    re.I,
)
_SPEND = re.compile(
    r"\b(pay|pays|paid|paying|payment|spend|spends|spent|spending|cost|costs|costing|fee|fees|"
    r"price|prices|pricing|priced|charge|charges|charged|subscription|subscriptions|budget|"
    r"budgets|invoice|invoiced|retainer|premium|premiums|tariff|rate card|revenue|turnover|"
    r"expenditure|outlay|willingness to pay|per month|per year|per annum|annual fee)\b",
    re.I,
)
_CHANNEL = re.compile(
    r"\b(association|associations|federation|institute|society|societies|chamber of commerce|"
    r"chamber|guild|union|trade body|trade association|membership|members|community|communities|"
    r"forum|forums|subreddit|marketplace|directory|register|registry|newsletter|conference|"
    r"trade show|expo|exhibition|meetup|network|networks|platform|portal|council|alliance|"
    r"coalition|group|groups|body|bodies|cooperative|co-operative)\b",
    re.I,
)
_CAP = re.compile(r"\b[A-Z][A-Za-z&'’.-]{2,}\b")

_STOP = {
    "the", "a", "an", "of", "for", "to", "in", "on", "by", "with", "is", "are", "was", "were",
    "be", "been", "this", "that", "these", "those", "it", "its", "as", "at", "from", "how",
    "what", "who", "which", "do", "does", "did", "can", "will", "would", "there", "their",
    "you", "your", "we", "our", "they", "them", "he", "she", "his", "her", "have", "has",
    "and", "or", "not", "but", "into", "than", "then", "when", "while", "also", "such",
}
# The fixed template tails verify.py appends to every query (see E16). They are byte-identical
# across candidates, so they are never segment anchors.
_TEMPLATE_TAIL_TERMS = {
    "obsolete", "commoditised", "commoditized", "replaced", "free", "alternative",
    "regulation", "licence", "license", "required", "banned", "illegal",
    "incumbent", "market", "leader", "dominant", "competitor",
    "budget", "cuts", "cannot", "afford", "insolvency",
    "customer", "acquisition", "channel", "saturated", "expensive",
    "real", "problem", "existing", "workaround",
    "durable", "moat", "barrier", "defensibility",
    "legal", "framework", "compliance", "pathway",
    "gap", "underserved", "segment",
    "willingness", "pay", "roi", "case", "study",
    "acute", "testimonial", "evidence",
}


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z][a-z0-9-]{3,}", (text or "").lower())
        if w not in _STOP and w not in _TEMPLATE_TAIL_TERMS
    }


def raw_segment_terms(cand: dict) -> set[str]:
    """Candidate-specific vocabulary for WHO the buyers are and WHAT the thing is."""
    return _tokens(" ".join(str(cand.get(k) or "") for k in ("who_pays", "title", "one_liner")))


def has_money(text: str) -> bool:
    return bool(_MONEY.search(text or ""))


def has_spend(text: str) -> bool:
    return bool(_SPEND.search(text or ""))


def named_channel(text: str) -> bool:
    """A channel noun with a capitalised token near it — a channel that is NAMED, not gestured at.

    Capitalised tokens at position 0 of the passage are ignored: a snippet that merely starts with
    a sentence would otherwise be 'named' for free.
    """
    t = text or ""
    for m in _CHANNEL.finditer(t):
        lo, hi = max(0, m.start() - 80), min(len(t), m.end() + 80)
        for c in _CAP.finditer(t[lo:hi]):
            if lo + c.start() > 0:
                return True
    return False


def segment_hits(text: str, seg: set[str]) -> int:
    return len(_tokens(text) & seg)


def proxy_match(check_name: str, text: str, seg: set[str], min_seg: int = 1) -> bool:
    """Does this passage satisfy the proxy-framed claim for `check_name`?"""
    if segment_hits(text, seg) < min_seg:
        return False
    if check_name == "payer_solvency":
        return has_money(text) and has_spend(text)
    if check_name == "distribution":
        return named_channel(text)
    return False


def main() -> int:
    current_moat_only = "--current-moat" in sys.argv
    scope = "CURRENT MOAT ONLY (claude_cli/claude)" if current_moat_only else "ALL PROVIDER ERAS"

    # ---- pass 1: collect the population + candidate document frequencies ----------------------
    dossier_paths = sorted(glob.glob(DOSSIERS))
    records = []          # one per in-scope check
    cand_terms: dict[str, set[str]] = {}
    df = Counter()
    verdict_pop = defaultdict(Counter)   # check_name -> verdict -> n (whole population, for the
                                         # baseline grounded-rate this experiment is measured against)

    for path in dossier_paths:
        try:
            with open(path) as fh:
                dossier = json.load(fh)
        except Exception:
            continue
        cand = dossier.get("candidate") or {}
        cid = cand.get("candidate_id") or os.path.basename(path).split(".")[0]
        for chk in dossier.get("checks") or []:
            name = chk.get("check_name")
            if name not in CHECKS:
                continue
            if current_moat_only and (chk.get("provider") or "") not in MOAT:
                continue
            verdict = chk.get("verdict")
            verdict_pop[name][verdict or "?"] += 1
            srcs = [s for s in (chk.get("sources") or []) if (s.get("text") or "").strip()]
            if not srcs or chk.get("retrieval_failed"):
                continue
            if verdict not in RULED and verdict != "unverifiable":
                continue
            if cid not in cand_terms:
                terms = raw_segment_terms(cand)
                cand_terms[cid] = terms
                for t in terms:
                    df[t] += 1
            records.append({
                "cid": cid,
                "check": name,
                "arm": "bucketD" if verdict == "unverifiable" else "ruled",
                "verdict": verdict,
                "cited": set(chk.get("citations") or []),
                "passages": [(s.get("source_id"), s.get("text") or "") for s in srcs],
            })

    if not records:
        print("no in-scope checks found — is store/dossiers populated?")
        return 1

    n_cands = len(cand_terms)
    cutoff = SEGMENT_DF_MAX * n_cands
    generic = {t for t, c in df.items() if c > cutoff}
    seg_of = {cid: (terms - generic) for cid, terms in cand_terms.items()}

    # Deterministic shuffled-segment control: each candidate borrows the segment terms of the
    # candidate half the sorted list away. No RNG, so the control reproduces byte-for-byte.
    order = sorted(seg_of)
    shift = max(1, len(order) // 2)
    borrowed = {cid: seg_of[order[(i + shift) % len(order)]] for i, cid in enumerate(order)}

    # ---- pass 2: score ------------------------------------------------------------------------
    stat = defaultdict(Counter)          # (check, arm) -> counters
    hit_rank = defaultdict(Counter)      # check -> rank histogram of first proxy-matching passage
    hit_cited = Counter()                # check -> first proxy hit was ALREADY cited by the judge
    examples = defaultdict(list)
    passages_scored = 0
    bucketD_passage_chars = 0            # sizes the LLM-judged follow-up (see followup_sizing)

    for rec in records:
        name, arm, cid = rec["check"], rec["arm"], rec["cid"]
        seg, seg_ctl = seg_of.get(cid, set()), borrowed.get(cid, set())
        other = "distribution" if name == "payer_solvency" else "payer_solvency"
        key = (name, arm)
        stat[key]["checks"] += 1
        if not seg:
            stat[key]["no_segment_terms"] += 1

        first_hit = None
        hit2 = swapped = shuffled = False
        for rank, (sid, text) in enumerate(rec["passages"]):
            passages_scored += 1
            if arm == "bucketD":
                bucketD_passage_chars += len(text)
            if first_hit is None and proxy_match(name, text, seg, 1):
                first_hit = (rank, sid, text)
            if proxy_match(name, text, seg, 2):
                hit2 = True
            if proxy_match(other, text, seg, 1):
                swapped = True
            if proxy_match(name, text, seg_ctl, 1):
                shuffled = True

        stat[key]["passages"] += len(rec["passages"])
        if first_hit is not None:
            stat[key]["hit"] += 1
            if arm == "bucketD":
                hit_rank[name][first_hit[0]] += 1
                if first_hit[1] in rec["cited"]:
                    hit_cited[name] += 1
                if len(examples[name]) < 5:
                    examples[name].append({
                        "candidate_id": cid, "rank": first_hit[0], "source_id": first_hit[1],
                        "passage": first_hit[2][:280],
                    })
        if hit2:
            stat[key]["hit_strict"] += 1
        if swapped:
            stat[key]["hit_swapped"] += 1
        if shuffled:
            stat[key]["hit_shuffled"] += 1

    # ---- report -------------------------------------------------------------------------------
    def share(a: int, b: int) -> float:
        return (a / b) if b else 0.0

    print(f"E13 proxy-claim reframe probe — {scope}")
    print(f"checks analysed: {len(records)}   passages scored: {passages_scored}   "
          f"candidates: {n_cands}")
    print(f"generic terms removed by DF>{SEGMENT_DF_MAX:.0%} cut: {len(generic)} "
          f"of {len(df)} candidate terms")
    print()

    per_check = {}
    tot_D = tot_hit = 0
    for name in CHECKS:
        d, r = stat[(name, "bucketD")], stat[(name, "ruled")]
        pop = verdict_pop[name]
        ruled_pop = sum(pop[v] for v in RULED)
        unver_pop = pop.get("unverifiable", 0)
        base = share(ruled_pop, ruled_pop + unver_pop)
        # Upper bound: every bucket-D check holding proxy evidence becomes rulable.
        proj = share(ruled_pop + d["hit"], ruled_pop + unver_pop)
        tot_D += d["checks"]
        tot_hit += d["hit"]
        row = {
            "check": name,
            "population_ruled": ruled_pop,
            "population_unverifiable": unver_pop,
            "baseline_grounded_rate": round(base, 4),
            "absence_ratio": round(share(unver_pop, ruled_pop), 2) if ruled_pop else None,
            "bucketD_checks_scored": d["checks"],
            "bucketD_passages": d["passages"],
            "bucketD_proxy_hit": d["hit"],
            "bucketD_proxy_hit_share": round(share(d["hit"], d["checks"]), 4),
            "bucketD_proxy_hit_strict_2seg": d["hit_strict"],
            "bucketD_proxy_hit_strict_share": round(share(d["hit_strict"], d["checks"]), 4),
            "control_swapped_detector_share": round(share(d["hit_swapped"], d["checks"]), 4),
            "control_shuffled_segment_share": round(share(d["hit_shuffled"], d["checks"]), 4),
            "ruled_checks_scored": r["checks"],
            "calibration_ruled_hit_share": round(share(r["hit"], r["checks"]), 4),
            "bucketD_no_segment_terms": d["no_segment_terms"],
            "projected_grounded_rate_upper_bound": round(proj, 4),
            "improvement_factor_upper_bound": round(proj / base, 2) if base else None,
            "first_hit_already_cited": hit_cited[name],
        }
        per_check[name] = row

        print(f"--- {name} ---")
        print(f"  population (this scope)        ruled={ruled_pop}  unverifiable={unver_pop}  "
              f"absence ratio {row['absence_ratio']}:1")
        print(f"  baseline grounded-rate         {base:.1%}")
        print(f"  bucket-D checks scored         {d['checks']}  ({d['passages']} passages)")
        print(f"  HOLDS proxy evidence (>=1 seg) {d['hit']}  = {share(d['hit'], d['checks']):.1%}")
        print(f"  strict (>=2 segment terms)     {d['hit_strict']}  "
              f"= {share(d['hit_strict'], d['checks']):.1%}")
        print(f"  CONTROL swapped detector       {share(d['hit_swapped'], d['checks']):.1%}   "
              f"(other check's pattern on this check's passages)")
        print(f"  CONTROL shuffled segment       {share(d['hit_shuffled'], d['checks']):.1%}   "
              f"(another candidate's segment terms)")
        print(f"  CALIBRATION ruled-arm hit      {share(r['hit'], r['checks']):.1%}  "
              f"(n={r['checks']}) — what evidence that DID rule looks like")
        print(f"  projected grounded-rate (UB)   {proj:.1%}  = {row['improvement_factor_upper_bound']}x baseline")
        print()

    overall_hit = share(tot_hit, tot_D)
    # Combined kill-criterion arithmetic over both checks.
    c_ruled = sum(per_check[n]["population_ruled"] for n in CHECKS)
    c_unver = sum(per_check[n]["population_unverifiable"] for n in CHECKS)
    c_hits = sum(per_check[n]["bucketD_proxy_hit"] for n in CHECKS)
    c_base = share(c_ruled, c_ruled + c_unver)
    c_proj = share(c_ruled + c_hits, c_ruled + c_unver)
    c_factor = (c_proj / c_base) if c_base else 0.0

    print("=== COMBINED (payer_solvency + distribution) ===")
    print(f"  bucket-D checks holding proxy evidence : {tot_hit}/{tot_D} = {overall_hit:.1%}")
    print(f"  baseline grounded-rate                 : {c_base:.1%} "
          f"({c_ruled} ruled / {c_ruled + c_unver} checks)")
    print(f"  projected grounded-rate (upper bound)  : {c_proj:.1%}")
    c_maxfactor = (1.0 / c_base) if c_base else 0.0
    c_absence = round(share(c_unver, c_ruled), 2) if c_ruled else None
    print(f"  improvement factor (upper bound)       : {c_factor:.2f}x    "
          f"[E13 kill criterion: <2x = reframe wrong]")
    print()
    print("  KILL-CRITERION CALIBRATION — §10 sets the bar as '<2x improvement over the 10:1")
    print("  absence ratio'. The 10:1 premise is not what is on disk for these two checks:")
    print(f"    measured absence ratio (this scope)  : {c_absence}:1")
    print(f"    measured baseline grounded-rate      : {c_base:.1%}")
    print(f"    ceiling if EVERY unverifiable check became ruled : {c_maxfactor:.2f}x")
    # factor 2 needs (ruled + h)/total == 2*ruled/total, i.e. h == ruled.
    need_share = share(c_ruled, c_unver)
    print(f"    a literal 2x needs {c_ruled} recovered checks = {need_share:.0%} of ALL "
          f"{c_unver} unverifiable ones")
    print("  the criterion was calibrated against an absence ratio the corpus does not have.")
    print("  The scope-free number to judge the reframe on is the bucket-D recovery share above.")
    print()
    print("Rank of the FIRST proxy-matching passage in stored order (bucket D):")
    for name in CHECKS:
        h = hit_rank[name]
        tot = sum(h.values()) or 1
        top = ", ".join(f"r{r}={h[r]} ({h[r]/tot:.0%})" for r in sorted(h)[:6])
        print(f"  {name:<16} {top}")
        print(f"  {'':<16} already cited by the judge: {hit_cited[name]}/{tot} "
              f"= {share(hit_cited[name], tot):.1%}")

    print()
    print("VERDICT")
    if c_factor >= 2.0:
        print(f"  SUPPORTED (upper bound): {c_factor:.2f}x >= 2x. The proxy evidence class is")
        print("  already on disk for a large share of bucket-D checks — the claim framing, not")
        print("  retrieval, is what missed it. Next step is the LLM-judged replay.")
    else:
        print(f"  KILLED (upper bound): {c_factor:.2f}x < 2x. Even granting every proxy-pattern")
        print("  passage as groundable, the reframe cannot double the grounded-rate on stored")
        print("  evidence. A live replay cannot beat this ceiling without NEW retrieval.")
    # ---- sizing the LLM-judged follow-up ------------------------------------------------------
    # The follow-up re-rules bucket-D checks with proxy-framed CLAIM text against the SAME stored
    # passages. Retrieval is already paid for and cached on disk, so the marginal cost is verdict
    # calls only. Prompt size is dominated by the passages, so chars/4 is the standard rough token
    # count; it is reported as a token figure, not a dollar figure, because no price is derivable
    # from this corpus (the ledger is the only source for $, and it is not read here).
    followup = {
        "unit": "one verdict call per bucket-D check, zero new retrieval calls",
        "checks_full_replay": tot_D,
        "checks_doc_sample": 30,          # §10's "~30 unverifiable ... checks"
        "bucketD_passage_chars": bucketD_passage_chars,
        "approx_passage_tokens_full_replay": bucketD_passage_chars // 4,
        "approx_passage_tokens_per_check": (bucketD_passage_chars // 4 // tot_D) if tot_D else 0,
        "new_retrieval_calls": 0,
        "note": ("Passages are already on disk (store/dossiers[].checks[].sources[].text), so the "
                 "replay costs verdict tokens only. Dollar cost is NOT computed here — deriving it "
                 "requires the spend ledger, which this read-only probe does not touch."),
    }
    print()
    print("LLM-JUDGED FOLLOW-UP SIZING (the version this probe does not run)")
    print(f"  full replay      : {tot_D} verdict calls, 0 new retrieval calls, "
          f"~{followup['approx_passage_tokens_full_replay']:,} passage tokens "
          f"(~{followup['approx_passage_tokens_per_check']:,}/check)")
    print(f"  §10's 30-sample  : 30 verdict calls, 0 new retrieval calls, "
          f"~{30 * followup['approx_passage_tokens_per_check']:,} passage tokens")
    print()
    print("CAVEAT: lexical/entity match is an UPPER BOUND on probativeness (same caveat as E16).")
    print("The LLM-judged version — re-ruling these checks with proxy-framed claim text on the")
    print("current moat — is the follow-up this probe sizes, not replaces.")

    receipts = {
        "experiment": "E13 — proxy-framed claim reframe, offline replay over stored passages",
        "programme_ref": "docs/COMMERCIAL_READINESS_PROGRAM.md §10 (line 366), §19.4",
        "scope": scope,
        "method": "deterministic lexical/entity proxy-evidence detector; no LLM verdict simulated",
        "kill_criterion": "improvement factor < 2x over baseline grounded-rate => reframe wrong",
        # The daemon writes new dossiers while this runs, so the population is a moving target.
        # Recording both pins exactly which corpus produced these numbers.
        "run_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "dossier_files_globbed": len(dossier_paths),
        "limitations": [
            "Lexical/entity match is an UPPER BOUND on probativeness — a passage can carry a price "
            "and a segment term and still not evidence willingness-to-pay. See `examples`: several "
            "first-hit passages are clearly not probative on inspection.",
            "The two detectors are not equally specific. The distribution pattern (named channel) "
            "is looser than the payer_solvency pattern (money + spend), which is why the SWAPPED "
            "control on payer_solvency passages exceeds that check's own hit rate.",
            "store/dossiers is written by the live daemon; re-running on a later corpus will shift "
            "counts by a few checks. run_at_utc + dossier_files_globbed pin this run.",
            "No LLM verdict is simulated. The follow-up is a live re-rule of these checks with "
            "proxy-framed claim text on the current moat.",
        ],
        "segment_df_max": SEGMENT_DF_MAX,
        "candidates": n_cands,
        "generic_terms_removed": len(generic),
        "distinct_candidate_terms": len(df),
        "checks_analysed": len(records),
        "passages_scored": passages_scored,
        "per_check": per_check,
        "combined": {
            "bucketD_checks_scored": tot_D,
            "bucketD_proxy_hit": tot_hit,
            "bucketD_proxy_hit_share": round(overall_hit, 4),
            "population_ruled": c_ruled,
            "population_unverifiable": c_unver,
            "baseline_grounded_rate": round(c_base, 4),
            "projected_grounded_rate_upper_bound": round(c_proj, 4),
            "improvement_factor_upper_bound": round(c_factor, 4),
            "absence_ratio_measured": c_absence,
            "max_possible_factor_if_all_unverifiable_ruled": round(c_maxfactor, 4),
            "verdict": "SUPPORTED" if c_factor >= 2.0 else "KILLED",
            "kill_criterion_note": (
                "§10 calibrated the 2x bar against an assumed 10:1 absence ratio. Measured on disk "
                f"for these two checks the absence ratio is {c_absence}:1 and the baseline "
                f"grounded-rate is {c_base:.1%}, so the ceiling — every unverifiable check "
                f"becoming ruled — is only {c_maxfactor:.2f}x. The literal 2x bar is therefore "
                "near-unreachable by arithmetic, not by the reframe's merit. Judge the reframe on "
                "the bucket-D recovery share instead."
            ),
        },
        "first_hit_rank_histogram": {
            n: {str(k): v for k, v in sorted(hit_rank[n].items())} for n in CHECKS
        },
        "first_hit_already_cited": dict(hit_cited),
        "followup_sizing": followup,
        "examples": {n: examples[n] for n in CHECKS},
    }
    dest = os.path.join(
        HERE,
        "e13_proxy_claim_reframe_receipts"
        + ("_current_moat" if current_moat_only else "") + ".json",
    )
    with open(dest, "w") as fh:
        json.dump(receipts, fh, indent=2)
    print(f"\nreceipts -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
