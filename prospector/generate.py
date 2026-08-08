"""Generate raw opportunity candidates from a signal (Part 3).

Nothing here judges or drops candidates on quality — that is Part 3's explicit
contract. Only structurally-invalid JSON elements are skipped.
"""
from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

from .config import Config
from .coverage import plan_cells
from .landscape import incumbent_brief
from .models import Candidate
from .operator import Operator
from .prompts import ALL_MARKET_KEYS, market_kwargs, render
from .sampling import typicality_directive, typicality_score
from .telemetry import logger, track_latency
from .telemetry import stage as telemetry_stage


def _parse_candidates(data: Any) -> list[Candidate]:
    """Coerce a model response (bare list or wrapper dict) into Candidates.

    Never kills on quality — only skips elements that cannot be parsed as a dict
    with at least a 'title' key (structural invalidity only).
    """
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        for key in ("opportunities", "candidates", "results", "items"):
            if isinstance(data.get(key), list):
                raw_list = data[key]
                break
        else:
            raw_list = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        raw_list = []

    out: list[Candidate] = []
    for item in raw_list:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        try:
            cand = Candidate.from_dict(item)
        except Exception:
            continue
        # G4: carry the model's self-reported typicality into tags so the diversity meter
        # (prospector/diversity.py) can measure whether the Verbalized Sampling directive
        # actually moved the batch off its mode. setdefault, never overwrite: a value the
        # model already put in its own `tags` dict wins. This is observability only — no
        # candidate is ever dropped, reordered or down-weighted for its typicality.
        t = typicality_score(item.get("typicality"))
        if t is not None and isinstance(cand.tags, dict):
            cand.tags.setdefault("typicality", t)
        out.append(cand)
    return out


def _norm_title(t: str) -> str:
    return " ".join(str(t).lower().split())


# Word → score map for self-reported automatability (the model emits a number OR a word).
_AUTOMATABILITY_WORDS: dict[str, float] = {
    "none": 0.0, "manual": 0.1, "very low": 0.1, "low": 0.25, "med": 0.5,
    "medium": 0.5, "moderate": 0.5, "high": 0.85, "very high": 0.95,
    "full": 1.0, "fully": 1.0, "fully automated": 1.0, "complete": 1.0,
    "autonomous": 1.0,
}


def _automatability_score(val: Any) -> Optional[float]:
    """Coerce a self-reported automatability value to a float in [0, 1], or None if
    it cannot be parsed. Tolerant of the schema being loosely specified: accepts a
    0-1 float, a 0-100 number/percentage, or a word ('high', 'fully automated', ...).
    None is returned for missing/unintelligible values so the caller decides policy."""
    if val is None or isinstance(val, bool):
        return None if val is None else (1.0 if val else 0.0)
    if isinstance(val, (int, float)):
        f = float(val)
        return max(0.0, min(1.0, f / 100.0 if f > 1.0 else f))
    s = str(val).strip().lower()
    if not s:
        return None
    if s.endswith("%"):
        s = s[:-1].strip()
    if s in _AUTOMATABILITY_WORDS:
        return _AUTOMATABILITY_WORDS[s]
    try:
        f = float(s)
        return max(0.0, min(1.0, f / 100.0 if f > 1.0 else f))
    except ValueError:
        for word, score in _AUTOMATABILITY_WORDS.items():
            if word in s:
                return score
        return None


