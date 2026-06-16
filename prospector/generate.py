"""Generate raw opportunity candidates from a signal (Part 3).

Nothing here judges or drops candidates on quality — that is Part 3's explicit
contract. Only structurally-invalid JSON elements are skipped.
"""
from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional

from .config import Config
from .models import Candidate
from .operator import Operator
from .prompts import render
from .telemetry import logger, track_latency


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
            out.append(Candidate.from_dict(item))
        except Exception:
            continue
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
    lenses = [l.strip() for l in str(strategy_lens).split(",") if l.strip()] or ["broaden"]

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
    }

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
            pass_patterns=pass_patterns)
        # FIX 4: Use gen_op (MiniMax, fast=True → abab6.5s-chat) for generation if
        # provided, else fall back to op.  abab6.5s-chat is the creative chat model;
        # MiniMax-M3 is a reasoning model — better at math/coding, worse at ideation.
        _gen = gen_op or op
        try:
            raw_response = _gen.complete_json(system, user, temperature=0.9)
            cands = _parse_candidates(raw_response)
        except Exception as e:
            logger.error(f"Generation batch {seed} failed: {e}", extra={"error": str(e)})
            return []
            
        if form:
            for c in cands:
                # Categorical field (survives asdict() into the dossier), not a boolean tag.
                c.structural_form = form
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
        
        # Use a slightly lower temperature for refinement to encourage strictness
        try:
            raw_response = _gen.complete_json(system, user, temperature=0.5)
            refined_data = raw_response if isinstance(raw_response, list) else []
            
            # Re-map and track history
            refined_cands = []
            original_by_title = {c.title: c for c in substantive}
            
            for r_dict in refined_data:
                # Find matching original candidate
                orig_title = r_dict.get("title")
                orig = original_by_title.get(orig_title)
                
                if orig:
                    # Capture the sharpening diff
                    r_cand = Candidate.from_dict(r_dict)
                    r_cand.structural_form = orig.structural_form
                    r_cand.ambition_tier = orig.ambition_tier
                    
                    # Store the 'before' state in history
                    history_entry = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "action": "refined",
                        "model": _gen.name,
                        "before": {
                            "title": orig.title,
                            "one_liner": orig.one_liner,
                            "hypothesis": orig.hypothesis,
                            "who_pays": orig.who_pays,
                            "why_now": orig.why_now
                        }
                    }
                    r_cand.refinement_history = orig.refinement_history + [history_entry]
                    refined_cands.append(r_cand)
                    
            return thin + refined_cands
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
        avoid = "; ".join(c.title for c in candidates[-40:]) if candidates else ""
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
            return form, lens, aud

        def _fan_out(indices: range) -> list[tuple[str, str, list[Candidate]]]:
            with ThreadPoolExecutor(max_workers=max(1, len(indices))) as ex:
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
) -> list[Candidate]:
    """Fan generation OUT across ambition lanes for a mixed-ambition catalogue (Part 14).

    For each tier in `lanes`, resolve `cfg.for_lane(tier)` (which swaps in that lane's
    generation framing — e.g. side-hustle-scale opportunities vs venture moats) and ask for
    `lane_counts[tier]` candidates, tagging each result with `ambition_tier=tier`. The same
    shared machinery (the `generate` divergence engine) runs underneath every lane; only the
    framing and quota differ. Returns the concatenated, tier-tagged candidate list. Generation
    still judges nothing — the per-tier moat downstream does that.
    """
    out: list[Candidate] = []
    for tier in lanes:
        lane_cfg = cfg.for_lane(tier)
        k = (lane_counts or {}).get(tier)
        # ML Improvement: Grid Scheduler (Stage 3)
        priorities = (grid_priorities or {}).get(tier)
        cands = generate(
            op, lane_cfg, signal_text=signal_text, sector=sector,
            strategy_lens=strategy_lens, exploration_level=exploration_level,
            target_qualities=target_qualities, recent_failure_modes=recent_failure_modes,
            k=k, gen_op=gen_op, grid_priorities=priorities, focus=focus,
            pass_patterns=pass_patterns)
        for c in cands:
            c.ambition_tier = tier
        logger.info(f"Lane {tier!r}: generated {len(cands)} candidate(s)",
                    extra={"lane": tier, "count": len(cands)})
        out.extend(cands)
    return out
