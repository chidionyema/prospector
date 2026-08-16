#!/usr/bin/env python3
"""Re-grade the copy that is ALREADY on the shelf, and rewrite what fails.

`pack_linter.check_shelf_copy` is a publish-time gate: it grades a pack once, on its way
out, and never again. So the rule that landed on 2026-08-13 cleaned every pack published
after it and left every pack published before it exactly as it was — 27 live lines written
to the service's end customer, still live on 2026-08-16 when the founder read them back to
us off the homepage. A gate cannot fix a shelf it only sees at the door; this walks the
shelf.

    python tools/sweep_shelf_copy.py                 # report: what is live and defective
    python tools/sweep_shelf_copy.py --fix           # rewrite the breaches, in place
    python tools/sweep_shelf_copy.py --fix --limit 5 # rewrite a few first

Rewrites are re-graded before they are accepted, so a model that fails to fix the line
leaves the old line alone rather than replacing one defect with another. The rewrite may
only RE-WORD: every figure, place and institution in the original must survive it, because
the one-liner is graded against the pack's own sources downstream and a new fact here is an
unsourced claim on a source-or-die storefront.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospector.pack_linter import check_shelf_copy  # noqa: E402

DB = ROOT / "store" / "prospector.db"
LISTINGS = ROOT / "store" / "listings"
DOSSIERS = ROOT / "store" / "dossiers"

SYSTEM = (
    "You rewrite one line of shelf copy for a storefront that sells research packs about "
    "businesses. The reader is a person deciding whether to BUILD this business, never the "
    "business's own customer."
)
USER = """Rewrite this one-line description.

TITLE: {title}
LINE:  {line}

RULES
- Third person throughout. Never the words you, your, yours, yourself.
- Describe the business to someone considering running it, not to its end customer.
- Do not open on it, we, our, they, this, that, these, those — open on the thing itself:
  "A tool for UK freelance designers ... that turns every out-of-scope client request into
  a priced, dated change note the client has to answer" is the shape.
- Keep every fact: every figure, price, place, institution and named market must survive
  unchanged. Add nothing that is not already in the line.
- One sentence, under 200 characters, plain words a stranger to the trade reads once.

Return JSON: {{"one_liner": "<the rewritten line>"}}"""


def breaches(title: str, one_liner: str) -> list[str]:
    """The errors the publish gate would raise on this row today."""
    fields = {"title": title or "", "oneLine": one_liner or ""}
    return [p["detail"] for p in check_shelf_copy(fields, block=True)
            if p.get("severity") == "error"]


def listed_ids() -> set[str]:
    out = set()
    for p in LISTINGS.glob("*.json"):
        try:
            out.add(json.load(p.open()).get("candidate_id"))
        except Exception:
            continue
    return out - {None}


def live_rows():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        live = listed_ids()
        rows = []
        for cid, title, one, created in con.execute(
                "SELECT candidate_id, title, one_liner, created_at FROM dossiers "
                "WHERE decision = 'pass'"):
            if cid in live:
                rows.append((cid, title or "", one or "", created or ""))
        return sorted(rows, key=lambda r: r[3])
    finally:
        con.close()


def rewrite_one(op, title: str, line: str) -> str | None:
    """One cheap call. Returns the new line only if it grades clean, else None."""
    try:
        got = op.complete_json(SYSTEM, USER.format(title=title, line=line))
    except Exception as exc:  # an outage is not a verdict on the copy
        print(f"    rewrite call failed: {exc}")
        return None
    new = (got or {}).get("one_liner", "") if isinstance(got, dict) else ""
    new = re.sub(r"\s+", " ", str(new)).strip().strip('"')
    if not new:
        return None
    if breaches(title, new):
        print(f"    rewrite still breaches, keeping the original: {new!r}")
        return None
    return new


def persist(cid: str, new_line: str) -> None:
    """Both copies, or neither: the DB row is what the shelf reads, the dossier JSON is
    what a republish would read back. Leaving one behind is how the shelf silently reverts
    the next time the pack is republished."""
    con = sqlite3.connect(DB)
    try:
        con.execute("UPDATE dossiers SET one_liner = ? WHERE candidate_id = ?", (new_line, cid))
        con.commit()
    finally:
        con.close()
    for path in (DOSSIERS / f"{cid}.pass.json", DOSSIERS / f"{cid}.json"):
        if not path.exists():
            continue
        doc = json.load(path.open())
        if isinstance(doc.get("candidate"), dict):
            doc["candidate"]["one_liner"] = new_line
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="rewrite the breaching lines in place")
    ap.add_argument("--limit", type=int, default=0, help="stop after N rewrites")
    args = ap.parse_args()

    rows = live_rows()
    bad = [(cid, t, o, c, b) for cid, t, o, c in rows if (b := breaches(t, o))]
    print(f"live packs: {len(rows)}   defective shelf copy: {len(bad)}")
    if not bad:
        return 0

    op = None
    if args.fix:
        # The cheap chain, and only the cheap chain: rewording a line that is already
        # published rules nothing, so it never goes near a moat brain. `_build_operator`
        # raises for a tier that is not configured, so the first that CONSTRUCTS wins —
        # the same order `run.py` uses, read from `config.yaml noncritical_operator`.
        from prospector.config import load_config
        from prospector.operator import _build_operator
        from prospector.run import _noncritical_order
        cfg = load_config()
        for kind in _noncritical_order(cfg):
            try:
                op = _build_operator(kind, cfg, fast=True)
                print(f"rewriting on: {kind}")
                break
            except RuntimeError:
                continue
        if op is None:
            print("no non-critical operator available — nothing rewritten")
            return 1

    fixed = 0
    for cid, title, one, created, why in bad:
        print(f"\n{cid}  listed from {created[:10]}")
        print(f"  OLD: {one}")
        for w in why:
            print(f"   ! {w.split(':')[0]}")
        if not args.fix:
            continue
        if args.limit and fixed >= args.limit:
            print("  (limit reached)")
            break
        new = rewrite_one(op, title, one)
        if new:
            persist(cid, new)
            fixed += 1
            print(f"  NEW: {new}")
    if args.fix:
        print(f"\nrewritten: {fixed} of {len(bad)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
