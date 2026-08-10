"""The moat (Part 4): six grounded kill-checks, verdict-from-retrieval-only,
adversarial pass. Kill-fast — stop at the first hard fail.

Per check: query_gen -> retrieve real passages -> verdict (grounded ONLY in those
passages). Source-or-die and graceful degradation are enforced here:
  - no passages retrieved  => verdict forced to `unverifiable` (degraded), never killed-by-crash
  - model says supported with no citations => downgraded to unverifiable (anti-hallucination)
"""
from __future__ import annotations

import contextvars
import json
import re
from typing import Callable, Optional

from .admissibility import demotion_reason
from .admissibility import host_of as admissibility_host_of
from .audit import audit
from .config import Admissibility, Config
from .entity_templates import ENTITY_SLOTS, ENTITY_TEMPLATES, entity_phrase
from .errors import GroundingInfrastructureError, ProviderExhaustedError
from .kill_filter import is_hard_fail
from .models import (
    CHECKS,
    DEFAULT_CHECKS,
    DEFER_GATE,
    PRICING_CHECK,
    AdversarialResult,
    Candidate,
    CheckResult,
    Source,
    Verdict,
)
from .numeric_citation import record_shadow as record_numeric_shadow
from .operator import Operator
from .pricing import price_for
from .prompts import ALL_MARKET_KEYS, MOAT_MARKET_KEYS, market_kwargs, render
from .retrieval import SearchProvider, market_retrieval
from .telemetry import logger, track_latency
from .telemetry import stage as telemetry_stage
from .trimming import RATIONALE_MAX, clip_to_sentence


