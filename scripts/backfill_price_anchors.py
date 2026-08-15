#!/usr/bin/env python3
"""Backfill cited price anchors onto PASS dossiers generated before the check existed.

Why: on 2026-08-14 the price ladder was challenged as "silly, predictable and unscientific",
and it is -- `config.yaml:1446` says so in its own words ("These numbers are a HYPOTHESIS, not
a finding"). The mechanism that would make it a finding already exists: `price_comparables`
retrieves CITED willingness-to-pay anchors for every idea that survives the gates. It just has
not run on most of the catalogue.

Measured 2026-08-14 across 135 pass dossiers:
    dated 2026-08-06 -> 08-14      24 of 24 carry the check   (100%)
    dated before 2026-08-06         0 of 38
    no date field (older still)     0 of 73
The check shipped on 2026-08-06 and has not missed a pass since. The 111 gaps are backlog that
predates the feature, NOT a retrieval failure -- which is why the fix is this script and not a
repair to `price_comparables`. Where it does run, 16 of 24 ideas yield usable numeric anchors.

Why this is safe to run over historical passes: the check is evidence-only and structurally
cannot change a verdict. `verify.py:1018-1024` attaches its output to `cand.tags` rather than to
`checks`, precisely so it can never reach kill_filter, apply_gates or the pass-ceiling logic;
`kill_filter.is_hard_fail` bars PRICING_CHECK outright. "No price page on the open web" is a
fact about the web, not about the idea. This script preserves that property by writing ONLY
`candidate.tags.price_comparables` and re-asserting afterwards that every other byte of the
dossier is unchanged -- a backfill that silently re-rules a published pack would be far worse
than no backfill at all.

It does NOT reprice anything. Anchors are evidence; letting them move a rung is a separate,
deliberately separate switch (`comparables.rung_adjust_enabled`, false by default), and a
catalogue row and its Stripe Price object are minted together by one PriceDecision, so nothing
here may touch a live price.

    python3 scripts/backfill_price_anchors.py                 # dry run: what would be done
    python3 scripts/backfill_price_anchors.py --apply --limit 10
    python3 scripts/backfill_price_anchors.py --apply         # the whole backlog
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

GRN, RED, YEL, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def pending(dossier_dir: Path) -> list[Path]:
    """Pass dossiers with no price_comparables key.

    Selected by the `.pass.json` suffix, NOT by excluding `.kill.`. The directory also holds
    `.lint.json` sidecars, which carry no candidate at all; an exclude-kills filter sweeps them
    in, and they then read as ideas with a missing title and a missing check -- inflating both
    the backlog count and the "never ran the check" rate with files that were never dossiers.
    A killed idea is separately excluded because it is never priced, so anchoring one is spend
    with no consumer (`verify.py:1018`)."""
    out = []
    for p in sorted(dossier_dir.glob("*.pass.json")):
        try:
            d = json.loads(p.read_text())
        except (ValueError, OSError):
            continue
        tags = ((d.get("candidate") or {}).get("tags") or {})
        if "price_comparables" not in tags:
            out.append(p)
    return out


def write_atomic(path: Path, payload: dict) -> None:
    """tmp + rename. A truncating in-place write that dies mid-flush leaves a zero-byte file,
    which reads back as an empty dossier rather than as corruption -- the failure looks like the
    idea never existed."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def summarise(comps: dict) -> str:
    anchors = [a for a in (comps.get("anchors") or [])
               if isinstance(a.get("amount_pence_gbp"), (int, float))]
    if not anchors:
        n_src = len(comps.get("sources") or [])
        n_rej = len(comps.get("rejected") or [])
        return f"{YEL}0 anchors{OFF} ({n_src} passages, {n_rej} rejected)"
    oneoff = [a["amount_pence_gbp"] for a in anchors if a.get("cadence") == "one_off"]
    med = statistics.median(oneoff or [a["amount_pence_gbp"] for a in anchors]) / 100
    return f"{GRN}{len(anchors)} anchors{OFF}, median £{med:,.0f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually spend and write (default: dry run)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N dossiers (0 = all)")
    ap.add_argument("--dossiers", default=str(REPO / "store" / "dossiers"))
    args = ap.parse_args()

    todo = pending(Path(args.dossiers))
    if args.limit:
        todo = todo[: args.limit]

    print(f"==> {len(todo)} pass dossiers carry no price_comparables")
    if not todo:
        return 0

    if not args.apply:
        for p in todo[:12]:
            d = json.loads(p.read_text())
            title = ((d.get("candidate") or {}).get("title") or "?")[:56]
            print(f"{DIM}    would backfill  {p.name}  {title}{OFF}")
        if len(todo) > 12:
            print(f"{DIM}    … and {len(todo) - 12} more{OFF}")
        print(f"\n{YEL}dry run — nothing spent, nothing written. Re-run with --apply.{OFF}")
        print(f"{DIM}    cost: 3 searches (DDG, free) + 1 extraction call per idea.{OFF}")
        return 0

    from prospector.config import load_config
    from prospector.errors import GroundingInfrastructureError
    from prospector.models import Candidate
    from prospector.operator import _build_operator
    from prospector.price_comparables import comparables_config, run_price_comparables
    from prospector.retrieval import make_provider

    cfg = load_config()
    conf = comparables_config(cfg)
    if not conf["enabled"]:
        print(f"{RED}comparables.enabled is false in config.yaml — refusing to run{OFF}")
        return 2

    search = make_provider(cfg)
    # Extraction runs on the head of the configured verdict chain. It is not RULING anything --
    # every anchor must appear literally in the passage it cites (`_appears_in`) -- but a weaker
    # brain paraphrases numbers, and a paraphrased number that survives the literal check is the
    # one failure mode this evidence cannot tolerate.
    head = cfg.operator[0] if isinstance(cfg.operator, (list, tuple)) else cfg.operator
    # fast=False: extraction is a reasoning call over retrieved passages, and `verify.py` builds
    # its verdict-path operators the same way. A fast tier here trades the one thing this
    # evidence cannot lose -- numbers read literally out of the passage that cites them.
    op = _build_operator(head, cfg, fast=False)

    done = failed = anchored = 0
    for p in todo:
        d = json.loads(p.read_text())
        before = json.dumps(d, sort_keys=True)
        cand_raw = d.get("candidate") or {}
        title = (cand_raw.get("title") or "?")[:52]
        try:
            cand = Candidate.from_dict(cand_raw)
            comps = run_price_comparables(op, search, cfg, cand, pooled_sources=None)
        except GroundingInfrastructureError:
            print(f"{RED}==> all retrieval providers are dead — stopping (nothing further written){OFF}")
            break
        except Exception as e:  # evidence-only: one bad idea must not end the backfill
            failed += 1
            print(f"{RED}  FAIL  {p.name}  {title}: {type(e).__name__}: {e}{OFF}")
            continue

        payload = comps.to_dict()
        d.setdefault("candidate", {}).setdefault("tags", {})["price_comparables"] = payload

        # The safety property, asserted rather than assumed: the ONLY difference between the
        # dossier we read and the one we write is the key we added. If anything else moved,
        # Candidate.from_dict/to_dict round-tripping has rewritten history on a published pack.
        d_check = json.loads(before)
        d_check.setdefault("candidate", {}).setdefault("tags", {})["price_comparables"] = payload
        if json.dumps(d_check, sort_keys=True) != json.dumps(d, sort_keys=True):
            failed += 1
            print(f"{RED}  REFUSED  {p.name} — backfill would alter fields beyond the anchors{OFF}")
            continue

        write_atomic(p, d)
        done += 1
        if [a for a in (payload.get("anchors") or [])
                if isinstance(a.get("amount_pence_gbp"), (int, float))]:
            anchored += 1
        print(f"  ok    {p.name}  {summarise(payload):<46} {title}")

    print(f"\n==> backfilled {done}, of which {anchored} produced usable anchors; {failed} failed")
    print(f"{DIM}    No price was changed. Anchors are evidence; moving a rung is "
          f"comparables.rung_adjust_enabled, still false.{OFF}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
