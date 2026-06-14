"""Adaptive-creativity controller (Part 3).
Adjusts exploration_level based on the rolling kill-rate to find fresh niches.
"""
from __future__ import annotations

from urllib.parse import urlparse

from .models import Decision
from .store import Store


def calculate_exploration_level(store: Store, window: int = 50) -> float:
    """Determine the creativity level (0.0 to 1.0) based on recent kill-rate.
    
    If the moat is killing almost everything (>90%), we raise exploration
    to vary the lens and find fresh patterns.
    """
    rows = store.all()
    if not rows:
        return 0.5
    
    # Sort by creation date descending to get most recent
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent = rows[:window]
    
    kills = sum(1 for r in recent if r.get("decision") == Decision.KILL.value)
    kill_rate = kills / len(recent)
    
    # High kill-rate (>90%) -> Maximum exploration
    if kill_rate >= 0.9:
        return 1.0
    # Healthy kill-rate (70-90%) -> High exploration
    if kill_rate >= 0.7:
        return 0.8
    # Low kill-rate (<30%) -> Low exploration (exploit current patterns)
    if kill_rate <= 0.3:
        return 0.2
    
    # Default/Medium
    return 0.5


# Lenses ordered from convergent (exploit) to divergent (explore). The divergent
# ones force structurally different ideas instead of variations on one obvious frame.
_DIVERGENT = ["analogical", "first_principles", "invert", "cross_sector", "combine_signals"]
_CONVERGENT = ["broaden", "narrow"]
_DEFAULT_LENSES = _CONVERGENT + _DIVERGENT


def select_lenses(cfg, exploration_level: float, k: int = 5) -> str:
    """Choose which creativity lenses generation should apply this run.

    The 7 lenses are configured but were never used: generation always ran under
    the single default "broaden" lens, so every candidate was a variation on one
    obvious frame. We now rotate lenses by exploration level — the higher the
    kill-rate, the more we lean on divergent lenses (analogical / first-principles /
    invert / cross-sector / combine) to escape the consensus shape. Returns a
    comma-joined string the generate prompt distributes across its k ideas.
    """
    controller = (cfg.generation or {}).get("controller", {}) if hasattr(cfg, "generation") else {}
    configured = [str(x) for x in controller.get("lenses", [])] or list(_DEFAULT_LENSES)

    def _avail(names: list[str]) -> list[str]:
        keep = [n for n in names if n in configured]
        return keep or names

    if exploration_level >= 0.8:
        chosen = _avail(_DIVERGENT)
    elif exploration_level <= 0.3:
        chosen = _avail(_CONVERGENT)
    else:
        chosen = _avail(["broaden", "analogical", "first_principles", "invert", "cross_sector"])

    # Cap to k so the prompt can give ~one idea per lens without diluting.
    return ", ".join(chosen[:k]) if k else ", ".join(chosen)


