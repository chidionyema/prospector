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
        # Hard exclusion, not a footnote: these domains are the recurring CAPTURERS the
        # value_durability gate keeps citing to prove value is already taken. The model
        # cannot retrieve at generation time, so hand it the wall directly — anything
        # whose core value these already supply is dead on arrival; do not propose it.
        parts.append(
            "PROVEN CAPTURERS — these already supply this value (free, first-party, or as "
            "an established product) and keep killing ideas: " + ", ".join(d for d, _ in top)
            + ". Do NOT propose any idea whose core value any of them already provides; your "
            "wedge must sit OUTSIDE what they offer or pick a different problem entirely."
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


def get_exemplars(store: Store, op: Optional[Operator] = None, n: int = 5) -> str:
    """Stage 2: Retrieve top winners and decisive kills as few-shot exemplars.
    
    Includes:
      - Top 2 PASSes by composite score.
      - Top 2 Decisive Kills (adversarial certainty).
      - 1 Diverse PASS (via DPP if op provided).
    """
    all_pass = store.all(decision=Decision.PASS.value)
    all_kill = store.all(decision=Decision.KILL.value)
    
    if not all_pass and not all_kill:
        return ""

    exemplars = []

    # 1. Top Winners
    winners = sorted(all_pass, key=lambda x: x.get("composite") or 0.0, reverse=True)[:2]
    for w in winners:
        exemplars.append(f"PASS (Score {w.get('composite'):.1f}): {w['title']} - {w['one_liner']}")

    # 2. Diverse Winner (DPP-ish)
    if op and len(all_pass) > 2:
        from .novelty import select_diverse_candidates
        # Exclude the winners we already picked
        winner_ids = {w["candidate_id"] for w in winners}
        diverse_pool = []
        for p in all_pass:
            if p["candidate_id"] not in winner_ids:
                # Mock candidate for DPP
                from .models import Candidate
                c = Candidate(title=p["title"], one_liner=p["one_liner"])
                diverse_pool.append((c, p.get("composite") or 1.0, ""))
        
        if diverse_pool:
            diverse = select_diverse_candidates(op, diverse_pool, k=1)
            for d in diverse:
                exemplars.append(f"PASS (Diverse): {d.title} - {d.one_liner}")

    # 3. Decisive Kills (Feedback on what to avoid)
    decisive_kills = sorted(all_kill, key=lambda x: x.get("adversarial_confidence") or 0.0, reverse=True)[:2]
    for k in decisive_kills:
        reason = "Critique decisive"
        if k.get("gate_fired"):
            reason = f"Killed by {k['gate_fired']}"
        exemplars.append(f"KILL ({reason}): {k['title']} - {k['one_liner']}")

    if not exemplars:
        return ""

    return "\nFEEDBACK FROM HISTORIC VERIFICATIONS (Learn from these):\n" + "\n".join(f"- {e}" for e in exemplars)


def calculate_grid_priorities(store: Store, cfg: Config) -> dict[str, list[str]]:
    """Stage 3: Identify underrepresented (tier x form) cells.
    
    Returns a dict {tier: [underrepresented_forms]} to bias the scheduler.
    """
    rows = store.all(decision=Decision.PASS.value)
    
    # Grid: tier -> form -> count
    grid: dict[str, dict[str, int]] = {}
    
    # Initialize grid from config
    active_lanes = getattr(cfg, "active_lanes", ["venture"]) or ["venture"]
    for lane in active_lanes:
        grid[lane] = {}
        lane_cfg = cfg.for_lane(lane)
        forms = lane_cfg.generation.get("structural_forms", [])
        for f in forms:
            grid[lane][f] = 0

    # Populate from store
    for r in rows:
        tier = r.get("ambition_tier") or "venture"
        form = r.get("structural_form")
        if tier in grid and form in grid[tier]:
            grid[tier][form] += 1
            
    # Identify priorities: forms with 0 passes in that tier
    priorities: dict[str, list[str]] = {}
    for tier, forms in grid.items():
        if not forms:
            continue
        # Find forms with zero passes
        empty = [f for f, count in forms.items() if count == 0]
        if empty:
            priorities[tier] = empty
        else:
            # If none are empty, target the ones with the minimum count
            min_count = min(forms.values())
            priorities[tier] = [f for f, count in forms.items() if count == min_count]
            
    return priorities
