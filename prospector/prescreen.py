"""Lightweight pre-screen gate (Part 3).

FIX #1: structural prescreen is now a THREE-STAGE gate:
  Stage 1 (deterministic, zero cost): _FORBID_PATTERNS — catches the explicitly-
    forbidden solo-agent shapes BEFORE any LLM call fires.  A solo operator
    structurally CANNOT be any of these things.
  Stage 2 (deterministic, zero cost): _WEAK_PATTERNS — catches ideas so thin
    (no pricing, no target buyer, no mechanism) that the moat would kill them
    on unverifiable anyway.  Catching them here redirects the generator to
    sharpen the idea rather than spending LLM budget on a guaranteed kill.
  Stage 3 (LLM): the existing model-based triage for nuanced quality judgment.
    Retained as a backstop for genuinely novel ideas that slip past both regex
    stages.  Bias toward keep: uncertainty → pass so novel ideas survive.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .config import Config
from .models import Candidate
from .operator import Operator
from .prompts import render
from .telemetry import logger, track_latency

# Regex patterns keyed by structural violation. Each maps to a human-readable label
# for the rejection reason. Order matters: most specific first (avoid substring false
# positives, e.g. "market" matching "marketplace" before "two-sided marketplace").
# Structural failure patterns: solo-operator infeasible shapes.
# These are deterministic — a solo operator structurally CANNOT be these things.
# Order matters: most specific first to avoid substring false positives.
_FORBID_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Licensed / accredited institutions
    (re.compile(r'\baccredited\s+(rating|assessment|evaluation)\b', re.I),    "accredited rating/assessment body"),
    (re.compile(r'\brating\s+(agency|firm|service|council)\b', re.I),        "rating agency"),
    (re.compile(r'\bcredit\s+rating\b', re.I),                                 "credit rating service"),
    # Regulators / standards bodies
    (re.compile(r'\b(regulatory|regulation)\s+(body|agency|authority|organisation)\b', re.I), "regulatory body"),
    (re.compile(r'\bstandards?\s+(body|organisation|organization|authority)\b', re.I), "standards body"),
    (re.compile(r'\bregulator\b'),                                            "regulator"),
    (re.compile(r'\bofficially\s+accredited\b', re.I),                        "accredited body"),
    # Central registries / indices / authorities
    (re.compile(r'\bcentral\s+(registry|index|register|authority)\b', re.I),  "central registry/index/authority"),
    (re.compile(r'\bnational\s+(registry|index|register)\b', re.I),           "national registry/index"),
    (re.compile(r'\bpublic\s+(registry|index|register)\b', re.I),            "public registry/index"),
    # Banking / insurance / DFI at scale
    (re.compile(r'\b(neo)?bank\b', re.I),                                     "bank (licensed)"),
    (re.compile(r'\b(cryptocurrency|crypto)\s+exchange\b', re.I),            "crypto exchange"),
    (re.compile(r'\bDFI\b', re.I),                                           "development finance institution"),
    (re.compile(r'\b(insurance|insurer)\s+(company|firm|underwriter|group)\b', re.I), "insurance company/underwriter"),
    (re.compile(r'\bunderwrite?s?\s+(at\s+)?scale\b', re.I),                "insurance underwriting at scale"),
    # Two-sided marketplaces
    (re.compile(r'\btwo[\s\-]?sided\s+marketplace\b', re.I),                 "two-sided marketplace"),
    (re.compile(r'\bmarketplace\b'),                                         "generic marketplace"),
    # Capital / scale requirements (structural, not just hard)
    (re.compile(r'\blarge\s+incumbent\b', re.I),                             "large incumbent"),
    (re.compile(r'\brequires?\s+(a\s+)?(large|big|big)\s+(team|staff|headcount)\b', re.I), "large team required"),
    (re.compile(r'\b(requires?|need)s?\s+outside\s+(investment|capital|funding|venture\s+capital)\b', re.I), "requires outside capital"),
    (re.compile(r'\b(only|works?)\s+if\s+already\s+a\s+(large|big)\s+incumbent\b', re.I), "requires incumbent status"),
    (re.compile(r'\bexisting\s+book\s+of\s+(business|clients|customers)\b', re.I), "existing book required"),
    (re.compile(r'\bneed\s+\d+[\s\-]?\w+\s+(staff|employees|people)\b', re.I), "large headcount required"),
    # Licensed professional services
    (re.compile(r'\b(legal|law)\s+firm\b', re.I),                            "law firm"),
    (re.compile(r'\b(accountancy|accounting)\s+firm\b', re.I),               "accountancy firm"),
    (re.compile(r'\brequires?\s+(a\s+)?(financial|law|legal)\s+licence\b', re.I), "requires financial/legal licence"),
    (re.compile(r'\bFCA\b'),                                                  "FCA-licensed firm"),
    (re.compile(r'\bPRA\b'),                                                  "PRA-regulated firm"),
]

# Weak/dilatory signal patterns: ideas that lack the minimum structural information
# needed for the moat to evaluate them.  These are softer than _FORBID — they
# represent ideas so vaguely described that the moat cannot apply its checks
# meaningfully.  The idea is NOT structurally impossible (keep), but it CANNOT
# survive the moat in its current form (the moat would kill on unverifiable).
# Catching them here redirects the generator to sharpen the idea before submission.
# These are additions to the LLM stage 2 backstop: if an idea slips past these
# patterns, the LLM still judges it — but now more ideas die early at zero cost.
_WEAK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # No pricing signal whatsoever
    (re.compile(r'\bfree\s+for\s+(everyone|all|anybody)\b', re.I),
     "value is framed as free-for-all (no monetisation path)"),
    (re.compile(r'\bmonetise?z?\s+later\b', re.I),
     "explicit deferred-monetisation admission"),
    # No target buyer
    (re.compile(r'\bfor\s+(everyone|anybody|all\s+people)\b', re.I),
     "no specific target buyer"),
    (re.compile(r'\bthe\s+(mass|general)\s+market\b', re.I),
     "mass-market positioning with no niche"),
    (re.compile(r'\bevery\s+(business|company|organisation|organization)\b', re.I),
     "no specific buyer segment"),
    # No mechanism — pure aspiration
    (re.compile(r'\bAI[- ]powered\s+everything\b', re.I),
     "AI-everything with no specific application"),
    (re.compile(r'\bdisrupt\s+the\s+industry\b', re.I),
     "disruption aspiration without mechanism"),
    (re.compile(r'\bglobal\s+platform\b', re.I),
     "global platform without product specificity"),
    (re.compile(r'\becosystem\s+of\s+(\w+\s+){0,3}\w+\b', re.I) if (lambda p: True) else None,  # placeholder
     ""),  # replaced below
]

# Filter None entries (placeholder not yet compiled)
_WEAK_PATTERNS = [(p, lbl) for (p, lbl) in _WEAK_PATTERNS if p is not None]


def structural_filter(cand: Candidate, cfg: Config) -> tuple[bool, str]:
    """Deterministic two-stage regex filter.

    Stage 1 (_FORBID_PATTERNS): catch explicitly-forbidden solo-agent shapes.
      A solo operator structurally CANNOT be any of these things — proposing one
      is an automatic reject before any LLM call fires.

    Stage 2 (_WEAK_PATTERNS): catch ideas so structurally thin that the moat
      cannot evaluate them (they would die on unverifiable).  Catching them here
      at zero cost redirects generation to sharpen before submission rather than
      spending LLM budget on an idea that cannot pass the moat in its current form.

    The LLM prescreen stage 2 is retained as a backstop for genuinely novel ideas
    that slip past both regex stages.

    Returns:
        (pass_filter, reason) — pass_filter=True means the candidate passes both
        deterministic stages.  False means it is rejected with the given reason.
    """
    # Fields to scan: title, one_liner, hypothesis (most informative), tags.
    haystack = " ".join(
        str(x) for x in (cand.title, cand.one_liner, cand.hypothesis,
                         cand.tags.get("hypothesis", "")))

    # Stage 1 — hard structural failures (solo-operator infeasible).
    for pattern, label in _FORBID_PATTERNS:
        if pattern.search(haystack):
            logger.info(f"STRUCTURAL FILTER REJECTED: {cand.title!r} — {label}",
                        extra={"candidate_id": cand.candidate_id, "pattern": label,
                               "stage": "forbid"})
            return False, f"Structurally infeasible for solo operator: {label}"

    # Stage 2 — weak/dilatory signals (idea too thin for moat evaluation).
    for pattern, label in _WEAK_PATTERNS:
        if label and pattern.search(haystack):
            logger.info(f"STRUCTURAL FILTER REJECTED (weak): {cand.title!r} — {label}",
                        extra={"candidate_id": cand.candidate_id, "pattern": label,
                               "stage": "weak"})
            return False, f"Structurally thin: {label}"

    return True, "passed structural filter"


@track_latency(name="prescreen")
def prescreen(
    op: Operator,
    cfg: Config,
    cand: Candidate,
    *,
    run_structural_first: bool = True,
) -> tuple[bool, float, str, str]:
    """Ask the model whether a candidate is worth pursuing further.

    Three-stage gate (deterministic stages cost zero and run first):
      Stage 1: _FORBID_PATTERNS — hard structural failures (solo infeasible).
      Stage 2: _WEAK_PATTERNS — thin ideas that moat would kill on unverifiable.
      Stage 3: model-based triage for nuanced quality judgment (LLM backstop).

    Returns:
        (keep, score, reason, diversity_features) — keep is True unless the model explicitly says False.
        Score is 0.0 to 1.0 (quality signal for DPP).
        Diversity_features is a string of keywords for embedding.

    Critical invariant (Part 3): bias toward keep. On ANY exception, parse
    failure, or ambiguous output, return (True, 0.5, "kept on uncertainty", "") so that
    novel ideas are never silently discarded.
    """
    logger.info(f"Prescreening candidate: {cand.title!r}",
                extra={"candidate_id": cand.candidate_id})

    # Stage 1 — deterministic structural filter (no LLM call, no cost).
    if run_structural_first:
        passed, reason = structural_filter(cand, cfg)
        if not passed:
            logger.info(f"PRESCREEN REJECTED (structural): {cand.title!r} — {reason}")
            return False, 0.0, reason, ""
        logger.debug(f"Structural filter passed: {cand.title!r}")

    # Stage 2 — model-based triage (only for structural survivors).
    try:
        system, user = render("prescreen", candidate_json=json.dumps(cand.to_dict()))
        data = op.complete_json(system, user)
    except Exception as e:
        logger.warning(f"Prescreen failed for {cand.title!r}: {e}", extra={"error": str(e)})
        return True, 0.5, "kept on uncertainty", ""

    # Guard: non-dict response is treated as ambiguous.
    if not isinstance(data, dict):
        logger.warning(f"Prescreen returned non-dict response for {cand.title!r}",
                       extra={"response": str(data)})
        return True, 0.5, "kept on uncertainty", ""

    raw_keep = data.get("keep")
    score = float(data.get("score", 0.5))
    diversity_features = str(data.get("diversity_features", ""))

    # Only reject on an explicit falsy value — anything else keeps.
    if raw_keep is False or (isinstance(raw_keep, str) and raw_keep.lower() == "false"):
        reason = str(data.get("reason", "")) or "pre-screen rejected"
        logger.info(f"PRESCREEN REJECTED (model): {cand.title!r}",
                    extra={"reason": reason})
        return False, score, reason, diversity_features

    reason = str(data.get("reason", "")) or "kept"
    logger.info(f"Prescreen kept: {cand.title!r}", extra={"reason": reason})
    return True, score, reason, diversity_features
