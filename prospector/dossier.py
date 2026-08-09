"""Dossier assembly and human-readable rendering (Part 4/8).

build_dossier() is the single place that converts raw check results + score into a
Decision and assembles the Dossier record.  All callers pass in pre-computed values;
no datetime or model calls happen here (determinism in tests).

render_markdown() produces a human-readable audit document from a Dossier — KILL
dossiers render their cited reason prominently (a cited KILL is first-class).
"""
from __future__ import annotations

import re
from typing import Optional

from .models import (
    DEFER_GATE,
    AdversarialResult,
    Candidate,
    CheckResult,
    Decision,
    Dossier,
    ScoreResult,
)
from .score import passes_composite

# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_dossier(
    cand: Candidate,
    checks: list[CheckResult],
    adversarial: Optional[AdversarialResult],
    gate_fired: Optional[str],
    score: Optional[ScoreResult],
    cfg,                          # Config — typed loosely to avoid circular import issues
    op_model_version: str,
    provider_chain: str = "",
    created_at: str = "",
    reverify_due_at: Optional[str] = None,
) -> Dossier:
    """Assemble a Dossier from pre-computed artefacts.

    Decision logic:
      - gate_fired is not None  -> Decision.KILL (hard gate or adversarial).
      - score passes composite  -> Decision.PASS.
      - otherwise               -> Decision.KILL with gate_fired="min_composite".

    The caller is responsible for computing `score` whenever gate_fired is None
    (i.e., the candidate survived all hard gates and needs ranking).
    """
    if gate_fired in (DEFER_GATE, "moat_exhausted"):
        # Not a kill: a decisive check could not be retrieved or the moat was unavailable.
        # Park the candidate for re-vet — never publish, never count as an evidentiary kill.
        decision = Decision.DEFER
        failed = next((c for c in checks if getattr(c, "retrieval_failed", False)), None)
        if gate_fired == "moat_exhausted":
            reason = ("Deferred — moat (verdict / adversarial pass) was unavailable "
                      "(Claude + Gemini exhausted).  NOT an evidentiary kill; re-vet when "
                      "moat recovers.  Candidate will auto-resume on next `vet --resume`.")
        else:
            cn = failed.check_name if failed else "a decisive gate"
            reason = (f"Deferred — could not retrieve evidence for '{cn}' "
                      f"(retrieval/infra failure). NOT an evidentiary kill; re-vet when "
                      f"retrieval is healthy.")
        gate_fired = None  # no real gate fired; keep the audit honest
    elif gate_fired is not None:
        decision = Decision.KILL
        # Plain-English reason with the internal gate name kept for audit.
        # adaptive.py strips on the first ":" — keep that contract so the
        # substance after the colon still feeds generation feedback.
        failing = next((c for c in checks if c.check_name == gate_fired), None)
        labelled = _labelled(gate_fired, _CHECK_LABEL)
        if failing is not None:
            reason = (
                f"It failed on: {labelled} — "
                f"{failing.verdict.value} (conf {failing.confidence:.2f}): "
                f"{failing.rationale}"
            )
        elif gate_fired == "adversarial_decisive":
            adv_text = adversarial.kill_case if adversarial else "the case against it was decisive"
            reason = f"It failed on: {labelled} — {adv_text}"
        elif gate_fired == "moat_ungrounded":
            moat_checks = tuple(getattr(cfg.thresholds, "moat_critical_checks",
                                        ("value_durability", "incumbency")))
            reason = (f"It failed on: {labelled} — no publish-critical check "
                      f"({', '.join(moat_checks)}) was grounded-supported. "
                      f"Source-or-die: refuse to publish without grounded evidence "
                      f"on the lane's decisive dimension.")
        elif gate_fired == "source_or_die":
            floor = getattr(cfg.thresholds, "min_supported_confidence", None)
            if floor is None:
                floor = cfg.thresholds.confidence_floor
            min_supported = getattr(cfg.thresholds, "min_supported_to_pass", 1)
            n_supported = sum(1 for c in checks
                              if c.verdict.value == "supported" and c.confidence >= floor)
            reason = (f"It failed on: {labelled} — only {n_supported} "
                      f"grounded-supported check(s) (need {min_supported}). "
                      f"Source-or-die: refuse to publish on unverifiable evidence.")
        elif gate_fired == "min_composite":
            reason = (f"It failed on: {labelled} — even the theoretical maximum "
                      f"composite cannot clear "
                      f"{cfg.thresholds.min_composite_to_pass}.")
        else:
            reason = f"It failed on: {labelled}."
    elif score is not None and passes_composite(score, cfg):
        # SOURCE-OR-DIE at the pass boundary. Clearing the composite is necessary but NOT
        # sufficient: the scorer rules on the candidate narrative and will happily score an
        # ungrounded idea highly. A PASS must rest on actual grounded evidence, or we are
        # "publishing on silence" — forbidden (CLAUDE.md: verdict-from-retrieval-only;
        # publish only on PASS). This is the exact class that minted 9 ungrounded "passes"
        # during the 2026-06-16 grounding outage (every check unverifiable, conf 0.0, 0
        # sources, yet composite 2.95 -> PASS). A genuine retrieval OUTAGE is caught upstream
        # (DEFER_GATE) and never reaches here; reaching here with no support means we looked
        # and found nothing to stand on.
        # PASS-SIDE floor: a SUPPORTED check only counts as grounded toward a PASS when its
        # confidence clears min_supported_confidence. Decoupled from confidence_floor (the
        # kill-side lever) so tightening passes never loosens kills. Falls back to
        # confidence_floor, then 0.0, for configs that predate the split.
        floor = getattr(cfg.thresholds, "min_supported_confidence", None)
        if floor is None:
            floor = cfg.thresholds.confidence_floor
        min_supported = getattr(cfg.thresholds, "min_supported_to_pass", 1)
        n_supported = sum(1 for c in checks
                          if c.verdict.value == "supported" and c.confidence >= floor)
        # PUBLISH-CRITICAL requirement: at least one lane-declared decisive check must be
        # grounded-supported. The check set is LANE-AWARE (cfg.thresholds.moat_critical_checks)
        # so each lane requires its OWN headline evidence (smb: payer_solvency; side_hustle:
        # buyer_intent; venture/default: value_durability/incumbency). Hardcoding the venture moat
        # here made the smb/side_hustle PASS path structurally unreachable — those lanes never run
        # value_durability/incumbency (PROVEN 2026-06-28, Martyn's Law composite 2.95 KILLed on
        # moat_ungrounded). This still enforces source-or-die — a candidate cannot publish unless
        # the lane's decisive dimension is grounded in fetched evidence — it asks the RIGHT one.
        moat_checks = tuple(getattr(cfg.thresholds, "moat_critical_checks",
                                    ("value_durability", "incumbency")))
        moat_grounded = sum(1 for c in checks
                            if c.check_name in moat_checks
                            and c.verdict.value == "supported"
                            and c.confidence >= floor)
        if n_supported >= min_supported and moat_grounded >= 1:
            decision = Decision.PASS
            reason = (f"Survived all gates; composite {score.composite:.4f}; "
                      f"{n_supported} grounded-supported check(s) "
                      f"(moat grounded: {moat_grounded}).")
        elif moat_grounded < 1:
            decision = Decision.KILL
            gate_fired = "moat_ungrounded"
            reason = (f"Composite {score.composite:.4f} cleared the bar but no publish-critical "
                      f"check ({', '.join(moat_checks)}) was grounded-supported. "
                      f"Source-or-die: refuse to publish without grounded evidence on the lane's "
                      f"decisive dimension.")
        else:
            decision = Decision.KILL
            gate_fired = "source_or_die"
            reason = (f"Composite {score.composite:.4f} cleared the bar but only "
                      f"{n_supported} grounded-supported check(s) (need {min_supported}). "
                      f"Source-or-die: refuse to publish on unverifiable evidence.")
    else:
        # Composite below threshold (or score missing unexpectedly)
        decision = Decision.KILL
        gate_fired = "min_composite"
        comp = score.composite if score else 0.0
        reason = (
            f"It failed on: {_labelled('min_composite', _CHECK_LABEL)} — "
            f"composite {comp:.4f} below the bar of "
            f"{cfg.thresholds.min_composite_to_pass}."
        )

    # Provisional rollup: the decision is real but untrusted if ANY ruling that fed it
    # was served by the cheap emergency fallback tail (moat exhausted). A degraded/
    # deferred check never ruled, so it carries provisional=False and a DEFER stays
    # non-provisional. A provisional PASS will not publish; both PASS and KILL auto
    # re-vet on the next `vet --resume`.
    provisional = any(getattr(c, "provisional", False) for c in checks) or \
        bool(adversarial is not None and getattr(adversarial, "provisional", False))

    return Dossier(
        candidate=cand,
        decision=decision,
        gate_fired=gate_fired,
        reason=reason,
        checks=checks,
        adversarial=adversarial,
        score=score,
        model_version=op_model_version,
        provider_chain=provider_chain,
        persona=cfg.active_persona,
        created_at=created_at,
        reverify_due_at=reverify_due_at,
        provisional=provisional,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

_VERDICT_EMOJI = {
    "supported": "✅",
    "refuted": "❌",
    "unverifiable": "⚠️",
}

_VERDICT_LABEL = {
    "supported": "Yes — the sources back this",
    "refuted": "No — the sources contradict this",
    "unverifiable": "Can't tell — the sources don't say",
}

# A plain-English question for each check, for the person reading the dossier. The
# CHECKS text in models.py stays as it is: that is the verifier's contract with the
# moat, and rewording it would change what actually gets ruled on. This is a label.
_CHECK_LABEL = {
    "pain_reality": "Is the problem real?",
    "value_durability": "Will this still be worth money later?",
    "incumbency": "Is someone already doing this well?",
    "payer_solvency": "Can the customer afford it?",
    "distribution": "Can you actually reach the customer?",
    "legality": "Is it legal?",
    "buyer_intent": "Are people already looking for this?",
    "route_to_market": "Could a beginner reach buyers?",
    "currency": "Is this live right now?",
    "claims_verifiable": "Can the claims be checked?",
    "adversarial_decisive": "The case against it was decisive",
    "min_composite": "The overall score was too low",
    "moat_ungrounded": "The decisive checks weren't backed by evidence",
    "source_or_die": "Not enough grounded evidence to publish",
    DEFER_GATE: "We couldn't fetch enough evidence to rule",
}

# Legacy dossiers still carry a "Gate 'x' fired — " prefix. Strip it for the
# reader; new reasons are already plain English (see build_dossier).
_GATE_PREFIX = re.compile(r"^Gate '[^']+' fired(?: — |\.\s*)")

_AXIS_LABEL = {
    "pain_acuity": "How badly it hurts",
    "money_provability": "How provable the money is",
    "distribution": "How easy buyers are to reach",
    "defensibility": "How hard it is to copy",
    "build_feasibility": "How buildable it is",
    "automatability": "How much one person can automate",
}

_DECISION_BADGE = {
    Decision.PASS: "## ✅ PASS",
    Decision.KILL: "## ❌ KILL",
    Decision.DEFER: "## ⏸️ DEFER — no verdict yet",
}

_DECISION_GLOSS = {
    Decision.PASS: ("This cleared every check we hold it to, on evidence we fetched "
                    "and cited below."),
    Decision.KILL: "We stopped on this one. The reason and the evidence are below.",
    Decision.DEFER: ("We could not fetch enough evidence to rule either way, so this "
                     "waits for another run. Not knowing is not the same as a no."),
}


def _labelled(name: str, labels: dict[str, str]) -> str:
    """Plain label with the internal name kept alongside it. The token stays because a
    dossier is an audit document: someone has to be able to match this line to a gate
    in config.yaml. Clarity is added, never substituted."""
    label = labels.get(name)
    return f"{label} (`{name}`)" if label else f"`{name}`"


def render_markdown(dossier: Dossier) -> str:
    """Render a human-readable audit document from a Dossier.

    Both PASS and KILL are first-class: a KILL renders its cited reason prominently.
    """
    cand = dossier.candidate
    lines: list[str] = []

    # --- Header ---
    lines.append(f"# {cand.title}")
    if cand.one_liner:
        lines.append(f"\n_{cand.one_liner}_")
    lines.append("")

    # --- Decision badge (prominent) ---
    lines.append(_DECISION_BADGE[dossier.decision])
    lines.append("")
    lines.append(f"_{_DECISION_GLOSS[dossier.decision]}_")
    lines.append("")

    # Provisional banner: this verdict was reached by the cheap emergency fallback tail
    # because the trusted moat was exhausted. Real-but-untrusted — never publishes on
    # PASS, auto re-vetted by the moat on the next `vet --resume`.
    if dossier.provisional:
        lines.append("> ⚠️ **This verdict is not final.** The models we trust to judge "
                     "were unavailable, so a cheaper backup ruled instead. We don't "
                     "trust that enough to publish on. It gets judged again properly "
                     "on the next `vet --resume`.")
        lines.append("")

    # KILL reason gets its own highlighted block
    if dossier.decision == Decision.KILL:
        lines.append("> **Why we stopped:**")
        lines.append(f"> {_GATE_PREFIX.sub('', dossier.reason or '').strip()}")
        if dossier.gate_fired:
            lines.append(">")
            lines.append(f"> It failed on: {_labelled(dossier.gate_fired, _CHECK_LABEL)}")
        lines.append("")

    # --- Candidate details ---
    if cand.why_now:
        lines.append("### Why this is possible now")
        lines.append(cand.why_now)
        lines.append("")
    if cand.who_pays:
        lines.append("### Who pays for it")
        lines.append(cand.who_pays)
        lines.append("")
    if cand.hypothesis:
        lines.append("### How it works")
        lines.append(cand.hypothesis)
        lines.append("")

    # --- Generation Refinement (Diff) ---
    if cand.refinement_history:
        lines.append("---")
        lines.append("## How the idea was sharpened")
        lines.append("")
        lines.append("> A second pass narrowed and toughened the first draft. "
                     "Here's what changed.")
        lines.append("")
        for entry in cand.refinement_history:
            before = entry.get("before", {})
            lines.append("#### Changes:")
            if before.get("title") != cand.title:
                lines.append(f"- **Title**: ~~{before.get('title')}~~ → {cand.title}")
            if before.get("one_liner") != cand.one_liner:
                lines.append(f"- **One-liner**: ~~{before.get('one_liner')}~~ → {cand.one_liner}")
            if before.get("hypothesis") != cand.hypothesis:
                lines.append(f"- **How it works**: ~~{before.get('hypothesis')}~~ → {cand.hypothesis}")
            if before.get("who_pays") != cand.who_pays:
                lines.append(f"- **Who pays**: ~~{before.get('who_pays')}~~ → {cand.who_pays}")
            if before.get("why_now") != cand.why_now:
                lines.append(f"- **Why now**: ~~{before.get('why_now')}~~ → {cand.why_now}")
        lines.append("")

    # --- Per-check verdicts ---
    if dossier.checks:
        lines.append("---")
        lines.append("## What we checked")
        lines.append("")
        for chk in dossier.checks:
            emoji = _VERDICT_EMOJI.get(chk.verdict.value, "?")
            label = _CHECK_LABEL.get(chk.check_name, chk.check_name)
            verdict = _VERDICT_LABEL.get(chk.verdict.value, chk.verdict.value)
            lines.append(f"### {emoji} {label}")
            lines.append("")
            lines.append(f"**{verdict}.** Confidence {chk.confidence:.2f}. "
                         f"*(check: `{chk.check_name}`)*")
            lines.append("")
            if chk.degraded:
                lines.append("> Some searches failed here, so this rests on thinner "
                             "evidence than usual.")
                lines.append("")
            lines.append(chk.rationale)
            lines.append("")

            if chk.citations:
                lines.append("**Sources used:** " + ", ".join(f"`{c}`" for c in chk.citations))
                lines.append("")

            # --- Chain-of-Evidence (Contextual Snippets) ---
            if chk.sources:
                lines.append("**What those sources said:**")
                for src in chk.sources:
                    snippet = src.text[:300].replace("\n", " ")
                    lines.append(f"- [{src.source_id}] *\"{snippet}...\"* — [{src.url}]({src.url})")
                lines.append("")

    # --- Adversarial case ---
    if dossier.adversarial:
        adv = dossier.adversarial
        lines.append("---")
        lines.append("## The case against")
        lines.append("")
        lines.append("> We argue against every idea on purpose. This is the strongest "
                     "case we could build for walking away.")
        lines.append("")
        lines.append("**Decisive on its own — this is enough to stop the idea.**"
                     if adv.decisive else
                     "**Not decisive.** Worth knowing, but it doesn't sink the idea.")
        lines.append("")
        lines.append(adv.kill_case)
        if adv.citations:
            lines.append("")
            lines.append("**Sources used:** " + ", ".join(f"`{c}`" for c in adv.citations))
            lines.append("")

    # --- Scores table (PASS only, but render for KILLs that have a score too) ---
    if dossier.score:
        sc = dossier.score
        lines.append("---")
        lines.append("## How it scored")
        lines.append("")
        lines.append(f"**Overall: {sc.composite:.4f}** (each line is rated out of 5, "
                     f"then weighted)")
        lines.append("")
        lines.append("| What we rated | Score | Why |")
        lines.append("|---------------|------:|-----|")
        for ax, val in sc.scores.items():
            just = sc.justification.get(ax, "")
            lines.append(f"| {_labelled(ax, _AXIS_LABEL)} | {val}/5 | {just} |")
        lines.append("")

    # PASS reason
    if dossier.decision == Decision.PASS:
        lines.append("---")
        lines.append("## Why this passed")
        lines.append("")
        lines.append(dossier.reason)
        lines.append("")

    # --- All sources ---
    all_src = dossier.all_sources
    if all_src:
        lines.append("---")
        lines.append("## Every source we used")
        lines.append("")
        archived_any = any(getattr(s, "archived_url", None) for s in all_src)
        lines.append("Every claim above traces back to one of these. Follow any of "
                     "them and check us."
                     + (" Where a page has since moved or gone, the archived copy is the "
                        "same text we read, captured on the day we read it."
                        if archived_any else ""))
        lines.append("")
        for src in all_src:
            pub = f" ({src.published_at})" if src.published_at else ""
            snippet = src.text[:500].replace("\n", " ")
            lines.append(f"### Source [{src.source_id}]")
            lines.append(f"**URL:** [{src.url}]({src.url}){pub}")
            # The second pointer. `url` is the part that rots (measured 2026-08-09: 12 of 14
            # dead citations were genuinely gone), `text` below is the evidence and never
            # does. Rendering the memento is what stops "follow any of them and check us"
            # from quietly becoming false a year after the sale.
            archived = getattr(src, "archived_url", None)
            if archived:
                fetched = src.fetched_at if isinstance(src.fetched_at, str) else ""
                on = f", as retrieved {fetched[:10]}" if fetched else ""
                lines.append(f"**Archived copy:** [permanent snapshot]({archived}){on}")
            lines.append("")
            lines.append(f"> {snippet}...")
            lines.append("")

    # --- Metadata footer ---
    lines.append("---")
    lines.append("## Run details")
    lines.append("")
    if dossier.persona:
        lines.append(f"- **Persona:** {dossier.persona}")
    lines.append(f"- **Judged by:** {dossier.model_version}")
    if getattr(cand, "market", ""):
        lines.append(f"- **Market:** {cand.market}")
    lines.append(f"- **Candidate ID:** `{cand.candidate_id}`")
    lines.append(f"- **Created:** {dossier.created_at}")
    if dossier.reverify_due_at:
        lines.append(f"- **Evidence goes stale after:** {dossier.reverify_due_at}")
    lines.append("")

    return "\n".join(lines)
