"""Deterministic kill-filter (Part 4) — pure code over the verdicts, no model.
Evaluate cheapest decisive gates first; stop at the first hard fail.

A gate fires (KILL) iff the check's verdict is a cited killing verdict for that gate
AND its grounding confidence clears `thresholds.confidence_floor`. We NEVER kill on
`unverifiable`/silence: a KILL must be grounded in evidence (CLAUDE.md — "a KILL is not
the model's opinion; it is grounded in evidence"). Weak, unproven, or weakly-grounded
ideas are not killed here — they fall through to scoring, where a low composite (and the
adversarial gate) stop them publishing. The confidence_floor lever defaults to 0.0
(inert); it is calibrated live under supervision (see config.yaml thresholds note / P0-2).
"""
from __future__ import annotations

from typing import Optional

from .config import Config
from .models import CheckResult


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
    # Kill ONLY on a cited killing verdict (e.g. `refuted` = grounded disconfirming
    # evidence; `supported` for incumbency = a real incumbent). `unverifiable`/silence
    # never kills — that would be a kill with no evidence behind it.
    if result.verdict.value not in set(gates[check_name]):
        return False
    # And a killing verdict only HARD-kills when its grounding confidence clears the
    # floor. A weakly-grounded refutation (e.g. one thinly-matching source) is not
    # decisive evidence: it falls through to scoring, where a low composite + the
    # adversarial gate stop it publishing. This closes the value_durability
    # over-restriction wall (war-room 2026-06-15): known-good theses were killed at
    # conf 0.25 while the gate already computed the good/bad signal — the kill rule was
    # discarding it. Tunable per-lane via thresholds.confidence_floor in config.yaml.
    return result.confidence >= cfg.thresholds.confidence_floor


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
