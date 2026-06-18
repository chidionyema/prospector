"""The moat (Part 4): six grounded kill-checks, verdict-from-retrieval-only,
adversarial pass. Kill-fast — stop at the first hard fail.

Per check: query_gen -> retrieve real passages -> verdict (grounded ONLY in those
passages). Source-or-die and graceful degradation are enforced here:
  - no passages retrieved  => verdict forced to `unverifiable` (degraded), never killed-by-crash
  - model says supported with no citations => downgraded to unverifiable (anti-hallucination)
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from .config import Config
from .errors import ProviderExhaustedError
from .kill_filter import is_hard_fail
from .models import (CHECKS, DEFAULT_CHECKS, DEFER_GATE, AdversarialResult, Candidate,
                     CheckResult, Source, Verdict)
from .operator import Operator
from .prompts import render
from .retrieval import SearchProvider
from .telemetry import logger, track_latency


def _served_provider(op: Operator) -> str:
    """The concrete brain that actually ruled. For a moat FallbackOperator this is the
    tier that served (e.g. 'gemini_cli', 'deepseek') — the precise audit answer to "who
    ruled"; for a single operator it's its model_version/name."""
    served = getattr(op, "last_served", lambda: "")()
    return served or getattr(op, "model_version", "") or getattr(op, "name", "") or "unknown"


def _served_is_provisional(op: Operator) -> bool:
    """True if the most recent ruling was served by the cheap emergency tail (outside
    MOAT_PRIMARY) rather than a trusted moat brain. Always False for a single operator
    (no fallback tail can have engaged), so pinned/test configs never mark provisional."""
    return bool(getattr(op, "served_is_provisional", lambda: False)())


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
    # Stage-1 pack-intent checks — disconfirm = evidence the demand/route/currency is absent.
    "buyer_intent": ["{q} no demand OR nobody searching OR no buyers OR niche too small"],
    "route_to_market": ["{q} no marketing channel OR hard to reach customers OR ads banned"],
    "currency": ["{q} outdated OR trend over OR declined OR no longer relevant"],
    "claims_verifiable": ["{q} false OR debunked OR no evidence OR contradicted"],
}


def _calc_confidence(sources: list[Source], citations: list[str],
                     check_question: str) -> float:
    """Deterministic confidence from evidence, replacing the LLM's self-calibration.

    FIX #4b — Algorithmic Confidence Scoring:
    LLMs are notoriously bad at calibrating their own confidence (defaults to 0.8/0.9
    regardless of evidence). This formula is an objective audit of the grounding quality:

    1. Citation fraction  (0–0.30): what share of retrieved passages the model cited.
       0 citations → 0.0; full citation of all sources → 0.30.
    2. Source diversity   (0–0.40): how many distinct netlocs are cited.
       Citing 3+ distinct domains → 0.40; 1 domain → 0.10.
    3. Keyword relevance  (0–0.30): does passage text overlap with the check question?
       Measured by normalised word overlap.  Each cited source scores independently;
       the best score wins (we care about having ONE high-quality passage).

    Score is clamped [0.0, 1.0].  All weights sum to 1.0.
    """
    CITED_WEIGHT = 0.30
    DIVERSITY_WEIGHT = 0.40
    RELEVANCE_WEIGHT = 0.30

    # --- 1. Citation fraction ---
    total = len(sources)
    cited = len(citations)
    citation_score = (cited / total * CITED_WEIGHT) if total > 0 else 0.0

    # --- 2. Source diversity (netloc of cited sources only) ---
    cited_netlocs: set[str] = set()
    cited_sources_map = {s.source_id: s for s in sources}
    for cid in citations:
        src = cited_sources_map.get(cid)
        if src:
            from urllib.parse import urlparse
            netloc = urlparse(src.url).netloc.replace("www.", "").lower()
            if netloc:
                cited_netlocs.add(netloc)
    n_domains = len(cited_netlocs)
    if n_domains >= 3:
        diversity_score = DIVERSITY_WEIGHT
    elif n_domains == 2:
        diversity_score = 0.25
    elif n_domains == 1:
        diversity_score = 0.10
    else:
        diversity_score = 0.0

    # --- 3. Keyword relevance (best cited passage vs. check question) ---
    question_words = set(check_question.lower().split())
    # Strip common stopwords to avoid false-low scores on generic questions.
    stopwords = {"a", "an", "the", "is", "are", "or", "and", "it", "does", "not",
                    "doesn", "can", "that", "this", "with", "for", "from"}
    question_words -= stopwords
    relevance_score = 0.0
    for cid in citations:
        src = cited_sources_map.get(cid)
        if not src:
            continue
        passage_words = set(src.text.lower().split())
        overlap = question_words & passage_words
        score = (len(overlap) / len(question_words)) if question_words else 0.0
        relevance_score = max(relevance_score, score * RELEVANCE_WEIGHT)

    confidence = round(citation_score + diversity_score + relevance_score, 3)
    return min(1.0, max(0.0, confidence))


