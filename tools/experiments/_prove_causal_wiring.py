#!/usr/bin/env python3
"""Prove the two causal families are wired right, without downloading 31 GB of weights.

Runs ONLY under the python3.12 sidecar interpreter. A tiny RANDOM Llama stands in for
Bespoke-MiniCheck-7B and Lynx-8B: its scores are meaningless, which is the point -- every check
here is about plumbing, and plumbing is what a 31 GB download cannot tell you anything extra about.

THE CHECK THAT MATTERS IS BATCH INVARIANCE. Both causal families read the next-token distribution
at the LAST position. Under the tokenizer's default right padding, that position holds a pad token
for every sequence in a batch that is not the longest, so the score becomes the model's opinion
about padding. That failure is invisible: it produces plausible numbers in [0, 1], it does not
raise, and a weak AUC from it reads as "the model disagrees with the moat" -- the exact finding
E-101 exists to measure. Scoring the same pairs at batch_size=1 and at batch_size=8 must agree to
float tolerance. With right padding they do not, so this check fails when the bug returns.

    python3.12 _prove_causal_wiring.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _verifier_sidecar as vs  # noqa: E402

TINY = "hf-internal-testing/tiny-random-LlamaForCausalLM"

# Deliberately ragged: lengths must differ a lot, or padding does nothing and the check is vacuous.
PAIRS = [
    ("Acme Ltd reported revenue of 4.2 million pounds in 2024.", "Acme earned 4.2m in 2024."),
    ("The permit was refused on appeal.", "The permit was granted."),
    ("A very short doc.", "Short claim."),
    (("Long document. " * 90).strip(), "The document is long. It repeats itself."),
    ("Only one sentence here about pricing at 30 dollars per seat.", "Pricing is 30 per seat."),
]

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  -- ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main() -> int:
    print(f"tiny stand-in model: {TINY}")
    print(f"sentence split: {vs._sentences(PAIRS[3][1])}")
    for family in ("causal-minicheck", "causal-judge"):
        print(f"\n=== {family} ===")
        one = vs._run(TINY, family, PAIRS, 1)
        eight = vs._run(TINY, family, PAIRS, 8)

        check("one score per pair", len(one["scores"]) == len(PAIRS),
              f"{len(one['scores'])} of {len(PAIRS)}")
        check("every score in [0,1]", all(0.0 <= s <= 1.0 for s in one["scores"]),
              f"min {min(one['scores']):.4f} max {max(one['scores']):.4f}")

        # TWO checks, because the behavioural one alone was measured to be half vacuous.
        # Flipping padding_side to "right" on 2026-08-20 produced a divergence of 3.37e-03 for
        # causal-judge but only 2.01e-05 for causal-minicheck, so a 1e-4 tolerance caught the bug
        # in one family and waved it through in the other. Correct float non-determinism between
        # batch sizes measured 1.46e-11 and 5.96e-08 on the same runs, so 1e-6 sits between the
        # two populations with more than an order of magnitude of margin on each side. The number
        # comes from those four measurements, not from looking tidy.
        worst = max(abs(a - b) for a, b in zip(one["scores"], eight["scores"]))
        check("BATCH INVARIANCE: batch_size 1 == batch_size 8", worst < 1e-6,
              f"largest divergence {worst:.2e}")

        # The structural half. A tolerance is a judgement about a real model's float behaviour and
        # could go flaky at 7B scale; "which side did we pad" is a fact, and it fails identically
        # for every family and every model size.
        check("padding is on the LEFT, so the last position is never a pad token",
              one["padding_side"] == "left", f"padding_side={one['padding_side']!r}")

        check("decision tokens resolved by name, both polarities",
              bool(one["positive_ids"]) and bool(one["negative_ids"]),
              f"{len(one['positive_ids'])} positive / {len(one['negative_ids'])} negative ids")

        # PAIRS[3] is the only two-sentence claim, so the reference's min-over-sentences reduction
        # must have had exactly one claim to work on.
        check("multi-sentence claims counted", one["n_multi_sentence"] == 1,
              f"n_multi_sentence={one['n_multi_sentence']}")

        # One unit per (pair, sentence, chunk). Premises here are single-chunk, so units == the
        # sentence count across all claims: 4 single-sentence claims + 1 two-sentence claim.
        check("one scoring unit per claim sentence", one["n_units"] == 6,
              f"n_units={one['n_units']}")

        check("nothing hit the context window", one["n_over_window"] == 0,
              f"n_over_window={one['n_over_window']}")

        if family == "causal-judge":
            check("judge normalises PASS against FAIL",
                  one["forced_prefix"] == vs.LYNX_FORCED_PREFIX,
                  f"forced prefix {one['forced_prefix']!r}")

    print(f"\n{len(FAILURES)} failure(s)" + (f": {FAILURES}" if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
