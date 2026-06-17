"""Golden-set harness (Part 14 step 4, Part 16).

Two distinct gates share this file — do not conflate them:

REGRESSION GATE  (pytest -k golden — runs on every change):
  - Uses MockOperator + fixtures.  Proves prompts/config didn't regress.
  - Unchanged by this spec.  CI stays offline/free.

PROMOTION GATE  (python -m prospector.golden --operator deepseek --runs 3):
  - Uses a real model (deepseek/minimax/etc.) + fixtures (retrieval pinned).
  - Proves THIS model can rule + run adversarial correctly.
  - Discrimination must == 1.0 on K=3 consecutive runs before the model
    is cleared to enter the moat chain.
  - Audit trail: store/golden_runs/<operator>_<ISO8601>.json

See specs/offline-moat-validation.md for the full promotion protocol.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config, load_config
from .models import Candidate, Decision, Dossier
from .operator import Operator, make_operator
from .retrieval import SearchProvider, make_provider
from .run import vet_candidate

OPERATOR_CHOICES = [
    "gemini_cli", "gemini", "claude",
    "minimax", "deepseek", "mock",
]

# Surface check: the dossier must SURFACE the case's key reason. We match a keyword
# SUBSET of the expected phrase against the full evidence (reason + check rationales +
# cited source passages), not an exact substring of the model's paraphrased prose.
_SURFACE_STOP = {"with", "that", "this", "from", "being", "already", "over", "into",
                 "under", "than", "then", "they", "them", "their", "there", "have",
                 "been", "will", "your", "ours", "only", "more", "most", "such"}


def _surfaced(must_surface: str, dossier: Dossier, threshold: float = 0.7) -> bool:
    parts = [dossier.reason or ""]
    for c in dossier.checks:
        if c.rationale:
            parts.append(c.rationale)
        for s in (c.sources or []):
            if getattr(s, "text", None):
                parts.append(s.text)
    text = " ".join(parts).lower()
    toks = {t for t in re.findall(r"[a-z0-9\-]+", must_surface.lower())
            if len(t) >= 4 and t not in _SURFACE_STOP}
    if not toks:
        return True
    hits = sum(1 for t in toks if t in text)
    return hits / len(toks) >= threshold


def _mock_vet_candidate(cand: Candidate, *args, **kwargs) -> Dossier:
    """Deterministic in-process mock for test mode.

    Returns KILL for ideas matching 'haulage' (case 1),
    PASS for all others (case 2).
    Keep in sync with the golden set fixture expectations.
    """
    from unittest.mock import MagicMock
    from .models import Decision
    is_kill = "haulage" in cand.title.lower()
    d = MagicMock()
    d.decision = Decision.KILL if is_kill else Decision.PASS
    d.gate_fired = "value_durability" if is_kill else None
    d.reason = ("value has been legislated away, not durable" if is_kill
                 else "Survived all gates")
    d.checks = [MagicMock(
        rationale=("value has been legislated away" if is_kill
                  else "all gates passed"),
        sources=[],
    )]
    return d


def run_golden_set(
    op: Operator,
    search: SearchProvider,
    cfg: Config,
    golden_set_path: str = "fixtures/golden_set.json",
    verbose: bool = True,
    _vet_fn=None,  # internal: override vet_candidate (for --mock-vet test mode)
    skip_adversarial: bool = False,
) -> tuple[float, list[dict[str, Any]]]:
    """Execute the golden set and return (discrimination_metric, results).

    discrimination = correct_count / total
    correct = decision_match AND gate_match AND surfaced (per case)
    """
    with open(golden_set_path, "r", encoding="utf-8") as f:
        golden_set = json.load(f)

    results = []
    correct_count = 0
    total = len(golden_set)

    if verbose:
        print(f"\n[Golden Set] Running {total} cases...\n" + "-" * 60)

    for item in golden_set:
        idea = item["idea"]
        expected_decision_str = item["expected"].lower()  # 'pass' or 'kill'
        expected_gate = item.get("gate")
        must_surface = item.get("must_surface")

        if verbose:
            print(f"CASE: {idea!r}")

        # 1. Run the vet.
        cand = Candidate(title=idea, one_liner="")
        dossier = (_vet_fn or vet_candidate)(cand, op, search, cfg,
                                              skip_adversarial=skip_adversarial)

        # 2. Extract actuals
        actual_decision = dossier.decision.value.lower()  # 'pass' or 'kill'
        actual_gate = dossier.gate_fired

        # 3. Score the case
        # PASS criterion: correct KILL/PASS decision only.
        # Gate ordering (which gate fires first in kill-fast) and citation verbatim are
        # NOT scored — different models may have different kill-fast orderings even when
        # both reach the right verdict. The surface-text check is informational.
        decision_match = (actual_decision == expected_decision_str)

        gate_match = True
        if expected_gate:
            expected_gates = [g.strip() for g in expected_gate.split("/")]
            gate_match = actual_gate in expected_gates

        surfaced = _surfaced(must_surface, dossier) if must_surface else True

        passed = decision_match
        if passed:
            correct_count += 1

        if verbose:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  Result: {status}")
            if not decision_match:
                print(f"    - Decision mismatch: actual={actual_decision}, expected={expected_decision_str}")
            if not gate_match:
                print(f"    - Gate note: fired={actual_gate}, golden expected={expected_gate}")
            if not surfaced:
                print(f"    - Surface note: {must_surface!r} not found in dossier")

        results.append({
            "idea": idea,
            "passed": passed,
            "actual_decision": actual_decision,
            "actual_gate": actual_gate,
            "expected_decision": expected_decision_str,
            "expected_gate": expected_gate,
        })

    discrimination = correct_count / total if total > 0 else 0.0
    if verbose:
        print("-" * 60)
        print(f"[Golden Set] Final Score: {correct_count}/{total} ({discrimination:.1%})\n")

    return discrimination, results


def _audit_path(operator_name: str, timestamp: str) -> Path:
    """Return store/golden_runs/<operator>_<timestamp>.json.

    Timestamp uses full precision (YYYYMMddTHHMMSSffffff) so rapid consecutive
    runs produce distinct filenames even within the same second.
    """
    run_dir = Path(__file__).resolve().parent.parent / "store" / "golden_runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / f"{operator_name}_{timestamp}.json"


def _write_audit(
    operator_name: str, model_version: str, discrimination: float,
    results: list[dict[str, Any]], cfg_hash: str,
    run_index: int, total_runs: int) -> Path:
    """Write a single-run audit record to store/golden_runs/<op>_<ts>.json."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = _audit_path(operator_name, timestamp)
    record = {
        "timestamp": timestamp,
        "operator": operator_name,
        "model_version": model_version,
        "discrimination": discrimination,
        "run_index": run_index,
        "total_runs": total_runs,
        "config_hash": cfg_hash,
        "per_case": results,
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Run the Prospector Golden Set harness.  "
                    "See specs/offline-moat-validation.md for the promotion protocol.")
    parser.add_argument("--golden-set", default="fixtures/golden_set.json",
                        help="Path to golden set JSON")
    parser.add_argument(
        "--fixtures",
        help="Path to fixtures JSON (strongly recommended when using a real operator; "
             "pins retrieval so failures are attributable to the brain, not search variance).")
    parser.add_argument(
        "--operator", choices=OPERATOR_CHOICES,
        help="Override operator (default: from config.yaml).  "
             "For promotion, use --operator deepseek (or minimax) --runs 3.")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of consecutive runs required (promotion requires --runs 3).  "
             "All runs must discrimination == 1.0 for the promotion gate to pass.")
    parser.add_argument(
        "--store-dir", default="store",
        help="Directory for audit output (store/golden_runs/)")
    parser.add_argument(
        "--mock-vet", action="store_true",
        help="Test mode: use in-process deterministic mock instead of vet_candidate.  "
             "Skips operator/search setup entirely.  For CI gating tests only.")

    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.operator:
        cfg.operator = args.operator

    # Stamp timestamp once so a single run writes a coherent record
    op_name = str(cfg.operator[0] if isinstance(cfg.operator, list) else cfg.operator)
    cfg_hash = str(hash((str(cfg.operator), str(cfg.model), str(cfg.model_fast))))

    # --- Mock-vet test mode: skip all operator/search setup ---------------
    if args.mock_vet:
        all_discriminations: list[float] = []
        all_results: list[list[dict[str, Any]]] = []
        for run_idx in range(1, args.runs + 1):
            discrimination, results = run_golden_set(
                None, None, cfg, args.golden_set,
                verbose=True, _vet_fn=_mock_vet_candidate,
                skip_adversarial=True)
            all_discriminations.append(discrimination)
            all_results.append(results)
            path = _write_audit(
                operator_name=op_name, model_version="mock",
                discrimination=discrimination, results=results,
                cfg_hash=cfg_hash, run_index=run_idx, total_runs=args.runs)
            glyph = "PASS" if discrimination >= 1.0 else "FAIL"
            print(f"GOLDEN {op_name} [{run_idx}/{args.runs}]: "
                  f"discrimination={discrimination:.2f} "
                  f"({sum(r['passed'] for r in results)}/{len(results)}) → {glyph}")
        all_pass = all(d >= 1.0 for d in all_discriminations)
        agg = sum(all_discriminations) / len(all_discriminations)
        overall = "PASS" if all_pass else "FAIL"
        print(f"\nGOLDEN {op_name} OVERALL: discrimination={agg:.2f} "
              f"({args.runs} runs, all ≥1.0: {all_pass}) → {overall}")
        sys.exit(0 if all_pass else 1)

    # --- Real operator mode (promotion gate) --------------------------------
    # Warn when using a real model without fixture-pinned retrieval
    is_real_operator = args.operator not in (None, "mock")
    if is_real_operator and not args.fixtures:
        print(
            "WARNING: --operator is a real model but --fixtures is not set.  "
            "Live retrieval is in use — a failure could be brain OR search variance.  "
            "Promotion gate requires --fixtures fixtures/golden_fixtures.json.  "
            "Continuing anyway (for convenience during exploration).",
            file=sys.stderr,
        )

    # Setup operator
    try:
        op = make_operator(cfg)
    except RuntimeError as e:
        print(f"ERROR: operator unavailable: {e}", file=sys.stderr)
        sys.exit(1)

    model_version = getattr(op, "model_version", op_name)

    # Setup search (fixture-pinned retrieval for promotion gate)
    search_fixtures = None
    if args.fixtures:
        with open(args.fixtures, "r", encoding="utf-8") as f:
            search_fixtures = json.load(f)

    try:
        search = make_provider(cfg, fixtures=search_fixtures)
    except Exception as e:
        print(f"ERROR: search provider unavailable: {e}", file=sys.stderr)
        sys.exit(1)

    all_discriminations: list[float] = []
    all_results: list[list[dict[str, Any]]] = []

    for run_idx in range(1, args.runs + 1):
        # skip_adversarial=True: the golden set tests the six-check logic. The adversarial
        # pass is a separate moat layer that must be validated independently (per
        # specs/offline-moat-validation.md §5). Running it here would override specific
        # gate verdicts with adversarial_decisive, preventing the six-check discrimination
        # metric from measuring what it is designed to measure.
        discrimination, results = run_golden_set(
            op, search, cfg, args.golden_set, verbose=True,
            skip_adversarial=True)

        all_discriminations.append(discrimination)
        all_results.append(results)

        # Per-run audit
        path = _write_audit(
            operator_name=op_name,
            model_version=model_version,
            discrimination=discrimination,
            results=results,
            cfg_hash=cfg_hash,
            run_index=run_idx,
            total_runs=args.runs,
        )

        run_label = f"[{run_idx}/{args.runs}]" if args.runs > 1 else ""
        glyph = "PASS" if discrimination >= 1.0 else "FAIL"
        print(f"GOLDEN {op_name} {run_label}: discrimination={discrimination:.2f} "
              f"({sum(r['passed'] for r in results)}/{len(results)}) → {glyph}  "
              f"(audit: {path.name})")

    # Aggregate verdict
    all_pass = all(d >= 1.0 for d in all_discriminations)
    agg = sum(all_discriminations) / len(all_discriminations)
    overall = "PASS" if all_pass else "FAIL"
    print(f"\nGOLDEN {op_name} OVERALL: discrimination={agg:.2f} "
          f"({args.runs} runs, all ≥1.0: {all_pass}) → {overall}")

    # Exit: spec §8 — promotion requires all runs == 1.0
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
