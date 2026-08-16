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

Deliberately NOT a gate here. `--score` reports; nothing in this tool fails. What CAN gate
is `prospector/register_lint.py`, and only through the target file this tool writes with
`--write-target`, one measure at a time. See "arming" below.

Usage:
    python -m tools.corpus.structure --ours corpora/ours --human corpora/fos
    python -m tools.corpus.structure --score corpora/ours --human corpora/fos --top 15
    python -m tools.corpus.structure --write-target prospector/data/prose_target.json
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from prospector.prose_measure import TOKENISER_VERSION, document_measures, profile  # noqa: E402
from tools.corpus.load import load_corpus  # noqa: E402

#: The measures the distance metric runs on. Counts (documents, words, sentence_count) are
#: excluded on purpose: a long document is not an off-register one.
SCORED = ("sent_len_mean", "sent_len_sd", "long_sentence_rate", "heavy_sentence_rate",
          "clause_load_mean", "opener_diversity", "hedges_per_1k", "attribution_per_1k",
          "mattr", "punct_comma_per_1k", "punct_semicolon_per_1k", "punct_colon_per_1k",
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

#: ARMING. A measure is armed — meaning `register_lint` may report a pack against it — when
#: our corpus sits OUTSIDE the human 5th-95th interval by at least a tenth of that interval's
#: width. The margin is the whole point: parentheses came out at 15.66 against a human p95 of
#: 15.63, which is outside the interval by 0.03 and is not a finding about anything. Arming on
#: "outside" alone would have gated a pack on rounding.
#:
#: The rule is deliberately not "z >= 2". These distributions are skewed — a document-level
#: hedge rate has a floor at zero and a long tail — so a standard deviation over-states how
#: unusual the low side is. Hedging sits 1.7 sd under the human mean and a full 2.16 per 1,000
#: words below the human p5; a z-rule would have waved it through.
ARM_MARGIN_FRACTION = 0.10

#: Measures that may NEVER arm, whatever the numbers say, each for a stated reason. This is
#: the list to argue with — everything else arms on the rule above.
NEVER_ARM = {
    "clause_load_mean":
        "commas plus subordinators per sentence is the comma finding counted a second way. "
        "Arming both fails a pack twice for one habit and the writer cannot tell which to fix.",
    "sent_len_sd":
        "variety of sentence length. Ours sits inside the human interval, and a floor on it "
        "would reward padding a short sentence to make the spread look human.",
}


def per_document(docs: list[str]) -> list[dict]:
    out = []
    for d in docs:
        row = document_measures(d)
        if row.get("words", 0) >= MIN_DOC_WORDS:
            out.append(row)
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


def arming(measure: str, t: dict, ours_mean: float) -> dict:
    """Whether `register_lint` may report a pack against this measure, and why."""
    if measure in NEVER_ARM:
        return {"armed": False, "side": None, "reason": NEVER_ARM[measure]}
    if measure in REPORTED_ONLY:
        return {"armed": False, "side": None,
                "reason": "the measurement itself is confounded; see REPORTED_ONLY"}
    lo, hi, width = t["p5"], t["p95"], t["p95"] - t["p5"]
    margin = width * ARM_MARGIN_FRACTION
    if ours_mean > hi + margin:
        return {"armed": True, "side": "above",
                "reason": f"our corpus mean {ours_mean:.2f} is above the human p95 {hi:.2f} "
                          f"by more than a tenth of the interval ({margin:.2f})"}
    if ours_mean < lo - margin:
        return {"armed": True, "side": "below",
                "reason": f"our corpus mean {ours_mean:.2f} is below the human p5 {lo:.2f} "
                          f"by more than a tenth of the interval ({margin:.2f})"}
    return {"armed": False, "side": None,
            "reason": f"our corpus mean {ours_mean:.2f} sits inside the human interval "
                      f"{lo:.2f}–{hi:.2f} (or within a tenth of it)"}


def build_target(t: dict, h_rows: list[dict], o_rows: list[dict],
                 human_agg: dict, ours_agg: dict, *, human_docs: int, ours_docs: int) -> dict:
    """The committed artifact `register_lint` reads.

    It carries the FINGERPRINT of the corpora that produced it — document counts, word counts
    and the tokeniser version — so any number in it can be traced back to the measurement,
    and so a target measured under one tokeniser can never be read under another. Lint time
    then does no network I/O and reads no corpus: it reads this file and nothing else.
    """
    measures = {}
    for k in (*SCORED, *REPORTED_ONLY):
        if k not in t:
            continue
        ours_mean = statistics.fmean(r[k] for r in o_rows if k in r) if o_rows else None
        entry = {"human_mean": round(t[k]["mean"], 4), "human_sd": round(t[k]["sd"], 4),
                 "p5": round(t[k]["p5"], 4), "p50": round(t[k]["p50"], 4),
                 "p95": round(t[k]["p95"], 4),
                 "ours_mean": round(ours_mean, 4) if ours_mean is not None else None,
                 "scored": k in SCORED}
        if ours_mean is not None:
            entry["z"] = round((ours_mean - t[k]["mean"]) / t[k]["sd"], 2)
            entry.update(arming(k, t[k], ours_mean))
        measures[k] = entry
    return {
        "version": 1,
        "tokeniser_version": TOKENISER_VERSION,
        "measured_on": date.today().isoformat(),
        "arm_rule": (f"armed when our corpus mean sits outside the human p5–p95 by at least "
                     f"{ARM_MARGIN_FRACTION:.0%} of that interval's width"),
        "corpus": {
            "human": {"name": "Financial Ombudsman Service final decisions",
                      "documents": human_docs, "scored_documents": len(h_rows),
                      "words": human_agg.get("words")},
            "ours": {"name": "prospector dossiers via tools.corpus.build_ours",
                     "documents": ours_docs, "scored_documents": len(o_rows),
                     "words": ours_agg.get("words")},
        },
        "measures": measures,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ours", default="corpora/ours")
    ap.add_argument("--human", default="corpora/fos")
    ap.add_argument("--score", default=None, help="directory of .txt to score against the human target")
    ap.add_argument("--out", default="corpora/structure.json")
    ap.add_argument("--write-target", default=None,
                    help="also write the committed target register_lint reads, "
                         "e.g. prospector/data/prose_target.json")
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
    print(f"\nwrote report -> {args.out}")

    if args.write_target:
        tgt = build_target(t, h_rows, o_rows, h_all, o_all,
                           human_docs=len(human), ours_docs=len(ours))
        dest = Path(args.write_target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(tgt, indent=1) + "\n")
        armed = [k for k, v in tgt["measures"].items() if v.get("armed")]
        print(f"wrote target -> {dest}")
        print(f"  ARMED ({len(armed)}): {', '.join(armed) or 'none'}")
        for k, v in tgt["measures"].items():
            if not v.get("armed"):
                print(f"  not armed: {k} — {v.get('reason', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
