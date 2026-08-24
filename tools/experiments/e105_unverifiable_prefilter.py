#!/usr/bin/env python3
"""E-105 — how much of the `unverifiable` rate is decidable with no model call?

    python3 tools/experiments/e105_unverifiable_prefilter.py --store <store>

The claim under test, from the 2026-08-20 cost research: a large share of `unverifiable` verdicts
are decidable BEFORE the brain is called, because the retrieved passages plainly cannot address
the claim — no passage was retrieved at all, or no entity or number from the check's own queries
appears anywhere in what came back.

Every such check is a full-price model call that produced no discriminating information. This
script bounds the lever exactly, against the corpus we already hold, for nothing.

**It can only ever emit `unverifiable`.** That is what makes the accuracy cost zero by
construction rather than by measurement: the engine's own rule already says silence means
`unverifiable` and never `supported`. A rule that could emit `supported` would be a new brain,
and would need a new proof.

The control matters as much as the number. If the same rule fires on the checks that were
RULED (supported or refuted), it is not detecting absence of evidence, it is detecting some
property of our own text, and the saving is imaginary. That false-positive rate is the number to
read first.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.experiments import _corpus  # noqa: E402

STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "for",
    "to",
    "in",
    "on",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "by",
    "with",
    "that",
    "this",
    "it",
    "its",
    "as",
    "at",
    "from",
    "do",
    "does",
    "how",
    "what",
    "who",
    "why",
    "when",
    "where",
    "which",
    "there",
    "their",
    "have",
    "has",
    "can",
    "will",
    "would",
    "any",
    "all",
    "not",
    "no",
    "yes",
    "uk",
    "us",
}


def _tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in STOPWORDS
    }


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*", text or ""))


def classify(check: dict, index: dict) -> str:
    """Which no-model rule, if any, would have answered this check."""
    sources, _missing = _corpus.cited_sources(check, index)
    all_sources = [s for s in (check.get("sources") or []) if isinstance(s, dict)]
    texts = [str(s.get("text") or "") for s in all_sources if s.get("text")]

    if not all_sources:
        return "no_source_retrieved"
    if not texts:
        return "sources_carry_no_text"

    # The check's own queries are the best available statement of what it went looking for.
    queries = " ".join(str(q) for q in (check.get("queries") or []))
    if not queries.strip():
        return "not_decidable_no_queries"

    q_tokens, q_nums = _tokens(queries), _numbers(queries)
    blob = " ".join(texts)
    p_tokens, p_nums = _tokens(blob), _numbers(blob)

    if not q_tokens:
        return "not_decidable_no_queries"
    if not (q_tokens & p_tokens) and not (q_nums & p_nums):
        return "zero_overlap"
    return "not_decidable"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", required=True)
    args = ap.parse_args(argv)
    store = Path(args.store).expanduser().resolve()
    os.environ.setdefault("PROSPECTOR_CORPUS_DIR", str(store / "dossiers"))

    unver: Counter = Counter()
    ruled: Counter = Counter()
    totals = Counter()

    for path, dossier in _corpus.iter_dossiers():
        if not isinstance(dossier, dict) or "checks" not in dossier:
            continue
        index = _corpus.source_index(dossier)
        for check in dossier.get("checks") or []:
            if not isinstance(check, dict):
                continue
            verdict = str(check.get("verdict") or "")
            reason = classify(check, index)
            if verdict == "unverifiable":
                totals["unverifiable"] += 1
                unver[reason] += 1
            elif verdict in ("supported", "refuted"):
                totals["ruled"] += 1
                ruled[reason] += 1

    n_unver = totals["unverifiable"] or 1
    n_ruled = totals["ruled"] or 1
    catchable = sum(
        v
        for k, v in unver.items()
        if k in ("no_source_retrieved", "sources_carry_no_text", "zero_overlap")
    )
    false_pos = sum(
        v
        for k, v in ruled.items()
        if k in ("no_source_retrieved", "sources_carry_no_text", "zero_overlap")
    )

    lo, hi = _corpus.wilson(catchable, n_unver)
    flo, fhi = _corpus.wilson(false_pos, n_ruled)

    out = {
        "corpus": _corpus.corpus_fingerprint(),
        "unverifiable_checks": totals["unverifiable"],
        "ruled_checks": totals["ruled"],
        "unverifiable_breakdown": dict(unver.most_common()),
        "ruled_breakdown": dict(ruled.most_common()),
        "catchable_with_no_model_call": catchable,
        "catchable_pct_of_unverifiable": round(100.0 * catchable / n_unver, 2),
        "catchable_ci95": [round(100 * lo, 2), round(100 * hi, 2)],
        "control_false_positive_on_ruled": false_pos,
        "control_false_positive_pct": round(100.0 * false_pos / n_ruled, 2),
        "control_ci95": [round(100 * flo, 2), round(100 * fhi, 2)],
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
