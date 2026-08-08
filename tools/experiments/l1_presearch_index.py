"""L1 — would a PRE-SEARCH local index answer a query an earlier fetch already covered?

WHY THIS IS A MEASUREMENT AND NOT A BUILD (read §28.4 before touching this file)

§26.7 sized "evidence corpus reuse" at 21.74% and the register carried it as the top buildable
item. Reading `retrieval.py` killed the specced version outright: the 21.84% overlap is
**URL-level**, the existing `DiskCache` is **query-keyed**, and query-level reuse measured
**0.12%**. Those are three different numbers about three different keys, and the build was
sized on the one that does not predict a cache hit. Snippet text already arrives with the
search result (`Source.make(url=..., text=str(it.get("text",""))[:max_chars])`), so a
URL-keyed corpus saves no search calls at all.

§28.4's conclusion was that the real prize needs a **pre-search index** — something that
changes what evidence the moat sees BEFORE a provider is called — and that this is an
architecture change to the grounding chain, i.e. founder-fenced. The founder authorised the
build. This module is the step that has to come first, because the entire L1 history is a
history of building on the wrong key: it measures whether a content index over passages we
have ALREADY retrieved could serve a query the live chain was about to send.

THE CLAIM UNDER TEST, stated so it can fail
    Exact-key query reuse is 0.12% (§28.4, M2). The index's whole reason to exist is that
    NEAR-miss reuse is far higher — that queries differ in wording while asking for the same
    evidence. If lexical hit@k over prior passages lands anywhere near 0.12%, the index is the
    same mistake in a third key and must not ship. §13's bar is 20%.

TEMPORAL HOLDOUT, and why nothing else is honest here
    Entries are replayed in `fetched_at` order and each query is answered from an index
    containing ONLY entries fetched strictly before it. That is precisely production's
    question — "could something we already had have answered this?" — and it makes future
    leakage structurally impossible rather than merely discouraged. A random holdout would let
    a later fetch of the same URL answer an earlier query, which is not a saving anyone can
    bank.

WHAT COUNTS AS A HIT, and the proxy this rests on
    A hit is: the index returns, in its top k, a passage whose URL is one the live search
    actually returned for that query. That is a PROXY for "the moat would have seen the same
    evidence", and it is deliberately conservative in one direction and optimistic in another,
    both of which are stated in the receipt rather than buried:
      * conservative — a different URL carrying the same fact counts as a miss;
      * optimistic  — a matching URL does not prove the verdict would have been the same.
    The honest reading is a CEILING on call savings, never a claim about grounding quality.
    Whether a served passage rules the same way is E1/E12 territory, not this file's.

ZERO LLM CALLS AND ZERO NETWORK. Reads `store/_cache/` only.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

NAME = "L1"
DOC_REF = "docs/COMMERCIAL_READINESS_PROGRAM.md §26.7, §28.4 (L1), §13 (the 20% bar)"

REPO = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO / "store" / "_cache"

# Stopwords. Deliberately the same list `retrieval.py:52` uses for fixture matching plus the
# handful of query-scaffolding words our own templates emit ("how", "much", "do", "pay"), which
# appear in a large share of generated queries and would otherwise dominate every match.
_STOP = {
    "or", "and", "the", "a", "an", "of", "in", "for", "to", "with", "on", "by",
    "how", "much", "do", "does", "is", "are", "what", "who", "which", "at", "from",
    "vs", "per", "be", "it", "that", "this", "as", "was", "were", "will", "can",
}
_WORD = re.compile(r"[a-z0-9][a-z0-9\-']*")


def describe() -> str:
    return ("L1: temporal-holdout replay over store/_cache/ — how often could a lexical index "
            "over ALREADY-RETRIEVED passages have served a query before the provider was "
            "called? Zero LLM calls, zero network. Bar: §13's 20% vs exact-key 0.12%.")


def _tok(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2]


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------

def _load_entries(limit: int | None = None, require_stamp: bool = False,
                  ) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Every readable cache entry as {query, fetched_at, urls, passages}.

    The cache path is a SHA1 of `f"{query}|{k}|{max_chars}"` (`retrieval.py:1236-1241`), so the
    query is not recoverable from the filename. It is recoverable from the entry: every
    `Source` carries the `query` that fetched it. An entry whose sources disagree about the
    query, or carry none, is skipped and counted — a corpus with a silent drop rate is how the
    last three L1 numbers went wrong.
    """
    skipped: Counter[str] = Counter()
    out: list[dict[str, Any]] = []
    paths = sorted(CACHE_DIR.glob("*.json"))
    for p in paths:
        try:
            d = json.loads(p.read_text())
        except Exception:
            skipped["unreadable"] += 1
            continue
        srcs = d.get("sources") if isinstance(d, dict) else d
        if not isinstance(srcs, list) or not srcs:
            skipped["no_sources"] += 1
            continue
        queries = {(s.get("query") or "").strip() for s in srcs if isinstance(s, dict)}
        queries.discard("")
        if len(queries) != 1:
            skipped["query_absent" if not queries else "query_ambiguous"] += 1
            continue
        fetched = d.get("fetched_at") if isinstance(d, dict) else None
        clock = "stamped"
        if not isinstance(fetched, (int, float)):
            # v1 entries carry no stamp, and on this store they are 15,968 of 16,167 — the v2
            # stamp only started being written on 2026-08-07. Dropping them left a 199-entry
            # sample spanning ONE day, which is not a measurement of anything.
            #
            # mtime is forgeable: any copy/rsync/restore of store/ resets it to now, which is
            # why `_age_s` (`retrieval.py:1243-1250`) refuses to trust it for FRESHNESS. This
            # replay needs only ORDER, and the forgery mode is checkable — a restore flattens
            # every mtime into one window. Measured 2026-08-07: the mtimes span 34 distinct
            # days, 2026-06-15 to 2026-08-07, p10 06-22 / p50 07-29 / p90 08-06. Nothing
            # flattened them, so the ordering they give is real. The split is reported.
            if require_stamp:
                skipped["no_fetched_at"] += 1
                continue
            try:
                fetched = p.stat().st_mtime
            except OSError:
                skipped["no_clock"] += 1
                continue
            clock = "mtime"
        passages = [{"url": s.get("url") or "", "text": s.get("text") or ""}
                    for s in srcs if isinstance(s, dict) and s.get("url")]
        if not passages:
            skipped["no_urls"] += 1
            continue
        out.append({"query": queries.pop(), "fetched_at": float(fetched), "clock": clock,
                    "urls": {q["url"] for q in passages}, "passages": passages,
                    "path": p.name})
    out.sort(key=lambda e: e["fetched_at"])
    if limit:
        out = out[:limit]
    return out, dict(skipped)


