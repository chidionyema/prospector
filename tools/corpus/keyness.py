#!/usr/bin/env python3
"""Keyness: what our generator over-uses relative to a human writing the same genre.

Log-likelihood (Dunning's G2) on every token and every 2-, 3- and 4-gram, both directions.
This is the standard corpus-linguistics statistic — the same number AntConc reports.

TWO NUMBERS, NOT ONE. G2 alone rewards sheer frequency: on a 500k-word corpus a trivial
difference in a very common word clears any significance threshold. So every row also
carries log ratio (how many times more often), and the table is filtered on BOTH. A word
that is 20 times more frequent in our prose is actionable; one that is 1.05 times more
frequent is noise with a big G2.

Output is a table you can act on and a JSON file the linter can read later.

Usage:
    python -m tools.corpus.keyness --ours corpora/ours --human corpora/fos --top 40
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.corpus.load import load_corpus  # noqa: E402
from tools.corpus.text import (  # noqa: E402
    classify_item,
    log_likelihood,
    log_ratio,
    ngrams,
    tokens,
)

#: Print order, and the order of how actionable a row is. `content` is printed last and
#: exists to be READ, never to be turned into a rule — see text.FUNCTION_WORDS.
CATEGORIES = ("meta", "form", "content")
CATEGORY_NOTE = {
    "meta": "we describe our own retrieval instead of the world — actionable in any genre",
    "form": "how we build sentences — this is the human pattern to adopt",
    "content": "what we write ABOUT — NOT a target, we are not adjudicating complaints",
}

#: G2 = 15.13 is p < 0.0001 at 1 degree of freedom. Below that, the difference is not
#: distinguishable from sampling noise and has no business in a style rule.
G2_FLOOR = 15.13
#: 1.0 = twice as frequent. Under that, an over-use is real but too small to write a rule on.
LOG_RATIO_FLOOR = 1.0


def counts(docs: list[str], n: int) -> tuple[Counter, int]:
    c: Counter = Counter()
    total = 0
    for d in docs:
        toks = tokens(d)
        items = toks if n == 1 else ngrams(toks, n)
        c.update(items)
        total += len(items)
    return c, total


def compare(ours: list[str], human: list[str], n: int, min_freq: int) -> list[dict]:
    a_counts, a_total = counts(ours, n)
    b_counts, b_total = counts(human, n)
    rows = []
    for item, a in a_counts.items():
        if a < min_freq:
            continue
        b = b_counts.get(item, 0)
        g2 = log_likelihood(a, b, a_total, b_total)
        lr = log_ratio(a, b, a_total, b_total)
        if g2 < G2_FLOOR or lr < LOG_RATIO_FLOOR:
            continue
        text = " ".join(item) if n > 1 else item
        rows.append({"n": n, "item": text, "category": classify_item(text),
                     "ours": a, "human": b, "g2": round(g2, 1), "log_ratio": round(lr, 2),
                     "ours_per_1k": round(a / a_total * 1000, 3),
                     "human_per_1k": round(b / b_total * 1000, 3)})
    rows.sort(key=lambda r: -r["g2"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ours", default="corpora/ours")
    ap.add_argument("--human", default="corpora/fos")
    ap.add_argument("--out", default="corpora/keyness.json")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--max-n", type=int, default=4)
    ap.add_argument("--min-freq", type=int, default=10,
                    help="an item seen 3 times is not a habit")
    args = ap.parse_args()

    ours, dropped_o = load_corpus(args.ours)
    human, dropped_h = load_corpus(args.human)
    if not ours or not human:
        print(f"EMPTY CORPUS: ours={len(ours)} human={len(human)}", file=sys.stderr)
        return 2
    print(f"ours:  {len(ours):>5} docs, {sum(len(tokens(d)) for d in ours):>9,} words, "
          f"{len(dropped_o)} boilerplate lines removed")
    print(f"human: {len(human):>5} docs, {sum(len(tokens(d)) for d in human):>9,} words, "
          f"{len(dropped_h)} boilerplate lines removed")

    all_rows: list[dict] = []
    for n in range(1, args.max_n + 1):
        all_rows.extend(compare(ours, human, n, args.min_freq))

    for cat in CATEGORIES:
        rows = [r for r in all_rows if r["category"] == cat]
        rows.sort(key=lambda r: -r["g2"])
        print(f"\n=== OVER-USED BY US — {cat.upper()} — {len(rows)} items over "
              f"G2 {G2_FLOOR} and log ratio {LOG_RATIO_FLOOR} ===")
        print(f"    {CATEGORY_NOTE[cat]}")
        print(f"{'item':<44}{'G2':>9}{'x more':>9}{'ours/1k':>9}{'human/1k':>10}")
        for r in rows[:args.top]:
            x = 2 ** r["log_ratio"]
            print(f"{r['item'][:43]:<44}{r['g2']:>9.0f}{x:>8.0f}x"
                  f"{r['ours_per_1k']:>9.2f}{r['human_per_1k']:>10.2f}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    counts_by_cat = {c: sum(1 for r in all_rows if r["category"] == c) for c in CATEGORIES}
    Path(args.out).write_text(json.dumps(
        {"g2_floor": G2_FLOOR, "log_ratio_floor": LOG_RATIO_FLOOR,
         "ours_docs": len(ours), "human_docs": len(human),
         "rows_by_category": counts_by_cat, "rows": all_rows}, indent=1))
    print(f"\nwrote {len(all_rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
