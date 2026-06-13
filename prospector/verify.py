"""The moat (Part 4): six grounded kill-checks, verdict-from-retrieval-only,
adversarial pass. Kill-fast — stop at the first hard fail.

Per check: query_gen -> retrieve real passages -> verdict (grounded ONLY in those
passages). Source-or-die and graceful degradation are enforced here:
  - no passages retrieved  => verdict forced to `unverifiable` (degraded), never killed-by-crash
  - model says supported with no citations => downgraded to unverifiable (anti-hallucination)
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from .config import Config
from .kill_filter import is_hard_fail
from .models import (CHECKS, DEFER_GATE, AdversarialResult, Candidate, CheckResult,
                     Source, Verdict)
from .operator import Operator
from .prompts import render
from .retrieval import SearchProvider
from .telemetry import logger, track_latency


def _coerce_verdict(v: str) -> Verdict:
    try:
        return Verdict(str(v).strip().lower())
    except ValueError:
        return Verdict.UNVERIFIABLE


# Deterministic disconfirming queries for cheap decisive gates — skips an LLM
# query-gen call on the gates that kill most candidates. Phrased to surface the
# evidence that would FAIL the check (kill-fast wants the negative first).
_DISCONFIRM_TEMPLATES: dict[str, list[str]] = {
    "value_durability": ["{q} obsolete OR commoditised OR replaced by free alternative",
                         "{q} open-source OR built-in OR cheaper substitute"],
    "legality": ["{q} regulation OR licence required OR banned OR illegal"],
    "incumbency": ["{q} incumbent market leader dominant competitor"],
    "payer_solvency": ["{q} budget cuts OR cannot afford OR insolvency"],
    "distribution": ["{q} customer acquisition channel saturated OR expensive"],
    "pain_reality": ["{q} not a real problem OR existing workaround"],
}


def _templated_queries(cand: Candidate, check_name: str, n: int) -> list[str]:
    base = f"{cand.title} {cand.one_liner}".strip() or cand.title
    tmpls = _DISCONFIRM_TEMPLATES.get(check_name) or ["{q} " + check_name]
    out = [t.format(q=base) for t in tmpls][:max(1, n)]
    return out or [f"{base} {check_name}"]


@track_latency(name="gen_queries")
def gen_queries(op: Operator, cand: Candidate, check_name: str, n: int) -> list[str]:
    system, user = render("query_gen", candidate_json=json.dumps(cand.to_dict()),
                          check_name=check_name, check_question=CHECKS[check_name])
    try:
        data = op.complete_json(system, user, temperature=0.5)
        qs = data if isinstance(data, list) else data.get("queries", [])
        return [str(q) for q in qs][:n] or [f"{cand.title} {check_name}"]
    except Exception as e:
        logger.warning(f"Query gen failed for {check_name}: {e}")
        return [f"{cand.title} {check_name}"]


@track_latency(name="verdict_for")
def verdict_for(op: Operator, cand: Candidate, check_name: str,
                sources: list[Source]) -> CheckResult:
    """Rule ONLY from the provided passages. Silence => unverifiable."""
    if not sources:
        return CheckResult(check_name=check_name, verdict=Verdict.UNVERIFIABLE,
                           confidence=0.0,
                           rationale="No passages retrieved; downgraded (graceful degradation).",
                           degraded=True)
    passages = "\n".join(
        f"[{s.source_id}] ({s.url}, {s.published_at or 'n.d.'}) {s.text}" for s in sources)
    system, user = render("verdict", candidate_json=json.dumps(cand.to_dict()),
                          check_name=check_name, check_question=CHECKS[check_name])
    user = user.replace("{for each: [source_id] (url, published_at) text}", passages)
    user += f"\n\nPassages:\n{passages}"
    try:
        data = op.complete_json(system, user, temperature=0.0)
    except Exception as e:
        logger.error(f"Verdict call failed for {check_name}: {e}")
        return CheckResult(check_name=check_name, verdict=Verdict.UNVERIFIABLE,
                           confidence=0.0, rationale="Verdict call failed; fail-safe.",
                           sources=sources, degraded=True)
    verdict = _coerce_verdict(data.get("verdict", "unverifiable"))
    citations = [str(c) for c in (data.get("citations") or [])]
    valid_ids = {s.source_id for s in sources}
    citations = [c for c in citations if c in valid_ids]
    # source-or-die: 'supported' with no valid citation is not grounded -> unverifiable
    if verdict == Verdict.SUPPORTED and not citations:
        logger.info(f"Downgrading supported check {check_name} to unverifiable (no citations)")
        verdict = Verdict.UNVERIFIABLE
    return CheckResult(
        check_name=check_name, verdict=verdict,
        confidence=float(data.get("confidence", 0.0) or 0.0),
        rationale=str(data.get("rationale", ""))[:600],
        citations=citations,
        sources=[s for s in sources if s.source_id in citations] or sources)


@track_latency(name="run_check")
def run_check(op: Operator, search: SearchProvider, cfg: Config,
              cand: Candidate, check_name: str,
              query_op: Optional[Operator] = None) -> CheckResult:
    logger.info(f"Running check: {check_name}")
    r = cfg.retrieval
    # Cheap decisive gates use deterministic templates (no LLM query-gen call);
    # everything else generates queries with the (optionally lighter) query_op.
    if check_name in (r.template_checks or []):
        queries = _templated_queries(cand, check_name, r.fast_queries)
    else:
        queries = gen_queries(query_op or op, cand, check_name, r.queries_per_check)

    from concurrent.futures import ThreadPoolExecutor
    passages: list[Source] = []
    n_failed = 0

    with ThreadPoolExecutor(max_workers=len(queries)) as executor:
        # Launch searches in parallel
        futures = [executor.submit(search.search, q, k=r.results_per_query,
                                   max_chars=r.max_passage_chars)
                   for q in queries]

        for future in futures:
            try:
                passages.extend(future.result())
            except Exception as e:
                n_failed += 1
                logger.error(f"Search failed for check {check_name}: {e}")

    # Distinguish a retrieval OUTAGE from a legitimate empty result. If every search
    # errored and nothing came back, we never got to look — that is INCONCLUSIVE, not
    # evidence of a weak idea. Flag it so kill_filter/verify defer instead of killing.
    if queries and n_failed == len(queries) and not passages:
        logger.warning(f"Retrieval unavailable for {check_name}: all {n_failed} "
                       f"search(es) failed; marking retrieval_failed (will defer, not kill)",
                       extra={"check": check_name, "failed": n_failed})
        return CheckResult(
            check_name=check_name, verdict=Verdict.UNVERIFIABLE, confidence=0.0,
            rationale=("Retrieval unavailable — all searches failed (infra/outage). "
                       "Cannot rule; candidate deferred for re-vet."),
            queries=queries, degraded=True, retrieval_failed=True)

    # dedup by source_id, keep order
    seen, uniq = set(), []
    for s in passages:
        if s.source_id not in seen:
            seen.add(s.source_id)
            uniq.append(s)
    result = verdict_for(op, cand, check_name, uniq)
    result.queries = queries
    logger.info(f"Check {check_name} result: {result.verdict.value}", 
                extra={"check": check_name, "verdict": result.verdict.value, "confidence": result.confidence})
    return result


@track_latency(name="adversarial")
def adversarial(op: Operator, cand: Candidate,
                checks: list[CheckResult]) -> AdversarialResult:
    verification_json = json.dumps([c.to_dict() for c in checks])
    system, user = render("adversarial", candidate_json=json.dumps(cand.to_dict()),
                          verification_json=verification_json)
    try:
        data = op.complete_json(system, user, temperature=0.3)
        return AdversarialResult(
            kill_case=str(data.get("kill_case", "")),
            decisive=bool(data.get("decisive", False)),
            citations=[str(c) for c in (data.get("citations") or [])])
    except Exception as e:
        logger.error(f"Adversarial call failed: {e}")
        return AdversarialResult(kill_case="adversarial call failed", decisive=False)


def verify(op: Operator, search: SearchProvider, cfg: Config, cand: Candidate,
           on_check: Optional[Callable[[CheckResult], None]] = None,
           query_op: Optional[Operator] = None
           ) -> tuple[list[CheckResult], Optional[AdversarialResult], Optional[str]]:
    """Run the six checks kill-fast. Returns (checks_run, adversarial_or_None,
    first_failing_gate_or_None). Stops at the first hard fail (skips remaining checks
    and the adversarial pass) to save cost and keep throughput on contenders."""
    checks: list[CheckResult] = []
    # Kill-fast order is driven by config (cheapest decisive gates first), so config
    # is the single source of truth: gated checks in hard_gates order, then any rest.
    gated = [k for g in cfg.hard_gates for k in g if k in CHECKS]
    run_order = gated + [c for c in CHECKS if c not in gated]
    for name in run_order:
        res = run_check(op, search, cfg, cand, name, query_op=query_op)
        checks.append(res)
        if on_check:
            on_check(res)
        # A retrieval outage on a decisive gate means we cannot rule. Defer the whole
        # candidate (re-vet later) rather than let a failed search count as a kill.
        if res.retrieval_failed and name in cfg.gate_map():
            logger.warning(f"Deferring candidate: retrieval failed on gate {name!r}",
                           extra={"gate": name, "deferred": True})
            return checks, None, DEFER_GATE
        if is_hard_fail(name, res, cfg):
            logger.info(f"Kill-fast triggered by gate: {name}", extra={"gate": name})
            return checks, None, name        # short-circuit
    adv = adversarial(op, cand, checks)
    if cfg.adversarial_decisive_kills and adv.decisive:
        logger.info("Kill-fast triggered by adversarial pass")
        return checks, adv, "adversarial_decisive"
    return checks, adv, None
