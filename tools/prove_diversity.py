#!/usr/bin/env python3
"""Prove the anti-duplication fixes WORK — runtime artifacts, not passing unit stubs.

Two defects let near-duplicate / ungrounded packs reach the live storefront:
  1. The PASS decision required only a composite score, never grounding -> an ungrounded
     candidate (0 sources, all unverifiable) scored 2.95 and PASSed (source-or-die hole).
  2. Generation had no memory across runs -> the blue-sky daemon kept re-minting the same
     idea families (9 probate/estate/clear-out variants accumulated in the store).

This harness drives the REAL classes end-to-end and prints a PASS/FAIL receipt per claim.
Exit is nonzero if ANY claim fails OR the live-generation capstone could not be run — so it
can gate a deploy and we never declare victory on an unproven path.

    python -m tools.prove_diversity        # or: python tools/prove_diversity.py

Claims:
  D1  source-or-die DECISION   ungrounded high-composite -> KILL gate=source_or_die (not PASS);
                               >=1 grounded-supported -> PASS  (real build_dossier, real config)
  D2  source-or-die PUBLISH    EngineBridge refuses a stale ungrounded PASS, no network (backstop)
  D3  cross-run memory LIVE     store.recent_titles() surfaces the probate family the daemon was
                               blind to (real store.db)
  D4  generation diverges      a REAL generation batch, seeded with the probate family in
                               prior_titles, carries those titles into the avoid prompt AND
                               produces ZERO probate/estate/clear-out near-variants
"""
from __future__ import annotations

import os
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prospector.config import load_config
from prospector.errors import ProviderExhaustedError
from prospector.models import (Candidate, CheckResult, Decision, Dossier, ScoreResult,
                               Verdict)
from prospector.dossier import build_dossier
from prospector.store import Store

_RESULTS: list[tuple[str, bool, str]] = []

# A probate/estate/clear-out idea in ANY wording. If a fresh batch — explicitly told the family
# is spent — still emits one of these, the cross-run memory did not steer the model.
_FAMILY = re.compile(
    r"probate|estate|clear[\s-]?out|inheritance|deceased|bereave|executor|will\s+admin|"
    r"legacy\s+(?:sale|clear)|house\s+clearance",
    re.IGNORECASE,
)

_PROBATE_SEED = [
    "The Probate Property Clear-Out Service",
    "Probate Property Buyout Broker",
    "The Probate Locker Clear-Out Agent",
    "The Inheritance Tax Estate Liquidity Fixer",
    "The Widow's Estate Sale Negotiator",
    "The Bureaucrat's Estate Bypass",
]


def record(claim: str, ok: bool, detail: str) -> None:
    _RESULTS.append((claim, ok, detail))
    mark = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
    print(f"  [{mark}] {claim}: {detail}")


def _passing_score(cfg) -> ScoreResult:
    return ScoreResult(scores={ax: 5 for ax in cfg.weights}, justification={},
                       composite=cfg.thresholds.min_composite_to_pass + 1.0,
                       score_failed=False)


def d1_source_or_die_decision(cfg) -> None:
    """A high composite over all-unverifiable checks must NOT pass; >=1 supported must."""
    ungrounded = [CheckResult("pain_reality", Verdict.UNVERIFIABLE, 0.0, "no passage"),
                  CheckResult("payer_solvency", Verdict.UNVERIFIABLE, 0.0, "no passage")]
    bad = build_dossier(Candidate(title="Ungrounded idea"), ungrounded, None, None,
                        _passing_score(cfg), cfg, "proof")
    grounded = [CheckResult("pain_reality", Verdict.SUPPORTED, 0.8, "grounded"),
                CheckResult("payer_solvency", Verdict.UNVERIFIABLE, 0.0, "no passage")]
    good = build_dossier(Candidate(title="Grounded idea"), grounded, None, None,
                         _passing_score(cfg), cfg, "proof")
    ok = (bad.decision == Decision.KILL and bad.gate_fired == "source_or_die"
          and good.decision == Decision.PASS)
    detail = (f"ungrounded+composite -> {bad.decision.name} (gate={bad.gate_fired}); "
              f"grounded -> {good.decision.name}"
              if ok else
              f"LEAK: ungrounded={bad.decision.name}/{bad.gate_fired}, grounded={good.decision.name}")
    record("D1 source-or-die decision", ok, detail)


def d2_source_or_die_publish(cfg) -> None:
    """The publish backstop must refuse a stale ungrounded PASS without touching the network."""
    from prospector.bridge import EngineBridge
    os.environ.setdefault("STORE_INTERNAL_API_KEY", "proof-key")
    bridge = EngineBridge(cfg)
    stale = Dossier(
        candidate=Candidate(title="Stale ungrounded pass"),
        decision=Decision.PASS, gate_fired=None, reason="pre-fix stale pass",
        checks=[CheckResult("pain_reality", Verdict.UNVERIFIABLE, 0.0, "no passage")],
        adversarial=None, score=None, model_version="proof", provider_chain="",
        persona="", created_at="2026-06-16T00:00:00Z", reverify_due_at=None, provisional=False,
    )
    # If the guard were absent this would attempt to bundle/upload; the guard must short it to False.
    published = bridge.publish_pass(stale)
    ok = published is False
    record("D2 source-or-die publish backstop", ok,
           "bridge refused ungrounded PASS (no upload)" if ok else "LEAK: bridge published it")


