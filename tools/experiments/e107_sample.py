#!/usr/bin/env python3
"""E-107 stage 1 — draw a balanced sample from LLM-AggreFact.

Runs under python3.10 (pyarrow 17.0.0), NOT the engine venv. E-100 convention:
an experiment sidecar never adds a dependency to prospector/.venv.

Reads   ~/.local/share/prospector-evalsets/llm-aggrefact/{dev,test}.parquet
Writes  ~/.local/share/prospector-evalsets/e107/sample.jsonl

The sample is BALANCED 50/50 on the human label, because the source set is
skewed 3:1 toward `supported` (measured: 75.7% dev, 77.9% test). On the raw
set an always-say-supported model scores 76-78% accuracy. On a balanced
sample it scores 50%, which is what a benchmark is supposed to say about it.

Selection is deterministic: rows are ordered by sha256 of the
contamination_identifier, so re-running picks the same rows without a seed
and without Random(). Two runs are comparable; that is the point.
"""
import hashlib
import json
import os
import sys

import pyarrow.parquet as pq

ROOT = os.path.expanduser("~/.local/share/prospector-evalsets")
SRC = os.path.join(ROOT, "llm-aggrefact")
OUT = os.path.join(ROOT, "e107")

# 100 per class. Standard error on each of TPR/TNR is ~5pp at p=0.5, which
# separates "grounded" from "coin toss" — the decision this sample has to make.
# It does not separate 0.82 from 0.85, and nothing here should claim it does.
PER_CLASS = 100
SPLIT = "dev"  # dev, not test: keep test clean for a later confirmation run.


def _rank(row_id: str) -> str:
    return hashlib.sha256(row_id.encode()).hexdigest()


def main() -> int:
    path = os.path.join(SRC, f"{SPLIT}.parquet")
    tbl = pq.read_table(path)
    cols = tbl.column_names
    need = {"dataset", "doc", "claim", "label", "contamination_identifier"}
    missing = need - set(cols)
    if missing:
        print(f"FAIL: {path} is missing columns {sorted(missing)}; has {cols}")
        return 1

    rows = tbl.to_pylist()
    print(f"read {len(rows)} rows from {SPLIT}.parquet")

    # Label may arrive as bool or as 0/1. Coerce once, here, and prove it —
    # a silent type surprise here would flip the whole benchmark.
    kinds = sorted({type(r["label"]).__name__ for r in rows})
    print(f"label python types present: {kinds}")
    for r in rows:
        r["label"] = 1 if bool(r["label"]) else 0

    pos = [r for r in rows if r["label"] == 1]
    neg = [r for r in rows if r["label"] == 0]
    print(f"population: supported={len(pos)} not_supported={len(neg)} "
          f"({100.0 * len(pos) / len(rows):.1f}% supported)")
    if len(pos) < PER_CLASS or len(neg) < PER_CLASS:
        print(f"FAIL: need {PER_CLASS} of each class")
        return 1

    pos.sort(key=lambda r: _rank(str(r["contamination_identifier"])))
    neg.sort(key=lambda r: _rank(str(r["contamination_identifier"])))
    sample = pos[:PER_CLASS] + neg[:PER_CLASS]
    # Order the 200 by a DIFFERENT hash from the one that selected them. Sorting the
    # merged list by _rank clusters the labels: the supported pool is 23018 rows and the
    # not_supported pool is 7402, so the 100 smallest supported hashes are nearly all
    # smaller than the 100 smallest not_supported ones. Measured on the first build of
    # this file: the longest same-label run in the output was 65, and the last ~70 pairs
    # were all not_supported. A run that is interrupted, or read while it is still going,
    # then reports a number computed on almost one class. The salt breaks the correlation
    # with selection while keeping the order deterministic.
    sample.sort(key=lambda r: _rank("order:" + str(r["contamination_identifier"])))

    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "sample.jsonl")
    with open(out, "w") as fh:
        for i, r in enumerate(sample):
            fh.write(json.dumps({
                "pair_id": f"e107-{i:04d}",
                "source_dataset": r["dataset"],
                "doc": r["doc"],
                "claim": r["claim"],
                "label": r["label"],
                "contamination_identifier": r["contamination_identifier"],
            }) + "\n")

    # DOC LENGTH is not decoration. The engine truncates every passage to
    # VERDICT_PASSAGE_TRUNCATE = 600 chars (verify.py:777). If the documents
    # here are much longer than that, the shipped truncation removes the
    # evidence before the brain ever sees it, and the benchmark has to run
    # both widths to say which one it is measuring.
    lens = sorted(len(r["doc"]) for r in sample)
    n = len(lens)
    over = sum(1 for x in lens if x > 600)
    print(f"wrote {n} pairs -> {out}")
    print(f"doc chars: min={lens[0]} p50={lens[n // 2]} "
          f"p90={lens[int(n * 0.9)]} max={lens[-1]}")
    print(f"docs longer than the engine's 600-char truncation: {over}/{n} "
          f"({100.0 * over / n:.1f}%)")
    by_src: dict[str, int] = {}
    for r in sample:
        by_src[r["dataset"]] = by_src.get(r["dataset"], 0) + 1
    print("source mix: " + ", ".join(
        f"{k}={v}" for k, v in sorted(by_src.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
