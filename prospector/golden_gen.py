"""Generative Golden-Set harness (Part 16 principal upgrade).

Verifies that the generator can find 'Alpha' (high-value strategic ideas)
for a given signal. Grades the output using a 'Professor' model.
"""
from __future__ import annotations

import json
from typing import Any

from .config import Config, load_config
from .generate import generate
from .operator import Operator
from .paths import repo_path


def run_generative_golden(
    op: Operator,
    prof_op: Operator,
    cfg: Config,
    golden_path: str | None = None,
    k: int = 5
) -> dict[str, Any]:
    """Execute the generative golden set and return quality scores.
    
    Returns: {
        "overall_alpha": 0.0,
        "cases": [{
            "signal": "...",
            "generated": [...],
            "alpha_score": 0.0,
            "rationale": "..."
        }]
    }
    """
    # Anchored on the repo, not the cwd: the cockpit calls this from wherever streamlit
    # was launched, so a relative default resolved to a missing file for every caller
    # except one run from the repo root.
    path = repo_path("fixtures", "generative_golden.json") if golden_path is None else golden_path
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []
    total_alpha = 0.0

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
        
        try:
            grade = prof_op.complete_json(system, user, temperature=0.0)
            alpha = float(grade.get("alpha_score", 0.0))
            rationale = grade.get("rationale", "No rationale.")
        except Exception as e:
            alpha = 0.0
            rationale = f"Grading failed: {e}"

        results.append({
            "signal": signal,
            "generated": [c.title for c in generated],
            "alpha_score": alpha,
            "rationale": rationale
        })
        total_alpha += alpha

    return {
        "overall_alpha": round(total_alpha / len(cases), 2) if cases else 0.0,
        "cases": results
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
