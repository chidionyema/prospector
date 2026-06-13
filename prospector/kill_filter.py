"""Deterministic kill-filter (Part 4) — pure code over the verdicts, no model.
Evaluate cheapest decisive gates first; stop at the first hard fail.

A gate fires (KILL) if the check's verdict is in the gate's killing-verdicts set,
OR a required verdict is below the confidence floor.
"""
from __future__ import annotations

from typing import Optional

from .config import Config
from .models import CheckResult, Verdict


def is_hard_fail(check_name: str, result: CheckResult, cfg: Config) -> bool:
    """Does THIS check trip its hard gate? (used for kill-fast short-circuit)."""
    # A check whose retrieval failed wholesale is INCONCLUSIVE, not evidence: we never
    # got to look, so we cannot rule. It can never trip a gate — the candidate is
    # deferred for re-vet upstream (verify()). This is the line that stops an infra
    # outage from masquerading as a grounded kill.
    if getattr(result, "retrieval_failed", False):
        return False
    gates = cfg.gate_map()
    if check_name not in gates:
        return False
    killing = set(gates[check_name])
    if result.verdict.value in killing:
        return True
    # confidence floor: a gated check that isn't decisively clear is treated as a fail
    # (a 'supported' incumbency below floor, or any required pass below floor).
    if result.confidence < cfg.thresholds.confidence_floor:
        # Only fail on low confidence when the check is one whose 'unverifiable' kills
        # (i.e. we REQUIRE positive evidence). incumbency kills on 'supported', so a
        # low-confidence incumbency=supported is handled above; low-confidence otherwise
        # means we lack firm ground => treat as unverifiable for kill purposes.
        if Verdict.UNVERIFIABLE.value in killing:
            return True
    return False


def apply_gates(checks: list[CheckResult], cfg: Config,
                adversarial_decisive: bool = False) -> tuple[bool, Optional[str], str]:
    """Return (killed, gate_fired, reason). Evaluates in config gate order (kill-fast)."""
    by_name = {c.check_name: c for c in checks}
    for gate in cfg.hard_gates:
        for key, killing in gate.items():
            if key == "adversarial_decisive":
                if killing and adversarial_decisive:
                    return True, "adversarial_decisive", "Adversarial pass made a decisive kill case."
                continue
            res = by_name.get(key)
            if res is None:
                continue
            if is_hard_fail(key, res, cfg):
                return True, key, (f"{key}={res.verdict.value} "
                                   f"(conf {res.confidence:.2f}): {res.rationale}")
    return False, None, "All hard gates passed."
