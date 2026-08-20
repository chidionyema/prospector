"""E-101g — the control that decides whether E-101's headline is a fact or an artefact.

E-101 Stage A measured eleven arms on 3,472 pairs drawn from the engine's own store and reported
that `lex-token`, three lines of token overlap, beat every neural arm at 0.8273 while NOTHING got
above chance at separating supported from refuted. Both halves of that were read as findings about
the MODELS.

THERE IS A SECOND EXPLANATION AND E-101 CANNOT DISTINGUISH IT. Every label in that corpus is the
moat's own ruling. If the moat itself leans on lexical agreement between a claim and its passage,
then `lex-token` scoring 0.8273 measures agreement with the moat's shortcut, not skill; and
"nothing beats chance on supported vs refuted" would be a statement about the moat's labels being
noisy on that axis, not about the models being unable to read. E-101d already flagged this in one
line — "a screen agreeing with it 98% of the time is concordance, not accuracy" — and then every
later section carried on as if the arms had been graded against truth.

THE CONTROL. Run the same scorers against labels no model produced. `tals/vitaminc` (Schuster et
al., 2021) is 63,054 human-annotated claim/evidence pairs whose three labels map exactly onto the
engine's three verdicts:

    SUPPORTS        -> supported
    REFUTES         -> refuted
    NOT ENOUGH INFO -> unverifiable

VitaminC is the sharpest available choice rather than a convenient one. Its pairs are CONTRASTIVE:
they are built from real Wikipedia revisions where a small edit to the evidence flips the label
while the wording barely moves. It was designed specifically to defeat systems that pattern-match
on overlap. So it puts the strongest possible pressure on exactly the arm that won E-101.

WHAT EACH OUTCOME WOULD MEAN, PRE-REGISTERED BEFORE THE RUN:

  A. lex-token is at chance on SUPPORTS vs REFUTES here, AND the neural arms are well above it.
     -> E-101's second finding is an ARTEFACT OF OUR LABELS. The models can read; our corpus
        cannot tell that they can. The moat's rulings are then not fit to grade anything, and
        E-104 must build labels that are not the moat's own.

  B. lex-token is at chance AND the neural arms are also at chance.
     -> E-101's finding survives the hardest available test. Nothing local reads entailment,
        full stop, and the local-verifier route is closed on external evidence too.

  C. lex-token is well above chance here.
     -> Overlap is doing real work and our corpus is the thing suppressing it. E-101's ordering
        needs re-reading.

Any of the three is worth the run, which is the mark of a control rather than a confirmation.

THREE DEVIATIONS, RECORDED NOT HIDDEN.

1.  VitaminC evidence is ONE sentence; the engine's premises are clipped to 1,500 characters
    (`_groundedness.py:35`) and typically hold several. Overlap statistics are sensitive to premise
    length, so the two corpora are not interchangeable and this file never averages across them.
    It compares each arm to CHANCE on each corpus separately, which is the comparison that carries.

2.  The `vitaminc` ARM is `tals/albert-xlarge-vitaminc-mnli`, trained on this dataset's own train
    split. Scoring it on the dev split is CONTAMINATED. It is run anyway and reported separately as
    a ceiling — it says what a model that has seen this distribution can do, which usefully bounds
    what the honest arms are being asked for. It is excluded from every comparison. Not running it
    would leave that ceiling unmeasured; running it unlabelled would be a false number.

3.  No threshold is fitted here and no accuracy is reported. AUC only, which is threshold-free, so
    nothing in this file can be inflated by a cutoff chosen after seeing the answers.

    tools/experiments/e101g_external_benchmark.py <vitaminc_dev.jsonl> [--limit N]
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from _verifiers import ARMS, LEXICAL, score_arm  # noqa: E402
from e101_verifier_sweep import _auc  # noqa: E402

LABEL_MAP = {"SUPPORTS": "supported", "REFUTES": "refuted", "NOT ENOUGH INFO": "unverifiable"}

# E-101 Stage A's numbers on OUR corpus, for the side-by-side. Copied as literals from
# `e101_fly_stageA_receipts.json` rather than recomputed, so this file cannot quietly restate them.
OURS = {
    "lex-token": (0.8273, None), "lex-number": (0.7270, None), "lex-3gram": (0.5508, None),
    "vitaminc": (0.7742, 0.4744), "minicheck-rob": (0.7136, 0.4849), "hhem": (0.6485, 0.4687),
    "minicheck-deb": (0.6258, 0.5110), "nli-mnli-lg": (0.5438, 0.4989),
    "minicheck-t5": (0.4973, 0.5907), "nli-fever-bs": (0.4836, 0.5444),
    "nli-fever-lg": (0.4495, 0.5224),
}


def _fast_auc(pos: list[float], neg: list[float]) -> float:
    """Same statistic as `e101_verifier_sweep._auc`, computed by ranking instead of by pairs.

    THE PUBLISHED HELPER IS NOT REPLACED, IT IS CHECKED AGAINST. `_auc` compares every positive to
    every negative, which is 31,484 x 22,528 = 709 million Python-level comparisons on this corpus
    and does not finish. That is a reason to compute the number a cheaper way, and NOT a reason to
    trust the cheaper way: a rewritten metric that quietly disagrees with the one every earlier
    number in this programme was measured with would make E-101 and E-101g incomparable, and the
    disagreement would look like a finding. So `main()` runs BOTH on a subsample and refuses to
    report if they differ by more than 1e-9. Ties are averaged here exactly as `_auc` counts them
    at a half, which is the only place the two could legitimately drift.
    """
    if not pos or not neg:
        return 0.0
    marked = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg], key=lambda t: t[0])
    rank_sum, i, n = 0.0, 0, len(marked)
    while i < n:
        j = i
        while j + 1 < n and marked[j + 1][0] == marked[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        rank_sum += avg_rank * sum(t[1] for t in marked[i:j + 1])
        i = j + 1
    n_pos = len(pos)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * len(neg))


def load(path: Path, limit: int) -> tuple[list[tuple[str, str]], list[str]]:
    """(evidence, claim) pairs and mapped labels. Deterministic STRIDE subsample, never random:
    a seed is one more thing that has to be reported and matched to reproduce a number."""
    rows = []
    with path.open() as fh:
        for line in fh:
            d = json.loads(line)
            lab = LABEL_MAP.get(d.get("label"))
            ev, cl = (d.get("evidence") or "").strip(), (d.get("claim") or "").strip()
            if lab and ev and cl:
                rows.append((ev, cl, lab))
    if not rows:
        raise SystemExit(f"{path}: 0 usable rows. Refusing to report.")
    if limit and limit < len(rows):
        stride = len(rows) / limit
        rows = [rows[int(i * stride)] for i in range(limit)]
    return [(e, c) for e, c, _ in rows], [lab for _, _, lab in rows]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: e101g_external_benchmark.py <vitaminc_dev.jsonl> [--limit N]")
    limit = 0
    for a in sys.argv[1:]:
        if a.startswith("--limit"):
            limit = int(a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1])

    pairs, labels = load(Path(args[0]), limit)
    counts = Counter(labels)
    for need in ("supported", "refuted", "unverifiable"):
        if counts[need] < 30:
            raise SystemExit(f"only {counts[need]} '{need}' rows. Too few for an AUC. Refusing.")
    print(f"{len(pairs)} pairs  {dict(counts)}\n")

    # Prove the fast AUC is the published AUC before any headline uses it. 1,200 pairs is small
    # enough that the O(|pos|*|neg|) original finishes, and large enough to catch a tie-handling
    # or off-by-one difference. A mismatch stops the run rather than printing a number that cannot
    # be compared to E-101's.
    probe = pairs[:1200]
    probe_lab = labels[:1200]
    pscores, _ = score_arm("lex-token", probe, use_cache=False, progress=False)
    ppos = [s for s, lab in zip(pscores, probe_lab) if lab == "supported"]
    pneg = [s for s, lab in zip(pscores, probe_lab) if lab != "supported"]
    slow, fast = _auc(ppos, pneg), _fast_auc(ppos, pneg)
    if abs(slow - fast) > 1e-9:
        raise SystemExit(f"AUC helpers disagree: published {slow!r} vs fast {fast!r} on "
                         f"{len(ppos)}/{len(pneg)}. Refusing to report a number that is not "
                         f"comparable to E-101's.")
    print(f"AUC helper agreement on {len(probe)} pairs: {slow:.12f} == {fast:.12f}  OK\n")

    # --arms picks the roster. The lexical default is free and instant and answers half the
    # question; `--arms=neural` runs the four safetensors arms that fit on this laptop and answers
    # the other half, which is the DECISIVE one: if the neural arms read entailment well here while
    # scoring at chance on our own corpus, then E-101's "nothing reads entailment" was never a fact
    # about the models.
    sel = "lexical"
    for a in sys.argv[1:]:
        if a.startswith("--arms="):
            sel = a.split("=", 1)[1]
    if sel == "lexical":
        names = [n for n in LEXICAL if n in ARMS]
    elif sel == "neural":
        names = [n for n, arm in ARMS.items()
                 if not arm.is_lexical and arm.where == "local" and arm.fmt == "safetensors"]
    else:
        names = [n.strip() for n in sel.split(",")]
    if not names:
        raise SystemExit(f"--arms={sel} selected no arms. Refusing to write an empty result.")
    print("arms:", ", ".join(names), flush=True)
    out = {
        "benchmark": "tals/vitaminc dev", "source_file": args[0],
        "n_pairs": len(pairs), "label_counts": dict(counts), "arm_roster": sel,
        "contaminated_arms": {"vitaminc": "tals/albert-xlarge-vitaminc-mnli is TRAINED on this dataset's train split. Reported as a ceiling, excluded from every comparison."},
        "labels_are": "human annotation (Schuster et al. 2021), NOT this engine's rulings",
        "chance": 0.5, "auc_helper_verified_against": "e101_verifier_sweep._auc, 1200-pair probe, |delta| <= 1e-9", "results": {},
    }
    print(f"{'arm':16s} {'AUC sup vs ref':>15s} {'AUC ruled vs NEI':>18s} {'pairs/s':>10s}"
          f"   {'ours: ruled-vs-unv':>20s}")
    print("-" * 88)
    for name in names:
        t0 = time.time()
        scores, _ = score_arm(name, pairs, use_cache=False, progress=False)
        if len(scores) != len(pairs):
            raise SystemExit(f"{name} returned {len(scores)} scores for {len(pairs)} "
                             f"pairs. Refusing to align them by position.")
        rate = len(pairs) / max(time.time() - t0, 1e-9)
        sup = [s for s, lab in zip(scores, labels) if lab == "supported"]
        ref = [s for s, lab in zip(scores, labels) if lab == "refuted"]
        nei = [s for s, lab in zip(scores, labels) if lab == "unverifiable"]
        a_sr, a_rn = round(_fast_auc(sup, ref), 4), round(_fast_auc(sup + ref, nei), 4)
        out["results"][name] = {
            "auc_supported_vs_refuted": a_sr,
            "auc_ruled_vs_notenoughinfo": a_rn,
            "pairs_per_second": round(rate, 2),
            "ours_auc_ruled_vs_unverifiable": OURS.get(name, (None, None))[0],
        }
        print(f"{name:16s} {a_sr:15.4f} {a_rn:18.4f} {rate:10.1f}   "
              f"{OURS.get(name, (None, None))[0] or float('nan'):20.4f}")

    suffix = "" if sel == "lexical" else f"_{sel}"
    dest = HERE / f"e101g_external_benchmark{suffix}_receipts.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(f"\nreceipt: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
