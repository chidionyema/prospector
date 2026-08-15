"""Generative Golden-Set harness (Part 16 principal upgrade).

Verifies that the generator can find 'Alpha' (high-value strategic ideas)
for a given signal. Grades the output using a 'Professor' model.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .config import Config, load_config
from .errors import ProviderExhaustedError
from .generate import generate
from .operator import Operator
from .paths import repo_path

logger = logging.getLogger(__name__)


def run_generative_golden(
    op: Operator,
    prof_op: Operator,
    cfg: Config,
    golden_path: str | None = None,
    k: int = 5
) -> dict[str, Any]:
    """Execute the generative golden set and return quality scores.

    Returns: {
        "overall_alpha": 0.0 | None,   # None when NOTHING was graded — never a stand-in 0.0
        "graded_n": 0, "failed_n": 0, "degraded": False,
        "cases": [{
            "signal": "...",
            "generated": [...],
            "alpha_score": 0.0 | None, # None when the Professor did not return a grade
            "rationale": "...",
            "graded": True
        }]
    }

    A FAILED GRADE IS NOT A ZERO. This harness is the promotion gate that decides whether a
    second brain can be trusted, so a grader that errored and a generator that scored nothing
    must never reduce to the same number. They did until 2026-08-15: `alpha = 0.0` under a
    bare `except` averaged every outage straight into `overall_alpha`, which is how the gate
    came to record that a model "answers without reasons" when we had thrown its answers away.
    Ungraded cases are now excluded from the mean and counted in `failed_n`; the healthy path
    (`failed_n == 0`) computes exactly the number it always did.
    """
    # Anchored on the repo, not the cwd: the cockpit calls this from wherever streamlit
    # was launched, so a relative default resolved to a missing file for every caller
    # except one run from the repo root.
    path = repo_path("fixtures", "generative_golden.json") if golden_path is None else golden_path
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []
    total_alpha = 0.0
    graded_n = 0

    for case in cases:
        signal = case["signal"]
        targets = case["targets"]
        
        # 1. Generate candidates for this signal
        generated = generate(op, cfg, signal_text=signal, k=k)
        
        # 2. Professor grades the batch against the targets
        batch_json = json.dumps([c.to_dict() for c in generated])
        targets_json = json.dumps(targets)
        
        system = ("You are a world-class venture capitalist. Grade a batch of AI-generated "
                  "business ideas against a set of 'High-Alpha Targets'. "
                  "Did the AI find the strategic depth we expected?")
        user = (f"Signal: {signal}\n\n"
                f"Targets (The Gold Standard):\n{targets_json}\n\n"
                f"Generated Batch:\n{batch_json}\n\n"
                "Output ONLY JSON: {\"alpha_score\": 0.0 to 5.0, \"rationale\": \"...\"}")
        
        alpha: float | None
        try:
            grade = prof_op.complete_json(system, user, temperature=0.0)
            alpha = float(grade.get("alpha_score", 0.0))
            rationale = grade.get("rationale", "No rationale.")
            graded = True
        except ProviderExhaustedError:
            # Abort rather than grade the rest of the set on a brain that cannot answer. A
            # partial run whose remaining cases are all "failures" is worse than no run: it
            # still prints a number, and that number is a fact about our quota, not about the
            # generator. `--resume` semantics belong to the caller; a benched Professor is
            # exactly what ProviderExhaustedError exists to tell it.
            logger.error("Generative golden aborted: the Professor operator is exhausted "
                         "after %d graded case(s); no score is being reported", graded_n)
            raise
        except Exception as e:
            # Everything else — a malformed grade, a missing alpha_score, an adapter crash —
            # marks the case UNGRADED. It must not enter `total_alpha`: a 0.0 here is the
            # lowest possible score the Professor can award, so an outage and a damning
            # verdict were literally the same value.
            logger.error("Generative golden: the Professor returned no usable grade for "
                         "signal %r; this case is excluded from the mean: %s",
                         str(signal)[:60], e, exc_info=True)
            alpha = None
            rationale = f"Grading failed: {e}"
            graded = False

        results.append({
            "signal": signal,
            "generated": [c.title for c in generated],
            "alpha_score": alpha,
            "rationale": rationale,
            "graded": graded,
        })
        if graded:
            total_alpha += float(alpha or 0.0)
            graded_n += 1

    failed_n = len(results) - graded_n
    return {
        # None, not 0.0, when nothing was graded: a caller that renders this cannot be handed
        # a floor score for a measurement that never happened.
        "overall_alpha": round(total_alpha / graded_n, 2) if graded_n else None,
        "graded_n": graded_n,
        "failed_n": failed_n,
        "degraded": failed_n > 0,
        "cases": results,
    }

def _build_operator(kind: str, cfg: Config, fast: bool) -> Operator:
    from .operator import _build_operator as build
    return build(kind, cfg, fast)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator", default="claude")
    parser.add_argument("--professor", default="claude")
    args = parser.parse_args()

    cfg = load_config()
    op = _build_operator(args.operator, cfg, fast=False)
    prof_op = _build_operator(args.professor, cfg, fast=False)

    report = run_generative_golden(op, prof_op, cfg)
    print(json.dumps(report, indent=2))
