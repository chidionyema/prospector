#!/usr/bin/env python
"""E11 (corrected) — confidence-floor calibration.

METHODOLOGY CORRECTION over the first pass. `apply_gates` only ever fires the PER-CHECK
hard gates (value_durability, incumbency, payer_solvency, distribution, legality,
pain_reality) plus the adversarial flag. Kills recorded as `min_composite`,
`moat_ungrounded` or `source_or_die` fire in scoring/verify, DOWNSTREAM of apply_gates —
so a replay naturally does not reproduce them, and counting them as "freed by the floor"
would be an artefact of the harness, not a finding.

So the honest denominator is: kills that REPRODUCE under the shipped config (floor 0.0).
Those are the ones confidence_floor can actually move. Everything else is reported
separately and explicitly, not folded into a headline percentage.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path("/Users/chidionyema/Documents/code/prospector")
sys.path.insert(0, str(REPO))

from prospector.config import load_config  # noqa: E402
from prospector.kill_filter import apply_gates  # noqa: E402
from prospector.models import CheckResult, Verdict  # noqa: E402

FLOORS = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7]


def rebuild(c: dict) -> CheckResult:
    return CheckResult(
        check_name=c.get("check_name", ""),
        verdict=Verdict(c.get("verdict", "unverifiable")),
        confidence=float(c.get("confidence") or 0.0),
        rationale=c.get("rationale", "") or "",
        citations=list(c.get("citations") or []),
        sources=[], queries=list(c.get("queries") or []),
        degraded=bool(c.get("degraded")),
        retrieval_failed=bool(c.get("retrieval_failed")),
        provider=c.get("provider", "") or "",
    )


def main() -> int:
    base = load_config(str(REPO / "config.yaml"))
    lanes: dict = {}

    def cfg_for(t):
        if t not in lanes:
            try:
                lanes[t] = base.for_lane(t)
            except Exception:
                lanes[t] = base
        return lanes[t]

    reproducing = []      # (file, tier, gate, killer_conf, on_moat, checks, adv)
    non_reproducing = Counter()

    for f in sorted((REPO / "store" / "dossiers").glob("*.kill.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        raw = d.get("checks") or []
        if not raw:
            continue
        tier = d.get("ambition_tier")
        checks = [rebuild(c) for c in raw]
        adv = bool((d.get("adversarial") or {}).get("decisive")) if isinstance(d.get("adversarial"), dict) else False
        cfg = cfg_for(tier)
        cfg.thresholds.confidence_floor = 0.0
        killed, gate, _ = apply_gates(checks, cfg, adv)
        if not killed:
            non_reproducing[d.get("gate_fired") or "?"] += 1
            continue
        killer = next((c for c in checks if c.check_name == gate), None)
        prov = (killer.provider if killer else "").lower()
        reproducing.append((f.name, tier, gate,
                            killer.confidence if killer else 0.0,
                            prov.startswith("claude"), checks, adv))

    n = len(reproducing)
    print("=" * 78)
    print("E11 (CORRECTED) — CONFIDENCE-FLOOR CALIBRATION")
    print("=" * 78)
    print(f"kill dossiers whose gate REPRODUCES under the shipped config (floor 0.0): {n}")
    print(f"  of those, ruled by a brain still on the moat today: "
          f"{sum(1 for r in reproducing if r[4])}")
    print()
    print("NOT reproducible in apply_gates (they fire downstream — scoring/verify, NOT the")
    print("floor's business; listed so the number above is not mistaken for a kill audit):")
    for g, c in non_reproducing.most_common(8):
        print(f"    {g:<24} {c}")
    print()

    print(f"{'floor':>6} | {'still KILL':>10} | {'freed to scoring':>16} | {'% of reproducing':>17}")
    print("-" * 62)
    freed_by_gate = defaultdict(Counter)
    for fl in FLOORS:
        still = 0
        for fname, tier, gate, conf, moat, checks, adv in reproducing:
            cfg = cfg_for(tier)
            cfg.thresholds.confidence_floor = fl
            killed, g2, _ = apply_gates(checks, cfg, adv)
            if killed:
                still += 1
            else:
                freed_by_gate[fl][gate] += 1
        print(f"{fl:>6.1f} | {still:>10} | {n - still:>16} | {100.0*(n-still)/n:>16.1f}%")

    print()
    print("FREED, BY THE GATE THAT HAD FIRED:")
    for fl in (0.4, 0.5, 0.6):
        print(f"  floor {fl}: " + ", ".join(f"{g}={c}" for g, c in freed_by_gate[fl].most_common()))

    confs = sorted(r[3] for r in reproducing)
    if confs:
        def q(p):
            return confs[min(len(confs) - 1, int(p * len(confs)))]
        print()
        print(f"CONFIDENCE OF THE FIRING CHECK, reproducing kills only (n={len(confs)}):")
        print(f"  p10={q(.10):.2f}  p25={q(.25):.2f}  median={q(.50):.2f}  p75={q(.75):.2f}  p90={q(.90):.2f}")

    out = Path(__file__).with_name("e11_corrected_receipts.json")
    out.write_text(json.dumps({
        "reproducing": n,
        "on_current_moat": sum(1 for r in reproducing if r[4]),
        "non_reproducing_by_recorded_gate": dict(non_reproducing),
        "freed_by_floor": {str(f): dict(freed_by_gate[f]) for f in FLOORS},
        "killer_confidence_sorted": confs,
    }, indent=2))
    print(f"\nreceipts → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