def d3_cross_run_memory_live(cfg) -> None:
    """The real store must now expose the probate family that generation was blind to."""
    titles = Store(cfg).recent_titles(limit=200)
    fam = [t for t in titles if _FAMILY.search(t)]
    ok = len(titles) > 0 and len(fam) >= 1
    detail = (f"recent_titles={len(titles)}; {len(fam)} probate/estate variant(s) now in the "
              f"avoid memory (e.g. {fam[0]!r})" if ok else
              f"store memory empty/blind (titles={len(titles)}, family={len(fam)})")
    record("D3 cross-run memory (live store)", ok, detail)


def _build_gen_op(cfg):
    """Replicate run.py's non-critical generation chain (deepseek -> minimax -> gemini)."""
    from prospector.operator import _build_operator, FallbackOperator
    from prospector.health import get_noncritical_health
    tiers = []
    for kind in ("deepseek", "minimax", "gemini"):
        try:
            tiers.append((kind, _build_operator(kind, cfg, fast=True)))
        except RuntimeError:
            pass
    if not tiers:
        raise ProviderExhaustedError("no non-critical generation tier available")
    if len(tiers) == 1:
        return tiers[0][1]
    r = cfg.retrieval
    return FallbackOperator(tiers, failure_threshold=r.breaker_failure_threshold,
                            cooldown_s=r.breaker_cooldown_s, health=get_noncritical_health())


class _CapturingGenOp:
    """Wrap the real generation chain, recording the prompts so we can prove the avoid list."""
    def __init__(self, inner):
        self._inner = inner
        self.prompts: list[str] = []
        self.model_version = getattr(inner, "model_version", "chain")

    def complete_json(self, system, user, temperature=0.0):
        self.prompts.append(user)
        return self._inner.complete_json(system, user, temperature=temperature)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def d4_generation_diverges(cfg) -> None:
    """REAL batch: seed the probate family in prior_titles; expect 0 near-variants out."""
    from prospector.generate import generate
    cfg.generation["refinement_enabled"] = False  # cheaper + deterministic call count
    try:
        op = _CapturingGenOp(_build_gen_op(cfg))
    except ProviderExhaustedError as e:
        record("D4 generation diverges (live)", False,
               f"UNPROVEN — generation chain unavailable ({e}); cannot prove on a dead chain")
        return
    try:
        out = generate(op, cfg, signal_text="", k=8, prior_titles=_PROBATE_SEED)
    except Exception as e:
        record("D4 generation diverges (live)", False,
               f"UNPROVEN — live generation raised {type(e).__name__}: {e}")
        return

    titles = [c.title for c in out]
    prompt_blob = "\n".join(op.prompts)
    seed_in_prompt = sum(1 for s in _PROBATE_SEED if s in prompt_blob)
    offenders = [t for t in titles if _FAMILY.search(t)]
    ok = (len(titles) >= 5 and seed_in_prompt >= 1 and len(offenders) == 0
          and len(set(titles)) == len(titles))
    detail = (f"{len(titles)} fresh, distinct ideas; {seed_in_prompt}/{len(_PROBATE_SEED)} seed "
              f"titles reached the avoid prompt; 0 probate/estate near-variants. e.g. "
              f"{titles[:3]}"
              if ok else
              f"seed_in_prompt={seed_in_prompt}, offenders={offenders}, n={len(titles)}, "
              f"distinct={len(set(titles))}")
    record("D4 generation diverges (live)", ok, detail)


def main() -> int:
    print("=" * 76)
    print("PROSPECTOR ANTI-DUPLICATION PROOF — real classes, real store, real generation")
    print("=" * 76)
    cfg = load_config()
    print(f"  config: min_composite_to_pass={cfg.thresholds.min_composite_to_pass}, "
          f"confidence_floor={cfg.thresholds.confidence_floor}")
    print()

    d1_source_or_die_decision(cfg)
    d2_source_or_die_publish(cfg)
    d3_cross_run_memory_live(cfg)
    d4_generation_diverges(cfg)

    print()
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    allgreen = passed == total
    banner = "\033[32m" if allgreen else "\033[31m"
    print(f"{banner}ANTI-DUPLICATION: {passed}/{total} claims proven\033[0m")
    if not allgreen:
        print("  Unproven/failing:")
        for claim, ok, detail in _RESULTS:
            if not ok:
                print(f"    - {claim}: {detail}")
    return 0 if allgreen else 1


if __name__ == "__main__":
    raise SystemExit(main())