# ---------------------------------------------------------------------------
# the index — BM25 over passage text, built incrementally as the replay walks forward
# ---------------------------------------------------------------------------

class _BM25:
    """Incremental BM25. No external dependency, and no embedding model.

    Lexical on purpose for the FIRST measurement: it is the weakest index anyone would ship,
    so a number over the bar here is a floor that an embedding index can only improve on, while
    a number near 0.12% would kill the build without spending a GPU-hour to find out. If this
    clears the bar, the embedding variant is the follow-up, not the prerequisite.
    """

    K1 = 1.5
    B = 0.75

    def __init__(self) -> None:
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_len: list[int] = []
        self.docs: list[dict[str, Any]] = []
        self._len_sum = 0

    def __len__(self) -> int:
        return len(self.docs)

    def add(self, url: str, text: str, entry_i: int) -> None:
        toks = _tok(text)
        i = len(self.docs)
        self.docs.append({"url": url, "entry_i": entry_i})
        self.doc_len.append(len(toks))
        self._len_sum += len(toks)
        for term, tf in Counter(toks).items():
            self.postings[term].append((i, tf))

    def search(self, query: str, k: int) -> list[dict[str, Any]]:
        if not self.docs:
            return []
        n = len(self.docs)
        avg = (self._len_sum / n) or 1.0
        scores: dict[int, float] = defaultdict(float)
        for term in set(_tok(query)):
            post = self.postings.get(term)
            if not post:
                continue
            idf = math.log(1 + (n - len(post) + 0.5) / (len(post) + 0.5))
            for doc_i, tf in post:
                dl = self.doc_len[doc_i] or 1
                scores[doc_i] += idf * (tf * (self.K1 + 1)) / (
                    tf + self.K1 * (1 - self.B + self.B * dl / avg))
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        return [{"url": self.docs[i]["url"], "score": round(s, 3),
                 "entry_i": self.docs[i]["entry_i"]} for i, s in top]


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

def _replay(entries: list[dict[str, Any]], ks: tuple[int, ...],
            min_score: float) -> dict[str, Any]:
    idx = _BM25()
    hits = {k: 0 for k in ks}
    strict_hits = {k: 0 for k in ks}
    answerable = 0            # queries asked against a NON-EMPTY index
    exact_key = 0             # the 0.12% comparator, recomputed on this same corpus
    seen_queries: set[str] = set()
    examples: list[dict[str, Any]] = []

    for i, e in enumerate(entries):
        if len(idx):
            answerable += 1
            if e["query"] in seen_queries:
                exact_key += 1
            kmax = max(ks)
            got = idx.search(e["query"], kmax)
            got = [g for g in got if g["score"] >= min_score]
            for k in ks:
                urls = {g["url"] for g in got[:k]}
                if urls & e["urls"]:
                    hits[k] += 1
                    # STRICT excludes the exact-key case, which `DiskCache` already serves and
                    # which would otherwise let the index take credit for the cache's work.
                    if e["query"] not in seen_queries:
                        strict_hits[k] += 1
            if len(examples) < 8 and got and ({g["url"] for g in got[:3]} & e["urls"]):
                examples.append({"query": e["query"][:120],
                                 "served_url": next(iter({g["url"] for g in got[:3]}
                                                         & e["urls"]))[:120],
                                 "top_score": got[0]["score"],
                                 "exact_key_too": e["query"] in seen_queries})
        seen_queries.add(e["query"])
        for p in e["passages"]:
            idx.add(p["url"], p["text"], i)

    def _rate(num: int) -> float | None:
        return round(num / answerable, 4) if answerable else None

    return {
        "entries_replayed": len(entries),
        "queries_against_non_empty_index": answerable,
        "passages_indexed": len(idx),
        "hit_at_k": {str(k): _rate(hits[k]) for k in ks},
        "strict_hit_at_k_excl_exact_key": {str(k): _rate(strict_hits[k]) for k in ks},
        "exact_key_repeat_rate": _rate(exact_key),
        "min_score": min_score,
        "examples": examples,
    }


