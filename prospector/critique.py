"""Critique -> revise, one pass (G8).

WHY THIS EXISTS, measured rather than assumed. Two facts about the pass it replaces:

1. `prompts/refine.md` says "Drop the weak/obvious ones" and `prompts/refine_system.md`
   carries a section literally headed "THE KILL LIST (Ideas to drop)". The CODE was made
   non-lossy on 2026-07-02 after the refine wave wiped whole batches, but the PROMPT never
   was. The two now contradict each other, and the way that contradiction resolves is the
   defect: an idea the analyst decides to drop is simply not returned, and the non-lossy
   guarantee in `generate._refine_wave` then passes it through UNREFINED. So refinement is
   anti-targeted — the ideas judged weakest are precisely the ones that receive no
   improvement at all.
2. Measured on the live 1789-row index (`tools/generation_survival.py`, 2026-08-08),
   `min_composite` is the modal kill gate in 8 of 9 persona cells. These ideas are mostly
   not dying on a hard gate; they clear the gates and then score too low to publish. The
   refine prompt never mentions the six scoring axes or their weights, so even the ideas it
   does improve are improved blind to what determines that outcome.

So this module does two things the old pass could not: it critiques EVERY candidate, and it
critiques against the actual composite axes and their configured weights.

ONE pass, deliberately. arXiv:2507.08350 finds a single critique-revise round is where the
gain is; further rounds regress toward the model's own priors. There is no loop here and
adding one would need evidence, not enthusiasm.

NON-LOSSY IS A HARD INVARIANT, enforced in code and not merely requested in the prompt.
Nothing may kill a candidate at generation time — all kills are grounded and downstream.
Matching is by an injected integer `idx`, never by title: a revision that rewords a title
(which is the entire point of a revision) is exactly the case that broke title-matching
before. Any index the model omits, duplicates, or returns unparseably keeps its ORIGINAL
candidate. The output length always equals the input length.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .models import Candidate
from .prompts import render
from .telemetry import logger
from .telemetry import stage as telemetry_stage

# Fallback wording only — the real definitions live in `config.yaml weights` and are rendered
# from there, so the prompt cannot drift from the scorer. This map supplies the one-line
# description per axis; a weight with no description here still renders, with its name alone,
# because a new axis appearing in config must not silently vanish from the critique brief.
_AXIS_HINTS = {
    "pain_acuity": "how sharp and how frequent the pain is for a specifically named sufferer",
    # JOB-LEVEL, not product-level. Read the corpus before widening this back: of 161
    # money_provability scores <=1 since 2026-08-01, 117 justify themselves with some form of
    # "no passage prices this", and the scorer twice rejected money it had FOUND for being the
    # wrong artifact — "same buyer, different service" (a £825 probate fee against a lease
    # buyout) and "quote-on-request only, no figure" (ResearchManager, Medidata). Both are
    # facts about what the open web publishes, not about whether the buyer spends. That is the
    # exact principle `price_comparables` is already built on: it may never kill, because "no
    # price page on the open web" is a fact about the web. The scorer was applying the
    # opposite rule, so a genuinely new solution to a job people already pay to get done
    # scored as if nobody paid for anything.
    "money_provability": (
        "whether this BUYER already spends on this OUTCOME today — an adjacent invoice, staff "
        "hours, an agency or professional fee, a fine, or a paid workaround. A new solution to "
        "a job that is already funded scores HIGH; a job nobody spends anything to get done "
        "scores LOW. No public price page, quote-on-request pricing, and no direct competitor "
        "are facts about the market's disclosure, not evidence that the money is absent"
    ),
    "defensibility": "what accumulates here that a competitor starting tomorrow would not have",
    "distribution": "whether a beginner can actually reach the buyer through an open channel",
    "automatability": "how much of the work real tooling can do TODAY, not aspirationally",
    "build_feasibility": "whether a small team can ship the first useful version",
}


def _axes_brief(cfg: Any) -> str:
    """Render the configured scoring axes, heaviest first, as a prompt fragment.

    Read from `cfg.weights` rather than hardcoded so a re-weighting (as happened on
    2026-06-25, when defensibility went .15 -> .25 to stop the composite structurally
    rewarding clonable ideas) changes what the critic optimises for on the same day it
    changes what the scorer measures. A hardcoded copy here would have kept the critic
    tuned to the old formula indefinitely, and nothing would have reported it.
    """
    weights = getattr(cfg, "weights", {}) or {}
    items = sorted(((str(k), float(v)) for k, v in weights.items()),
                   key=lambda kv: kv[1], reverse=True)
    if not items:
        return ""
    lines = [f"- {name} (weight {w:.2f}): {_AXIS_HINTS.get(name, '')}".rstrip()
             for name, w in items]
    return "THE COMPOSITE AXES, heaviest first:\n" + "\n".join(lines)


def _unwrap(raw: Any) -> list:
    """Accept a bare list or a wrapper dict. Mirrors `generate._parse_candidates`.

    A dict-wrapped array collapsing to [] is the specific shape that wiped whole waves in
    the 2026-07-02 incident, so it is handled identically in every place a model returns a
    list of objects rather than being re-derived per call site.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("critiques", "revisions", "opportunities", "candidates", "results", "items"):
            if isinstance(raw.get(key), list):
                return raw[key]
        for v in raw.values():
            if isinstance(v, list):
                return v
    return []


