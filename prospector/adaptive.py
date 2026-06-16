"""Adaptive-creativity controller (Part 3).
Adjusts exploration_level based on the rolling kill-rate to find fresh niches.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Optional
from urllib.parse import urlparse

from .config import Config
from .models import Decision


def calculate_exploration_level(store: Store, cfg: Optional[Config] = None, 
                               window: int = 50) -> float:
    """Determine the creativity level (0.0 to 1.0) based on recent kill-rate.
    
    PERSONA-NORMALIZED (Part 16 principal upgrade): Different personas have 
    different baseline "severity". A 95% kill rate for the 'shark' is normal,
    but for a 'clinical auditor' it signals a failure in generative creativity.
    We normalize the actual kill rate against the persona's pass-bar.
    """
    rows = store.all()
    if not rows:
        return 0.5
    
    # Sort by creation date descending to get most recent
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    # Filter by the active persona if provided, to ensure we are comparing 
    # apples to apples.
    active_persona = cfg.active_persona if cfg else ""
    persona_rows = [r for r in rows if (r.get("persona") or "") == active_persona]
    
    # If not enough data for THIS persona, fall back to global but with 
    # a warning/adjustment.
    target_rows = persona_rows[:window] if len(persona_rows) >= 10 else rows[:window]
    
    if not target_rows:
        return 0.5

    kills = sum(1 for r in target_rows if r.get("decision") == Decision.KILL.value)
    kill_rate = kills / len(target_rows)
    
    # Baseline severity adjustment:
    # Shark (bar=3.8) -> expects ~95% kill
    # Default (bar=3.2) -> expects ~70% kill
    baseline = 0.7
    if cfg and active_persona:
        p_cfg = cfg.personas.get(active_persona) or {}
        p_thresh = p_cfg.get("thresholds", {}).get("min_composite_to_pass", 3.2)
        # Heuristic: every 0.1 above 3.2 adds 5% to the expected kill-rate baseline
        baseline = min(0.98, 0.7 + (max(0, p_thresh - 3.2) * 0.5))

    # Normalized deviation: how much are we killing compared to what we EXPECT?
    deviation = kill_rate - baseline

    # High deviation (>15% above baseline) -> Maximum exploration
    if deviation >= 0.15:
        return 1.0
    # Moderate deviation (>5% above baseline) -> High exploration
    if deviation >= 0.05:
        return 0.8
    # Negative deviation (lower kill rate than expected) -> Exploit current patterns
    if deviation <= -0.1:
        return 0.2
    
    # Default/Medium
    return 0.5


def calculate_persona_drift(store: Store, window: int = 50) -> dict[str, float]:
    """Calculate the 'Philosophy Delta' — how much personas disagree.
    
    Consensus Collapse occurs when all personas agree 100% of the time, 
    meaning they aren't providing distinct analytical value.
    Returns: {persona_pair: disagreement_rate}
    """
    # This requires looking at the audit log for ADVISORY BOARD DRIFT events
    # since the SQLite store only holds the final decision.
    drift_events = []
    jsonl_path = store._root / "prospector.jsonl"
    if not jsonl_path.exists():
        return {}

    total_board_vets = 0
    disagreements = Counter()

    for line in jsonl_path.read_text().splitlines():
        try:
            d = json.loads(line)
            if "ADVISORY BOARD" in d.get("message", ""):
                total_board_vets += 1
                if "differs" in d.get("message", ""):
                    shadow = d.get("shadow_persona", "unknown")
                    disagreements[shadow] += 1
        except Exception:
            pass
    
    if total_board_vets == 0:
        return {}

    return {p: count / total_board_vets for p, count in disagreements.items()}


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


def get_recent_failure_modes(store: Store, cfg: Optional[Config] = None, 
                             window: int = 20) -> str:
    """Summarise WHY recent ideas died — not just which gate fired.

    The gate name alone ("value_durability (16)") tells the generator nothing
    actionable; it cannot out-think a wall it is never shown. So we also mine the
    actual kill *reasons* and the *sources/incumbents* that keep refuting ideas
    (loaded from the per-dossier JSON, which the index row omits). This is the
    learning signal: it lets generation pivot the value-capture model away from a
    commoditised category instead of re-submitting the same dead shape.
    """
    active_persona = cfg.active_persona if cfg else ""
    rows = store.all(decision=Decision.KILL.value)
    
    # Persona-specific learning (Part 16 principal upgrade)
    persona_rows = [r for r in rows if (r.get("persona") or "") == active_persona]
    target_rows = persona_rows[:window] if len(persona_rows) >= 5 else rows[:window]

    target_rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent = target_rows[:window]
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
    """
    all_pass = store.all(decision=Decision.PASS.value)
    all_kill = store.all(decision=Decision.KILL.value)
    
    if not all_pass and not all_kill:
        return ""

    exemplars = []

    # 1. Top Winners — load full dossier for one_liner
    winners = sorted(all_pass, key=lambda x: x.get("composite") or 0.0, reverse=True)[:3]
    for w in winners:
        cid = w.get("candidate_id", "")
        dossier = store.get(cid) if cid else None
        cand = (dossier or {}).get("candidate", {}) if dossier else {}
        one_liner = cand.get("one_liner", "") or w.get("one_liner", "")
        title = cand.get("title", "") or w.get("title", "")
        comp = w.get("composite", 0)
        exemplars.append(f"PASS (Score {float(comp):.1f}): {title} - {one_liner}")

    # 2. Decisive Kills (Feedback on what to avoid)
    decisive_kills = sorted(all_kill, key=lambda x: x.get("adversarial_confidence") or 0.0, reverse=True)[:2]
    for k in decisive_kills:
        reason = "Critique decisive"
        if k.get("gate_fired"):
            reason = f"Killed by {k['gate_fired']}"
        cid = k.get("candidate_id", "")
        dossier = store.get(cid) if cid else None
        cand = (dossier or {}).get("candidate", {}) if dossier else {}
        one_liner = cand.get("one_liner", "") or k.get("one_liner", "")
        title = cand.get("title", "") or k.get("title", "")
        exemplars.append(f"KILL ({reason}): {title} - {one_liner}")

    if not exemplars:
        return ""

    return "\nFEEDBACK FROM HISTORIC VERIFICATIONS (Learn from these):\n" + "\n".join(f"- {e}" for e in exemplars)