# Filler/brand/product-noise stripped from search queries.
_QUERY_NOISE = frozenset({
    "a", "an", "the", "and", "or", "for", "of", "to", "in", "on", "with", "that",
    "this", "any", "into", "turns", "turn", "your", "their", "our", "its", "is",
    "are", "by", "as", "it", "via", "using", "use", "based", "enabling", "helps",
    "help", "new", "real", "time", "first", "grade", "professional", "platform",
    "tool", "tools", "app", "apps", "solution", "solutions", "service", "services",
    "system", "systems", "software", "product", "powered", "driven", "instrument",
    "enabled", "compliant", "under", "underneath", "across", "between", "through",
})


def _keywords(cand: Candidate, k: int = 12) -> str:
    """Compress one_liner+title+hypothesis into salient search keywords. 
    Increased cap (k=12) and hypothesis inclusion ensures domain-specific terms 
    (e.g. 'EU Data Act') survive the generic framing."""
    text = f"{cand.one_liner} {cand.title} {cand.hypothesis}"
    out: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9-]+", text):
        low = raw.lower()
        if len(low) < 3 or low in _QUERY_NOISE or low in seen:
            continue
        seen.add(low)
        out.append(raw if raw.isupper() else low)
        if len(out) >= k:
            break
    return " ".join(out) or cand.title


# Balanced search templates: disconfirm (kill-fast) + confirm (score-high).
_DISCONFIRM_TEMPLATES: dict[str, list[str]] = {
    "value_durability": ["{q} obsolete OR commoditised OR replaced by free alternative"],
    "legality": ["{q} regulation OR licence required OR banned OR illegal"],
    "incumbency": ["{q} incumbent market leader dominant competitor"],
    "payer_solvency": ["{q} budget cuts OR cannot afford OR insolvency"],
    "distribution": ["{q} customer acquisition channel saturated OR expensive"],
    "pain_reality": ["{q} not a real problem OR existing workaround"],
}

_CONFIRM_TEMPLATES: dict[str, list[str]] = {
    "value_durability": ["{q} durable moat barrier defensibility"],
    "legality": ["{q} legal framework compliance pathway"],
    "incumbency": ["{q} market gap underserved segment"],
    "payer_solvency": ["{q} budget willingness to pay ROI"],
    "distribution": ["{q} acquisition channel case study"],
    "pain_reality": ["{q} acute problem testimonial evidence"],
}


