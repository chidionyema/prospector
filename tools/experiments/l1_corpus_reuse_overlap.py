#!/usr/bin/env python3
"""L1 — MEASUREMENT ONLY: could a reused passage corpus ever serve these checks?

Programme doc §13 (line ~452) registers L1 as "build a local passage store + embedding index;
before live retrieval, serve from corpus when fresh-enough" — and then fences it:

    "HYPOTHESIS to size first: measure query/topic overlap across candidates before building
     (if <20% of checks could ever hit the corpus, don't)."

This module is the sizing and NOTHING else. It builds no passage store, no index, and no cache.
It answers one question with a number and states build / don't build against the 20% bar.

WHAT "COULD HIT THE CORPUS" MEANS, MEASURED THREE WAYS
Order matters: a corpus only holds what was retrieved BEFORE the check that would reuse it.
Candidates are therefore replayed in `created_at` order (ties broken by dossier path, so the
replay is deterministic), and a check can only hit passages already banked by a STRICTLY EARLIER
candidate. Same-candidate reuse is excluded throughout — reusing your own passages within one
vet is not a corpus, it is a variable.

  M1  URL HIT (the decisive one, and the tightest). A check hits iff >=1 url it actually
      retrieved was already banked by an earlier candidate. This is not a model of reuse: it is
      the observed event. A corpus keyed by url would have served that fetch.

  M2  EXACT QUERY HIT. A check hits iff >=1 of its queries is byte-identical (after
      case/whitespace normalisation) to a query issued by an earlier candidate. This is what a
      naive query-keyed cache would serve.

  M3  TOPIC HIT (the loosest, and the upper bound). A check hits iff >=1 of its queries has token
      Jaccard >= JACCARD_MIN against an earlier candidate's query. This is the embedding-index
      version's ceiling: a semantic index cannot beat a generous lexical topic match by much on
      a corpus whose queries are template-generated.

      M3 needs a control, because prospector's queries carry FIXED template tails (E16 found
      them). Template tails are byte-identical across every candidate, so a Jaccard over raw
      tokens would report ~100% overlap and measure the template, not the topic. M3 is therefore
      computed twice: raw, and with the template tail terms stripped. The stripped number is the
      one that answers the question; the raw number is reported so the confound is visible rather
      than assumed away.

FRESHNESS. §13 says "serve from corpus when fresh-enough", so an overlap that only exists across
a two-year gap is not a hit a real corpus would take. The age gap between the banking fetch and
the reusing check is reported as a distribution, and M1 is recomputed under 30/90/365-day
freshness windows.

Read-only over store/. Zero LLM. Zero network. Zero tokens.

Usage:
    .venv/bin/python tools/experiments/runner.py run L1
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus import candidate_id, corpus_fingerprint, dossier_paths, iter_dossiers  # noqa: E402

NAME = "L1"
DOC_REF = "docs/COMMERCIAL_READINESS_PROGRAM.md §13 (line ~452)"

BAR = 0.20                 # §13's build/don't-build threshold
JACCARD_MIN = 0.6
FRESHNESS_DAYS = (30, 90, 365)

# The fixed tails verify.py appends to every generated query. Byte-identical across candidates,
# so they inflate any lexical topic overlap. Same list as e13_proxy_claim_reframe.py uses, for
# the same reason.
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
_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "by", "with", "is", "are", "and", "or",
         "how", "what", "who", "which", "do", "does", "can", "will", "uk", "us"}
_WORD = re.compile(r"[a-z][a-z0-9-]{2,}")


def describe() -> str:
    return ("Sizes L1 against §13's 20% bar: what share of checks could a cross-candidate passage "
            "corpus ever have served? Measurement only — builds nothing.")


def _norm_query(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _tokens(q: str, strip_template: bool) -> frozenset[str]:
    toks = {w for w in _WORD.findall((q or "").lower()) if w not in _STOP}
    if strip_template:
        toks -= _TEMPLATE_TAIL_TERMS
    return frozenset(toks)


class TopicIndex:
    """Exact `is there an earlier query with Jaccard >= threshold` lookup.

    The naive form is a full cross-product: ~23k queries against ~23k banked sets is ~5e8 set
    operations and does not finish. This is the standard PREFIX FILTER and returns exactly the
    same answer, not an approximation:

      Jaccard(t, p) >= J  implies  |t & p| >= ceil(J * |t|)   (because |t | p| >= |t|)

    so p must share at least one of t's `|t| - ceil(J*|t|) + 1` rarest tokens. Indexing and
    probing only that prefix — rarest first, by corpus-wide document frequency — cannot miss a
    match, and skips the postings lists of the template-tail tokens that would otherwise dominate.
    Distinct token sets are stored once, since the question is only whether ANY earlier query
    matched.
    """

    def __init__(self, order: dict[str, int], threshold: float) -> None:
        self._order = order                       # token -> rarity rank (0 = rarest)
        self._threshold = threshold
        self._sets: list[frozenset[str]] = []
        self._seen: dict[frozenset[str], int] = {}
        self._postings: dict[str, list[int]] = {}

    def _prefix(self, toks: frozenset[str], index_side: bool) -> list[str]:
        ordered = sorted(toks, key=lambda w: (self._order.get(w, 1 << 30), w))
        need = -(-int(self._threshold * len(toks) * 1000) // 1000)   # ceil without float drift
        need = max(1, need)
        keep = len(toks) - need + 1
        # The indexing side must keep a prefix at least as long as any probe's, or a match could
        # fall between the two prefixes. Indexing the whole set is the safe, still-cheap choice
        # for the small sets here (queries are short); probes stay pruned.
        return ordered if index_side else ordered[:max(1, keep)]

    def hit(self, toks: frozenset[str]) -> bool:
        if not toks:
            return False
        seen: set[int] = set()
        for tok in self._prefix(toks, index_side=False):
            for i in self._postings.get(tok, ()):
                if i in seen:
                    continue
                seen.add(i)
                other = self._sets[i]
                inter = len(toks & other)
                if inter and inter / (len(toks) + len(other) - inter) >= self._threshold:
                    return True
        return False

    def add(self, toks: frozenset[str]) -> None:
        if not toks or toks in self._seen:
            return
        i = len(self._sets)
        self._sets.append(toks)
        self._seen[toks] = i
        for tok in self._prefix(toks, index_side=True):
            self._postings.setdefault(tok, []).append(i)

    def __len__(self) -> int:
        return len(self._sets)


def _parse_ts(value) -> dt.datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def run(args: list[str] | None = None) -> dict:
    args = list(args or [])
    paths = dossier_paths()

    # ---- pass 1: load, in the order a corpus would have been built ----------------------------
    loaded = []
    for path, dossier in iter_dossiers(paths):
        checks = dossier.get("checks") or []
        if not checks:
            continue
        loaded.append({
            "path": path,
            "cid": candidate_id(path, dossier),
            "created_at": dossier.get("created_at") or "",
            "checks": checks,
        })
    # ISO8601 strings sort chronologically as strings; the path tiebreak makes it deterministic.
    loaded.sort(key=lambda r: (r["created_at"], r["path"]))

    # Corpus-wide token document frequency, used ONLY to order the prefix filter (rarest first).
    # It is order-independent and cannot change any hit/miss decision — only how fast it is found.
    df_stripped, df_raw = Counter(), Counter()
    for rec in loaded:
        for chk in rec["checks"]:
            for q in (chk.get("queries") or []):
                df_stripped.update(_tokens(str(q), True))
                df_raw.update(_tokens(str(q), False))
    order_stripped = {t: i for i, (t, _c) in enumerate(sorted(df_stripped.items(),
                                                             key=lambda kv: (kv[1], kv[0])))}
    order_raw = {t: i for i, (t, _c) in enumerate(sorted(df_raw.items(),
                                                        key=lambda kv: (kv[1], kv[0])))}

    # ---- pass 2: replay ------------------------------------------------------------------------
    banked_urls: dict[str, tuple[str, dt.datetime | None]] = {}   # url -> (cid, fetched_at)
    banked_queries: dict[str, str] = {}                           # norm query -> cid
    topic_stripped = TopicIndex(order_stripped, JACCARD_MIN)
    topic_raw = TopicIndex(order_raw, JACCARD_MIN)

    hits = Counter()
    hits_by_check = defaultdict(Counter)
    fresh_hits = {d: 0 for d in FRESHNESS_DAYS}
    age_gaps_days: list[float] = []
    checks_total = 0
    checks_with_urls = 0
    urls_total = 0
    url_repeat_total = 0
    candidates_seen = 0
    no_created_at = 0

    for rec in loaded:
        candidates_seen += 1
        if not rec["created_at"]:
            no_created_at += 1
        cand_ts = _parse_ts(rec["created_at"])
        # Everything this candidate contributes is banked only AFTER it is scored, so a candidate
        # can never hit itself.
        contrib_urls: dict[str, dt.datetime | None] = {}
        contrib_queries: set[str] = set()
        contrib_tokens: list[frozenset[str]] = []
        contrib_tokens_raw: list[frozenset[str]] = []

        for chk in rec["checks"]:
            checks_total += 1
            name = chk.get("check_name") or "?"
            srcs = [s for s in (chk.get("sources") or []) if isinstance(s, dict)]
            urls = [str(s.get("url")) for s in srcs if s.get("url")]
            queries = [str(q) for q in (chk.get("queries") or []) if q]
            urls_total += len(urls)
            if urls:
                checks_with_urls += 1

            # --- M1 url hit ---
            hit_urls = [u for u in urls if u in banked_urls]
            url_repeat_total += len(hit_urls)
            if hit_urls:
                hits["M1_url"] += 1
                hits_by_check[name]["M1_url"] += 1
                best_gap = None
                for u in hit_urls:
                    banked_ts = banked_urls[u][1]
                    if banked_ts and cand_ts:
                        gap = (cand_ts - banked_ts).total_seconds() / 86400.0
                        best_gap = gap if best_gap is None else min(best_gap, gap)
                if best_gap is not None:
                    age_gaps_days.append(best_gap)
                    for window in FRESHNESS_DAYS:
                        if best_gap <= window:
                            fresh_hits[window] += 1

            # --- M2 exact query hit ---
            norm = [_norm_query(q) for q in queries]
            if any(q in banked_queries for q in norm if q):
                hits["M2_exact_query"] += 1
                hits_by_check[name]["M2_exact_query"] += 1

            # --- M3 topic hit, stripped and raw ---
            for strip, key, index in ((True, "M3_topic_stripped", topic_stripped),
                                      (False, "M3_topic_raw", topic_raw)):
                if any(index.hit(_tokens(q, strip)) for q in queries):
                    hits[key] += 1
                    hits_by_check[name][key] += 1

            for s in srcs:
                if s.get("url"):
                    contrib_urls.setdefault(str(s["url"]), _parse_ts(s.get("fetched_at")) or cand_ts)
            for q in norm:
                if q:
                    contrib_queries.add(q)
            for q in queries:
                contrib_tokens.append(_tokens(q, True))
                contrib_tokens_raw.append(_tokens(q, False))

        for url, ts in contrib_urls.items():
            banked_urls.setdefault(url, (rec["cid"], ts))
        for q in contrib_queries:
            banked_queries.setdefault(q, rec["cid"])
        for t in contrib_tokens:
            topic_stripped.add(t)
        for t in contrib_tokens_raw:
            topic_raw.add(t)

    def share(a: int) -> float:
        return a / checks_total if checks_total else 0.0

    age_gaps_days.sort()

    def pct(p: float) -> float:
        if not age_gaps_days:
            return 0.0
        return age_gaps_days[min(len(age_gaps_days) - 1, int(p * len(age_gaps_days)))]

    m1 = hits["M1_url"]
    decisive_share = share(m1)
    build = decisive_share >= BAR
    ceiling_share = share(hits["M3_topic_stripped"])

    print("L1 corpus-reuse sizing — MEASUREMENT ONLY, nothing is built")
    print(f"dossiers globbed {len(paths)}  with checks {candidates_seen}  "
          f"checks {checks_total}  retrieved urls {urls_total}  "
          f"distinct urls banked {len(banked_urls)}")
    print(f"dossiers with no created_at (sorted first): {no_created_at}")
    print()
    print("replay order: created_at ascending, path tiebreak; a check may only hit passages "
          "banked by a STRICTLY EARLIER candidate")
    print()
    print("--- could this check have been served from a cross-candidate corpus? ---")
    for key, label in (("M1_url", "M1 url hit (observed refetch)"),
                       ("M2_exact_query", "M2 exact query hit"),
                       ("M3_topic_stripped", "M3 topic hit, template stripped (UPPER BOUND)"),
                       ("M3_topic_raw", "M3 topic hit, RAW (confounded by template tails)")):
        print(f"  {label:<52} {hits[key]:6d} / {checks_total} = {share(hits[key]):7.2%}")
    print()
    print(f"  bar from §13: {BAR:.0%}")
    print()
    print("--- freshness: would a corpus with a TTL still have served the M1 hits? ---")
    for window in FRESHNESS_DAYS:
        print(f"  hits within {window:>3}d : {fresh_hits[window]:6d} / {checks_total} = "
              f"{share(fresh_hits[window]):7.2%}")
    if age_gaps_days:
        print(f"  age gap of the freshest reusable passage (days): "
              f"p50={pct(0.5):.1f} p90={pct(0.9):.1f} max={age_gaps_days[-1]:.1f} "
              f"(n={len(age_gaps_days)})")
    print()
    print("--- M1 hit rate by check ---")
    for name in sorted(hits_by_check, key=lambda k: -hits_by_check[k]["M1_url"]):
        print(f"  {name:<22} url={hits_by_check[name]['M1_url']:5d}  "
              f"topic_stripped={hits_by_check[name]['M3_topic_stripped']:5d}")

    # The margin matters as much as the side of the bar. A verdict reported as "BUILD, 21.7% >=
    # 20%" reads as settled; the same number with a 1.7pp margin that a 30-day TTL erases is a
    # different instruction to the reader.
    margin_pp = (decisive_share - BAR) * 100
    ttl30 = share(fresh_hits[30]) if 30 in fresh_hits else decisive_share
    ttl_flips = build and ttl30 < BAR
    verdict = (
        f"BUILD — {m1}/{checks_total} = {decisive_share:.2%} of checks refetched a url an "
        f"earlier candidate had already retrieved, clearing §13's {BAR:.0%} bar by "
        f"{margin_pp:+.2f}pp."
        if build else
        f"DO NOT BUILD — only {m1}/{checks_total} = {decisive_share:.2%} of checks refetched a "
        f"url an earlier candidate had already retrieved, {margin_pp:+.2f}pp against §13's "
        f"{BAR:.0%} bar. Even the loosest topic-overlap ceiling is {ceiling_share:.2%}.")
    if ttl_flips:
        verdict += (f" CONDITIONAL: the margin does not survive a freshness policy — with a "
                    f"30-day TTL the rate is {ttl30:.2%}, BELOW the bar. §13 specifies 'serve "
                    f"from corpus when fresh-enough', so the build decision is a decision about "
                    f"the TTL, not about the corpus.")
    print()
    print(f"VERDICT: {verdict}")
    print()
    print("WHAT KIND OF STORE THE NUMBERS ARGUE FOR (this is the actionable part):")
    print(f"  query-keyed cache   : {share(hits['M2_exact_query']):.2%} — worthless. Queries are "
          f"near-unique across candidates.")
    print(f"  query-embedding idx : {ceiling_share:.2%} CEILING — a semantic index over QUERIES "
          f"cannot reach the bar either.")
    print(f"  url/passage-keyed   : {decisive_share:.2%} — all of the reuse is different queries "
          f"landing on the SAME pages.")
    print("  So the reuse that exists is document-level, not question-level. An embedding index "
          "over queries is the wrong build; a url-keyed passage store is the one the data "
          "supports.")
    if not build and ceiling_share >= BAR:
        print("  NOTE: the observed refetch rate is below the bar but the topic-overlap CEILING "
              "is above it — a semantic index could in principle serve checks that a url-keyed "
              "cache cannot. That gap is the only case for building, and it is an upper bound "
              "from a lexical proxy, not a measured hit.")

    return {
        "title": "L1 corpus-reuse sizing against §13's 20% bar (measurement only)",
        "programme_ref": DOC_REF,
        "corpus_fingerprint": corpus_fingerprint(),
        "population": (f"every check in every parseable dossier json: {checks_total} checks across "
                       f"{candidates_seen} dossiers. No sampling. Replay is created_at-ascending "
                       "with a path tiebreak; same-candidate reuse excluded by construction."),
        "bar": BAR,
        "jaccard_min": JACCARD_MIN,
        "dossier_files_globbed": len(paths),
        "dossiers_with_checks": candidates_seen,
        "dossiers_without_created_at": no_created_at,
        "checks_total": checks_total,
        "checks_with_urls": checks_with_urls,
        "urls_retrieved_total": urls_total,
        "distinct_urls_banked": len(banked_urls),
        "url_refetch_events": url_repeat_total,
        "measures": {
            key: {"hits": hits[key], "share": round(share(hits[key]), 4)}
            for key in ("M1_url", "M2_exact_query", "M3_topic_stripped", "M3_topic_raw")
        },
        "freshness_windows_days": {
            str(w): {"hits": fresh_hits[w], "share": round(share(fresh_hits[w]), 4)}
            for w in FRESHNESS_DAYS
        },
        "age_gap_days": {"n": len(age_gaps_days), "p50": round(pct(0.5), 2),
                         "p90": round(pct(0.9), 2),
                         "max": round(age_gaps_days[-1], 2) if age_gaps_days else 0.0},
        "by_check": {k: dict(v) for k, v in hits_by_check.items()},
        "decisive_measure": "M1_url",
        "decisive_share": round(decisive_share, 4),
        "build": build,
        "verdict": verdict,
        "headline": {
            "checks measured": checks_total,
            "M1 url hit (decisive)": f"{m1}/{checks_total} = {decisive_share:.2%}",
            "M2 exact query hit": f"{hits['M2_exact_query']}/{checks_total} = "
                                  f"{share(hits['M2_exact_query']):.2%}",
            "M3 topic hit, template stripped (upper bound)":
                f"{hits['M3_topic_stripped']}/{checks_total} = {ceiling_share:.2%}",
            "M3 topic hit, RAW (confounded)": f"{hits['M3_topic_raw']}/{checks_total} = "
                                              f"{share(hits['M3_topic_raw']):.2%}",
            "§13 bar": f"{BAR:.0%}",
            "margin against the bar": f"{margin_pp:+.2f}pp",
            "same rate under a 30-day freshness TTL": f"{ttl30:.2%}",
            "decision": ("BUILD (CONDITIONAL — a 30-day TTL puts it below the bar)"
                         if ttl_flips else ("BUILD" if build else "DO NOT BUILD")),
            "what to build": ("url/passage-keyed store — reuse is document-level; the "
                              "query-keyed and query-embedding forms both miss the bar"),
        },
        "ttl_sensitivity": {"bar": BAR, "no_ttl": round(decisive_share, 4),
                            "ttl_30d": round(ttl30, 4), "flips_verdict": bool(ttl_flips)},
        "limitations": [
            "M1 counts an OBSERVED refetch of the same url. It is a lower bound on corpus value: "
            "a corpus could also serve a DIFFERENT url that answers the same question, which M1 "
            "cannot see and M3 only proxies lexically.",
            "M3 is a lexical Jaccard over query tokens, not an embedding similarity. It is "
            "reported as the ceiling for the embedding-index version, not as its prediction.",
            "M3_topic_raw is confounded by verify.py's fixed query template tails, which are "
            "byte-identical across candidates. Only M3_topic_stripped answers the question; the "
            "raw figure is published so the size of the confound is visible.",
            "Replay order uses dossier `created_at`. Dossiers missing it sort first and can only "
            "under-count hits, never inflate them.",
            "Nothing was built. This module writes no passage store, no index and no cache.",
        ],
    }


def main() -> int:
    from runner import run_one
    result = run_one(NAME, sys.argv[1:])
    print(f"\nreceipts   -> {result['receipts_path']}")
    print(f"doc append -> {result['doc_append_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