def _served_provider(op: Operator) -> str:
    """The concrete brain that actually ruled. For a moat FallbackOperator this is the
    tier that served (e.g. 'claude_cli', 'deepseek') — the precise audit answer to "who
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
            # Shared with the admissibility tiers so "distinct domains" means the same thing
            # in the confidence score and in the gate. The old inline expression lowercased
            # AFTER stripping, so `WWW.x.com` and `x.com` counted as two distinct domains and
            # inflated the diversity term.
            netloc = admissibility_host_of(src.url)
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
    # Product-format / wrapper vocabulary. These describe the DELIVERABLE (a report, a
    # kit, a dashboard) or its framing (personalised, bespoke, ultimate) — not the market
    # fact a verification check turns on. Leaving them in makes the query restate the
    # non-existent product ("printed personalised report mailed...") so search returns junk
    # or nothing. Stripping them surfaces the domain/entity nouns that ground the check.
    "printed", "personalised", "personalized", "mailed", "posted", "report", "reports",
    "kit", "kits", "dashboard", "atlas", "index", "tracker", "monthly", "weekly", "daily",
    "guide", "playbook", "toolkit", "scorecard", "bundle", "pack", "package", "newsletter",
    "digest", "brief", "briefing", "map", "maps", "mapping", "personal", "custom",
    "customised", "customized", "bespoke", "automated", "automatic", "hidden", "exact",
    "specific", "pinpoints", "pinpoint", "maximise", "maximize", "ultimate", "essential",
    "complete", "definitive", "premium", "curated", "insider", "secret", "smart",
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
    # Tight base (6 domain keywords): with product-wrapper noise stripped, the leading
    # salient terms are the market/entity nouns. Short queries match real public pages far
    # better than a 12-word product restatement, and recur across candidates so the disk
    # cache actually hits (faster, fewer live searches). The +3-4 word template suffix
    # keeps the total in the ~9-word band that the engines/ddg return results for.
    base = _keywords(cand, k=6)
    disconfirm = _DISCONFIRM_TEMPLATES.get(check_name, [])
    confirm = _CONFIRM_TEMPLATES.get(check_name, [])

    out = []
    if disconfirm:
        out.append(disconfirm[0].format(q=base))
    if confirm:
        out.append(confirm[0].format(q=base))

    return out[:max(1, n)] or [f"{base} {check_name}"]


# E1: templates that NAME the concrete entity the check turns on. The data lives in the
# leaf module `entity_templates` so `config.py` can validate against it at load time
# without importing this one (see that module's docstring). Re-exported under the original
# private name because that is what the arm's tests and this file already bind.
_ENTITY_TEMPLATES = ENTITY_TEMPLATES


def _entity_queries(cand: Candidate, check_name: str, n: int) -> list[str]:
    """E1 hybrid arm: queries naming the concrete payer/audience entity, or [] to fall through.

    A template whose entity slot is blank is SKIPPED (it would degenerate to the product-shaped
    query this arm exists to replace); all-blank returns [] and the caller uses the LLM chain.

    Returning [] for an unknown check is deliberate and is asserted by
    tests/unit/test_e1_hybrid_queries.py — a missing template must never crash a verdict
    mid-run. That is precisely why a config naming a check with no template has to be
    rejected at LOAD time (`config._validate_hybrid_entity_checks`); caught here it would
    be a silent no-op, and the experiment would report a null result it never ran.
    """
    tpls = _ENTITY_TEMPLATES.get(check_name, [])
    if not tpls:
        return []
    # `entity_phrase` (entity_templates.py), not the raw field. `who_pays` is prose with a
    # median of 29 words, and interpolating it verbatim rendered payer_solvency queries with a
    # median of 38 words, 100% of them over 12 - the product restatement this arm replaces.
    values = {
        "{payer}": entity_phrase(cand.who_pays or ""),
        "{aud}": entity_phrase((cand.audience or "").replace("_", " ")),
        "{market}": entity_phrase(cand.market or ""),
    }
    base = _keywords(cand, k=4)
    out: list[str] = []
    for t in tpls:
        if any(slot in t and not values[slot] for slot in ENTITY_SLOTS):
            continue
        out.append(t.format(
            payer=values["{payer}"], aud=values["{aud}"],
            market=values["{market}"], base=base,
        ))
    return out[:max(1, n)]


def _market_vars(cfg: Config | None, *, for_moat: bool = False) -> dict[str, str]:
    """Market prompt variables, tolerating a None cfg (several call paths allow it).

    A missing cfg yields EMPTY values rather than no keys: an absent key leaves the
    literal `{market_context}` in the prompt sent to the model, which is worse than
    rendering nothing. The moat/open split is preserved in both cases.
    """
    if cfg is None:
        keys = MOAT_MARKET_KEYS if for_moat else ALL_MARKET_KEYS
        return {k: "" for k in keys}
    return market_kwargs(cfg, for_moat=for_moat)


def _check_question(check_name: str, cand: Candidate, cfg: Config | None) -> str:
    """``CHECKS[check_name]``, plus the pack's REAL ladder price for ``payer_solvency``.

    Register §25.6 item 3: this check argued affordability against a price it INVENTED,
    sometimes off the ladder entirely, and those invented figures are ~2/3 of the corpus's
    untraceable-number count. The price is the one quantity in the check that is not
    retrievable and never could be — it is OUR list price, declared in
    ``config.yaml listing.pricing``, not a claim about the world. So the fix is not a
    grounding fix: handing the number over replaces an invented figure with the true one.

    This does NOT weaken verdict-from-retrieval-only. A list price is not market knowledge
    and carries no information about the buyer; the model still rules on whether the
    PASSAGES show the payer can pay, only now against the right figure.

    Scope is deliberately one check. The other six questions render byte-identically, so
    the golden set cannot move underneath this change. ``gen_queries`` (`:292`) is
    deliberately NOT given the price either — a list price in a search query retrieves our
    own storefront, which is self-citation, not evidence about the payer.
    """
    question = CHECKS[check_name]
    if check_name != "payer_solvency" or cfg is None:
        return question
    try:
        # `score` is accepted for interface stability and never consulted (pricing.py:98),
        # which is exactly what lets the moat ask this before scoring has run at all.
        price_pence = price_for(cand, None, cfg).price_pence
    except Exception as exc:
        # A config edit must never take the moat down. Degrade to today's behaviour — the
        # bare question — rather than failing a check over a pricing lookup.
        logger.warning(
            f"payer_solvency price lookup failed; asking without a price: {exc}",
            extra={"candidate_id": getattr(cand, "candidate_id", None)})
        return question
    # Charm-priced rungs (D1, 2026-08-09) end in 99p, so a bare `.0f` would round £49.99 to
    # "£50" — the exact rounding-away-the-pence bug this fix exists to kill, and it would
    # contradict the very next sentence's claim that this is "not an estimate". Whole-pound
    # rungs keep their old bare "£49" form.
    pounds = f"{price_pence // 100:,}" if price_pence % 100 == 0 else f"{price_pence / 100:,.2f}"
    return (f"{question} The buyer pays £{pounds} once for this pack — that is our actual "
            f"list price, not an estimate. Judge affordability against £{pounds} and do "
            f"not substitute a different figure.")


@track_latency(name="gen_queries")
def gen_queries(op: Operator, cand: Candidate, check_name: str, n: int,
                cfg: Config | None = None) -> list[str]:
    system, user = render("query_gen", candidate_json=json.dumps(cand.to_dict()),
                          check_name=check_name, check_question=CHECKS[check_name],
                          **_market_vars(cfg))
    try:
        # retries=0: query-gen already falls back to a template on failure; do not
        # burn multi-minute CLI retries on a non-verdict call.
        with telemetry_stage("query_gen"):
            data = op.complete_json(system, user, temperature=0.5, retries=0)
        qs = data if isinstance(data, list) else data.get("queries", [])
        return [str(q) for q in qs][:n] or [f"{cand.title} {check_name}"]
    except Exception as e:
        logger.warning(f"Query gen failed for {check_name}: {e}")
        return [f"{cand.title} {check_name}"]


@track_latency(name="gen_queries_batched")
def gen_queries_batched(op: Operator, cand: Candidate,
                        check_names: list[str], n: int = 2,
                        cfg: Config | None = None) -> dict[str, list[str]]:
    """ONE fast-tier LLM call → search queries for ALL `check_names` at once.

    Decompose-don't-echo: the model turns the (usually non-existent) product into the
    real-world market/legal/payer questions each check turns on, so search hits authoritative
    on-topic pages instead of the dictionary/social/retail junk a product-pitch restatement
    returns (proven failure mode: `_keywords` queries like "productized transforms tenant
    answers adversarial" → cambridge.org dictionary, web.whatsapp.com, diy.com → ~93%
    unverifiable). Runs on `op` = the non-critical query chain (deepseek→minimax), NEVER the
    moat verdict brain.

    Returns {check_name: [query, ...]} ONLY for checks the model answered cleanly; a
    missing/garbled check is omitted so the caller falls back to its deterministic template.
    On total failure returns {} → every check falls back to a template (no hard-fail when the
    fast chain is down).
    """
    checks_block = "\n".join(f"- {c}: {CHECKS[c]}" for c in check_names if c in CHECKS)
    try:
        system, user = render("query_gen_batched",
                              candidate_json=json.dumps(cand.to_dict()),
                              checks_block=checks_block,
                              **_market_vars(cfg))
        # retries=0: total failure → {} → every check uses its template; hanging
        # Cursor/CLI retries here wedged candidates for 6+ minutes per batch.
        with telemetry_stage("query_gen"):
            data = op.complete_json(system, user, temperature=0.5, retries=0)
    except Exception as e:
        logger.warning(f"Batched query gen failed (falling back to templates): {e}")
        return {}
    if not isinstance(data, dict):
        logger.warning("Batched query gen returned non-dict; falling back to templates")
        return {}
    out: dict[str, list[str]] = {}
    for c in check_names:
        raw = data.get(c)
        if isinstance(raw, list):
            qs = [str(q).strip() for q in raw if str(q).strip()][:max(1, n)]
            if qs:
                out[c] = qs
    return out


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
    # for_moat=True: the verdict brain gets the jurisdiction's NAME and the relevance
    # precedents, never the market's evidence-landscape prose. Handing the moat market
    # knowledge is the prior-knowledge leak that verdict-from-retrieval-only forbids.
    system, user = render("verdict", candidate_json=json.dumps(cand.to_dict()),
                          check_name=check_name,
                          check_question=_check_question(check_name, cand, cfg),
                          verdict_bias=verdict_bias,
                          **_market_vars(cfg, for_moat=True))
    user = user.replace("{for each: [source_id] (url, published_at) text}", passages)
    user += f"\n\nPassages:\n{passages}"
    try:
        with telemetry_stage("verdict"):
            data = op.complete_json(system, user, temperature=0.0)
    except ProviderExhaustedError:
        # Every brain (incl. the cheap tail) is out of quota/credit — an outage, not a
        # weak idea. Let it propagate so run_check defers the candidate (re-vet) instead
        # of killing.
        raise
    except Exception as e:
        # `retrieval_failed=True` is what makes this DEFER instead of counting as evidence.
        # Without it (until 2026-08-06) a failed verdict CALL produced a plain `unverifiable`
        # check that flowed into scoring and the kill gates like any other finding. Proof it
        # bites: store/dossiers/2102bacc6dd75cf9.kill.json is a KILL on gate `min_composite`
        # whose SEVEN checks all read `unverifiable, conf 0.0, "Verdict call failed; fail-safe."`
        # — a candidate killed by our own outage, with a dossier that looks fully reasoned.
        # An exception is not evidence. "A KILL is not the model's opinion; it is grounded in
        # evidence the operator can see" — an error string is not something a buyer can see.
        # This deliberately widens DEFER to non-quota failures (bad JSON, a crashed adapter):
        # a check we never got an answer for is unevaluated, and the honest verdict on an
        # unevaluated check is "come back to it", never "this idea is dead".
        logger.error(f"Verdict call failed for {check_name}: {e}")
        return CheckResult(check_name=check_name, verdict=Verdict.UNVERIFIABLE,
                           confidence=0.0, rationale="Verdict call failed; fail-safe.",
                           sources=sources, degraded=True, retrieval_failed=True,
                           provider=_served_provider(op))
    # Cheap-tail models sometimes wrap the object in a one-element list or emit a bare
    # list of claims. Coerce before .get — otherwise vetting crashes mid-batch
    # ('list' object has no attribute 'get') and burns the rest of the run.
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), {}) if data else {}
    if not isinstance(data, dict):
        data = {}
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
    # Q4 / programme doc §20: citation ADMISSIBILITY, applied at RULING time.
    # A ruling stands unless EVERY one of its citations sits in a tier that cannot establish
    # THIS check (an AI stats farm, dictionary chrome, or — for non-channel checks — a social
    # post). One good source rescues it. This runs here, not in retrieval, because §18 measured
    # grounding as relevance-bound: shrinking the fetched pool is the one thing that cannot
    # help. Demotion is to UNVERIFIABLE, never `retrieval_failed` — the evidence was fetched
    # and judged, so this is a ruling we decline to trust, not an outage to come back from.
    # `cfg` is Optional on this signature, so the policy falls back to the dataclass default —
    # which IS the config default, keeping ONE definition of "what we ship" (deterministic on
    # config: a caller that passes no config gets the configured default, not a special case).
    _policy = (cfg.admissibility.policy if cfg is not None else Admissibility().policy)
    _cited_urls = [s.url for s in sources if s.source_id in citations]
    if verdict in (Verdict.SUPPORTED, Verdict.REFUTED) and _cited_urls:
        _reason = demotion_reason(check_name, _cited_urls, _policy)
        if _reason:
            logger.info(f"Admissibility demotion on {check_name}: {_reason}",
                        extra={"check": check_name, "policy": cfg.admissibility.policy,
                               "was_verdict": verdict.value})
            verdict = Verdict.UNVERIFIABLE
            confidence = 0.0
            data = {**data, "rationale": _reason + " Original rationale: "
                    + str(data.get("rationale", ""))}
    return CheckResult(
        check_name=check_name, verdict=verdict,
        confidence=confidence,
        # Sentence-aware, not `[:600]`. The bare slice put 726 of 7,265 stored rationales on disk
        # ending mid-word (measured 2026-08-06), and this is the field a kill dossier renders as
        # its whole argument. See prospector/trimming.py.
        rationale=clip_to_sentence(str(data.get("rationale", "")), RATIONALE_MAX),
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
              query_op: Optional[Operator] = None,
              precomputed_queries: Optional[dict[str, list[str]]] = None) -> CheckResult:
    logger.info(f"Running check: {check_name}")
    # Audit: this fires on every path (success, retrieval_failed, short-circuit empty,
    # exhausted brain) so we can replay which checks actually reached the search block.
    audit("verify_search", check=check_name,
          candidate_id=getattr(cand, "candidate_id", None),
          invoked_from="verify.run_check")
    r = cfg.retrieval
    # Kill-fast: cheapest decisive gates first.
    # Query source priority:
    #  0. Entity templates (E1 hybrid arm, config-gated) — see _entity_queries.
    #  1. Batched LLM query-gen (precomputed by verify() on the fast tier) — real-world
    #     domain queries that ground the check instead of restating the product pitch.
    #  2. Deterministic template (for template_checks, or as the fallback when the batched
    #     call failed/omitted this check — graceful degradation, never a hard-fail).
    #  3. Per-check LLM gen_queries (legacy path when llm_query_gen is off and the check is
    #     not a template_check).
    # FIX #1 defensive guard: if queries_per_check is 0 we MUST NOT call gen_queries
    # (blank call, all tokens wasted).  Use the template path instead.
    precomputed = (precomputed_queries or {}).get(check_name)
    entity = (_entity_queries(cand, check_name, r.queries_per_check or r.fast_queries)
              if check_name in (r.hybrid_entity_checks or []) else [])
    if entity:
        queries, query_source = entity, "entity_template"
    elif precomputed:
        queries, query_source = precomputed, "llm_batched"
    elif check_name in (r.template_checks or []):
        queries, query_source = _templated_queries(cand, check_name, r.fast_queries), "template"
    elif r.queries_per_check > 0:
        queries = gen_queries(query_op or op, cand, check_name, r.queries_per_check,
                              cfg=cfg)
        query_source = "llm_percheck"
    else:
        # FIX #1: queries_per_check=0 means skip LLM query-gen entirely;
        # fall back to the deterministic template (no token cost, no latency).
        queries, query_source = _templated_queries(cand, check_name, r.fast_queries), "template_fallback"

    from concurrent.futures import ThreadPoolExecutor
    passages: list[Source] = []
    n_failed = 0

    with ThreadPoolExecutor(max_workers=len(queries)) as executor:
        # Launch searches in parallel, each carrying a copy of THIS context. A worker
        # thread otherwise starts on a blank context, so the active market's authority
        # domains (set by market_retrieval, read during the fetch) would never reach the
        # code that fetches. Copy per submit: a Context cannot be entered twice at once.
        futures = [executor.submit(contextvars.copy_context().run,
                                   search.search, q, k=r.results_per_query,
                                   max_chars=r.max_passage_chars)
                   for q in queries]

        for future in futures:
            try:
                passages.extend(future.result())
            except GroundingInfrastructureError:
                raise  # circuit breaker: ALL providers dead — halt, don't defer
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
        audit("verify_search", check=check_name,
              candidate_id=getattr(cand, "candidate_id", None),
              queries=queries, query_source=query_source,
              queries_n=len(queries), n_failed=n_failed,
              passages_n=0, retrieval_failed=True, short_circuit_empty=False)
        return CheckResult(
            check_name=check_name, verdict=Verdict.UNVERIFIABLE, confidence=0.0,
            rationale=("Retrieval unavailable — all searches failed (infra/outage). "
                       "Cannot rule; candidate deferred for re-vet."),
            queries=queries, query_source=query_source,
            degraded=True, retrieval_failed=True)

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
        audit("verify_search", check=check_name,
              candidate_id=getattr(cand, "candidate_id", None),
              queries=queries, query_source=query_source,
              queries_n=len(queries), n_failed=n_failed,
              passages_n=0, retrieval_failed=False, short_circuit_empty=True)
        return CheckResult(
            check_name=check_name, verdict=Verdict.UNVERIFIABLE,
            confidence=0.0,
            rationale=("No passages retrieved from any search query. "
                       "Downgraded to unverifiable without firing the verdict LLM call."),
            queries=queries, query_source=query_source, degraded=True)

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
            queries=queries, query_source=query_source,
            degraded=True, retrieval_failed=True)
    result.queries = queries
    result.query_source = query_source
    # §25.6 item 2 — deterministic numeric-citation check, SHADOW MODE ONLY (founder
    # decision: it logs, it never changes a verdict). Placed AFTER `result` is complete
    # and its return value DISCARDED, so it is structurally incapable of altering the
    # ruling; `record_shadow` is a no-op unless `numeric_citation.enabled` is true and
    # swallows every exception internally. It audits `result.sources` — the passages the
    # verdict actually cited — truncated to the same VERDICT_PASSAGE_TRUNCATE budget the
    # model saw, which is what makes "this figure was never retrieved" provable offline.
    record_numeric_shadow(cfg, cand, result, truncate=VERDICT_PASSAGE_TRUNCATE)
    logger.info(f"Check {check_name} result: {result.verdict.value}",
                extra={"check": check_name, "verdict": result.verdict.value, "confidence": result.confidence})
    audit("verify_search", check=check_name,
          candidate_id=getattr(cand, "candidate_id", None),
          queries=queries, query_source=query_source,
          queries_n=len(queries), n_failed=n_failed,
          passages_n=len(uniq), retrieval_failed=False, short_circuit_empty=False)
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
                          adversarial_bias=adv_bias,
                          **_market_vars(cfg, for_moat=True))
    try:
        with telemetry_stage("adversarial"):
            data = op.complete_json(system, user, temperature=0.3)
        if isinstance(data, list):
            data = next((x for x in data if isinstance(x, dict)), {}) if data else {}
        if not isinstance(data, dict):
            data = {}
        citations = [str(c) for c in (data.get("citations") or [])]
        # Register §27.2 item 1 — a citation must RESOLVE, not merely exist. The per-check
        # path has filtered against the retrieved source ids since forever (`:443-445`);
        # this path never did, so an adversarial pass could kill a candidate on invented
        # receipts and the guard below would wave it through because the LIST was non-empty.
        # Measured before the fix (tools/experiments/e12_adversarial_groundedness_receipts.json):
        # 8 of 142 adversarial_decisive kills cited ONLY ids resolving to nothing — two of
        # them at our own repo files — and the `partial` class was 0, i.e. no kill mixes
        # resolving and dangling ids, so this filter has never half-stripped a live kill.
        # The checks' sources are exactly what the model was shown (CheckResult.to_dict
        # ships each source_id), so a citable id was always available to it.
        _valid_ids = {s.source_id for c in checks for s in (c.sources or [])}
        _dangling = [c for c in citations if c not in _valid_ids]
        if _dangling:
            logger.warning(
                f"Adversarial cited {len(_dangling)} id(s) resolving to no retrieved "
                f"passage; dropping them",
                extra={"dangling": _dangling[:10], "candidate_id": getattr(cand, "candidate_id", None)})
        citations = [c for c in citations if c in _valid_ids]


        # New risk-sensor model: Python decides, LLM only classifies risk vectors.
        critical_regulatory = bool(data.get("critical_regulatory_blocker", False))
        impossible_economics = bool(data.get("impossible_unit_economics", False))
        incumbent_monopoly = bool(data.get("incumbent_monopoly", False))
        risk_summary = str(data.get("risk_summary", ""))

        # Circuit breaker: only kill on objective brick-wall risks.
        decisive = False
        if critical_regulatory or impossible_economics:
            # Objective, verifiable kill conditions.
            decisive = True
        # If 4+ checks are supported and no legal blocker, survive regardless.
        # "Competitors exist" does not override 4+ supported factual pillars.
        
        if decisive and not citations:
            logger.info("Adversarial claimed decisive with no citations; downgrading")
            decisive = False

        conf = 0.8 if (critical_regulatory or impossible_economics) else 0.2
        if incumbent_monopoly:
            conf = 0.5
            
        return AdversarialResult(
            kill_case=risk_summary or str(data.get("kill_case", "")),
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
    # Scope every fetch in this vet to the active market's authority domains, so a
    # market's own institutions get the patient high-authority timeout instead of being
    # dropped as slow. Context-local, so concurrent vets of different markets can never
    # borrow each other's authority list.
    with market_retrieval(cfg):
        return _verify_inner(op, search, cfg, cand, on_check=on_check, query_op=query_op,
                             skip_adversarial=skip_adversarial, full_vet=full_vet)


def _verify_inner(op: Operator, search: SearchProvider, cfg: Config, cand: Candidate,
                  on_check: Optional[Callable[[CheckResult], None]] = None,
                  query_op: Optional[Operator] = None,
                  skip_adversarial: bool = False,
                  full_vet: bool = False,
                  ) -> tuple[list[CheckResult], Optional[AdversarialResult], Optional[str]]:
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
    # PRICING_CHECK never joins the kill-fast run order, however config names it. It is not
    # a verdict on the idea and the generic verdict prompt would produce a meaningless
    # supported/refuted for it; it runs after the run set survives, via
    # price_comparables.run_price_comparables, and produces anchors instead of a verdict.
    run_order = [c for c in run_order if c != PRICING_CHECK]

    first_failing_gate = None

    # BATCHED LLM query-gen: ONE call decomposes the idea into real-world search queries
    # for the whole run set, replacing the product-restating deterministic templates.
    #
    # RELIABILITY BACKSTOP (2026-06-28): the fast tier (query_op = deepseek→minimax) was
    # timing out for ~2 weeks ("MiniMax read operation timed out → all brains exhausted").
    # When it failed, precomputed_queries stayed empty and EVERY check silently fell back to
    # _templated_queries — word-salad like "postcode-level data flags properties whose VOA
    # durable moat barrier defensibility" — which retrieves junk → ~90% unverifiable → 100%
    # KILL. PROVEN ROOT CAUSE of the zero-yield: a silent soft-fail that ran for days while
    # looking healthy. Fix: any check the fast tier didn't answer is re-generated on the
    # reliable brain `op` BEFORE it can degrade to a template. A search string is NOT a
    # verdict, so using `op` for query-gen does not touch the moat (verdicts still come from
    # `op` reading retrieved passages). The garbage template now fires only if BOTH brains
    # are down — and run_check audits that case so the batch alerts instead of blind-killing.
    precomputed_queries: dict[str, list[str]] = {}
    if getattr(cfg.retrieval, "llm_query_gen", False):
        if query_op is not None:
            precomputed_queries = gen_queries_batched(
                query_op, cand, run_order, n=cfg.retrieval.queries_per_check, cfg=cfg)
        missing = [c for c in run_order if c not in precomputed_queries]
        if missing and op is not None:
            logger.warning(
                "Fast-tier query-gen missed %d/%d checks (%s); recovering on reliable brain "
                "to avoid template fallback", len(missing), len(run_order), ",".join(missing))
            precomputed_queries.update(
                gen_queries_batched(op, cand, missing,
                                    n=cfg.retrieval.queries_per_check, cfg=cfg))

    for idx, name in enumerate(run_order):
        res = run_check(op, search, cfg, cand, name, query_op=query_op,
                        precomputed_queries=precomputed_queries)
        checks.append(res)
        if on_check:
            on_check(res)
        
        # Determine if this gate fired
        gate_fired = False
        if res.retrieval_failed:
            # DEFER on ANY failed retrieval, not just a hard gate's. Restricting this to
            # `name in cfg.gate_map()` was the actual 2026-08-06 fix ("an exception is never
            # evidence; a failed call DEFERs") -- but a lane can declare `score_checks` entries
            # that are NOT its own hard gates (side_hustle's own `hard_gates` replaces the
            # global six, then lists claims_verifiable/payer_solvency/distribution/pain_reality
            # only as score_checks — none of which are in ITS gate_map()). A retrieval outage
            # on one of those checks used to fall through this `and` untouched, land in
            # `checks` as an ordinary `unverifiable, conf 0.0` claim, and feed straight into
            # `score.py` (which has zero references to `retrieval_failed`) — able to drag the
            # composite below `min_composite_to_pass` and KILL on `min_composite`,
            # indistinguishable from a candidate killed on the merits. Same shape as the
            # incident this gate exists to prevent (store/dossiers/2102bacc6dd75cf9.kill.json),
            # surviving for the one class of check the original fix didn't cover. A failed call
            # is not evidence for a score axis any more than it is evidence for a hard gate.
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

        # Soft early-exit: PASS already impossible (same decision as finishing the
        # run then failing source_or_die / moat_ungrounded / min_composite). Does NOT
        # replace hard-gate kill-fast — only fires when no hard fail tripped above.
        #
        # DEFER-safe: never soft-kill when any check already retrieval_failed, and
        # never skip remaining hard gates (a later gate outage must still DEFER).
        # When remaining is empty, only soft-exit if adversarial would still run
        # (otherwise no savings — leave gate=None for golden-set / skip_adversarial).
        if not full_vet and first_failing_gate not in (DEFER_GATE, "moat_exhausted"):
            from .pass_ceiling import pass_impossible_reason
            remaining = list(run_order[idx + 1:])
            gate_names = cfg.gate_map()
            remaining_hard = [n for n in remaining if n in gate_names]
            infra_failed = any(getattr(c, "retrieval_failed", False) for c in checks)
            saves_work = bool(remaining) or not skip_adversarial
            if not infra_failed and not remaining_hard and saves_work:
                soft = pass_impossible_reason(checks, remaining, cfg)
                if soft:
                    checks_run = len(checks)
                    checks_skipped = len(remaining)
                    logger.info(
                        f"Soft early-exit: PASS impossible ({soft}) after {name}; "
                        f"checks_run={checks_run} checks_skipped_soft_exit={checks_skipped}",
                        extra={
                            "gate": soft,
                            "after_check": name,
                            "checks_run": checks_run,
                            "checks_skipped_soft_exit": checks_skipped,
                            "skipped_checks": remaining,
                        },
                    )
                    audit(
                        "soft_early_exit",
                        candidate_id=getattr(cand, "candidate_id", None),
                        gate=soft,
                        after_check=name,
                        checks_run=checks_run,
                        checks_skipped_soft_exit=checks_skipped,
                        skipped_checks=remaining,
                    )
                    if getattr(cand, "tags", None) is not None:
                        cand.tags["verify_throughput"] = {
                            "checks_run": checks_run,
                            "checks_skipped_soft_exit": checks_skipped,
                            "soft_exit_gate": soft,
                            "after_check": name,
                        }
                    return checks, None, soft

    # C3 — price_comparables. Runs ONLY on a candidate that survived every hard gate: a
    # killed idea is never priced, so anchoring one is spend with no consumer. Its output
    # is evidence, never a verdict, so it is attached to the candidate rather than appended
    # to `checks` — putting it in `checks` would let it reach kill_filter/apply_gates and
    # the pass-ceiling logic, none of which should ever see it.
    #
    # `skip_adversarial` is the golden-set harness isolating the six-check logic
    # (see the docstring above); anchors are not part of that contract, so skip the spend.
    if (first_failing_gate is None and not skip_adversarial
            and getattr(cand, "tags", None) is not None):
        from .price_comparables import comparables_config, run_price_comparables
        if comparables_config(cfg)["enabled"]:
            try:
                pooled = [s for c in checks for s in (c.sources or [])]
                comps = run_price_comparables(op, search, cfg, cand,
                                              pooled_sources=pooled)
                cand.tags["price_comparables"] = comps.to_dict()
            except GroundingInfrastructureError:
                raise  # all retrieval providers dead — halt the run, same as a check
            except Exception as e:
                # Evidence-only: a failure here must never change the verdict on the idea.
                logger.error(f"price_comparables step failed (continuing unpriced): {e}",
                             extra={"candidate_id": getattr(cand, "candidate_id", None)})

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