def _templated_queries(cand: Candidate, check_name: str, n: int) -> list[str]:
    """Mix confirm and disconfirm queries for a balanced view."""
    base = _keywords(cand)
    disconfirm = _DISCONFIRM_TEMPLATES.get(check_name, [])
    confirm = _CONFIRM_TEMPLATES.get(check_name, [])
    
    out = []
    if disconfirm:
        out.append(disconfirm[0].format(q=base))
    if confirm:
        out.append(confirm[0].format(q=base))
        
    return out[:max(1, n)] or [f"{base} {check_name}"]


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
                sources: list[Source], cfg: Config | None = None) -> CheckResult:
    """Rule ONLY from the provided passages. Silence => unverifiable.

    FIX #2: passages are truncated to VERDICT_PASSAGE_TRUNCATE chars — enough for
    the model to locate and cite the relevant claim; re-digesting the full passage
    is waste (verdict is a classification, not a summary task).

    MOAT DISCIPLINE: the verdict is ruled by the moat operator `op` (the trusted
    Claude/Gemini chain, with a guardrailed cheap tail). It is NOT routed to the
    non-critical query/generation chain — a kill or pass must be decided by a trusted
    brain. If the cheap emergency tail (deepseek/minimax) serves because Claude AND
    Gemini are exhausted, the result is stamped `provisional` (see verify.py helpers):
    throughput continues, but it does not publish on PASS and is auto re-vetted on the
    next `vet --resume`. (This replaces the old FIX #7, which wrongly routed verdicts to
    the DeepSeek-first chain as primary even when the moat had full quota.)
    """
    # P1-5 defense-in-depth: the moat rules on RETRIEVED pages, never on a cheap model's
    # self-synthesis. An LLM-search provider that finds no real URLs emits a
    # `synthesized://…` source (retrieval.py); strip those before ruling so they can be
    # neither cited nor counted. If that empties the set we fall through to the
    # graceful-degradation UNVERIFIABLE below — never a synthesis-grounded verdict.
    sources = [s for s in sources
               if not str(getattr(s, "url", "")).startswith("synthesized://")]
    if not sources:
        return CheckResult(check_name=check_name, verdict=Verdict.UNVERIFIABLE,
                           confidence=0.0,
                           rationale="No passages retrieved; downgraded (graceful degradation).",
                           degraded=True)
    
    # Persona bias (Part 16 principal upgrade)
    persona: dict = {}
    verdict_bias = ""
    if cfg is not None:
        persona = cfg.personas.get(cfg.active_persona) or {}
        verdict_bias = persona.get("verdict_bias", "")

    # FIX #2: truncate passages to reduce verdict input tokens by ~5-6x.
    # Format: [source_id] <truncated_text>  (url and title are in the prompt template).
    passages = "\n".join(
        f"[{s.source_id}] {s.text[:VERDICT_PASSAGE_TRUNCATE]}" for s in sources)
    system, user = render("verdict", candidate_json=json.dumps(cand.to_dict()),
                          check_name=check_name, check_question=CHECKS[check_name],
                          verdict_bias=verdict_bias)
    user = user.replace("{for each: [source_id] (url, published_at) text}", passages)
    user += f"\n\nPassages:\n{passages}"
    try:
        data = op.complete_json(system, user, temperature=0.0)
    except ProviderExhaustedError:
        # Every brain (incl. the cheap tail) is out of quota/credit — an outage, not a
        # weak idea. Let it propagate so run_check defers the candidate (re-vet) instead
        # of killing.
        raise
    except Exception as e:
        logger.error(f"Verdict call failed for {check_name}: {e}")
        return CheckResult(check_name=check_name, verdict=Verdict.UNVERIFIABLE,
                           confidence=0.0, rationale="Verdict call failed; fail-safe.",
                           sources=sources, degraded=True,
                           provider=_served_provider(op))
    # Who ACTUALLY ruled, and was it the guardrailed cheap tail (-> provisional)?
    _provider_used = _served_provider(op)
    _provisional = _served_is_provisional(op)
    if _provisional:
        logger.warning(
            f"Check {check_name} ruled by FALLBACK brain {_provider_used!r} (moat "
            f"exhausted) — marking provisional; will not publish on PASS and auto re-vets",
            extra={"check": check_name, "provider": _provider_used, "provisional": True})
    verdict = _coerce_verdict(data.get("verdict", "unverifiable"))
    citations = [str(c) for c in (data.get("citations") or [])]
    valid_ids = {s.source_id for s in sources}
    citations = [c for c in citations if c in valid_ids]
    # source-or-die: 'supported' with no valid citation is not grounded -> unverifiable
    if verdict == Verdict.SUPPORTED and not citations:
        logger.info(f"Downgrading supported check {check_name} to unverifiable (no citations)")
        verdict = Verdict.UNVERIFIABLE
    # FIX #4b: replace LLM confidence with algorithmic confidence.
    # LLM self-calibration is unreliable (defaults to 0.8/0.9 regardless of evidence).
    # The deterministic formula audits the actual grounding quality objectively:
    # citation fraction + source diversity + keyword relevance.
    confidence = _calc_confidence(sources, citations, CHECKS[check_name])
    return CheckResult(
        check_name=check_name, verdict=verdict,
        confidence=confidence,
        rationale=str(data.get("rationale", ""))[:600],
        citations=citations,
        sources=[s for s in sources if s.source_id in citations] or sources,
        provider=_provider_used, provisional=_provisional)


# Truncation budget for verdict call: the model needs enough context to cite a
# specific claim, not to re-digest the full passage. 300 chars covers the key
# assertion while cutting verdict input tokens by ~5-6x.  Source IDs + URLs are
# already in the prompt; the model can re-locate rather than re-read.
VERDICT_PASSAGE_TRUNCATE = 600


