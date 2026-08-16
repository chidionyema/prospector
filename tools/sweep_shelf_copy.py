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
- Do NOT name a customer group the line does not already name. If the line does not say who
  the customers are, describe what the business does and stop; inventing an audience is
  inventing a fact.
- One sentence, under 200 characters, plain words a stranger to the trade reads once.

Return JSON: {{"one_liner": "<the rewritten line>"}}"""


def breaches(title: str, one_liner: str) -> list[tuple[str, str]]:
    """The errors the publish gate would raise on this row today, each tagged with the
    FIELD it came from.

    Tagged because the row has two shelf strings and they fail independently: the first run
    of this sweep printed "second person on the shelf" twice against
    `Printed, weatherproof bin store signs made for one specific block of flats` — a line
    with no second person in it at all. Both findings were about its TITLE. An untagged
    report reads as a defect in the line the operator is looking at, and sends the rewrite
    at the wrong string."""
    fields = {"title": title or "", "oneLine": one_liner or ""}
    seen, out = set(), []
    for p in check_shelf_copy(fields, block=True):
        if p.get("severity") != "error":
            continue
        key = (p.get("where") or "?", p["detail"])
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def voice_breaches(one_liner: str) -> list[str]:
    """The subset a REWRITE of the one-liner can actually clear: the founder's two, second
    person and a bare opener.

    An initialism is deliberately not here. `PA RTY-100` and `British Standard BS 4142`
    both trip the initialism rule, and neither is a voice defect — spelling those out is a
    judgement about the term, not about who the sentence is addressed to, and asking a
    cheap brain to fix it while it rewords is how a rewrite invents an expansion. They are
    reported and left."""
    return [d for f, d in breaches("", one_liner)
            if "second person" in d or "opens on" in d]


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
    if voice_breaches(new):
        print(f"    rewrite still breaches, keeping the original: {new!r}")
        return None
    invented = _new_facts(f"{title} {line}", new)
    if invented:
        print(f"    rewrite invents {', '.join(invented)} — keeping the original: {new!r}")
        return None
    return new


#: Words a rewrite may introduce without inventing anything: they carry no fact.
_FREE_WORDS = frozenset("""
a an and the of for to in on at by with from that which who whose so it its their
one each every per turns builds gives makes into out up as is are be
service tool report pack app system engine kit dashboard business
""".split())


def _new_facts(source: str, new: str) -> list[str]:
    """Proper nouns and figures in the rewrite that are nowhere in the source.

    The first run produced "A data intelligence report for UK retirees that turns HMRC's
    real settlement data into evidence for negotiating inheritance tax bills" from a line
    that never mentioned retirees — and inheritance tax is not, as a rule, paid by them. A
    reworded line is allowed to be shorter, clearer and differently ordered; it is not
    allowed to know something the original did not, on a storefront whose whole claim is
    that every fact came from a source.

    Only names and numbers are checked. An ordinary word the rewrite reaches for is style;
    a capitalised term or a figure is a fact, and a fact that appeared from nowhere is the
    class worth blocking."""
    # Compared on a five-character stem, because a faithful rewrite reworks the grammar:
    # `HMRC.` becomes `HMRC's` and `negotiate` becomes `negotiating`, and an exact-token
    # guard calls both of those inventions and blocks a clean line.
    def _norm(s):
        return {re.sub(r"[^a-z0-9£$%]", "", w) for w in s.lower().split()} - {""}

    have = _norm(source)

    def known(w):
        if w in have or w.rstrip("s") in have or w in _FREE_WORDS:
            return True
        return len(w) >= 5 and any(h.startswith(w[:5]) or w.startswith(h[:5])
                                   for h in have if len(h) >= 4)

    out = []
    for tok in re.findall(r"[A-Z][\w'’-]+|[£$]?\d[\d,.]*%?", new):
        low = re.sub(r"[^a-z0-9£$%]", "", tok.lower())
        if low and not known(low):
            out.append(tok)

    # And the audience, which is the half `retirees` fell through: a lowercase noun, so no
    # capital marks it as a name, but "for X" is a claim about who buys — the one fact this
    # storefront is least able to source after the fact.
    for phrase in re.findall(r"\bfor ((?:[a-z][\w'’-]*[ ]?){1,4})", new.lower()):
        for word in phrase.split():
            w = re.sub(r"[^a-z0-9]", "", word)
            if len(w) > 3 and not known(w):
                out.append(w)
    return sorted(set(out))


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
    # Split by what a rewrite can reach. A row whose ONLY breach is its title is reported
    # and skipped: rewriting the one-liner cannot clear it, and spending a call to find
    # that out — 44 rows' worth on the first run — is the whole cost of the sweep.
    fixable = [r for r in bad if voice_breaches(r[2])]
    print(f"live packs: {len(rows)}   defective: {len(bad)}   "
          f"one-liners a rewrite can fix: {len(fixable)}")
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
    for cid, title, one, created, why in (fixable if args.fix else bad):
        print(f"\n{cid}  listed from {created[:10]}")
        print(f"  OLD: {one}")
        for field, detail in why:
            print(f"   ! [{field}] {detail.split(':')[0]}")
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
        print(f"\nrewritten: {fixed} of {len(fixable)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
