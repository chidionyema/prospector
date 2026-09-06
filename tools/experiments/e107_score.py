#!/usr/bin/env python3
"""E-107 stage 3 — score the run against the human labels. Pure stdlib.

BALANCED ACCURACY, not accuracy. The source set is 75.7% `supported`, so a
model that answers "supported" every time scores 75.7% on the raw set and
looks respectable. The sample here is balanced 50/50, which makes plain
accuracy honest too, but balanced accuracy is printed because it stays honest
if anyone re-runs this on the unbalanced population.

Mapping from our three-way verdict to the set's binary label:
  supported                 -> 1 (the passage supports the claim)
  refuted, unverifiable     -> 0 (it does not)
The document is the ONLY evidence offered, so "I cannot tell from this
passage" and "this passage contradicts it" are both "not supported by this
passage". That is the mapping the label was written under.

ABSTENTION is reported separately because it is the interesting half. A wrong
`supported` is a fabricated finding; an `unverifiable` on a claim the passage
did support is a missed one. They cost the engine different things and a single
accuracy number hides which one is happening.
"""
import collections
import json
import os
import sys

OUT = os.path.expanduser("~/.local/share/prospector-evalsets/e107")


def score(rows, title):
    ok = [r for r in rows if r.get("ok")]
    failed = len(rows) - len(ok)
    if not ok:
        print(f"\n{title}: no successful calls ({failed} failed)")
        return None
    tp = sum(1 for r in ok if r["label"] == 1 and r["verdict"] == "supported")
    fn = sum(1 for r in ok if r["label"] == 1 and r["verdict"] != "supported")
    fp = sum(1 for r in ok if r["label"] == 0 and r["verdict"] == "supported")
    tn = sum(1 for r in ok if r["label"] == 0 and r["verdict"] != "supported")
    pos, neg = tp + fn, fp + tn
    tpr = tp / pos if pos else float("nan")
    tnr = tn / neg if neg else float("nan")
    bal = (tpr + tnr) / 2
    acc = (tp + tn) / len(ok)
    vc = collections.Counter(r["verdict"] for r in ok)
    dg = sum(1 for r in ok if r.get("downgraded_no_citation"))
    secs = sorted(r["secs"] for r in ok)

    print(f"\n=== {title} ===")
    print(f"calls {len(ok)} ok, {failed} failed   "
          f"median {secs[len(secs) // 2]:.1f}s")
    print(f"BALANCED ACCURACY {bal:.3f}      (0.500 = coin toss)")
    print(f"  plain accuracy  {acc:.3f}")
    print(f"  recall  on supported (TPR) {tpr:.3f}   {tp}/{pos}")
    print(f"  recall  on not-supported (TNR) {tnr:.3f}   {tn}/{neg}")
    print(f"  false 'supported' (fabrications) {fp}/{neg}")
    print(f"  verdicts: " + ", ".join(f"{k}={v}" for k, v in vc.most_common()))
    print(f"  downgraded by source-or-die (no citation): {dg}")
    return {"title": title, "n": len(ok), "failed": failed, "balanced_acc": bal,
            "accuracy": acc, "tpr": tpr, "tnr": tnr, "tp": tp, "fn": fn,
            "fp": fp, "tn": tn, "verdicts": dict(vc), "downgraded": dg,
            "median_secs": secs[len(secs) // 2]}


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "results.jsonl")
    rows = [json.loads(l) for l in open(path) if l.strip()]
    arms = sorted({r["arm"] for r in rows})
    print(f"{len(rows)} result rows, arms: {arms}")

    # BASELINE FIRST. Every number below has to beat this to mean anything.
    labels = {}
    for r in rows:
        labels[r["pair_id"]] = r["label"]
    n1 = sum(1 for v in labels.values() if v == 1)
    n0 = len(labels) - n1
    print(f"pairs {len(labels)}: supported={n1} not_supported={n0}")
    print(f"always-say-supported baseline: balanced accuracy 0.500, "
          f"plain accuracy {n1 / len(labels):.3f}")

    out = [score([r for r in rows if r["arm"] == a], a) for a in arms]
    out = [o for o in out if o]

    # THE COMPARISON IS THE POINT. Same pairs, same model, same prompt; the only
    # difference is how much of the document the brain was allowed to see.
    if len(out) == 2:
        a, b = out
        d = b["balanced_acc"] - a["balanced_acc"]
        print(f"\n=== {b['title']} minus {a['title']} ===")
        print(f"balanced accuracy {a['balanced_acc']:.3f} -> {b['balanced_acc']:.3f} "
              f"({d:+.3f})")
        print(f"recall on supported {a['tpr']:.3f} -> {b['tpr']:.3f} "
              f"({b['tpr'] - a['tpr']:+.3f})")
        print(f"fabrications {a['fp']} -> {b['fp']}")
        # Paired disagreement: the same pair judged differently by the two arms is
        # a stronger statement than two aggregate numbers, because it removes the
        # sample from the comparison entirely.
        by = collections.defaultdict(dict)
        for r in rows:
            if r.get("ok"):
                by[r["pair_id"]][r["arm"]] = r["verdict"]
        both = [v for v in by.values() if len(v) == 2]
        flipped = [v for v in both if v[a["title"]] != v[b["title"]]]
        gained = [v for v in flipped
                  if v[b["title"]] == "supported" and v[a["title"]] != "supported"]
        print(f"paired: {len(both)} pairs judged by both arms, "
              f"{len(flipped)} verdicts changed, {len(gained)} became 'supported' "
              f"once the full document was visible")

    with open(os.path.join(OUT, "scores.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