@track_latency(name="run_check")
def run_check(op: Operator, search: SearchProvider, cfg: Config,
              cand: Candidate, check_name: str,
              query_op: Optional[Operator] = None) -> CheckResult:
    logger.info(f"Running check: {check_name}")
    r = cfg.retrieval
    # Kill-fast: cheapest decisive gates first.
    # FIX #1 defensive guard: if queries_per_check is 0 we MUST NOT call gen_queries
    # (blank call, all tokens wasted).  Use the template path instead.
    if check_name in (r.template_checks or []):
        queries = _templated_queries(cand, check_name, r.fast_queries)
    elif r.queries_per_check > 0:
        queries = gen_queries(query_op or op, cand, check_name, r.queries_per_check)
    else:
        # FIX #1: queries_per_check=0 means skip LLM query-gen entirely;
        # fall back to the deterministic template (no token cost, no latency).
        queries = _templated_queries(cand, check_name, r.fast_queries)

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

    # FIX #4a — ZERO-EVIDENCE SHORT-CIRCUIT:
    # If no passages were retrieved at all, the LLM must say unverifiable anyway;
    # firing verdict_for() just pays for the model to tell us what we already know.
    # Return immediately with no LLM call — saves 1 verdict call per empty check.
    if not uniq:
        logger.info(f"Check {check_name}: no passages retrieved; short-circuit to UNVERIFIABLE "
                     "(no verdict LLM call fired)", extra={"check": check_name})
        return CheckResult(
            check_name=check_name, verdict=Verdict.UNVERIFIABLE,
            confidence=0.0,
            rationale=("No passages retrieved from any search query. "
                       "Downgraded to unverifiable without firing the verdict LLM call."),
            queries=queries, degraded=True)

    # MOAT DISCIPLINE: the verdict is ruled by the moat `op` (trusted Claude/Gemini chain
    # + guardrailed cheap tail), NOT by query_op (the non-critical query/gen chain).
    # query_op above is used only for mechanical query-generation.
    try:
        result = verdict_for(op, cand, check_name, uniq, cfg)
    except ProviderExhaustedError as e:
        logger.warning(f"All brains exhausted ruling {check_name}: {e}; deferring",
                       extra={"check": check_name})
        return CheckResult(
            check_name=check_name, verdict=Verdict.UNVERIFIABLE, confidence=0.0,
            rationale=("Verdict brain unavailable — all LLMs out of quota/credit. "
                       "Cannot rule; candidate deferred for re-vet."),
            queries=queries, degraded=True, retrieval_failed=True)
    result.queries = queries
    logger.info(f"Check {check_name} result: {result.verdict.value}", 
                extra={"check": check_name, "verdict": result.verdict.value, "confidence": result.confidence})
    return result


@track_latency(name="adversarial")
def adversarial(op: Operator, cfg: Config, cand: Candidate,
                checks: list[CheckResult]) -> AdversarialResult:
    # Lane-aware framing: a lane may re-aim the adversarial pass at its OWN bar (e.g. a
    # £30-pack lane forbids "no moat" kills but keeps deliverability/demand kills). Empty
    # for venture/default => byte-for-byte the original prompt (golden-set safe).
    lane = cfg.lanes.get(cfg.active_lane) or {}
    lane_directive = lane.get("adversarial_directive") or ""
    
    # Persona bias (Part 16 principal upgrade)
    persona = cfg.personas.get(cfg.active_persona) or {}
    adv_bias = persona.get("adversarial_bias", "")

    verification_json = json.dumps([c.to_dict() for c in checks])
    system, user = render("adversarial", candidate_json=json.dumps(cand.to_dict()),
                          verification_json=verification_json,
                          lane_directive=lane_directive,
                          adversarial_bias=adv_bias)
    try:
        data = op.complete_json(system, user, temperature=0.3)
        citations = [str(c) for c in (data.get("citations") or [])]
        decisive = bool(data.get("decisive", False))
        # source-or-die: a DECISIVE kill must cite evidence. An uncited "decisive"
        # adversarial verdict is the model's opinion, not grounded disconfirmation —
        # downgrade it so it cannot fire the adversarial_decisive hard gate.
        if decisive and not citations:
            logger.info("Adversarial claimed decisive with no citations; "
                        "downgrading to non-decisive (source-or-die).")
            decisive = False

        # Continuous decisiveness score [0..1]
        # Decisive kill with many citations -> high confidence (1.0)
        # Decisive but few citations -> medium confidence (0.7)
        # Not decisive -> low confidence (0.2)
        if decisive:
            conf = min(1.0, 0.7 + (len(citations) * 0.1))
        else:
            conf = 0.2
            
        return AdversarialResult(
            kill_case=str(data.get("kill_case", "")),
            decisive=decisive,
            confidence=conf,
            citations=citations,
            provider=_served_provider(op),
            provisional=_served_is_provisional(op))
    except ProviderExhaustedError:
        # Moat exhausted — re-raise so verify() can distinguish this from a
        # benign parse/network error and defer the candidate rather than continue.
        raise
    except Exception as e:
        logger.error(f"Adversarial call failed: {e}")
        return AdversarialResult(kill_case="adversarial call failed", decisive=False)