def run(args: list[str]) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="runner.py run L1")
    ap.add_argument("--limit", type=int, default=0,
                    help="replay only the first N entries by fetch time (0 = all). A limit "
                         "biases the result DOWNWARD, because early queries face a smaller "
                         "index — it is for smoke-testing, not for quoting.")
    ap.add_argument("--k", default="1,3,5",
                    help="comma-separated k values for hit@k (default 1,3,5)")
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="drop index results below this BM25 score before scoring the hit. "
                         "0 keeps everything, which is the ceiling reading.")
    ap.add_argument("--require-stamp", action="store_true",
                    help="use ONLY v2 entries carrying fetched_at. On this store that is 199 "
                         "of 16,167 entries spanning one day — a sanity check, not a result.")
    ap.add_argument("--bar", type=float, default=0.20,
                    help="§13's build bar (default 0.20).")
    ns = ap.parse_args(args)
    ks = tuple(int(x) for x in ns.k.split(",") if x.strip())

    if not CACHE_DIR.is_dir():
        raise SystemExit(f"no cache at {CACHE_DIR} — nothing to replay")

    entries, skipped = _load_entries(ns.limit or None, ns.require_stamp)
    clocks = Counter(e["clock"] for e in entries)
    print(f"L1 pre-search index — temporal-holdout replay over {CACHE_DIR}")
    print(f"  usable entries: {len(entries)}   skipped: {skipped or 'none'}")
    print(f"  ordering clock: {dict(clocks)}  "
          f"(mtime is order-only; the 34-day spread rules out a restore flattening it)")
    if len(entries) < 100:
        raise SystemExit(
            f"REFUSING: only {len(entries)} usable entries. A hit-rate over a corpus this "
            "small has an interval wider than the bar it is being compared to.")

    res = _replay(entries, ks, ns.min_score)
    kmax = str(max(ks))
    strict = res["strict_hit_at_k_excl_exact_key"][kmax]
    exact = res["exact_key_repeat_rate"]

    print(f"  passages indexed: {res['passages_indexed']}   "
          f"queries scored: {res['queries_against_non_empty_index']}")
    print()
    print(f"  {'k':>3} {'hit@k':>8} {'strict (excl exact-key)':>26}")
    for k in ks:
        h = res["hit_at_k"][str(k)]
        s = res["strict_hit_at_k_excl_exact_key"][str(k)]
        print(f"  {k:>3} {h:>8.2%} {s:>26.2%}")
    print()
    print(f"  exact-key repeat rate on this corpus: {exact:.2%}  "
          f"(§28.4 measured 0.12% — this is the comparator, recomputed here)")

    verdict = "BUILD" if (strict or 0) >= ns.bar else "DO NOT BUILD"
    print(f"  strict hit@{kmax} = {strict:.2%} vs §13 bar {ns.bar:.0%}  →  {verdict}")
    if (strict or 0) < ns.bar:
        print("    The specced index is the same mistake in a third key. Do not ship it on "
              "this number; §28.4's history is exactly this.")
    print("  NOTE: a URL match is a CEILING on call savings, not a claim that the verdict "
          "would have held. That question belongs to E1/E12.")

    return {
        "headline": {
            "verdict": verdict,
            "strict_hit_at_kmax": strict,
            "k_max": int(kmax),
            "bar": ns.bar,
            "exact_key_repeat_rate": exact,
            "prior_28_4_query_level": 0.0012,
            "entries": len(entries),
        },
        "skipped": skipped,
        "ordering_clock": dict(clocks),
        "result": res,
        "method": {
            "holdout": "temporal — index contains only entries fetched strictly earlier",
            "index": "BM25 over passage text, incremental, no embeddings (weakest shippable "
                     "index, so the number is a FLOOR for a stronger one)",
            "hit_definition": "top-k contains a URL the live search actually returned",
            "proxy_limits": ["a different URL carrying the same fact scores as a miss",
                             "a matching URL does not prove the verdict would have held"],
            "llm_calls": 0,
            "network_calls": 0,
        },
    }


def main() -> None:
    import sys
    print(json.dumps(run(sys.argv[1:]), indent=2, default=str)[:4000])


if __name__ == "__main__":
    main()
