#!/usr/bin/env python3
"""Structural distributions, and the distance metric that replaces our invented numbers.

`prompts/style/voice.md` says a sentence may run to 25 words and carry two commas.
`register_lint.py:353-355` gates on those two numbers. Nobody measured them. This tool
measures the same properties on a human corpus in the same genre and produces an INTERVAL,
which is a target rather than an opinion.

THE DISTANCE METRIC. For each measure we take its distribution ACROSS the human corpus's
documents, giving a mean and a standard deviation per measure. A generated document is
scored as the mean absolute z across measures, plus the worst single z. A document sitting
inside the human range on every measure scores near zero. This is what a gate would read.

Deliberately NOT a gate yet. `--score` reports; nothing fails. Stage 8 of
docs/PROSE_CORPUS_PROGRAM.md is a separate decision, and this report is what it needs.

Usage:
    python -m tools.corpus.structure --ours corpora/ours --human corpora/fos
    python -m tools.corpus.structure --score corpora/ours --human corpora/fos --top 15
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.corpus.load import load_corpus  # noqa: E402
from tools.corpus.text import profile  # noqa: E402

#: The measures the distance metric runs on. Counts (documents, words, sentence_count) are
#: excluded on purpose: a long document is not an off-register one.
SCORED = ("sent_len_mean", "sent_len_sd", "long_sentence_rate", "clause_load_mean",
          "opener_diversity", "hedges_per_1k", "attribution_per_1k", "mattr",
          "punct_comma_per_1k", "punct_semicolon_per_1k", "punct_colon_per_1k",
          "punct_dash_per_1k", "punct_hyphen_per_1k", "punct_paren_per_1k")

#: Measured and printed, but NOT scored. Each exclusion is a defect in the MEASUREMENT, not
#: a judgement about the writing:
#:
#: `para_*` — NEITHER corpus carries usable paragraph structure. Ours: `build_ours.document`
#: writes each field as its own paragraph. Human: the FOS PDF extraction yields a MEDIAN OF
#: TWO paragraph blocks per decision (199 of 200 sampled have under three), so the human
#: 16.37 sentences per paragraph is the extractor's blank lines, not an ombudsman's habit.
#: Scoring either side would produce a large, confident z about nothing. Unblocking this
#: needs a human corpus whose paragraph breaks survive extraction, not a change here.
#:
#: `type_token_ratio` — length-confounded, superseded by `mattr`. It counts distinct words
#: over the WHOLE document, and that ratio falls as a document grows, so against our 654-word
#: mean and the human 1,923-word mean it measures length before vocabulary. Kept in the
#: report so both numbers can be read side by side; `mattr` is the one scored.
REPORTED_ONLY = ("para_sentences_mean", "para_words_mean", "type_token_ratio")

#: A document under this length gives an unstable profile — one long sentence moves the
#: mean by a third. Reported separately rather than scored.
MIN_DOC_WORDS = 150


def per_document(docs: list[str]) -> list[dict]:
    out = []
    for d in docs:
        p = profile([d])
        if p.words >= MIN_DOC_WORDS:
            out.append(p.as_row())
    return out


def target(rows: list[dict]) -> dict[str, dict[str, float]]:
    """mean, sd and the 5th-95th interval per measure, across the human corpus."""
    t = {}
    for k in (*SCORED, *REPORTED_ONLY):
        vals = sorted(r[k] for r in rows if k in r)
        if len(vals) < 2:
            continue
        t[k] = {"mean": statistics.fmean(vals), "sd": statistics.pstdev(vals) or 1e-9,
                "p5": vals[int(0.05 * (len(vals) - 1))],
                "p50": vals[int(0.50 * (len(vals) - 1))],
                "p95": vals[int(0.95 * (len(vals) - 1))]}
    return t


def distance(row: dict, t: dict) -> tuple[float, float, list[tuple[str, float]]]:
    zs = [(k, (row[k] - t[k]["mean"]) / t[k]["sd"]) for k in SCORED if k in t and k in row]
    if not zs:
        return 0.0, 0.0, []
    worst = sorted(zs, key=lambda kv: -abs(kv[1]))
    return (statistics.fmean(abs(z) for _, z in zs), abs(worst[0][1]), worst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ours", default="corpora/ours")
    ap.add_argument("--human", default="corpora/fos")
    ap.add_argument("--score", default=None, help="directory of .txt to score against the human target")
    ap.add_argument("--out", default="corpora/structure.json")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    human, _ = load_corpus(args.human)
    if not human:
        print(f"EMPTY human corpus at {args.human}", file=sys.stderr)
        return 2
    h_rows = per_document(human)
    t = target(h_rows)

    ours, _ = load_corpus(args.score or args.ours)
    o_rows = per_document(ours)

    h_all, o_all = profile(human).as_row(), profile(ours).as_row()
    print(f"human: {len(human)} docs ({len(h_rows)} scored)   "
          f"ours: {len(ours)} docs ({len(o_rows)} scored)\n")
    print(f"{'measure':<26}{'HUMAN mean':>12}{'(p5–p95)':>18}{'OURS mean':>12}{'z':>8}")
    for k in (*SCORED, *REPORTED_ONLY):
        if k not in t:
            continue
        ov = statistics.fmean(r[k] for r in o_rows) if o_rows else float("nan")
        z = (ov - t[k]["mean"]) / t[k]["sd"] if o_rows else float("nan")
        interval = f"{t[k]['p5']:.2f}–{t[k]['p95']:.2f}"
        flag = "  not scored" if k in REPORTED_ONLY else ("  <<<" if abs(z) >= 2 else "")
        print(f"{k:<26}{t[k]['mean']:>12.2f}{interval:>18}{ov:>12.2f}{z:>8.1f}{flag}")

    if o_rows:
        ds = [distance(r, t) for r in o_rows]
        mean_d = statistics.fmean(d[0] for d in ds)
        outside = sum(1 for d in ds if d[1] >= 2)
        print(f"\nDISTANCE: mean |z| across our documents = {mean_d:.2f}")
        print(f"  {outside}/{len(ds)} documents ({outside / len(ds) * 100:.0f}%) sit 2+ sd "
              f"outside the human corpus on at least one measure.")
        print("  This is the number a gate would read. No gate is armed.")
        worst = sorted(((d[0], d[2]) for d in ds), key=lambda x: -x[0])[:args.top]
        print("\n  worst documents, by mean |z|:")
        for md, zs in worst:
            drivers = ", ".join(f"{k} z={z:+.1f}" for k, z in zs[:3])
            print(f"    {md:5.2f}   {drivers}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"human_target": t, "human_corpus_docs": len(h_rows),
         "ours_aggregate": {k: o_all.get(k) for k in SCORED},
         "human_aggregate": {k: h_all.get(k) for k in SCORED}},
        indent=1, default=lambda v: None if isinstance(v, float) and math.isnan(v) else v))
    print(f"\nwrote target -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