def get_pass_traits(store, n: int = 20) -> str:
    """Extract common traits from PASS survivors for positive learning.

    Analyzes recent PASS dossiers for:
      - sectors (tags.sector)
      - structural forms (structural_form)
      - audience personas (tags.audience)
      - durable wedge types (from hypotheses and tags)

    Returns a compact summary string for injection into generation prompts,
    or "" when no PASSes exist (graceful degradation).
    """
    all_pass = store.all(decision=Decision.PASS.value)
    if not all_pass:
        return ""

    recent = sorted(all_pass, key=lambda x: x.get("created_at", ""), reverse=True)[:n]

    sectors: dict[str, int] = {}
    forms: dict[str, int] = {}
    audiences: dict[str, int] = {}
    wedges: dict[str, int] = {}
    titles_one_liners: list[str] = []

    _WEDGE_KEYWORDS = [
        "proprietary_data", "regulatory_license", "network_effect",
        "switching_cost", "exclusive_channel", "technical_ip",
        "regulatory", "arbitrage", "compliance", "statutory",
        "adjudication", "captive", "embedded", "compounding",
    ]

    for r in recent:
        cid = r.get("candidate_id", "")
        dossier = store.get(cid) if cid else None
        if not dossier:
            continue
        cand = dossier.get("candidate", {})
        if not cand:
            continue

        # Sector
        tags = cand.get("tags", {}) or {}
        sector = str(tags.get("sector", "") or "").strip().lower()
        if sector:
            sectors[sector] = sectors.get(sector, 0) + 1

        # Structural form — check both row level and candidate dict
        form = str(r.get("structural_form", "") or cand.get("structural_form", "") or "").strip().lower()
        if form:
            forms[form] = forms.get(form, 0) + 1

        # Audience
        aud = str(tags.get("audience", "") or "").strip().lower()
        if aud:
            audiences[aud] = audiences.get(aud, 0) + 1

        # Wedge type — mine from hypothesis and durable_wedge_type field
        hypothesis = str(cand.get("hypothesis", "") or "").lower()
        wedge_field = str(cand.get("durable_wedge_type", "") or "").strip().lower()
        if wedge_field and wedge_field != "none":
            wedges[wedge_field] = wedges.get(wedge_field, 0) + 1
        for kw in _WEDGE_KEYWORDS:
            if kw in hypothesis:
                wedges[kw] = wedges.get(kw, 0) + 1

        # Title + one_liner for pattern extraction
        tl = f"{cand.get('title', '')} — {cand.get('one_liner', '')}"
        if tl.strip():
            titles_one_liners.append(tl[:120])

    parts: list[str] = []
    top_sectors = sorted(sectors.items(), key=lambda x: x[1], reverse=True)[:3]
    top_forms = sorted(forms.items(), key=lambda x: x[1], reverse=True)[:3]
    top_audiences = sorted(audiences.items(), key=lambda x: x[1], reverse=True)[:3]
    top_wedges = sorted(wedges.items(), key=lambda x: x[1], reverse=True)[:3]

    parts.append("SURVIVOR PATTERNS — ideas that ACTUALLY PASSED the moat share these traits:")
    if top_sectors:
        parts.append(f"  Sectors: {', '.join(f'{s}({c})' for s, c in top_sectors)}")
    if top_forms:
        parts.append(f"  Forms: {', '.join(f'{f}({c})' for f, c in top_forms)}")
    if top_audiences:
        parts.append(f"  Audiences: {', '.join(f'{a}({c})' for a, c in top_audiences)}")
    if top_wedges:
        parts.append(f"  Wedges: {', '.join(f'{w}({c})' for w, c in top_wedges)}")

    if titles_one_liners:
        parts.append("  Examples (real PASS survivors):")
        for t in titles_one_liners[:3]:
            parts.append(f"    - {t}")

    return "\n".join(parts)


