"""Self-diagnostics for filter calibration — so calibration is *watched*, not
hand-checked. Two tiers:

  1. calibration_alarms(store, cfg)  — FREE, no model calls. Reads the catalogue and
     flags calibration pathologies the moment they appear.
     Lane-aware: each alarm reports per-lane kill rates separately so a dominant
     gate in one lane is not masked by different patterns in another.

  2. run_calibration(cfg)            — uses the PRODUCTION failover chain against
     fixed golden evidence (deterministic, no live web). Returns discrimination
     + per-case expected-vs-actual gate confusion list + a pass/fail vs a floor.

Neither tier hand-pins a provider: the brain is whatever the config chain resolves to,
so diagnostics keep working when one provider's quota is exhausted (it just fails over).
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .store import Store

# An alarm is {level: "alarm"|"warn", code, message, lane: Optional[str]}
# lane=None means the alarm spans the whole catalogue; lane="X" means it is lane-specific.
Alarm = dict[str, Any]


def _gate_map_for_lane(cfg: Config, lane: Optional[str]) -> dict[str, list[str]]:
    """Return the gate map for a specific lane (or the default gates if no lane set)."""
    if lane and lane in (cfg.lanes or {}):
        lane_cfg = cfg.lanes[lane]
        gates: list[dict[str, Any]] = lane_cfg.get("hard_gates") or []
    else:
        gates = cfg.hard_gates
    out: dict[str, list[str]] = {}
    for g in gates:
        for k, v in g.items():
            if k != "adversarial_decisive":
                out[k] = list(v)
    return out


def calibration_alarms(store: Store, cfg: Config, *,
                      dominance_threshold: float = 0.85,
                      min_sample: int = 5) -> list[Alarm]:
    """Flag calibration pathologies from the catalogue. No model calls.

    All alarms are lane-aware: if the catalogue mixes ambition tiers, each lane's
    kill-rate and gate distribution is reported separately so a dominant gate in
    one lane does not mask different patterns in another.
    """
    alarms: list[Alarm] = []

    # ── Catalogue-wide metrics (all decisions) ───────────────────────────────────
    all_rows = store.all()
    if not all_rows:
        return alarms

    # ── Per-lane breakdown ─────────────────────────────────────────────────
    # Group rows by ambition_tier (indexed in the SQLite store).
    by_lane: dict[str, list[dict]] = {}
    for r in all_rows:
        lane = r.get("ambition_tier") or ""
        by_lane.setdefault(lane, []).append(r)

    # Also check the raw dossier JSON for any that missed the index (backwards compat).
    # Load from JSON only for lanes with no indexed data.
    indexed_ids = {r["candidate_id"] for r in all_rows}
    for f in store._dossier_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            cid = d.get("candidate", {}).get("candidate_id", "")
            if cid in indexed_ids:
                continue
            lane = d.get("candidate", {}).get("ambition_tier", "") or ""
            by_lane.setdefault(lane, []).append(d)
        except Exception:
            pass

    for lane, rows in sorted(by_lane.items()):
        alarms.extend(_lane_alarms(rows, lane, cfg, dominance_threshold, min_sample))

    # ── Catalogue-wide structural quality alarms ───────────────────────────────
    # These span all lanes and flag generation quality, not calibration.
    alarms.extend(_generation_quality_alarms(store))

    return alarms


def _lane_alarms(rows: list[dict], lane: str, cfg: Config,
                  dominance_threshold: float, min_sample: int) -> list[Alarm]:
    """Compute alarms for one lane. Returns a list (may be empty)."""
    alarms: list[Alarm] = []
    n = len(rows)
    if n < min_sample:
        return alarms  # not enough data to judge this lane

    dec = Counter((r.get("decision") or "?").lower() for r in rows)
    n_pass = dec.get("pass", 0)
    n_kill = dec.get("kill", 0)
    n_defer = dec.get("defer", 0)
    ruled = n_pass + n_kill  # defers never reached a verdict
    kill_rate = n_kill / ruled if ruled else 0.0
    lane_label = f"[{lane}] " if lane else "[all] "

    # ── zero-yield: nothing survives over a meaningful sample ──────────────
    if ruled >= min_sample and n_pass == 0:
        # NOT a calibration bug: check whether generation is the problem first.
        # If form diversity is low and the dominant gate is value_durability, the
        # generator is producing wrappers that the filter correctly kills.
        forms = _structural_forms_in(rows)
        gates = Counter(r.get("gate_fired") or r.get("gate_fired") or "min_composite"
                       for r in rows if (r.get("decision") or "").lower() == "kill")
        top_gate = gates.most_common(1)[0] if gates else (None, 0)
        vd_share = gates.get("value_durability", 0) / n_kill if n_kill else 0.0
        low_form_diversity = len(forms) <= 2 and n_kill >= 3
        if vd_share >= 0.7 and low_form_diversity:
            message = (
                f"0 PASS across {ruled} {lane_label}ruled candidates — "
                f"but {top_gate[0]!r} fired {vd_share:.0%} of kills and only "
                f"{len(forms)} structural form(s) seen. "
                f"Root cause is GENERATION QUALITY (generator keeps producing the "
                f"same dead shape), not calibration. Fix the signal/diversity axis."
            )
        elif vd_share >= 0.5:
            message = (
                f"0 PASS across {ruled} {lane_label}ruled candidates. "
                f"value_durability dominates ({vd_share:.0%} of kills). "
                f"Possible generator monoculture or genuine selectivity problem. "
                f"Check signal diversity and anti-obvious rules."
            )
        else:
            message = (
                f"0 PASS across {ruled} {lane_label}ruled candidates — "
                f"investigate whether this reflects genuine selectivity or "
                f"a calibration regression."
            )
        alarms.append({"level": "alarm", "code": "zero_yield",
                      "message": message, "lane": lane or None,
                      "kill_rate": kill_rate, "n_ruled": ruled, "n_pass": n_pass})

    # ── gate-dominance: one gate executes almost all kills ─────────────────
    kill_gates = Counter(r.get("gate_fired") or r.get("gate_fired") or "min_composite"
                        for r in rows if (r.get("decision") or "").lower() == "kill")
    if n_kill >= min_sample and kill_gates:
        top_gate, top_n = kill_gates.most_common(1)[0]
        share = top_n / n_kill
        # Only alarm if this gate is NOT configured to dominate this lane
        # (i.e., it's dominating by accident, not by design).
        expected_gates = set(_gate_map_for_lane(cfg, lane or None).keys())
        if top_gate not in expected_gates and share >= dominance_threshold:
            alarms.append({
                "level": "alarm", "code": "gate_dominance",
                "message": (
                    f"{lane_label}{top_gate!r} fired {top_n}/{n_kill} kills "
                    f"({share:.0%}) — exceeds the {dominance_threshold:.0%} threshold "
                    f"and is not the expected dominant gate for this lane. "
                    f"It may be masking other gate failures under kill-fast."
                ),
                "lane": lane or None,
                "top_gate": top_gate,
                "share": share,
                "n_kill": n_kill,
            })

    # ── dead-gate: a configured gate has never fired in this lane ─────────
    configured = set(_gate_map_for_lane(cfg, lane or None).keys())
    fired = {g for g in kill_gates if g in configured}
    dead = configured - fired
    if ruled >= min_sample and dead:
        # Distinguish intentionally-non-decisive gates from truly dead ones.
        # legality and pain_reality in venture lane are often unverifiable — not dead.
        quiet_ok = {"legality", "pain_reality"} if not lane else set()
        genuinely_dead = dead - quiet_ok
        if genuinely_dead:
            alarms.append({
                "level": "warn", "code": "dead_gate",
                "message": (
                    f"{lane_label}configured gate(s) never fired: "
                    f"{sorted(genuinely_dead)} — untested discrimination "
                    f"(may be unreachable behind kill-fast)."
                ),
                "lane": lane or None,
                "dead_gates": sorted(genuinely_dead),
            })

    return alarms


def _structural_forms_in(rows: list[dict]) -> set[str]:
    """Extract structural forms seen in a set of rows (index or JSON)."""
    forms: set[str] = set()
    for r in rows:
        # Canonical first-class field (dossier index column + candidate field).
        # The legacy tags["form:*"] scan below is back-compat for pre-field rows.
        sform = r.get("structural_form")
        if sform:
            forms.add(str(sform))
        cand = r.get("candidate")
        if isinstance(cand, dict) and cand.get("structural_form"):
            forms.add(str(cand["structural_form"]))

        tags = r.get("tags", {})
        if isinstance(tags, dict):
            for k in tags:
                if k.startswith("form:"):
                    v = tags[k]
                    forms.add(str(v) if v else k.replace("form:", ""))
        elif isinstance(tags, list):
            for item in tags:
                if isinstance(item, str) and item.startswith("form:"):
                    forms.add(item.replace("form:", ""))
    return forms


def _generation_quality_alarms(store: Store) -> list[Alarm]:
    """Flag generation-quality problems that are NOT calibration bugs.

    These are observable from the catalogue alone without any model calls.
    """
    alarms: list[Alarm] = []
    rows = store.all()
    if len(rows) < 5:
        return alarms

    # ── Structural form diversity ───────────────────────────────────────────
    forms = _structural_forms_in(rows)
    if len(forms) <= 2 and len(rows) >= 10:
        alarms.append({
            "level": "warn", "code": "low_form_diversity",
            "message": (
                f"Only {len(forms)} structural form(s) across {len(rows)} candidates — "
                f"forms: {sorted(forms)}. "
                f"The generator may be collapsing to one shape. "
                f"Check signal diversity and the structural-form rotation logic."
            ),
            "lane": None,
            "forms": sorted(forms),
            "n_candidates": len(rows),
        })

    # ── No PASS candidates across the whole catalogue ──────────────────────
    dec = Counter((r.get("decision") or "?").lower() for r in rows)
    if dec["pass"] == 0 and len(rows) >= 10:
        # Check whether it's a generation problem vs. a filter problem.
        gates = Counter(r.get("gate_fired") or "min_composite"
                       for r in rows if (r.get("decision") or "").lower() == "kill")
        top_gate = gates.most_common(1)[0] if gates else (None, 0)
        alarms.append({
            "level": "alarm", "code": "catalogue_zero_pass",
            "message": (
                f"Entire catalogue ({len(rows)} candidates) has 0 PASS — "
                f"top kill gate: {top_gate[0]!r} ({top_gate[1]} kills). "
                f"Check: (1) Is the signal producing the right diversity of ideas? "
                f"(2) Are the anti-obvious rules specific enough? "
                f"(3) Is value_durability killing on silence (unverifiable)? "
                f"This is a generation + calibration joint diagnostic — both axes need review."
            ),
            "lane": None,
            "n": len(rows),
            "top_gate": top_gate[0],
        })

    return alarms


def render_alarms(alarms: list[Alarm]) -> str:
    if not alarms:
        return "  ✓ calibration: no pathologies detected"
    glyph = {"alarm": "🚨", "warn": "⚠️"}
    by_lane: dict[str | None, list[Alarm]] = {}
    for a in alarms:
        by_lane.setdefault(a.get("lane"), []).append(a)
    lines = []
    for lane_key, lane_alarms in sorted(by_lane.items(), key=lambda x: (x[0] is not None, x[0] or "")):
        if lane_key:
            lines.append(f"  ── lane: {lane_key!r} ──")
        for a in lane_alarms:
            g = glyph.get(a.get("level", "warn"), "•")
            lines.append(f"  {g} [{a['code']}] {a['message']}")
    return "\n".join(lines)


def run_calibration(cfg: Config,
                    golden_set_path: str = "fixtures/golden_set.json",
                    golden_fixtures_path: str = "fixtures/golden_fixtures.json",
                    floor: float = 0.75) -> dict[str, Any]:
    """Run the golden set through the PRODUCTION brain chain against fixed evidence.

    Returns {discrimination, floor, ok, cases:[{idea, expected, actual,
    expected_gate, actual_gate, passed, lane}].  Deterministic grounding (fixtures), so the
    only variable under test is the brain + prompts + gate config.
    """
    from .golden import run_golden_set
    from .operator import make_operator
    from .retrieval import make_provider

    diag_cfg = copy.deepcopy(cfg)
    diag_cfg.retrieval.provider = "fixture"
    diag_cfg.retrieval.cache = False

    fixtures = json.loads(Path(golden_fixtures_path).read_text(encoding="utf-8"))
    op = make_operator(diag_cfg)
    search = make_provider(diag_cfg, fixtures=fixtures)

    discrimination, results = run_golden_set(op, search, diag_cfg, golden_set_path)
    cases = [{
        "idea": r.get("idea") or r.get("title"),
        "expected": r.get("expected_decision"),
        "actual": r.get("actual_decision"),
        "expected_gate": r.get("expected_gate"),
        "actual_gate": r.get("actual_gate"),
        "passed": r.get("passed"),
        "lane": r.get("lane", ""),
    } for r in results]
    return {"discrimination": discrimination, "floor": floor,
            "ok": discrimination >= floor, "cases": cases}


def render_calibration(report: dict[str, Any]) -> str:
    out = ["═" * 72, "CALIBRATION HARNESS (real brain · fixed golden evidence)", "═" * 72,
           f"  discrimination   {report['discrimination']:.0%}   (floor {report['floor']:.0%})  "
           f"{'✅ OK' if report['ok'] else '🚨 REGRESSION'}", ""]
    for c in report["cases"]:
        mark = "✅" if c["passed"] else "❌"
        lane_tag = f"  [{c.get('lane', '')}]" if c.get('lane') else ""
        gate_diff = (f"  gate exp={c.get('expected_gate', '')} got={c.get('actual_gate', '')}"
                     if not c["passed"] else "")
        out.append(f"  {mark} expect={c['expected']:<4} got={c['actual']:<4}{lane_tag}  {c['idea']}{gate_diff}")
    return "\n".join(out)
