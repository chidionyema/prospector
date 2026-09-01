#!/usr/bin/env python3
"""Fill `ambition_tier` on legacy dossiers, so the L1 ladder can price them at all.

WHY THIS EXISTS (measured 2026-08-06)
-------------------------------------
`prospector/classify.py::classify_tier` was written, tested (`tests/unit/test_multilane.py`) and
then never called from anything::

    $ git grep -n classify_tier -- '*.py'
    prospector/classify.py:36   def classify_tier(...)
    tests/unit/test_multilane.py:...   (only)

The obvious reading — "wire it into the pipeline" — is WRONG, and measuring first is what shows
it. The live pipeline already assigns a tier: `generate.py:640` sets `c.ambition_tier = tier`
inside `generate_multilane`. Counting dossiers by day proves the forward path is healthy::

    day         empty tier   set tier
    2026-08-06        0          3
    2026-08-05        0         42
    2026-08-04        0         15
    2026-08-02        0         28
    2026-08-01       28         74     <- last day any dossier was written without a tier
    2026-07-31       84         12

So the gap is a BACKLOG, not a leak, and a pipeline hook would fix nothing. What is actually
stuck is the back catalogue:

  * 97 of 154 PASS dossiers (63%) carry `ambition_tier = ""`.
  * `pricing.py:146` returns the default rung for an empty tier, deliberately: "guessing
    silently re-prices the back catalogue the moment the ladder lands."
  * `config.yaml listing.pricing.default_rung_index: 2` -> 4900.
  * Joining the live `/catalog` (61 packs) to `store/prospector.db` on candidate_id, 61/61
    matched: **38 packs have no tier and sit at exactly 4900**, while all 23 classified packs
    agree with the declared ladder to the penny, market offset included. Zero disagreements.

That last number is the point. The ladder is not broken and the prices it sets are not wrong —
62% of the shelf simply has no segment to be priced from. `classify_tier` is the right tool for
that, applied backwards over stored dossiers, which is what this script does.

WHAT THIS SCRIPT DOES NOT DO
----------------------------
It never touches price, Stripe, or the catalogue. It writes one field to local dossiers. The
repricing act is `scripts/backfill_ladder_prices.py`, which is Claude-only under the founder
fence because it mutates the money rail, and which reads the tier from `store/dossiers/` — i.e.
it is the consumer of this script's output. Keeping them separate is deliberate: retrieving a
segment and acting on it must not be the same command, for the same reason
`comparables.rung_adjust_enabled` is a second switch (CLAUDE.md, "evidence and action are
separate decisions").

Run order:

    .venv/bin/python scripts/backfill_tiers.py --only-live            # dry run, the 38 that matter
    .venv/bin/python scripts/backfill_tiers.py --only-live --apply    # write tiers
    .venv/bin/python scripts/backfill_ladder_prices.py                # then price them (dry run)

DO NOT RUN --apply AGAINST LIVE PACKS ON TODAY'S EVIDENCE (2026-08-06)
---------------------------------------------------------------------
The script is safe; the CLASSIFIER is not yet good enough to move money. Three measurements,
all reproducible with the probes in this repo:

1. WHICH BRAIN ANSWERS DECIDES THE ANSWER. A dry run over the 38 live untiered packs produced a
   clean-looking 23 smb / 15 side_hustle. Repeating the first three ids gave a different result
   for two of them. One JSON call to each configured brain explains it::

       deepseek    HTTP Error 402: Payment Required
       cursor_cli  ActionRequiredError: You've hit your usage limit
       minimax     OK      <- so every call was served by the emergency tail
       claude_cli  OK

   And minimax is not reproducible on this prompt: at temperature 0.0, 4 of 6 candidates
   returned a DIFFERENT tier across 3 repeat runs. claude_cli returned the identical answer
   18/18. (`classify.py:71` also called `complete_json` with no temperature at all, i.e. the
   0.7 default — creative sampling for a routing decision.) Chain order is fixed in
   `run.py:_NONCRITICAL_ORDER`; the reproducibility of the classifier is not fixed by that.

2. IT BARELY DISCRIMINATES. Against the 12 dossiers that already carry a tier, with the label
   blanked out of the prompt so it cannot be copied, claude_cli agreed 4/12 — against 25% for a
   coin on four classes. 0/3 venture and 0/3 growth were recovered; 11 of 12 predictions fell
   into the two cheapest tiers.

3. AND THE BIAS IS BY DESIGN, POINTING DOWNWARD. `prompts/classify.md:13` instructs: "When
   genuinely between two, pick the LOWER (more conservative) tier." That is correct for what the
   classifier was BUILT for — routing which gate set runs, where a lower tier means a HARDER bar
   (`classify.py:6`: "classification only routes which gate set runs, it never rules on
   evidence"). Feed the same field to the ladder and conservative inverts: lower tier = lower
   rung = a price CUT. The 38 packs sit at the default rung 4900 today, so this backfill can
   only ever move them to 2900 (side_hustle) or leave them at 4900 (smb) — it has no path to a
   rise. A one-way downward repricing driven by a 33%-accurate signal is not a derivation.

None of that is fixed by better plumbing, so it is not fixed here. What has to happen first is a
decision the founder owns: either the classify prompt gets a pricing-grade rubric and a golden
set that measures it (the repo already gates prompt changes that way — CLAUDE.md, "golden-set
regression gates all changes"), or price stops deriving from a routing label. Until then this
script is the safe instrument that is ready to run, and `--apply` on live packs is blocked on
evidence, not on effort.

`--apply` against non-live dossiers (dossiers nobody is selling) is a different risk entirely
and is fine: it fills the field for future ladder work without touching a price anyone pays.

KEEP-BIASED, AND THE FAILURE THIS SCRIPT ALMOST SHIPPED
------------------------------------------------------
`classify_tier` is keep-biased: on any failure it returns the tier the candidate already had.
For these candidates that is `""` — but only since 2026-08-06. The fallback used to read
`cand.ambition_tier or (allowed[0] if allowed else "")` (`classify.py:42`), so a tier-less
candidate got `active_lanes[0]` = "side_hustle" back from a raising brain, a junk answer, or an
empty answer alike — indistinguishable from a real classification::

    cand = Candidate.from_dict({"title": "legacy pack", "ambition_tier": ""})
    classify_tier(BrainThatRaises(), cand, cfg)     -> 'side_hustle'
    classify_tier(BrainReturningJunk(), cand, cfg)  -> 'side_hustle'
    classify_tier(BrainReturningEmpty(), cand, cfg) -> 'side_hustle'

side_hustle is rung 1 = 2900 against the empty tier's default rung 2 = 4900, so running this
backfill during a brain outage would have marked all 38 live untiered packs side_hustle and the
ladder script would then have cut every one of them by a third, on no evidence. Fixed at the
source (keep-biased means keep what you HAD; nothing had nothing) and pinned by
`tests/unit/test_multilane.py::test_a_candidate_with_no_tier_gets_no_tier_back_when_classification_fails`,
which fails against the pre-fix line.

So here an empty result means exactly one thing — unresolved — and is NEVER written. The dossier
is left as it was and the id is reported. A wrong tier moves a live pack's price; a missing tier
leaves it at the price the shelf already sells at.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from prospector.classify import classify_tier  # noqa: E402
from prospector.config import load_config  # noqa: E402
from prospector.models import Candidate  # noqa: E402

CATALOG_URL = (os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}") + "/catalog"
# The same chain the pipeline uses for generation/prescreen/score — imported, not re-declared,
# so this script cannot drift from production the way a copied tuple would.
from prospector.run import _NONCRITICAL_ORDER as NONCRITICAL_ORDER  # noqa: E402


def _fast_operator(cfg):
    from prospector.operator import FallbackOperator, _build_operator
    tiers = []
    for kind in NONCRITICAL_ORDER:
        try:
            tiers.append((kind, _build_operator(kind, cfg, fast=True)))
        except Exception as exc:  # noqa: BLE001 — a missing key raises whatever it raises
            print(f"  (skipping {kind}: {type(exc).__name__}: {exc})", file=sys.stderr)
    if not tiers:
        raise SystemExit(
            f"No non-critical brain available ({'/'.join(NONCRITICAL_ORDER)}). Refusing to fall "
            "back to a moat brain: classification is not a verdict and must not spend the moat."
        )
    r = cfg.retrieval
    return FallbackOperator(tiers, failure_threshold=r.breaker_failure_threshold,
                            cooldown_s=r.breaker_cooldown_s)


def _live_pack_ids() -> set[str]:
    with urllib.request.urlopen(CATALOG_URL, timeout=30) as fh:
        return {str(p["id"]) for p in json.load(fh)}


def _untiered(store_db: Path, decision: str | None) -> list[tuple[str, str]]:
    """(candidate_id, path) for dossiers whose ambition_tier is empty."""
    q = ("SELECT candidate_id, path FROM dossiers "
         "WHERE COALESCE(ambition_tier,'') = ''")
    args: tuple = ()
    if decision:
        q += " AND decision = ?"
        args = (decision,)
    with sqlite3.connect(store_db) as db:
        return [(r[0], r[1]) for r in db.execute(q + " ORDER BY created_at DESC", args)]


def _write_tier(path: Path, store_db: Path, candidate_id: str, tier: str) -> None:
    """Set the tier in the dossier JSON (both places it lives) and in the SQLite index.

    The field is duplicated on disk: `d["ambition_tier"]` and `d["candidate"]["ambition_tier"]`.
    Writing only one leaves the two disagreeing, and `backfill_ladder_prices.py` reads the
    dossier while `report.py`/`diagnostics.py` read the index — so a partial write would price
    off one value and report the other.
    """
    d = json.loads(path.read_text(encoding="utf-8"))
    d["ambition_tier"] = tier
    if isinstance(d.get("candidate"), dict):
        d["candidate"]["ambition_tier"] = tier
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash mid-write must not truncate a dossier
    with sqlite3.connect(store_db) as db:
        db.execute("UPDATE dossiers SET ambition_tier = ? WHERE candidate_id = ?",
                   (tier, candidate_id))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the tiers; without it nothing is modified")
    ap.add_argument("--only-live", action="store_true",
                    help="restrict to candidate ids present in the live /catalog")
    ap.add_argument("--allow-live-writes", action="store_true",
                    help="required to --apply to a dossier behind a pack that is on sale; see "
                         "the 'DO NOT RUN --apply AGAINST LIVE PACKS' section of this file")
    ap.add_argument("--decision", default="pass",
                    help="dossier decision to backfill (default: pass; '' for all)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N dossiers (0 = no limit)")
    args = ap.parse_args()

    cfg = load_config()
    store_db = Path(cfg.store_dir) / "prospector.db"
    if not store_db.exists():
        print(f"no store at {store_db}", file=sys.stderr)
        return 1

    rows = _untiered(store_db, args.decision or None)

    # The fence. A tier written here becomes a rung in scripts/backfill_ladder_prices.py, so a
    # dossier behind a pack that is ON SALE is money-adjacent even though this script never
    # touches a price. The catalogue is fetched whenever we are about to write, not only under
    # --only-live: the default (all untiered PASS dossiers) SUPERSETS the live ones, so gating
    # on the flag would let the broadest invocation through the narrowest check.
    live: set[str] = set()
    if args.only_live or args.apply:
        live = _live_pack_ids()
        print(f"live catalogue: {len(live)} packs")
    if args.only_live:
        rows = [r for r in rows if r[0] in live]
    if args.limit:
        rows = rows[:args.limit]

    if args.apply and not args.allow_live_writes:
        at_risk = [cid for cid, _ in rows if cid in live]
        if at_risk:
            print(f"\nREFUSING: {len(at_risk)} of these {len(rows)} dossiers sit behind packs "
                  f"that are on sale right now.\nA tier written here becomes a price rung in "
                  f"scripts/backfill_ladder_prices.py, and as measured on 2026-08-06 the "
                  f"classifier\nagrees with the existing labels 4/12 and can only move these "
                  f"packs DOWN from 4900 (see the\n'DO NOT RUN --apply AGAINST LIVE PACKS' "
                  f"section at the top of this file).\n\n"
                  f"  --decision pass --limit N   to work on non-live dossiers first, or\n"
                  f"  --allow-live-writes         to override deliberately.",
                  file=sys.stderr)
            return 2

    print(f"untiered dossiers to classify: {len(rows)}"
          f"{' (decision=' + args.decision + ')' if args.decision else ''}")
    if not rows:
        return 0
    if not args.apply:
        print("DRY RUN — no dossier or index row will be written. Re-run with --apply.\n")

    op = _fast_operator(cfg)
    resolved: dict[str, int] = {}
    unresolved: list[str] = []

    for cid, path_s in rows:
        path = Path(path_s)
        if not path.is_absolute():
            path = REPO / path
        if not path.exists():
            print(f"  ?  {cid}  dossier file missing: {path}")
            unresolved.append(cid)
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        cand = Candidate.from_dict(d.get("candidate") or {})
        tier = classify_tier(op, cand, cfg)
        if not tier:
            # Indistinguishable from "the brain did not answer" — see module docstring.
            print(f"  ✗  {cid}  unresolved (kept empty)  {cand.title[:52]}")
            unresolved.append(cid)
            continue
        resolved[tier] = resolved.get(tier, 0) + 1
        print(f"  →  {cid}  {tier:12} {cand.title[:52]}")
        if args.apply:
            _write_tier(path, store_db, cid, tier)

    print(f"\nresolved {sum(resolved.values())}, unresolved {len(unresolved)}")
    for t, n in sorted(resolved.items(), key=lambda kv: -kv[1]):
        print(f"   {t:12} {n:4d}")
    if args.apply:
        print("\nTiers written. Price is NOT changed by this script — next step:\n"
              "   .venv/bin/python scripts/backfill_ladder_prices.py         # dry run\n"
              "   .venv/bin/python scripts/backfill_ladder_prices.py --apply # money rail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