def calculate_grid_priorities(store: Store, cfg: Config) -> dict[str, list[str]]:
    """Stage 3: Identify underrepresented AND fertile (tier x form) cells.

    Returns a dict {tier: [priority_forms]} to bias the scheduler.
    Underrepresented forms (zero PASSes) get top priority.
    Fertile forms (highest PASS counts) get boosted — repeated 2-3x
    in the priority list so they get more generation budget.
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
            
    # Identify priorities: zero-count forms first, then fertile forms boosted
    priorities: dict[str, list[str]] = {}
    for tier, forms in grid.items():
        if not forms:
            continue
        tier_priorities: list[str] = []

        # 1. Zero-count forms (exploration — need at least one PASS)
        zero_forms = [f for f, count in forms.items() if count == 0]
        tier_priorities.extend(zero_forms)

        # 2. Fertile forms (exploitation — boost what works)
        nonzero = [(f, count) for f, count in forms.items() if count > 0]
        if nonzero:
            nonzero.sort(key=lambda x: x[1], reverse=True)
            # Boost the top 2 fertile forms: repeat top 3x, second 2x
            if len(nonzero) >= 1:
                tier_priorities.extend([nonzero[0][0]] * 3)
            if len(nonzero) >= 2:
                tier_priorities.extend([nonzero[1][0]] * 2)

        if tier_priorities:
            priorities[tier] = tier_priorities
            
    return priorities
