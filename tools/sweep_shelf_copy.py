#!/usr/bin/env python3
"""Re-grade the copy that is ALREADY on the shelf, and rewrite what fails.

`pack_linter.check_shelf_copy` is a publish-time gate: it grades a pack once, on its way
out, and never again. So the rule that landed on 2026-08-13 cleaned every pack published
after it and left every pack published before it exactly as it was — 27 live lines written
to the service's end customer, still live on 2026-08-16 when the founder read them back to
us off the homepage. A gate cannot fix a shelf it only sees at the door; this walks the
shelf.

    python tools/sweep_shelf_copy.py                 # report: what is live and defective
    python tools/sweep_shelf_copy.py --fix           # rewrite the breaches, 8 in flight
    python tools/sweep_shelf_copy.py --fix --limit 5 # rewrite a few first
    python tools/sweep_shelf_copy.py --fix --jobs 4  # gentler on the provider
    python tools/sweep_shelf_copy.py --push --dry-run # what the LIVE shelf would change to
    STORE_INTERNAL_API_KEY=... python tools/sweep_shelf_copy.py --push

Rewrites are re-graded before they are accepted, so a model that fails to fix the line
leaves the old line alone rather than replacing one defect with another. The rewrite may
only RE-WORD: every figure, place and institution in the original must survive it, because
the one-liner is graded against the pack's own sources downstream and a new fact here is an
unsourced claim on a source-or-die storefront.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospector.pack_linter import (  # noqa: E402
    check_shelf_copy,
    expands_on_first_use,
    unexplained_initialisms,
)

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


def glossary() -> dict[str, str]:
    """The operator's declared expansions, `config.yaml listing.initialism_glossary`.

    Empty is a valid answer and means "expand nothing" — the sweep then reports every
    unexplained term and changes no copy, which is the honest outcome when nobody has said
    what the letters stand for."""
    from prospector.config import load_config
    return dict(load_config().listing.get("initialism_glossary") or {})


def _plural(words: str) -> str | None:
    """`independent software vendor` -> `independent software vendors`.

    Only regular plurals. A last word already ending in `s` gets None, and the caller then
    reports the term instead of writing `Resourcess` onto the shelf — the operator rewords
    it, which is the same answer we give for a term with no entry at all."""
    head, _, last = words.rpartition(" ")
    if not last or last.endswith("s"):
        return None
    if last.endswith("y") and last[-2:-1].lower() not in "aeiou":
        last = last[:-1] + "ies"
    elif last.endswith(("x", "ch", "sh", "z")):
        last += "es"
    else:
        last += "s"
    return f"{head} {last}".strip()


#: `a` before a consonant, `an` before a vowel. The article sits OUTSIDE the run, so
#: expanding in place leaves it agreeing with the letters and not with the words: the live
#: line `an HSE improvement notice` became `an Health and Safety Executive (HSE) notice`.
#: Letter-based, not sound-based, which is right for every term in the glossary today.
_ARTICLE_RE = re.compile(r"\b(a|an|A|An)\s+$")


def expand_initialisms(text: str, gloss: dict[str, str]):
    """Spell out the initialisms the operator has declared. No model call, no judgement.

    Returns `(new_text, unresolved, rejected, embedded)`.

    This exists because `voice_breaches` deliberately refuses to send an initialism to a
    brain: an expansion is a FACT, and a rewrite that invents one ships an unsourced claim on
    a source-or-die storefront. A declared glossary is the safe half of the same job — the
    words come from the operator, and this only pastes them in.

    Three things it will not do, each reported rather than guessed at:

    * `unresolved` — no glossary entry, or a plural this cannot form regularly.
    * `rejected` — an entry whose initials do not spell the run, judged by
      `expands_on_first_use`, the same function the publish gate uses. A typo in
      `config.yaml` cannot put a wrong gloss on the shelf.
    * `embedded` — the run only ever appears inside a longer word, as `STRS` does in
      `CalSTRS`. Pasting an expansion into the middle of a word is worse than leaving it,
      so the copy needs a human, not a substitution.
    """
    out, unresolved, rejected, embedded = text, [], [], []
    for run in unexplained_initialisms(text):
        words = gloss.get(run)
        if not words:
            unresolved.append(run)
            continue
        # A trailing `s` is the plural of the term (`IFAs`, `PACs`), and a following hyphen
        # is a compound (`FOI-sourced`, `RMF-ready`) — both are the term in use. A LEADING
        # letter or digit is not: `STRS` in `CalSTRS` is part of another word.
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(run)}(s?)(?![A-Za-z0-9])")
        match = pattern.search(out)
        if match is None:
            embedded.append(run)
            continue
        if match.group(1):
            words = _plural(words)
            if words is None:
                unresolved.append(run)
                continue
        replacement = f"{words} ({run}{match.group(1)})"
        # Sentence start: the glossary holds common nouns in lower case (`independent
        # software vendor`), and the line it replaces began the sentence.
        head = out[:match.start()]
        if not head.strip() or head.rstrip().endswith((".", "!", "?")):
            replacement = replacement[:1].upper() + replacement[1:]
        else:
            article = _ARTICLE_RE.search(head)
            if article:
                want = "an" if replacement[0].lower() in "aeiou" else "a"
                if article.group(1)[0].isupper():
                    want = want.capitalize()
                head = head[:article.start()] + want + " "
        candidate = head + replacement + out[match.end():]
        if not expands_on_first_use(candidate, run):
            rejected.append(run)
            continue
        out = candidate
    return out, unresolved, rejected, embedded


def expand_row(title: str, one: str, gloss: dict[str, str]):
    """Apply the glossary to both shelf strings, keeping only a change that helps.

    Returns `(new_title|None, new_line|None, needs_operator, rejected)`; None means "leave
    it". An expansion makes a line longer and the gate has a length limit, so it can trade
    one error for another. The test is the gate's own count: a field is only rewritten when
    the errors it would raise strictly go down."""
    new_t, unres_t, rej_t, emb_t = expand_initialisms(title, gloss)
    if new_t != title and len(breaches(new_t, one)) >= len(breaches(title, one)):
        new_t = title
    new_o, unres_o, rej_o, emb_o = expand_initialisms(one, gloss)
    if new_o != one and len(breaches(new_t, new_o)) >= len(breaches(new_t, one)):
        new_o = one
    return (new_t if new_t != title else None,
            new_o if new_o != one else None,
            sorted(set(unres_t) | set(unres_o) | set(emb_t) | set(emb_o)),
            sorted(set(rej_t) | set(rej_o)))


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


def rewrite_one(op, title: str, line: str, attempts: int = 2) -> str | None:
    """Rewrite until it grades clean, or keep the original.

    The second attempt is told WHY the first was refused. Four of the founder's twenty rows
    came back unfixed on the first parallel run — including the two lines he opened with,
    the stolen-tool claim and the Cal/OSHA citation — and a refusal we could name in one
    clause was thrown away instead of being handed back. A retry that repeats the same
    prompt is a coin flip; a retry that quotes the rejection is the cheapest correction
    available, at one extra call on failures only."""
    note = ""
    for attempt in range(max(1, attempts)):
        try:
            got = op.complete_json(SYSTEM, USER.format(title=title, line=line) + note)
        except Exception as exc:  # an outage is not a verdict on the copy
            print(f"    rewrite call failed: {exc}")
            return None
        new = (got or {}).get("one_liner", "") if isinstance(got, dict) else ""
        new = re.sub(r"\s+", " ", str(new)).strip().strip('"')
        if not new:
            return None

        why = ""
        if voice_breaches(new):
            why = ("it still addresses the reader as 'you' or opens on a pronoun "
                   "(it, we, this, they)")
        elif (invented := _new_facts(f"{title} {line}", new)):
            why = (f"it introduced {', '.join(invented)}, which appear nowhere in the "
                   f"original — use only the words and facts already there")
        if not why:
            return new

        print(f"    attempt {attempt + 1} refused ({why.split(',')[0]}): {new!r}")
        note = (f"\n\nYour previous answer was REJECTED because {why}. It was:\n{new}\n"
                f"Rewrite it again, fixing exactly that and changing nothing else.")
    return None


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
    # A compound term is indexed whole AND in pieces. `Cal/OSHA` reaches this function as
    # one whitespace token, normalises to `calosha`, and the rewrite's `Cal/OSHA` arrives
    # as two matches, `Cal` and `OSHA` — so a source that plainly contains the term was
    # read as containing neither half, and two good rewrites of `d6f72b9dc9a45c45` were
    # refused for inventing a fact quoted in their own input.
    def _norm(s):
        out = set()
        for w in s.lower().split():
            out.add(re.sub(r"[^a-z0-9£$%]", "", w))
            out.update(re.split(r"[^a-z0-9£$%]+", w))
        return out - {""}

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


def persist(cid: str, new_line: str | None = None, new_title: str | None = None) -> None:
    """Both copies, or neither: the DB row is what the shelf reads, the dossier JSON is
    what a republish would read back. Leaving one behind is how the shelf silently reverts
    the next time the pack is republished."""
    sets = [(col, val) for col, val in (("one_liner", new_line), ("title", new_title))
            if val is not None]
    if not sets:
        return
    con = sqlite3.connect(DB)
    try:
        con.execute(f"UPDATE dossiers SET {', '.join(c + ' = ?' for c, _ in sets)} "
                    f"WHERE candidate_id = ?", [v for _, v in sets] + [cid])
        con.commit()
    finally:
        con.close()
    for path in (DOSSIERS / f"{cid}.pass.json", DOSSIERS / f"{cid}.json"):
        if not path.exists():
            continue
        doc = json.load(path.open())
        if isinstance(doc.get("candidate"), dict):
            for col, val in sets:
                doc["candidate"][col] = val
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def pull_live(api_url: str, dry: bool) -> int:
    """Copy the live wording back into our own record, where the two disagree.

    The shelf is ahead of us, not behind: `backfill_listing_copy` edits copy directly on the
    catalogue, so on 2026-08-16 the live rows were voice-clean while this DB still held 16
    titles addressed to the end customer and five carrying trade initialisms. That is not a
    cosmetic gap — `bridge._update_catalog` sources the title from the DOSSIER
    (`bridge.py:1514`), so the next republish of any of those packs would push the old
    wording back onto the shelf and undo a fix nobody remembers making. Pulling is the
    cheap direction: it costs no model call and cannot invent a fact, because every string
    it writes is already the one the buyer is reading."""
    import requests
    live = requests.get(f"{api_url}/catalog", timeout=30).json()
    live = live if isinstance(live, list) else live.get("items", [])
    by_id = {r.get("id"): r for r in live}

    pending = []
    for cid, title, one, _created in live_rows():
        row = by_id.get(cid)
        if row is None:
            continue
        lt = (row.get("title") or "").strip()
        lo = (row.get("oneLine") or "").strip()
        # Only where OUR copy is the defective one. A live line that breaches is the push
        # path's business, and pulling it in would launder a defect into our record.
        want_t = lt if lt and lt != title.strip() and breaches(title, "") and not breaches(lt, "") else None
        want_o = lo if lo and lo != one.strip() and voice_breaches(one) and not voice_breaches(lo) else None
        if want_t or want_o:
            pending.append((cid, want_t, want_o))

    print(f"live rows: {len(by_id)}   local rows the shelf has already fixed: {len(pending)}")
    for cid, want_t, want_o in pending:
        print(f"\n{cid}")
        if want_t:
            print(f"  title -> {want_t[:100]}")
        if want_o:
            print(f"  line  -> {want_o[:100]}")
        if not dry:
            persist(cid, new_line=want_o, new_title=want_t)
    if dry:
        print("\nDRY RUN — nothing written.")
    return 0


#: The rollback. Written BEFORE each live PATCH, one row per pack: once the live `oneLine`
#: is overwritten no GET projects the old one, so this file is the only copy of it.
PUSH_LOG = ROOT / "store" / "shelf_copy_log.jsonl"


def push_live(api_url: str, key: str, dry: bool) -> int:
    """Send the repaired lines to the shelf the buyer actually reads.

    `--fix` writes the local dossier and the local DB, and a reader of this tool could
    reasonably think that is the shelf. It is not: `store/prospector.db` is this engine's
    own record, and mumchimp.com serves `oneLine` from the catalogue row behind
    `api.mumchimp.com/catalog`. Sixteen lines were repaired on 2026-08-16 and every one of
    them was still live in its old wording afterwards.

    The door is `PATCH /internal/catalog/{id}/copy` — the narrow one, which reaches copy and
    nothing else — through `backfill_listing_copy.patch_copy`, so the money-bearing fields
    are asserted unmoved by the same definition the other copy tools use rather than a
    second one written here."""
    import requests
    sys.path.insert(0, str(ROOT / "tools"))
    from backfill_listing_copy import patch_copy  # noqa: E402  (same dir)

    live = requests.get(f"{api_url}/catalog", timeout=30).json()
    live = live if isinstance(live, list) else live.get("items", [])
    by_id = {r.get("id"): r for r in live}

    pending = []
    for cid, title, one, _created in live_rows():
        row = by_id.get(cid)
        if row is None or not one:
            continue
        if (row.get("oneLine") or "").strip() == one.strip():
            continue
        # Push only where the LIVE line is the defective one. Difference is not evidence of
        # improvement in either direction: `backfill_listing_copy` has already rewritten
        # copy directly on the shelf, so for 20-odd rows the live line is the NEWER one and
        # the local DB carries the wording it replaced — `ac755ca1473e57fa` is live as
        # "When a nursery closes mid term, this recovers the parent's prepaid fees…" against
        # a local "A fixed-fee transaction broker that, when a nursery…". Pushing on
        # difference alone would have reverted every one of them. The two conditions are
        # separate on purpose: the live line must be broken, and ours must be clean.
        if not voice_breaches(row.get("oneLine") or ""):
            continue
        if voice_breaches(one):
            continue
        pending.append((cid, row, one))

    print(f"live rows: {len(by_id)}   lines to push: {len(pending)}")
    pushed = 0
    for cid, row, new in pending:
        print(f"\n{cid}\n  live:  {(row.get('oneLine') or '')[:110]}\n  local: {new[:110]}")
        if dry:
            continue
        with PUSH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"pack_id": cid, "field": "oneLine",
                                 "before": row.get("oneLine") or "", "after": new}) + "\n")
        ok, problem = patch_copy(api_url, key, cid, {"oneLine": new}, row)
        print(f"  -> {'pushed' if ok else 'REFUSED: ' + problem}")
        pushed += bool(ok)
    if not dry:
        print(f"\npushed: {pushed} of {len(pending)}   rollback log: {PUSH_LOG}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="rewrite the breaching lines in place")
    ap.add_argument("--push", action="store_true",
                    help="send repaired lines to the LIVE catalogue (needs STORE_INTERNAL_API_KEY)")
    ap.add_argument("--dry-run", action="store_true", help="with --push: show the diff, send nothing")
    ap.add_argument("--pull", action="store_true",
                    help="copy live copy back into the local record where the shelf is ahead")
    ap.add_argument("--api-url", default="https://api.mumchimp.com")
    ap.add_argument("--limit", type=int, default=0, help="stop after N rewrites")
    ap.add_argument("--jobs", type=int, default=8,
                    help="rewrites in flight at once (default 8, the measured-clean MiniMax figure)")
    args = ap.parse_args()

    if args.pull:
        return pull_live(args.api_url, args.dry_run)
    if args.push:
        key = os.environ.get("STORE_INTERNAL_API_KEY", "")
        if not key and not args.dry_run:
            print("--push needs STORE_INTERNAL_API_KEY; refusing.", file=sys.stderr)
            return 2
        return push_live(args.api_url, key, args.dry_run)

    rows = live_rows()
    bad = [(cid, t, o, c, b) for cid, t, o, c in rows if (b := breaches(t, o))]
    # Split by what a rewrite can reach. A row whose ONLY breach is its title is reported
    # and skipped: rewriting the one-liner cannot clear it, and spending a call to find
    # that out — 44 rows' worth on the first run — is the whole cost of the sweep.
    fixable = [r for r in bad if voice_breaches(r[2])]

    # The free half, first: spelling out a term the operator has DECLARED costs no model
    # call and cannot invent a fact. On 2026-08-16 initialisms alone held 31 of the 33
    # defective rows, so this is the larger half of the sweep and the cheaper one.
    gloss = glossary()
    expandable, unresolved, rejected = [], {}, set()
    for cid, title, one, created, why in bad:
        new_t, new_o, unres, rej = expand_row(title, one, gloss)
        for run in unres:
            unresolved[run] = unresolved.get(run, 0) + 1
        rejected |= set(rej)
        if new_t or new_o:
            expandable.append((cid, title, one, created, new_t, new_o))

    print(f"live packs: {len(rows)}   defective: {len(bad)}   "
          f"one-liners a rewrite can fix: {len(fixable)}   "
          f"rows the glossary alone repairs: {len(expandable)}")
    if unresolved:
        print(f"\nterms this cannot spell out ({len(unresolved)}) — declare them in "
              f"config.yaml listing.initialism_glossary, or reword the copy:")
        for run, n in sorted(unresolved.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {run:<8} on {n} row(s)")
    if rejected:
        print(f"\nDECLARED BUT WRONG — the initials do not spell the run, so these were "
              f"dropped rather than published: {', '.join(sorted(rejected))}")
    if not bad:
        return 0

    if args.fix and expandable:
        print(f"\nspelling out declared terms on {len(expandable)} row(s) — no model call")
        for cid, title, one, created, new_t, new_o in expandable:
            print(f"\n{cid}  listed from {created[:10]}")
            if new_t:
                print(f"  title -> {new_t}")
            if new_o:
                print(f"  line  -> {new_o}")
            persist(cid, new_line=new_o, new_title=new_t)
        # The rows moved, so re-grade before spending anything on the half a model must do.
        rows = live_rows()
        bad = [(cid, t, o, c, b) for cid, t, o, c in rows if (b := breaches(t, o))]
        fixable = [r for r in bad if voice_breaches(r[2])]
        print(f"\nafter the glossary: defective {len(bad)}   "
              f"one-liners a rewrite can fix: {len(fixable)}")
        if not fixable:
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

    if not args.fix:
        proposed = {cid: (nt, no) for cid, _t, _o, _c, nt, no in expandable}
        for cid, title, one, created, why in bad:
            print(f"\n{cid}  listed from {created[:10]}")
            print(f"  OLD: {one}")
            for field, detail in why:
                print(f"   ! [{field}] {detail.split(':')[0]}")
            new_t, new_o = proposed.get(cid, (None, None))
            if new_t:
                print(f"   > glossary title: {new_t}")
            if new_o:
                print(f"   > glossary line:  {new_o}")
        return 0

    # In flight together. Each rewrite is one independent call about one line, sharing
    # nothing with the others, and the founder's first run measured ~40s of latency per
    # call — 23 rows serially is a quarter of an hour of waiting for work that is almost
    # entirely idle. The default matches `config.yaml minimax_concurrency`, the figure this
    # estate measured clean at 16/16 with no 429s; the writes stay serial below, because
    # SQLite is the one part of this that is not idle-waiting.
    todo = fixable[:args.limit] if args.limit else fixable
    print(f"\nrewriting {len(todo)} line(s), {args.jobs} in flight")
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        done = list(pool.map(lambda r: (r, rewrite_one(op, r[1], r[2])), todo))

    fixed = 0
    for (cid, title, one, created, why), new in done:
        print(f"\n{cid}  listed from {created[:10]}")
        print(f"  OLD: {one}")
        if new:
            persist(cid, new)
            fixed += 1
            print(f"  NEW: {new}")
        else:
            print("  (kept — see the refusal above)")
    print(f"\nrewritten: {fixed} of {len(todo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