def _by_idx(items: list, n: int) -> dict[int, dict]:
    """Index the model's objects by their echoed `idx`, tolerating a missing one.

    First object wins on a duplicated idx: a model that repeats an index has told us nothing
    about which copy is authoritative, and taking the first is at least deterministic.
    Objects with no usable `idx` fall back to POSITION, which is what the prompt asks for
    anyway ("in the SAME ORDER as the input") — but position is the fallback, never the
    primary, because a model that drops one item mid-array would silently shift every
    subsequent mapping by one and hand each idea somebody else's critique.
    """
    out: dict[int, dict] = {}
    for pos, obj in enumerate(items):
        if not isinstance(obj, dict):
            continue
        raw = obj.get("idx")
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            idx = pos
        if 0 <= idx < n and idx not in out:
            out[idx] = obj
    return out


def critique_revise(candidates: list[Candidate], gen: Any, cfg: Any,
                    lane_directive: str = "") -> list[Candidate]:
    """Run one critique pass and one revision pass. ALWAYS returns len(candidates) items.

    Returns the input list unchanged when the gate is off, when there is nothing to do, or
    when either call fails — a refinement outage must cost sharpening, never candidates.
    """
    ccfg = (getattr(cfg, "generation", {}) or {}).get("critique_revise", {}) or {}
    if not ccfg.get("enabled", False) or not candidates:
        return candidates

    n = len(candidates)
    try:
        payload = []
        for i, c in enumerate(candidates):
            d = c.to_dict()
            d["idx"] = i
            payload.append(d)

        # --- pass 1: critique -------------------------------------------------
        system, user = render(
            "critique",
            candidates_json=json.dumps(payload, indent=2),
            n=n,
            score_axes=_axes_brief(cfg),
            lane_directive=lane_directive,
        )
        with telemetry_stage("generate"):
            critiques = _by_idx(_unwrap(gen.complete_json(system, user, temperature=0.4)), n)

        if not critiques:
            # No critique means the revision pass has nothing to act on, and a revision
            # prompted with empty critiques degenerates into an untargeted reword — which is
            # the pass we are replacing. Stop here and keep the originals.
            logger.warning("critique_revise: no usable critiques, keeping originals",
                           extra={"n": n})
            return candidates

        # --- pass 2: revise ---------------------------------------------------
        # Only candidates that actually received a critique are sent to be revised. The rest
        # are not "rejected"; they simply have nothing to act on, so rewriting them would be
        # a change with no stated reason behind it.
        to_revise = []
        for i, c in enumerate(candidates):
            crit = critiques.get(i)
            if not crit:
                continue
            d = c.to_dict()
            d["idx"] = i
            d["weakest_axis"] = str(crit.get("weakest_axis", "") or "").strip()
            # `.strip()` is load-bearing, not tidiness: a whitespace-only critique is no
            # critique, and without it a "  " passes the truthiness check below and buys a
            # revision call whose only instruction is a blank line.
            d["critique"] = str(crit.get("critique", "") or "").strip()
            if not d["critique"]:
                continue
            to_revise.append(d)

        if not to_revise:
            logger.warning("critique_revise: every critique was empty, keeping originals",
                           extra={"n": n})
            return candidates

        system, user = render(
            "revise",
            candidates_json=json.dumps(to_revise, indent=2),
            n=len(to_revise),
            lane_directive=lane_directive,
        )
        with telemetry_stage("generate"):
            revisions = _by_idx(_unwrap(gen.complete_json(system, user, temperature=0.5)), n)

        # --- merge: identity fallback per index --------------------------------
        out: list[Candidate] = []
        revised_n = 0
        for i, orig in enumerate(candidates):
            r_dict = revisions.get(i)
            if not isinstance(r_dict, dict) or not str(r_dict.get("title") or "").strip():
                out.append(orig)
                continue
            try:
                r_cand = Candidate.from_dict(r_dict)
            except Exception:
                out.append(orig)
                continue
            # Categorical axes belong to the RUN, not to the model's rewrite. The generator
            # was asked for this form/tier/market and the coverage sampler may have chosen
            # the cell; letting a revision move an idea between lanes would silently
            # invalidate both the quota it was generated under and the bar it is judged by.
            r_cand.structural_form = orig.structural_form
            r_cand.ambition_tier = orig.ambition_tier
            r_cand.market = orig.market
            # Tags carry the run's own stamps (audience, seed_kind, the G2/G4 audit fields).
            # The model echoes tags back and may drop some, so the original's tags are the
            # base and the revision may only add to them.
            merged = dict(orig.tags or {})
            merged.update(r_cand.tags or {})
            r_cand.tags = merged
            crit = critiques.get(i) or {}
            r_cand.refinement_history = list(orig.refinement_history or []) + [{
                "timestamp": datetime.utcnow().isoformat(),
                "action": "critique_revise",
                "model": getattr(gen, "name", ""),
                "weakest_axis": str(crit.get("weakest_axis", "") or "").strip(),
                "critique": str(crit.get("critique", "") or "").strip(),
                "before": {"title": orig.title, "one_liner": orig.one_liner,
                           "hypothesis": orig.hypothesis, "who_pays": orig.who_pays,
                           "why_now": orig.why_now},
            }]
            out.append(r_cand)
            revised_n += 1

        # The invariant, asserted rather than trusted. If this ever fails the bug is in the
        # merge above, and losing a candidate silently is the failure mode this whole module
        # is written to prevent.
        if len(out) != n:
            logger.error("critique_revise produced the wrong length, keeping originals",
                         extra={"got": len(out), "want": n})
            return candidates
        logger.info(f"critique_revise: {revised_n}/{n} revised",
                    extra={"revised": revised_n, "total": n})
        return out
    except Exception as e:
        logger.warning(f"critique_revise failed, keeping originals: {e}")
        return candidates
