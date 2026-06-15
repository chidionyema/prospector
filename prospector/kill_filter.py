"""Deterministic kill-filter (Part 4) — pure code over the verdicts, no model.
Evaluate cheapest decisive gates first; stop at the first hard fail.

A gate fires (KILL) iff the check's verdict is a cited killing verdict for that gate.
We NEVER kill on `unverifiable`/silence or on low confidence alone: a KILL must be
grounded in evidence (CLAUDE.md — "a KILL is not the model's opinion; it is grounded
in evidence"). Weak or unproven ideas are not killed here — they fall through to
scoring, where a low composite (and the adversarial gate) stop them publishing.
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
    # and low confidence never kill — that would be a kill with no evidence behind it.
    return result.verdict.value in set(gates[check_name])


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