def verify(op: Operator, search: SearchProvider, cfg: Config, cand: Candidate,
           on_check: Optional[Callable[[CheckResult], None]] = None,
           query_op: Optional[Operator] = None,
           skip_adversarial: bool = False,
           full_vet: bool = False,
           ) -> tuple[list[CheckResult], Optional[AdversarialResult], Optional[str]]:
    """Run the six checks kill-fast. Returns (checks_run, adversarial_or_None,
    first_failing_gate_or_None). Stops at the first hard fail (skips remaining checks
    and the adversarial pass) to save cost and keep throughput on contenders.

    Args:
        skip_adversarial: When True, skips the adversarial pass entirely.  Used by the
            golden-set harness to isolate the six-check logic from the adversarial layer.
            The adversarial pass must be validated separately (promotion gate).
        full_vet: When True, bypasses the kill-fast short-circuit and runs ALL checks.
            Used to gather a complete failure surface for adaptive learning.
    """
    checks: list[CheckResult] = []
    # Kill-fast order is driven by config (cheapest decisive gates first), so config
    # is the single source of truth: gated checks in hard_gates order, then any rest.
    # Lane-aware: with an active lane that declares `score_checks`, we run ONLY its hard
    # gates + those soft checks (a lane shouldn't pay for checks irrelevant to its ambition
    # class — e.g. side_hustle skips value_durability). Default/no-lane => the original six.
    gated = [k for g in cfg.hard_gates for k in g if k in CHECKS]
    lane = cfg.lanes.get(cfg.active_lane) or {}
    score_checks = lane.get("score_checks")
    if cfg.active_lane and score_checks is not None:
        extras = [c for c in score_checks if c in CHECKS and c not in gated]
        run_order = gated + extras
    else:
        run_order = gated + [c for c in DEFAULT_CHECKS if c not in gated]
    
    first_failing_gate = None
    
    for name in run_order:
        res = run_check(op, search, cfg, cand, name, query_op=query_op)
        checks.append(res)
        if on_check:
            on_check(res)
        
        # Determine if this gate fired
        gate_fired = False
        if res.retrieval_failed and name in cfg.gate_map():
            gate_fired = True
            if first_failing_gate is None:
                first_failing_gate = DEFER_GATE
        elif is_hard_fail(name, res, cfg):
            gate_fired = True
            if first_failing_gate is None:
                first_failing_gate = name

        # Short-circuit ONLY if not full_vet
        if gate_fired and not full_vet:
            logger.info(f"Kill-fast triggered by gate: {name}", extra={"gate": name})
            return checks, None, first_failing_gate

    # adversarial() calls op.complete_json — if the moat chain (Claude → Gemini) is
    # exhausted, it raises ProviderExhaustedError.  Catch it here so the candidate
    # defers (re-vet later when the moat recovers) instead of crashing the whole run.
    if not skip_adversarial:
        try:
            # adversarial() stamps its own provider + provisional from the brain that
            # actually served (the moat primary, or the guardrailed cheap tail).
            adv = adversarial(op, cfg, cand, checks)
        except ProviderExhaustedError as e:
            logger.warning(f"Moat exhausted during adversarial pass: {e}; deferring candidate "
                           f"{cand.candidate_id!r} (adversarial step unrun — re-vet when moat recovers)",
                           extra={"candidate_id": cand.candidate_id, "provider_exhausted": str(e)[:200]})
            return checks, None, first_failing_gate or "moat_exhausted"
        
        if cfg.adversarial_decisive_kills and adv.decisive:
            if first_failing_gate is None:
                first_failing_gate = "adversarial_decisive"
            if not full_vet:
                logger.info("Kill-fast triggered by adversarial pass")
                return checks, adv, first_failing_gate
    else:
        adv = None
    
    return checks, adv, first_failing_gate
