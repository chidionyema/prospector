"""Dossier assembly and human-readable rendering (Part 4/8).

build_dossier() is the single place that converts raw check results + score into a
Decision and assembles the Dossier record.  All callers pass in pre-computed values;
no datetime or model calls happen here (determinism in tests).

render_markdown() produces a human-readable audit document from a Dossier — KILL
dossiers render their cited reason prominently (a cited KILL is first-class).
"""
from __future__ import annotations

from typing import Optional

from .models import (DEFER_GATE, Decision, Dossier, ScoreResult, CheckResult,
                     AdversarialResult, Candidate)
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
    if gate_fired == DEFER_GATE:
        # Not a kill: a decisive check could not be retrieved (infra/outage). Park the
        # candidate for re-vet — never publish, never count as an evidentiary kill.
        decision = Decision.DEFER
        failed = next((c for c in checks if getattr(c, "retrieval_failed", False)), None)
        cn = failed.check_name if failed else "a decisive gate"
        reason = (f"Deferred — could not retrieve evidence for '{cn}' "
                  f"(retrieval/infra failure). NOT an evidentiary kill; re-vet when "
                  f"retrieval is healthy.")
        gate_fired = None  # no real gate fired; keep the audit honest
    elif gate_fired is not None:
        decision = Decision.KILL
        # Build a cited reason from the failing check
        failing = next((c for c in checks if c.check_name == gate_fired), None)
        if failing is not None:
            reason = (
                f"Gate '{gate_fired}' fired — "
                f"{failing.verdict.value} (conf {failing.confidence:.2f}): "
                f"{failing.rationale}"
            )
        elif gate_fired == "adversarial_decisive":
            adv_text = adversarial.kill_case if adversarial else "adversarial decisive kill"
            reason = f"Gate 'adversarial_decisive' fired — {adv_text}"
        else:
            reason = f"Gate '{gate_fired}' fired."
    elif score is not None and passes_composite(score, cfg):
        decision = Decision.PASS
        reason = f"Survived all gates; composite {score.composite:.4f}."
    else:
        # Composite below threshold (or score missing unexpectedly)
        decision = Decision.KILL
        gate_fired = "min_composite"
        comp = score.composite if score else 0.0
        reason = (
            f"Composite {comp:.4f} below threshold "
            f"{cfg.thresholds.min_composite_to_pass} — gate 'min_composite' fired."
        )

    return Dossier(
        candidate=cand,
        decision=decision,
        gate_fired=gate_fired,
        reason=reason,
        checks=checks,
        adversarial=adversarial,
        score=score,
        model_version=op_model_version,
        created_at=created_at,
        reverify_due_at=reverify_due_at,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

_VERDICT_EMOJI = {
    "supported": "✅",
    "refuted": "❌",
    "unverifiable": "⚠️",
}

_DECISION_BADGE = {
    Decision.PASS: "## ✅ DECISION: PASS",
    Decision.KILL: "## ❌ DECISION: KILL",
    Decision.DEFER: "## ⏸️ DECISION: DEFER (retrieval unavailable — re-vet)",
}


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

    # KILL reason gets its own highlighted block
    if dossier.decision == Decision.KILL:
        lines.append("> **Why killed:**")
        lines.append(f"> {dossier.reason}")
        if dossier.gate_fired:
            lines.append(f">")
            lines.append(f"> Gate fired: `{dossier.gate_fired}`")
        lines.append("")

    # --- Candidate details ---
    if cand.why_now:
        lines.append("### Why Now")
        lines.append(cand.why_now)
        lines.append("")
    if cand.who_pays:
        lines.append("### Who Pays")
        lines.append(cand.who_pays)
        lines.append("")
    if cand.hypothesis:
        lines.append("### Hypothesis")
        lines.append(cand.hypothesis)
        lines.append("")

    # --- Per-check verdicts ---
    if dossier.checks:
        lines.append("---")
        lines.append("## Gate Checks")
        lines.append("")
        for chk in dossier.checks:
            emoji = _VERDICT_EMOJI.get(chk.verdict.value, "?")
            degraded_note = " *(degraded — search failed)*" if chk.degraded else ""
            lines.append(
                f"### {emoji} `{chk.check_name}` — "
                f"{chk.verdict.value.upper()} (conf {chk.confidence:.2f}){degraded_note}"
            )
            lines.append("")
            lines.append(chk.rationale)
            lines.append("")
            if chk.citations:
                lines.append("**Citations:** " + ", ".join(f"`{c}`" for c in chk.citations))
                lines.append("")
            # Inline source URLs
            for src in chk.sources:
                pub = f" ({src.published_at})" if src.published_at else ""
                lines.append(f"- [{src.url}]({src.url}){pub}")
            if chk.sources:
                lines.append("")

    # --- Adversarial case ---
    if dossier.adversarial:
        adv = dossier.adversarial
        lines.append("---")
        lines.append("## Adversarial Case")
        lines.append("")
        decisive_label = "**DECISIVE**" if adv.decisive else "Non-decisive"
        lines.append(f"*{decisive_label}*")
        lines.append("")
        lines.append(adv.kill_case)
        if adv.citations:
            lines.append("")
            lines.append("**Citations:** " + ", ".join(f"`{c}`" for c in adv.citations))
        lines.append("")

    # --- Scores table (PASS only, but render for KILLs that have a score too) ---
    if dossier.score:
        sc = dossier.score
        lines.append("---")
        lines.append("## Scores")
        lines.append("")
        lines.append(f"**Composite: {sc.composite:.4f}**")
        lines.append("")
        lines.append("| Axis | Score | Justification |")
        lines.append("|------|------:|---------------|")
        for ax, val in sc.scores.items():
            just = sc.justification.get(ax, "")
            lines.append(f"| {ax} | {val}/5 | {just} |")
        lines.append("")

    # PASS reason
    if dossier.decision == Decision.PASS:
        lines.append("---")
        lines.append("## Verdict")
        lines.append("")
        lines.append(dossier.reason)
        lines.append("")

    # --- All sources ---
    all_src = dossier.all_sources
    if all_src:
        lines.append("---")
        lines.append("## Sources")
        lines.append("")
        for src in all_src:
            pub = f" ({src.published_at})" if src.published_at else ""
            snippet = src.text[:120].replace("\n", " ")
            lines.append(f"- **[{src.source_id}]** [{src.url}]({src.url}){pub}")
            lines.append(f"  > {snippet}…")
            lines.append("")

    # --- Metadata footer ---
    lines.append("---")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- **Model:** {dossier.model_version}")
    lines.append(f"- **Candidate ID:** `{cand.candidate_id}`")
    lines.append(f"- **Created:** {dossier.created_at}")
    if dossier.reverify_due_at:
        lines.append(f"- **Reverify by:** {dossier.reverify_due_at}")
    lines.append("")

    return "\n".join(lines)
