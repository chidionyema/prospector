#!/usr/bin/env python3
"""Q4b.2 — is the live £49 pack's evidence recoverable, or does it rest on the stats farm?

§25.2 established that `d8aa7528aa73eabb` ("StorefrontShield", £49, live) has two checks
citing `gitnux.org` — a `stats_farm` — and that BOTH remain admissible under the shipped
`P1_check_aware` policy, because a weak source arrived alongside plausible ones. The gate is
RULING-level; source-or-die is CLAIM-level; the pack sits in that gap.

The founder's decision was "re-vet, then decide". This probe is what should run BEFORE that
re-vet, because it can make the re-vet unnecessary or make it obviously necessary, at zero
cost. It asks the one question the ruling-level gate structurally cannot:

    Do the pack's headline FIGURES appear in any passage that is NOT the stats farm?

Two outcomes, and they imply different actions:

  * RECOVERABLE — every figure also appears in an admissible passage. The stats farm was
    corroboration, not the source. The ruling stands on evidence that survives the gate, and
    the remedy is an annotation (drop the gitnux citation), not a re-vet.
  * SOLE-BASIS — a figure appears ONLY in the stats-farm passage. Then the rationale a buyer
    paid £49 for rests, for that number, on a page that self-describes as a "statistics
    snapshot ... for a stable visual baseline". No re-vet of the same retrieved corpus can
    fix that; it needs fresh retrieval or a delist.

Read-only, offline, zero LLM, zero network. Tiering comes from `prospector.admissibility` —
the SAME module the shipped gate uses, never a second copy, so this cannot disagree with the
gate about what a `stats_farm` is.

Usage:
    .venv/bin/python tools/experiments/q4b2_storefrontshield_figures.py
    .venv/bin/python tools/experiments/q4b2_storefrontshield_figures.py --id <candidate_id>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prospector import admissibility  # noqa: E402
from prospector.paths import repo_path  # noqa: E402

DEFAULT_ID = "d8aa7528aa73eabb"

# A figure is a number that carries a claim. Bare years are dates, not claims, and matching
# them would drown the signal — "in 2024" is in every passage on the web.
_FIGURE_RE = re.compile(
    r"(?<![\w.])"
    r"(?:[£$€]\s?\d[\d,]*(?:\.\d+)?\s*(?:k|m|bn|billion|million|thousand)?"
    r"|\d[\d,]*(?:\.\d+)?\s*%"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:x|per\s+\d+|per\s+cent)"
    r"|\d[\d,]*(?:\.\d+)?)"
    r"(?![\w.])",
    re.I,
)
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def normalise(surface: str) -> set[str]:
    """Every string form the same quantity might legitimately take in a passage.

    `1,761` must match `1761`; `£1.2m` must match `1.2 million` and `1200000`. Without this
    the check reports "not in any passage" for a figure that is plainly there, which is the
    false-positive direction that would make the whole probe untrustworthy.
    """
    s = surface.strip().lower()
    forms = {s}
    bare = re.sub(r"[£$€,\s]", "", s)
    forms.add(bare)
    m = re.match(r"^([\d.]+)\s*(k|m|bn|billion|million|thousand)?", bare)
    if m and m.group(1):
        try:
            val = float(m.group(1))
        except ValueError:
            return forms
        mult = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6,
                "bn": 1e9, "billion": 1e9}.get(m.group(2) or "", 1)
        exact = val * mult
        if exact == int(exact):
            n = int(exact)
            forms.add(str(n))
            forms.add(f"{n:,}")
        forms.add(str(val))
        if val == int(val):
            forms.add(str(int(val)))
    return {f for f in forms if f}


def figures_in(text: str, ignore_years: bool = True) -> list[str]:
    out: list[str] = []
    for m in _FIGURE_RE.finditer(text or ""):
        surface = m.group(0).strip()
        digits = re.sub(r"[^\d]", "", surface)
        if ignore_years and _YEAR_RE.match(digits or "") and not re.search(r"[£$€%x]", surface):
            continue
        if not digits:
            continue
        out.append(surface)
    return out


def passage_contains(passage: str, surface: str) -> bool:
    hay = (passage or "").lower()
    hay_bare = re.sub(r"[,\s]", "", hay)
    for form in normalise(surface):
        if form in hay or re.sub(r"[,\s]", "", form) in hay_bare:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default=DEFAULT_ID)
    ap.add_argument("--policy", default="P1_check_aware")
    args = ap.parse_args()

    path = repo_path("store", "dossiers", f"{args.id}.pass.json")
    if not path.exists():
        print(f"FATAL: no PASS dossier at {path}", file=sys.stderr)
        return 2
    dossier = json.loads(path.read_text())

    rows = []
    for check in dossier.get("checks") or []:
        name = check.get("check_name", "?")
        sources = check.get("sources") or []
        # Tier every source through the shipped module, never a local copy of the rules.
        tiered = []
        for s in sources:
            url = s.get("url") or s.get("link") or ""
            tier = admissibility.tier(admissibility.host_of(url))
            tiered.append({"url": url, "tier": tier, "text": s.get("text") or ""})

        rationale = check.get("rationale") or ""
        for surface in sorted(set(figures_in(rationale))):
            hits = [t for t in tiered if passage_contains(t["text"], surface)]
            # LOW_TIERS is the shipped set (`ugc_social`, `reference_noise`, `stats_farm`);
            # reusing it means this probe cannot drift from the gate's own idea of "weak".
            clean = [h for h in hits if h["tier"] not in admissibility.LOW_TIERS]
            rows.append({
                "check": name,
                "verdict": check.get("verdict"),
                "figure": surface,
                "in_any_passage": bool(hits),
                "in_admissible_passage": bool(clean),
                "matched_urls": [h["url"] for h in hits],
                "admissible_urls": [h["url"] for h in clean],
            })

    untraceable = [r for r in rows if not r["in_any_passage"]]
    sole_basis = [r for r in rows if r["in_any_passage"] and not r["in_admissible_passage"]]
    recoverable = [r for r in rows if r["in_admissible_passage"]]

    print(f"=== Q4b.2 · {args.id} · {dossier.get('candidate', {}).get('title', '?')}")
    print(f"figures examined            : {len(rows)}")
    print(f"in NO retrieved passage     : {len(untraceable)}  (invented — §25.5 class)")
    print(f"ONLY in a low-tier passage  : {len(sole_basis)}  (sole-basis on a stats farm/UGC)")
    print(f"in an admissible passage    : {len(recoverable)}  (recoverable — annotate, don't re-vet)")
    print()
    for label, group in (("UNTRACEABLE", untraceable), ("SOLE-BASIS LOW-TIER", sole_basis)):
        for r in group:
            print(f"  [{label}] {r['check']}: {r['figure']!r}  matched={r['matched_urls']}")

    verdict = ("SOLE-BASIS" if (sole_basis or untraceable) else "RECOVERABLE")
    print(f"\nVERDICT: {verdict}")

    receipt = repo_path("tools", "experiments", "q4b2_storefrontshield_figures_receipts.json")
    receipt.write_text(json.dumps({
        "candidate_id": args.id,
        "policy": args.policy,
        "title": dossier.get("candidate", {}).get("title"),
        "counts": {
            "figures": len(rows),
            "untraceable": len(untraceable),
            "sole_basis_low_tier": len(sole_basis),
            "recoverable": len(recoverable),
        },
        "verdict": verdict,
        "rows": rows,
    }, indent=2))
    print(f"receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
