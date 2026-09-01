#!/usr/bin/env python3
"""Q4c — do the NUMBERS in our rationales come from the passages, or from the model?

§20/§21.2 measured and gated citation source QUALITY. §25 showed why that is not enough: the
shipped `P1_check_aware` gate is a RULING-level gate (it demotes a check only when *every*
citation is inadmissible), so it can never remove a bad figure from a rationale that also cites
an acceptable source. Source-or-die, however, is a CLAIM-level rule. This probe measures the gap.

THE QUESTION: for every figure a ruled rationale asserts ("92% plaintiff win rate",
"$35,000 per case"), does that figure appear in the text the model was actually given?

WHY THIS IS ANSWERABLE OFFLINE, AND EXACTLY WHAT IT PROVES:

  * `verify.py:375-376` builds the verdict prompt as `[source_id] s.text[:VERDICT_PASSAGE_TRUNCATE]`
    over `sources`, and `VERDICT_PASSAGE_TRUNCATE = 600` (`verify.py:477`). Nothing else grounds
    the call — `verify.py:338` "Rule ONLY from the provided passages."
  * `verify.py:469` stores `[s for s in sources if s.source_id in citations] or sources` on the
    check, so a dossier's `sources[].text` IS the passage set, and the model saw at most its
    first 600 characters.

  Therefore a figure absent from every stored passage was NOT retrieved. It came from the model's
  prior knowledge, which "Verdict-from-retrieval-only" forbids. That is a fact about our own
  files, not an inference about the web.

FIVE BUCKETS, checked in this order. The point of the middle three is that "not in the cited
passage" has innocent explanations, and a headline that does not subtract them is not a finding,
it is an accusation:

  traceable      figure appears within the first 600 chars of a cited passage — the model could
                 have read it. (This probe does not claim it DID; that needs entailment, §14.)
  truncated      figure appears in the stored passage but only BEYOND char 600 — retrieval found
                 it and the prompt threw it away. The number is real; our own truncation made it
                 unciteable. That would be a config fix, not a research problem.
  self_ref       figure appears in the CANDIDATE's own text, or equals a price rung declared in
                 `config.yaml listing.pricing.rungs`. "a £49 report is within budget" asserts
                 nothing about the world; it restates our own offer, and £49 is rung index 2, not
                 a retrieved fact. Not an evidence claim, so not a source-or-die breach. Matching
                 a rung can only move figures OUT of `untraceable`, so this keeps that count a
                 lower bound.
  other_passage  figure appears in a passage retrieved for this candidate but NOT cited by this
                 check. The number was grounded; the citation is wrong. A hygiene defect —
                 traceable by a human, invisible to any tool that trusts `citations`.
  untraceable    figure appears in NO text this run ever retrieved. The model supplied it.

MATCHING IS DELIBERATELY LENIENT, so `untraceable` is a LOWER BOUND. A figure counts as found if
its bare digits appear anywhere in the passage with digit boundaries — "92" matches whether the
passage says "92%", "92 percent" or "92 of them". Units, currency and wording are not required.
Anything this test calls untraceable is untraceable under any stricter test too. That is the
conservative direction, which is the only defensible one for a claim this serious.

Read-only. Zero LLM. Zero network unless `--live-only` fetches the catalogue.

Usage:
    .venv/bin/python tools/experiments/q4c_claim_level_tracing.py
    .venv/bin/python tools/experiments/q4c_claim_level_tracing.py --current-moat
    .venv/bin/python tools/experiments/q4c_claim_level_tracing.py --live-only
    .venv/bin/python tools/experiments/q4c_claim_level_tracing.py --live-only --catalogue /tmp/c.json
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from prospector.admissibility import host_of, tier  # noqa: E402

DOSSIERS = "store/dossiers/*.json"
CATALOGUE_URL = (os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}") + "/catalog"
RULED = {"supported", "refuted"}
MOAT = {"claude_cli", "claude", "claude-cli/default"}
# Mirrors verify.py:477. Read, not guessed — if that constant moves this probe is wrong.
VERDICT_PASSAGE_TRUNCATE = 600
HERE = os.path.dirname(os.path.abspath(__file__))

# A figure is a number that carries a claim. Bare small integers ("three of the passages",
# "2 sources") are prose, not evidence, so a number qualifies only if it wears a unit or is
# large enough that nobody writes it casually.
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
FIGURE_RE = re.compile(
    rf"(?:[£$€]\s?({_NUM})"                                   # currency
    rf"|({_NUM})\s?%"                                          # percent sign
    rf"|({_NUM})\s?(?:percent|per cent|pc\b)"                  # spelled percent
    rf"|({_NUM})\s?(?:million|billion|trillion|bn\b|m\b|k\b)"  # magnitude words
    rf"|({_NUM})\s?(?:x|fold|times)\b"                         # multiples
    rf"|\b({_NUM})\b)",                                        # bare — filtered below
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"^(?:19|20)\d\d$")


def figures(text: str) -> list[str]:
    """Normalised digit-strings of every claim-bearing number in `text`."""
    out, seen = [], set()
    for m in FIGURE_RE.finditer(text or ""):
        raw = next(g for g in m.groups() if g)
        bare = m.lastindex == 6                      # matched the trailing bare-number branch
        norm = raw.replace(",", "")
        if YEAR_RE.match(norm):
            continue                                 # a year is a date, not a measurement
        if bare:
            # No unit. Keep only numbers too big to be prose counting.
            try:
                if float(norm) < 1000:
                    continue
            except ValueError:
                continue
        norm = norm.rstrip("0").rstrip(".") if "." in norm else norm
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def contains(haystack: str, num: str) -> bool:
    """Lenient: bare digits with digit boundaries, commas in the haystack ignored."""
    h = re.sub(r"(?<=\d),(?=\d\d\d)", "", haystack)
    esc = re.escape(num)
    if re.search(rf"(?<![\d.]){esc}(?![\d])", h):
        return True
    # Trailing zeros are the same number: 92 must match "92.0", and 4.5 must match "4.50".
    tail = r"0*" if "." in num else r"\.0+"
    return bool(re.search(rf"(?<![\d.]){esc}{tail}(?![\d])", h))


def price_rungs() -> set[str]:
    """Declared price points, in both pence and pounds — a rationale writes £49, config says 4900."""
    try:
        import yaml
        rungs = ((yaml.safe_load(open("config.yaml")) or {})
                 .get("listing", {}).get("pricing", {}).get("rungs") or [])
    except Exception:
        return set()
    out = set()
    for r in rungs:
        out.add(str(int(r)))
        if int(r) % 100 == 0:
            out.add(str(int(r) // 100))
    return out


def live_ids(argv: list[str]) -> set[str] | None:
    if "--live-only" not in argv:
        return None
    for i, a in enumerate(argv):
        if a == "--catalogue" and i + 1 < len(argv):
            doc = json.load(open(argv[i + 1]))
            break
    else:
        with urllib.request.urlopen(CATALOGUE_URL, timeout=30) as r:
            doc = json.loads(r.read().decode())
    items = doc if isinstance(doc, list) else (doc.get("items") or doc.get("packs")
                                               or doc.get("data") or [])
    return {str(i.get("id") or i.get("Id")) for i in items if isinstance(i, dict)}


def main() -> int:
    moat_only = "--current-moat" in sys.argv
    live = live_ids(sys.argv)
    RUNGS = price_rungs()

    paths = sorted(glob.glob(DOSSIERS))
    if live is not None:
        paths = [p for p in paths
                 if any(os.path.basename(p).startswith(k) for k in live)]

    tot = collections.Counter()                       # traceable / truncated / untraceable
    by_check = collections.defaultdict(collections.Counter)
    by_verdict = collections.defaultdict(collections.Counter)
    untraceable_examples: list[dict] = []
    checks_all_traceable = checks_with_untraceable = checks_with_figures = 0
    ruled_cited = 0
    dossiers = 0
    dirty_items: set[str] = set()

    for path in paths:
        try:
            dossier = json.load(open(path))
        except Exception:
            continue
        if not dossier.get("checks"):
            continue
        dossiers += 1
        key = os.path.basename(path).split(".")[0]
        # The candidate's own words — its offer, not a claim about the world.
        self_text = json.dumps(dossier.get("candidate") or {})
        # Everything retrieval ever fetched for this candidate, cited or not.
        pooled = "\n".join(s.get("text") or "" for s in (dossier.get("sources") or [])
                           if isinstance(s, dict))

        for chk in dossier["checks"]:
            if chk.get("verdict") not in RULED:
                continue
            if moat_only and (chk.get("provider") or "") not in MOAT:
                continue
            by_id = {s.get("source_id"): (s.get("text") or "", s.get("url") or "")
                     for s in (chk.get("sources") or []) if isinstance(s, dict)}
            cited = [by_id[c] for c in (chk.get("citations") or []) if c in by_id]
            if not cited:
                continue
            ruled_cited += 1

            visible = "\n".join(t[:VERDICT_PASSAGE_TRUNCATE] for t, _ in cited)
            stored = "\n".join(t for t, _ in cited)
            figs = figures(chk.get("rationale") or "")
            if not figs:
                continue
            checks_with_figures += 1
            name = chk.get("check_name") or "?"
            verdict = chk.get("verdict")
            bad = 0
            for f in figs:
                if contains(visible, f):
                    b = "traceable"
                elif contains(stored, f):
                    b = "truncated"
                elif f in RUNGS or contains(self_text, f):
                    b = "self_ref"
                elif contains(pooled, f):
                    b = "other_passage"
                else:
                    b = "untraceable"
                    bad += 1
                tot[b] += 1
                by_check[name][b] += 1
                by_verdict[verdict][b] += 1
            if bad:
                checks_with_untraceable += 1
                dirty_items.add(key)
                if len(untraceable_examples) < 25:
                    untraceable_examples.append({
                        "candidate": key, "check": name, "verdict": verdict,
                        "untraceable_figures": [
                            f for f in figs
                            if not (f in RUNGS or contains(stored, f)
                                    or contains(self_text, f) or contains(pooled, f))],
                        "cited_hosts": sorted({host_of(u) for _, u in cited if u}),
                        "cited_tiers": sorted({tier(host_of(u)) for _, u in cited if u}),
                        "rationale": (chk.get("rationale") or "")[:280],
                    })
            else:
                checks_all_traceable += 1

    n = sum(tot.values()) or 1
    scope = ("LIVE CATALOGUE" if live is not None else "all dossiers") + \
            (", current moat only" if moat_only else "")
    print(f"Q4c claim-level tracing — {scope}")
    print(f"dossiers read: {dossiers}   ruled+cited checks: {ruled_cited}   "
          f"checks asserting >=1 figure: {checks_with_figures}   figures: {n}")
    print(f"passage budget the model actually saw: first {VERDICT_PASSAGE_TRUNCATE} chars "
          f"per cited source (verify.py:376,477)\n")
    for b, label in (("traceable", "in a cited passage the model could see"),
                     ("truncated", "in the passage but BEYOND the 600-char prompt budget"),
                     ("self_ref", "the candidate's OWN price/pitch, not a claim about the world"),
                     ("other_passage", "retrieved for this candidate but cited by another check"),
                     ("untraceable", "in NO retrieved text — the model supplied it")):
        print(f"  {tot[b]:6d}  {tot[b] / n:6.1%}  {b:12s} {label}")
    print(f"\nchecks whose every figure traces : {checks_all_traceable}")
    print(f"checks asserting >=1 untraceable : {checks_with_untraceable} of "
          f"{checks_with_figures} ({checks_with_untraceable / (checks_with_figures or 1):.1%})")
    if live is not None:
        print(f"LIVE items carrying an untraceable figure: {len(dirty_items)} of {len(live)} "
              f"({len(dirty_items) / (len(live) or 1):.0%})")

    print("\n--- untraceable rate by check ---")
    for name, c in sorted(by_check.items(), key=lambda kv: -kv[1]["untraceable"]):
        t = sum(c.values()) or 1
        print(f"  {name:20s} figures={t:5d}  untraceable={c['untraceable']:5d} "
              f"({c['untraceable'] / t:5.1%})  truncated={c['truncated']:4d}")

    print("\n--- by verdict ---")
    for v, c in by_verdict.items():
        t = sum(c.values()) or 1
        print(f"  {v:12s} figures={t:5d}  untraceable={c['untraceable']:5d} ({c['untraceable'] / t:5.1%})")

    print("\n--- examples (up to 25) ---")
    for e in untraceable_examples[:10]:
        print(f"  {e['candidate']}  {e['check']}/{e['verdict']}  "
              f"figures={e['untraceable_figures']}  hosts={e['cited_hosts']}")

    out = os.path.join(HERE, "q4c_claim_level_tracing_receipts"
                       + ("_live" if live is not None else "")
                       + ("_current_moat" if moat_only else "") + ".json")
    with open(out, "w") as fh:
        json.dump({
            "scope": scope, "dossiers": dossiers, "ruled_cited_checks": ruled_cited,
            "checks_with_figures": checks_with_figures, "figures": n,
            "verdict_passage_truncate": VERDICT_PASSAGE_TRUNCATE,
            "buckets": dict(tot),
            "checks_all_traceable": checks_all_traceable,
            "checks_with_untraceable": checks_with_untraceable,
            "live_items": (len(live) if live is not None else None),
            "live_items_dirty": (sorted(dirty_items) if live is not None else None),
            "by_check": {k: dict(v) for k, v in by_check.items()},
            "by_verdict": {k: dict(v) for k, v in by_verdict.items()},
            "examples": untraceable_examples,
        }, fh, indent=2, sort_keys=True)
    print(f"\nreceipts -> {os.path.relpath(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