# Audience persona descriptions injected into generate.md. Each description names a
# SPECIFIC person (age range, life situation, daily pains, spend profile, budget
# authority) so the model produces ideas aimed at a real buyer rather than a
# generic "B2B" frame. Module-level so the dict is importable for the persona-
# completeness regression test; contents are static (no runtime deps).
_AUDIENCE_DESCRIPTIONS: dict[str, str] = {
    "retiree_cohort":
        "A person aged 60-75, recently retired or approaching retirement. Has accumulated "
        "assets (pension pot, property) but irregular income. Feels: health anxiety, "
        "loneliness, desire to pass wealth on, digital exclusion. Spends on: healthcare, "
        "leisure, gifting, inheritance planning. Has budget authority over their own finances "
        "and often adult children's finances too.",
    "gen_z_worker":
        "A person aged 18-27, in casualised or gig work (rideshare, delivery, freelance). "
        "No pension, no savings buffer, income volatile week-to-week. Feels: instability, "
        "exclusion from mainstream financial products, time-poverty. Spends on: transport, "
        "housing, food. Has budget authority over a very tight monthly balance.",
    "smb_owner":
        "A person running a business with 1-20 employees, often themselves as the primary "
        "worker. Handles finance, sales, operations, HR simultaneously. Feels: cash-flow "
        "stress, admin overwhelm, competitive pressure. Spends on: software subscriptions, "
        "staff, supplies. Has budget authority but every pound is scrutinised.",
    "primary_carer":
        "A person (any age) who is the main carer for young children, elderly parents, or "
        "disabled relatives. Has fragmented work history and reduced earning capacity. Feels: "
        "time-poverty, guilt, isolation, financial precarity. Spends on: childcare, care "
        "products, respite services. Budget is constrained but decisions are high-stakes.",
    "manual_tradesperson":
        "A person aged 25-55 working in construction, plumbing, electrical, logistics, or "
        "hospitality. Physically skilled, time-poor, digitally underserved. Feels: "
        "admin burden eating into earning time, unfair tax treatment, physical risk. "
        "Spends on: tools, transport, training, insurance. Budget authority over "
        "business purchases, personal spending is disciplined.",
    "public_sector_worker":
        "A person aged 30-60 employed in the NHS, a school, local government, or the "
        "civil service. Stable income, defined pension, but pay is capped and conditions "
        "are tightening. Feels: workload pressure, frustration with under-resourcing, "
        "desire for side income. Spends on: housing, childcare, transport. Has budget "
        "authority within a constrained household.",
    "freelancer_creative":
        "A person aged 25-45 working as a designer, writer, developer, consultant, or "
        "creative professional. Income is project-based and lumpy. Feels: client "
        "management burden, feast-or-famine anxiety, desire for predictability. Spends on: "
        "software, subscriptions, professional development. Has budget authority over "
        "discretionary spend but is price-sensitive on subscriptions.",
    "squeezed_middle":
        "A person aged 35-55 with a professional career, mortgage, and children. "
        "Appears affluent on paper (property, pension) but cash-poor in the short term. "
        "Feels: the pinch between fixed costs and aspirational spending, complexity of "
        "financial decisions. Spends on: mortgage, school fees, healthcare, elder care. "
        "Budget authority is shared with a partner; decisions are deliberated.",
    "startup_operator":
        "an early-stage startup founder-operator wearing every hat, who pays for anything that removes a bottleneck to revenue, compliance or fundraising without hiring",
    "software_developer":
        "a professional software developer or indie hacker who buys tools, data and infrastructure that save engineering time or unlock a paid capability, and is allergic to fluff",
    "agency_owner":
        "the owner of a small client-services agency (marketing, dev, design) who buys leverage: anything that raises billable margin, wins retainers or de-risks client delivery",
    "ops_manager":
        "an operations manager inside a small or mid-sized firm who owns messy cross-system processes and has budget for tools that kill manual work, errors and audit risk",
    "ecommerce_seller":
        "an online-store operator (Shopify, Amazon, eBay) who pays for anything that raises conversion, cuts fulfilment or returns cost, or defends against platform policy shifts",
}