def get_recent_failure_modes(store: Store, window: int = 20) -> str:
    """Summarise WHY recent ideas died — not just which gate fired.

    The gate name alone ("value_durability (16)") tells the generator nothing
    actionable; it cannot out-think a wall it is never shown. So we also mine the
    actual kill *reasons* and the *sources/incumbents* that keep refuting ideas
    (loaded from the per-dossier JSON, which the index row omits). This is the
    learning signal: it lets generation pivot the value-capture model away from a
    commoditised category instead of re-submitting the same dead shape.
    """
    rows = store.all(decision=Decision.KILL.value)
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent = rows[:window]
    if not recent:
        return ""

    # Gate histogram — cheap, straight from the index.
    counts: dict[str, int] = {}
    for r in recent:
        g = r.get("gate_fired")
        if g:
            counts[g] = counts.get(g, 0) + 1
    if not counts:
        return ""
    sorted_gates = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    gate_summary = ", ".join(f"{g} ({c})" for g, c in sorted_gates[:3])

    # Mine the substance from the dossier JSON of the most recent kills.
    reasons: list[str] = []
    domains: dict[str, int] = {}
    for r in recent:
        cid = r.get("candidate_id")
        if not cid:
            continue
        dossier = store.get(cid)
        if not dossier:
            continue
        reason = (dossier.get("reason") or "").strip()
        # Drop the "Gate '...' fired — verdict (conf X):" prefix; keep the substance.
        if ":" in reason:
            reason = reason.split(":", 1)[1].strip()
        if reason:
            reasons.append(reason)
        for s in dossier.get("sources", []) or []:
            netloc = urlparse(s.get("url", "")).netloc.replace("www.", "")
            if netloc:
                domains[netloc] = domains.get(netloc, 0) + 1

    parts = [f"Recent kill-gates: {gate_summary}."]

    # When ONE gate dominates the kills, name the abstract structural rule behind it —
    # not just the per-idea instances below. Instance-only feedback is whack-a-mole: the
    # generator dodges yesterday's dead category and reinvents the same SHAPE in a new
    # sector. The dominant gate IS the pattern; stating it lets generation fix the shape.
    top_gate = sorted_gates[0][0]
    _STRUCTURAL_RULE = {
        "value_durability": (
            "DOMINANT FAILURE — value_durability: ideas keep dying because their value is "
            "already free/commoditised or is a predictable expense dressed as a product. The "
            "losing SHAPE is a middleman wrapper (insurance pool / concierge / marketplace / "
            "brokerage / registry / as-a-service) on a transparent market. Do not reskin it in "
            "a new sector — change the value-capture to a wedge an incumbent structurally cannot "
            "copy (proprietary compounding data, a licence/accreditation, a network effect, real "
            "switching cost, a captive channel, or owned technical IP)."),
        "incumbency": (
            "DOMINANT FAILURE — incumbency: a dominant incumbent already owns this space. Attack "
            "a niche the incumbent cannot serve without cannibalising itself, or change the payer."),
    }.get(top_gate)
    if _STRUCTURAL_RULE:
        parts.append(_STRUCTURAL_RULE)

    if domains:
        top = sorted(domains.items(), key=lambda x: x[1], reverse=True)[:5]
        parts.append(
            "Sources/incumbents that keep refuting ideas: "
            + ", ".join(d for d, _ in top) + "."
        )

    if reasons:
        # A few representative kill reasons (first sentence each), lightly deduped.
        seen: set[str] = set()
        examples: list[str] = []
        for rs in reasons:
            first = rs.split(". ")[0].strip().rstrip(".")
            key = first[:40].lower()
            if first and key not in seen:
                seen.add(key)
                examples.append(first[:160])
            if len(examples) >= 3:
                break
        if examples:
            parts.append("Why they died: " + " | ".join(examples) + ".")

    return " ".join(parts)


def blue_sky_failure_steer(fails: str) -> str:
    """Reframe domain-specific kill history for a SIGNAL-FREE (blue-sky) run.

    Fed raw, the kill log — which clusters in whatever domain the catalogue is
    saturated with — pins blue-sky generation right back into that same dead
    domain (observed: a no-signal run produced 8/8 UK-tax-compliance ideas). For
    blue-sky we INVERT it: the saturated area becomes a no-go zone and we mandate
    cross-sector spread, satisfying the Part 15B breadth KPI ("no single sector
    should dominate"). For signal-driven runs the raw failure modes are kept.
    """
    base = ("BLUE-SKY MANDATE: deliberately range across MANY UNRELATED sectors and "
            "geographies — no two ideas in the same domain; aim for >=6 distinct sectors. "
            "Treat the recently-killed / saturated area below as a NO-GO zone: do NOT "
            "propose anything in it or adjacent to it.")
    if fails and fails.strip():
        return base + "\nSaturated area to AVOID (not to 'out-think' — to leave entirely): " + fails
    return base