@track_latency(name="generate")
def generate(
    op: Operator,
    cfg: Config,
    signal_text: str = "",
    sector: str = "",
    strategy_lens: str = "broaden",
    exploration_level: float = 0.5,
    target_qualities: str | None = None,
    recent_failure_modes: str | None = None,
    k: int | None = None,
    *,
    gen_op: Optional[Operator] = None,
    grid_priorities: Optional[list[str]] = None,
    focus: str | None = None,
    pass_patterns: str = "",
    prior_titles: Optional[list[str]] = None,
) -> list[Candidate]:
    """Generate k raw Candidate opportunities from a signal.

    gen_op: optional separate operator for generation.  When set (e.g. MiniMax),
    generation calls go through gen_op while verification uses op (Claude/Gemini).
    This allows cheaper models for generation without touching the verification moat.
    Defaults to op when unset.  Never kills on quality — only skips elements
    that cannot be parsed as a dict with at least a 'title' key.
    """
    gen_cfg: dict[str, Any] = cfg.generation

    if k is None:
        k = gen_cfg.get("candidates_per_signal", 20)

    if target_qualities is None:
        controller: dict[str, Any] = gen_cfg.get("controller", {})
        qualities: list[str] = controller.get("target_qualities", [])
        target_qualities = ", ".join(str(q) for q in qualities)

    if recent_failure_modes is None:
        recent_failure_modes = ""

    # CROSS-RUN MEMORY (anti-duplication). Without this, `avoid` is rebuilt from scratch each
    # run from only the current run's candidates, so the blue-sky daemon regenerates the same
    # idea families (e.g. probate clear-out) every wave. We seed the avoid list with titles the
    # engine has ALREADY produced (kills included — a repeatedly-killed idea is exactly what we
    # must stop re-proposing). Bounded to the freshest ~120 to keep the prompt small.
    _prior = [t.strip() for t in (prior_titles or []) if t and t.strip()]
    # de-dup preserving order, then cap
    _seen_prior: set[str] = set()
    _prior_unique: list[str] = []
    for _t in _prior:
        key = _t.lower()
        if key not in _seen_prior:
            _seen_prior.add(key)
            _prior_unique.append(_t)
    _prior_avoid = _prior_unique[:120]

    # Models under-deliver on one large "give me k ideas" call, so we batch — but
    # batching SEQUENTIALLY (each round waiting on the prior round's avoid-list) made
    # one slow/retrying LLM call stall the whole chain (3+ min/round = not practical).
    # Instead we fan out a WAVE of independent calls CONCURRENTLY, each owning a
    # distinct creativity lens so they diverge by construction (minimal overlap to
    # dedup). A slow call no longer blocks its siblings. Cross-wave avoid-lists keep
    # later waves diverging from what's already in hand. Physical load stays bounded by
    # the CLI concurrency semaphores; a dry-guard stops us if the model is tapped out.
    target = k
    max_per_call = int(gen_cfg.get("max_per_call", 10) or 10)
    max_rounds = int(gen_cfg.get("max_rounds", 6) or 6)  # now a cap on WAVES
    lenses = [item.strip() for item in str(strategy_lens).split(",") if item.strip()] or ["broaden"]

    # PRIMARY diversity axis = the structural business FORM (not the creativity lens).
    # Lenses vary the angle of attack but every angle on a regulatory signal collapsed
    # onto the same "central data/rating/registry utility" shape. Each parallel call now
    # owns a DISTINCT form, so that dead shape is at most one cell of many. The operator
    # archetype's binding constraints are folded into every call so infeasible shapes
    # (rating agency, registry, capital-heavy plays) are never proposed in the first place.
    forms = [str(f).strip() for f in (gen_cfg.get("structural_forms") or []) if str(f).strip()]

    # SECONDARY diversity axis = the AUDIENCE PERSONA (the buyer). Together with forms this
    # creates an NxM diversity matrix (default 8x8=64 cells), breaking the B2B-institutional
    # monoculture that drives the value_durability kill wall. Each parallel call owns a
    # distinct form x audience cell. Descriptions are specific: named person, age range,
    # pain felt daily, budget authority.
    audience_forms = [str(a).strip() for a in (gen_cfg.get("audience_forms") or []) if str(a).strip()]

    arche = str(gen_cfg.get("operator_archetype", "")).strip()
    arche_cfg = (gen_cfg.get("archetypes") or {}).get(arche, {}) if arche else {}
    operator_constraints = " ".join(
        s for s in (str(arche_cfg.get("binding", "")).strip(),
                    str(arche_cfg.get("forbid", "")).strip()) if s)

    # Lane-aware generation framing. For a cheaper lane (e.g. side_hustle) this OVERRIDES
    # the venture moat language in generate_system.md — it tells the model to produce £30
    # info-product pack niches judged on demand + deliverability, not durable defensibility.
    # Empty for venture/default => the prompt renders byte-for-byte as today (golden-safe).
    lane_directive = str(gen_cfg.get("lane_directive", "") or "")

    # Targeted FOCUS directive (Part 16). A free-text steer ("online, fully-automated, acute
    # pain, makes money directly online") that biases WHAT KIND of idea every call produces.
    # Source precedence: the explicit `focus` arg (CLI --focus) overrides the active profile's
    # `generation.focus`. Empty => the prompt renders byte-for-byte as today (golden-safe).
    focus_text = focus if focus is not None else str(gen_cfg.get("focus", "") or "")
    focus_text = focus_text.strip()
    focus_directive = (
        "TARGETING CONSTRAINT (binding for THIS run — every idea MUST satisfy it; "
        f"an idea that does not fit is INVALID, do not propose it): {focus_text}"
        if focus_text else "")

    # Automatability HARD FLOOR (Part 16). Optional, opt-in: a profile (or config) may set
    # `generation.automatability_floor` to a 0-1 minimum. When set, candidates whose self-
    # reported automatability falls below it (or is unintelligible) are dropped at generation
    # time — turning "no human in the loop" from a soft prompt aim into a guarantee. Unset =>
    # None => no filtering, byte-for-byte today's behaviour (golden-safe). This is a generation
    # filter, never a verdict gate: it shapes the candidate pool, it does not judge truth.
    _floor_raw = gen_cfg.get("automatability_floor")
    automatability_floor: Optional[float] = (
        float(_floor_raw) if _floor_raw is not None else None)

    # The jurisdiction this run generates for (Epic D). Empty when no markets are
    # configured => candidates carry no market => byte-for-byte pre-Epic-D behaviour.
    try:
        run_market = cfg.active_market or cfg.default_market
        market_vars = market_kwargs(cfg)
    except AttributeError:  # a Config built before Epic D (e.g. a stubbed test double)
        run_market = ""
        market_vars = {k: "" for k in ALL_MARKET_KEYS}

    # G2 + G4 are appended to the RENDERED user prompt rather than added as {placeholders} in
    # prompts/generate.md, and that is deliberate: prompts.render() does not raise on an
    # unsubstituted token (prompts.py:194 only logs, and only for `{market_`), so a new
    # placeholder would be shipped to the model VERBATIM by the two call sites that do not pass
    # it — run.py:2039 and tests/unit/test_moat_discipline.py:44. Appending in Python is
    # golden-safe by construction: both helpers return "" when their gate is off, and an empty
    # suffix leaves the prompt byte-identical to today. Same pattern as the OUTPUT CONTRACT
    # prefix below.
    #
    # The sampling directive is a pure function of (cfg, k), so it is resolved once here. The
    # landscape brief is NOT, and that is the whole reason it moved: on the blue-sky path the
    # AUDIENCE PERSONA is the only topic available, and `_assign` rotates it call by call. The
    # daemon is that path — `scheduler/run_scheduled.py:724` calls `run_signal("", cfg=cfg,
    # k=batch_size, publish=True, lanes=lanes)` with an empty signal — so resolving the brief
    # once per generate() would have left the feature inert on the majority of all generation.
    # It costs nothing extra when a signal or sector IS present: every call then derives the
    # same topic and hits the same cache entry after the first fetch.
    sampling_directive = typicality_directive(cfg, k)

    # V2 COVERAGE SAMPLER (default OFF — `coverage_sampler.enabled: false`). When enabled it
    # replaces the round-robin form x audience rotation below with cells chosen from the
    # MEASURED under-coverage of store/prospector.db (read-only, zero LLM calls, deterministic
    # on seed). It returns [] when disabled, when the index is missing, when every axis is
    # suppressed by min_coverage, or on any error — so with the flag off, and whenever the
    # sampler cannot speak, generation behaves byte-for-byte as it does today.
    coverage_cells: list[dict[str, str]] = plan_cells(
        cfg, k,
        domains={"structural_form": forms, "audience": audience_forms},
        context={"market": run_market} if run_market else None,
    )

    # Audience forms loaded and rotated AFTER structural forms so both are ready here.
    logger.info("Generation started", extra={
        "sector": sector,
        "lens": strategy_lens,
        "exploration": exploration_level,
        "k": k,
        "forms": forms,
        "audiences": audience_forms,
    })

    # FIX #5: seed and avoid are now template variables in generate.md (user section).
    # The static taxonomy/lens/rules live in generate_system.md and are cached by the
    # model.  This cuts per-call tokens from ~2,500 to ~600 — a ~75% reduction.
    def _one_call(form: str, lens: str, audience: str, ask: int,
                   avoid: str, seed: str) -> list[Candidate]:
        # Persona bias (Part 16 principal upgrade)
        persona = cfg.personas.get(cfg.active_persona) or {}
        gen_bias = persona.get("generation_bias", "")

        # Audience persona description for the prompt.
        aud_desc = _AUDIENCE_DESCRIPTIONS.get(audience, audience)
        system, user = render(
            "generate", signal_text=signal_text, sector=sector, strategy_lens=lens,
            structural_form=form or "any feasible form", operator_constraints=operator_constraints,
            exploration_level=exploration_level, target_qualities=target_qualities,
            recent_failure_modes=recent_failure_modes, k=ask,
            avoid=(avoid or "(none so far — propose freely)"),
            seed=seed,
            audience_persona=audience,
            audience_description=aud_desc,
            lane_directive=lane_directive,
            focus_directive=focus_directive,
            generation_bias=gen_bias,
            pass_patterns=pass_patterns,
            **market_vars)
        # EXECUTION DIRECTIVE (generation-scoped, provider-agnostic). Without it, claude_cli —
        # now the generation PRIMARY (proven reliable 2026-07-02: 3/3 clean JSON vs MiniMax M3's
        # non-deterministic 7/8-then-0/6) — treats the flattened prompt as a conversational turn
        # and replies with meta-commentary ("I don't see a clear request … the Prospector engine's
        # own prompt") instead of candidates. Framing it as a literal task with a JSON-only output
        # contract fixes that, and also tightens MiniMax/other providers toward parseable output.
        # This does NOT touch the moat/verdict prompt path — it is applied only here in generation.
        system = (
            "OUTPUT CONTRACT — READ FIRST: Execute the generation task below LITERALLY. You are the "
            "generation engine, not a commentator. Do NOT describe, evaluate, or acknowledge this "
            "prompt. Return ONLY the JSON specified by the task — no preamble, no prose, no "
            "meta-discussion, no code fences.\n\n" + system
        )
        # Resolved per call so the blue-sky path can fall back to this cell's audience persona
        # as the topic (landscape._topic rung 3). Cached on (topic, market), so the repeated
        # calls that share a topic pay one fetch between them, not one each.
        landscape_directive = incumbent_brief(
            cfg, signal_text=signal_text, sector=sector, market=run_market,
            audience=audience)
        # Order matters: the landscape is context the model should read before it is told HOW
        # to sample, so it lands first.
        for _extra in (landscape_directive, sampling_directive):
            if _extra:
                user = f"{user}\n\n{_extra}"
        # gen_op is the non-critical generation chain (claude_cli primary → minimax tail); falls
        # back to the moat op only if no gen chain was wired.
        _gen = gen_op or op
        try:
            with telemetry_stage("generate"):
                raw_response = _gen.complete_json(system, user, temperature=0.9)
            cands = _parse_candidates(raw_response)
        except Exception as e:
            logger.error(f"Generation batch {seed} failed: {e}", extra={"error": str(e)})
            return []
            
        if form:
            for c in cands:
                # Categorical field (survives asdict() into the dossier), not a boolean tag.
                c.structural_form = form
        # Stamp the jurisdiction the run is generating for, BEFORE dedup so market-scoped
        # dedup (dedup.py) can tell "same idea, different market" from a real duplicate.
        # Setting it here also fixes the candidate_id derivation (models.Candidate) at
        # construction time rather than after a dossier already references the old id.
        if run_market:
            for c in cands:
                if not c.market:
                    c.market = run_market
        return cands

    def _refine_wave(candidates: list[Candidate], _gen: Operator, lane_directive: str) -> list[Candidate]:
        """Sharpen and filter candidates using a cynical analyst persona. 
        Cost Optimization: refined in a single batch per wave.
        Skips structurally-thin candidates (title+one_liner < 50 chars) —
        refinement won't help them survive the moat.
        """
        if not candidates or not gen_cfg.get("refinement_enabled", True):
            return candidates

        # Split: thin candidates return unchanged (refinement can't help them),
        # substantive candidates get the LLM refinement pass.
        thin: list[Candidate] = []
        substantive: list[Candidate] = []
        for c in candidates:
            text_len = len(str(c.title or "")) + len(str(c.one_liner or ""))
            if text_len < 50:
                thin.append(c)
            else:
                substantive.append(c)

        if not substantive:
            return thin

        cands_data = [c.to_dict() for c in substantive]
        system, user = render(
            "refine", 
            candidates_json=json.dumps(cands_data, indent=2),
            lane_directive=lane_directive
        )
        
        # Use a slightly lower temperature for refinement to encourage strictness.
        # HARD INVARIANT (2026-07-02): refinement may SHARPEN a candidate but must NEVER
        # reduce the set — generation-time dropping is forbidden (all kills are grounded &
        # downstream). Every substantive candidate leaves this function, refined-if-possible,
        # unrefined otherwise. The prior code dropped any candidate whose title the refiner
        # reworded (exact-title remap miss) and wiped the whole wave on a dict-wrapped response
        # (isinstance(list) else []) — the PROVEN zero-yield bug.
        try:
            with telemetry_stage("generate"):
                raw_response = _gen.complete_json(system, user, temperature=0.5)
            # Tolerant unwrap: accept a bare list OR a wrapper dict (same shapes as
            # _parse_candidates), never collapse a wrapped array to [].
            if isinstance(raw_response, list):
                refined_data = raw_response
            elif isinstance(raw_response, dict):
                refined_data = next(
                    (raw_response[k] for k in ("opportunities", "candidates", "results", "items")
                     if isinstance(raw_response.get(k), list)),
                    next((v for v in raw_response.values() if isinstance(v, list)), []))
            else:
                refined_data = []

            original_by_title = {c.title: c for c in substantive}
            refined_out: list[Candidate] = []
            # Positional fallback: the refiner emits items in input order, so an item whose
            # title was reworded (no exact match) is mapped to the next unconsumed original.
            unconsumed = list(substantive)
            for r_dict in refined_data:
                if not isinstance(r_dict, dict) or not r_dict.get("title"):
                    continue
                orig = original_by_title.get(r_dict.get("title"))
                if orig is None and unconsumed:
                    orig = unconsumed[0]  # positional map for a reworded title
                if orig is None:
                    continue
                try:
                    r_cand = Candidate.from_dict(r_dict)
                except Exception:
                    continue  # orig stays in `unconsumed` → survives unrefined below
                # Consume only AFTER a successful refine, so a bad refine dict can never
                # cost the original its place in the survivors.
                if orig in unconsumed:
                    unconsumed.remove(orig)
                r_cand.structural_form = orig.structural_form
                r_cand.ambition_tier = orig.ambition_tier
                r_cand.refinement_history = orig.refinement_history + [{
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": "refined",
                    "model": _gen.name,
                    "before": {"title": orig.title, "one_liner": orig.one_liner,
                               "hypothesis": orig.hypothesis, "who_pays": orig.who_pays,
                               "why_now": orig.why_now},
                }]
                refined_out.append(r_cand)

            # Non-lossy guarantee: every original the refiner did not successfully return
            # survives UNREFINED. Identity-based (`unconsumed`), not title-based, so two
            # originals sharing a title can never shadow each other out of the wave.
            survivors = refined_out + unconsumed
            return thin + survivors
        except Exception as e:
            logger.warning(f"Refinement wave failed: {e}")
            return thin + substantive  # Fallback: thin + unrefined substantive

    candidates: list[Candidate] = []
    seen: set[str] = set()
    seen_forms: set[str] = set()
    dry_rounds = 0

    # Audience rotation base. The audience axis MUST advance off the same global call
    # ordinal as the form axis (offset + i), NOT the per-wave index i — otherwise every
    # backfill wave (n_calls==1) and every fresh invocation restarts at index 0 and the
    # whole catalogue collapses onto audience_forms[0] (observed: 22/25 dossiers pinned to
    # 'retiree_cohort'). We also seed the start from the signal so different signals begin
    # at different personas, breaking the cross-run bias toward the first persona.
    _seed_src = (signal_text or sector or "").encode("utf-8")
    aud_base = int(hashlib.sha1(_seed_src).hexdigest(), 16) if audience_forms else 0

    for wave in range(1, max_rounds + 1):
        if len(candidates) >= target:
            break
        remaining = target - len(candidates)
        axis = forms or lenses
        # One call per DISTINCT form (capped at the form count), enough to cover the
        # remainder. Each call asks for a small share so it stays anchored to its form.
        n_calls = max(1, min(len(axis), max(remaining, len(lenses))))
        ask = max(1, min(max_per_call, math.ceil(remaining / n_calls)))
        # Avoid = cross-run memory (prior catalogue/kills) + this run's candidates so far.
        # Both axes matter: prior_avoid stops re-proposing old families across runs; the
        # in-run tail stops collapse within this run.
        _avoid_parts = _prior_avoid + [c.title for c in candidates[-40:]]
        avoid = "; ".join(_avoid_parts) if _avoid_parts else ""
        # Rotate the form window each wave so later waves try forms earlier waves skipped.
        offset = (wave - 1) * n_calls

        def _assign(i: int) -> tuple[str, str, str]:
            # Rotate forms and audience personas across the GLOBAL call ordinal (offset + i),
            # not the per-wave index, so both axes keep advancing through backfill waves and
            # across invocations instead of resetting to index 0 every time.
            g = offset + i
            form = forms[g % len(forms)] if forms else ""
            lens = lenses[i % len(lenses)]
            if audience_forms:
                A = len(audience_forms)
                # Decorrelate the audience from the form: forms and audiences are both length
                # ~8, so a plain `g % A` would lock the pair to the diagonal (8 of 64 cells).
                # Adding g // len(forms) shifts the persona by one each time the form list
                # wraps, sweeping the full form x audience matrix over successive calls.
                aud = audience_forms[(aud_base + g + (g // len(forms))) % A]
            else:
                aud = ""
            # V2: when the coverage sampler is on it OWNS the (form, audience) cell — the
            # rotation above is the fallback for axes the sampler suppressed or has no
            # domain for. Empty list (the default) => rotation, unchanged.
            if coverage_cells:
                cell = coverage_cells[g % len(coverage_cells)]
                form = cell.get("structural_form") or form
                aud = cell.get("audience") or aud
            return form, lens, aud

        def _fan_out(indices: range) -> list[tuple[str, str, list[Candidate]]]:
            # Cap concurrency at 4: 8 simultaneous MiniMax calls drove server-side latency into
            # 240s read-timeouts (proven 2026-07-01: 8 timeouts in one k=8 run). Fewer in-flight
            # calls trade a little wall-clock for far fewer timeouts. ex.map still processes every
            # index; only the number running at once is bounded.
            with ThreadPoolExecutor(max_workers=min(4, max(1, len(indices)))) as ex:
                def _go(i: int) -> tuple[str, str, list[Candidate]]:
                    form, lens, aud = _assign(i)
                    return form, aud, _one_call(form, lens, aud, ask, avoid, f"{wave}.{i + 1}")
                return list(ex.map(_go, indices))

        # L4 canary: on the FIRST wave, make one call alone before fanning out the rest.
        # If the active brain is exhausted this single call trips its breaker / marks it
        # dead (health.py), so the remaining calls — and every later wave — SKIP it for
        # free instead of N concurrent calls each paying the full failover timeout.
        if wave == 1 and n_calls > 1:
            f0, l0, a0 = _assign(0)
            batches = [(f0, a0, _one_call(f0, l0, a0, ask, avoid, f"{wave}.1"))]
            batches += _fan_out(range(1, n_calls))
        else:
            batches = _fan_out(range(n_calls))

        # --- ML Optimization: Wave-level Refinement ---
        # Collect all candidates from the wave and refine them in ONE call.
        # This reduces refinement cost from N calls to 1 call per wave.
        raw_wave_cands = []
        for _, _, clist in batches:
            raw_wave_cands.extend(clist)
        
        # FIX: gen_op for generation, else fall back to op.
        _gen = gen_op or op
        refined_wave_cands = _refine_wave(raw_wave_cands, _gen, lane_directive)

        # Automatability hard floor (opt-in): drop wave candidates below the configured
        # minimum so later waves backfill toward `target` with only automatable ideas.
        # A candidate with a missing/unintelligible automatability is dropped too — a
        # "no human in the loop" guarantee cannot be made for an unknown.
        if automatability_floor is not None:
            kept = []
            for c in refined_wave_cands:
                sc = _automatability_score(c.automatability)
                if sc is not None and sc >= automatability_floor:
                    kept.append(c)
            dropped = len(refined_wave_cands) - len(kept)
            if dropped:
                logger.info(
                    f"Automatability floor {automatability_floor:.2f}: dropped {dropped} "
                    f"of {len(refined_wave_cands)} wave candidate(s)",
                    extra={"floor": automatability_floor, "dropped": dropped})
            refined_wave_cands = kept

        # Re-batch the refined candidates for the diversity loop
        # We preserve the (form, aud) grouping by re-distributing refined cands.
        refined_batches = []
        for form, aud, _ in batches:
            # All candidates for this form/aud that survived refinement
            form_cands = [c for c in refined_wave_cands if c.structural_form == form]
            refined_batches.append((form, aud, form_cands))

        # Anti-collapse dedup: pass 1 accepts at most ONE idea per UNUSED form
        # (maximise structural diversity); pass 2 backfills seconds only if still short.
        added = 0
        for diversity_pass in (True, False):
            for form, aud, clist in refined_batches:
                for c in clist:
                    key = _norm_title(c.title)
                    if key in seen:
                        continue
                    if diversity_pass and form and form in seen_forms:
                        continue
                    seen.add(key)
                    if form:
                        seen_forms.add(form)
                    # Persist audience persona into the candidate's tags for audit.
                    if aud:
                        c.tags["audience"] = aud
                    candidates.append(c)
                    added += 1
                    if len(candidates) >= target:
                        break
                if len(candidates) >= target:
                    break
            if len(candidates) >= target:
                break

        logger.info(
            f"Generation wave {wave}: +{added} (total {len(candidates)}/{target}) "
            f"[{n_calls} parallel calls, forms={len(seen_forms)}]",
            extra={"wave": wave, "added": added, "total": len(candidates), "calls": n_calls})
        if added == 0:
            dry_rounds += 1
            if dry_rounds >= 2:
                logger.warning("Generation dry: no new candidates two waves running")
                break
        else:
            dry_rounds = 0

    candidates = candidates[:target]
    logger.info(f"Generated {len(candidates)} candidates", extra={"count": len(candidates)})
    return candidates


def generate_multilane(
    op: Operator,
    cfg: Config,
    *,
    lanes: list[str],
    lane_counts: dict[str, int] | None = None,
    signal_text: str = "",
    sector: str = "",
    strategy_lens: str = "broaden",
    exploration_level: float = 0.5,
    target_qualities: str | None = None,
    recent_failure_modes: str | None = None,
    gen_op: Optional[Operator] = None,
    grid_priorities: Optional[dict[str, list[str]]] = None,
    focus: str | None = None,
    pass_patterns: str = "",
    prior_titles: Optional[list[str]] = None,
) -> list[Candidate]:
    """Fan generation OUT across ambition lanes for a mixed-ambition catalogue (Part 14).

    For each tier in `lanes`, resolve `cfg.for_lane(tier)` (which swaps in that lane's
    generation framing — e.g. side-hustle-scale opportunities vs venture moats) and ask for
    `lane_counts[tier]` candidates, tagging each result with `ambition_tier=tier`. The same
    shared machinery (the `generate` divergence engine) runs underneath every lane; only the
    framing and quota differ. Returns the concatenated, tier-tagged candidate list. Generation
    still judges nothing — the per-tier moat downstream does that.
    """
    # Lanes run CONCURRENTLY. They were sequential until 2026-07-31, which cost a full
    # multiple of the slowest lane for no gate strength: measured `generate` p50 280.9s /
    # max 654.0s (n=5), so a 4-lane run spent ~19 min in generation before vetting saw a
    # single candidate — the dominant term in the 1731s failure of job 20260730T212901866.
    #
    # What sequencing actually bought, and why losing it is safe: the old code threaded
    # `[c.title for c in out]` into each later lane's `prior_titles` so a lane could see
    # what earlier lanes had just minted. That is a SOFT prompt hint, not a gate. The HARD
    # gate is `dedup()` (dedup.py:113 — "every candidate already accepted in this batch, in
    # the same market"), which runs on the concatenated batch in run.py immediately after
    # this returns and applies both signals (char ratio + content-word Jaccard at 0.34,
    # calibrated for same-idea-reworded). So no cross-lane duplicate can ship either way;
    # dropping the hint can only cost some wasted generation, never catalogue quality.
    # Cross-RUN memory (`prior_titles`, the last 200 catalogue titles) is still passed to
    # every lane in full — that is the echo suppression that actually carries weight.
    #
    # Lanes are independent by construction: each gets its own `cfg.for_lane(tier)` and
    # writes only to its own result slot, so there is no shared mutable state to race.
    # Order is reconstructed from `lanes` so the returned list stays deterministic.
    lane_list = list(lanes)
    results: dict[str, list[Candidate]] = {}

    def _run_lane(tier: str) -> tuple[str, list[Candidate]]:
        lane_cfg = cfg.for_lane(tier)
        k = (lane_counts or {}).get(tier)
        # ML Improvement: Grid Scheduler (Stage 3)
        priorities = (grid_priorities or {}).get(tier)
        cands = generate(
            op, lane_cfg, signal_text=signal_text, sector=sector,
            strategy_lens=strategy_lens, exploration_level=exploration_level,
            target_qualities=target_qualities, recent_failure_modes=recent_failure_modes,
            k=k, gen_op=gen_op, grid_priorities=priorities, focus=focus,
            pass_patterns=pass_patterns, prior_titles=list(prior_titles or []))
        for c in cands:
            c.ambition_tier = tier
        return tier, cands

    with ThreadPoolExecutor(max_workers=max(1, len(lane_list))) as pool:
        futures = {pool.submit(_run_lane, t): t for t in lane_list}
        for fut in as_completed(futures):
            tier = futures[fut]
            try:
                tier, cands = fut.result()
            except Exception as e:  # noqa: BLE001 — one lane failing must not void the rest
                logger.warning(f"Lane {tier!r} generation failed: {e}",
                               extra={"lane": tier})
                cands = []
            results[tier] = cands
            logger.info(f"Lane {tier!r}: generated {len(cands)} candidate(s)",
                        extra={"lane": tier, "count": len(cands)})

    out: list[Candidate] = []
    for tier in lane_list:
        out.extend(results.get(tier, []))
    return out
