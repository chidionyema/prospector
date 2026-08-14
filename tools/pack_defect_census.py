"""Census: how many of the packs ON SALE carry each defect in docs/PACK_QUALITY_PROGRAM.md.

The programme's own closing rule (`docs/PACK_QUALITY_PROGRAM.md:240-244`) is why this exists:

    "Nothing in this list is measured across the corpus yet. Every item above is proven on ONE
     pack. ... A defect on 1 of 62 is a repair; a defect on 62 of 62 is a generator change."

Every finding in that programme came from reading a single pack (`8d5e24fbe6c1f5d3`). One pack
cannot tell you whether to patch a listing or change the generator, and guessing wrong is the
difference between an afternoon and a fortnight. This counts.

SOURCE OF TRUTH: R2, via `tools/preview_packs.py::zip_for` — the same bytes the buyer's
presigned download resolves to. `publish/bundles/` on this disk is what was BUILT, and on
2026-08-14 it disagreed with what is SERVED for seven packs. Never census from disk.

    set -a; . .env; set +a
    .venv/bin/python tools/pack_defect_census.py

Read-only: it fetches the catalogue, reads objects out of the bucket, and writes one receipt
file. It never touches the catalogue, the bucket, the ledger or a listing.

EVERY DETECTOR IS LITERAL, AND SAYS SO. A detector that infers is a detector that invents a
number; where a defect cannot be decided by a literal string or a parse, it is reported as
`heuristic` in the receipt and must not be quoted as a count without opening the packs it flags.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "tools" / "experiments" / "pack_defect_census_receipts.json"

_spec = importlib.util.spec_from_file_location("preview_packs", REPO / "tools" / "preview_packs.py")
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)

CORE = pp.CORE
FINANCIAL = "04_Financial_Model.md"

# --------------------------------------------------------------------------------------------
# Detectors. Each returns (hit: bool, evidence: str). `kind` is "literal" or "heuristic".
# --------------------------------------------------------------------------------------------

#: P1. The placeholder strings the generator emits when it cannot compute a figure
#: (`prospector/artifacts.py:192,216,234,246,248,271,291,295` per the programme, §P1).
_PLACEHOLDER = re.compile(
    r"\((?:not specified|price or customer target not specified|COGS not specified|"
    r"cannot compute[^)]*|no [^)]*specified)\)", re.I)

#: P2(b). `dossier.py:413,440` join citation ids inside backticks; a renderer that strips inline
#: code spans leaves the separators behind. The symptom is the separator with nothing between.
_BARE_SOURCES = re.compile(r"Sources? used:\s*(?:,\s*){2,}")

#: P2(c). Same root cause at `dossier.py:507` — the id is backticked, the label is not.
_BLANK_ID = re.compile(r"Candidate ID:\s*(?:</[^>]+>|\n|$)")

#: P2(d). The operator chain is an audit fact, not buyer-facing copy (`dossier.py:504`).
_CHAIN = re.compile(r"Judged by:[^<\n]*fallback\(", re.I)

#: P0. The unconditional PASS banner (`dossier.py:299-300`) next to a check that came back
#: against the idea. Both strings must be present in the same pack for the contradiction to be
#: the one a buyer can screenshot.
_BANNER = re.compile(r"cleared every check we hold it to", re.I)
_REFUTED = re.compile(r"(?:❌|the sources contradict this|verdict:\s*refuted)", re.I)

#: P7. A printed expiry is a promise with a price we have not set.
_SHELF = re.compile(r"(?:evidence goes stale after|stale after)\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.I)

#: P3. Domains that cannot carry a load-bearing claim: a mood board, an upload, a video or a
#: blog restating a primary source. This is a SOURCE-QUALITY list, not a blocklist of bad sites —
#: the programme's point is that a retrieved primary source must outrank a blog restating it.
_WEAK_DOMAINS = ("pinterest.", "scribd.com", "youtube.com", "youtu.be", "blogspot.",
                 "wordpress.com", "medium.com", "quora.com", "reddit.com", "facebook.com",
                 "tiktok.com", "instagram.com", "etsy.com", "jeffreydachmd.com")
_URL = re.compile(r"https?://([^\s/\"'<>)\]]+)")

#: P6. The labels were swapped on the reviewed pack: the Launch Email section held a product
#: description, the Listing Page section opened with `Subject:`.
_LISTING_SECTION = re.compile(r"Listing Page(.{0,400})", re.I | re.S)
_EMAIL_SECTION = re.compile(r"Launch Email(.{0,400})", re.I | re.S)

#: P2(a). A hard character clip (`trimming.py RATIONALE_MAX`) leaves prose ending mid-word with
#: no terminal punctuation. HEURISTIC: a long run of text ending on a bare lowercase word.
_MIDWORD = re.compile(r"[a-z]{4,}[a-z]\s*(?:</(?:p|li|td|div)>|\n)")
_SENTENCE = re.compile(r"[^.!?\n]{60,}[.!?]")


def _text_of(zf) -> dict[str, str]:
    out = {}
    for name in zf.namelist():
        if name.endswith((".md", ".html", ".txt", ".json")):
            out[name] = zf.read(name).decode("utf8", "replace")
    return out


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s)


def audit(pid: str, texts: dict[str, str], names: list[str]) -> dict:
    """Every defect, decided per pack, with the evidence that decided it."""
    joined = "\n".join(texts.values())
    plain = _strip_tags(joined)
    md = {k: v for k, v in texts.items() if k.endswith(".md")}
    fin = texts.get(FINANCIAL, "")

    hits: dict[str, dict] = {}

    def note(key, hit, evidence="", kind="literal"):
        hits[key] = {"hit": bool(hit), "evidence": str(evidence)[:220], "kind": kind}

    # P0 — the banner claims more than the lane checked
    banner, ref = _BANNER.search(joined), _REFUTED.search(joined)
    note("P0_pass_banner_over_a_refuted_check", bool(banner and ref),
         f"banner={bool(banner)} refuted_marker={ref.group(0) if ref else None}")

    # P1 — the financial model cannot compute
    ph = _PLACEHOLDER.findall(fin)
    note("P1_financial_model_placeholders", bool(ph), f"{len(ph)}x e.g. {ph[:3]}")
    note("P1_monthly_arpu_on_a_one_off",
         bool(re.search(r"ARPU", fin, re.I) and re.search(r"/\s*month|per month", fin, re.I)),
         "ARPU quoted per month")

    # P2 — shipped-broken rendering
    note("P2b_sources_used_is_bare_separators", bool(_BARE_SOURCES.search(plain)),
         (_BARE_SOURCES.search(plain) or [""])[0] if _BARE_SOURCES.search(plain) else "")
    note("P2c_candidate_id_blank", bool(_BLANK_ID.search(joined)), "")
    note("P2d_operator_chain_shown_to_buyer", bool(_CHAIN.search(joined)),
         (_CHAIN.search(joined).group(0) if _CHAIN.search(joined) else ""))
    mid = _MIDWORD.findall(plain)
    note("P2a_text_cut_mid_word", len(mid) >= 3, f"{len(mid)} suspected clips", kind="heuristic")

    # P3 — sourcing that will not survive scrutiny
    domains = Counter(d.lower() for d in _URL.findall(joined))
    weak = {d: n for d, n in domains.items() if any(w in d for w in _WEAK_DOMAINS)}
    note("P3_non_primary_sources_cited", bool(weak), json.dumps(weak)[:200])
    dupe_urls = sum(n - 1 for n in domains.values() if n > 1)
    note("P3_source_count_padded_by_repeats", dupe_urls >= 5,
         f"{dupe_urls} repeated host citations across {len(domains)} hosts", kind="heuristic")

    # P4 — the same words sold three times
    sent_home = defaultdict(set)
    for fname, body in md.items():
        for s in _SENTENCE.findall(_strip_tags(body)):
            sent_home[" ".join(s.split()).lower()].add(fname)
    repeated = {s: sorted(f) for s, f in sent_home.items() if len(f) > 1}
    share = (len(repeated) / len(sent_home)) if sent_home else 0.0
    note("P4_same_sentences_in_multiple_documents", len(repeated) >= 5,
         f"{len(repeated)}/{len(sent_home)} sentences ({share:.0%}) appear in 2+ documents")

    # P5 — format
    note("P5_markdown_zip_no_typeset_artefact",
         not any(n.lower().endswith(".pdf") for n in names),
         f"{sum(1 for n in names if n.endswith('.md'))} .md files, "
         f"{sum(1 for n in names if n.lower().endswith('.pdf'))} .pdf")

    # P6 — marketing assets aimed at the wrong reader
    lp = _LISTING_SECTION.search(joined)
    em = _EMAIL_SECTION.search(joined)
    swapped = bool(lp and re.search(r"Subject:", lp.group(1), re.I))
    note("P6_listing_page_is_an_email", swapped, (lp.group(1)[:120] if lp else "no section"))
    note("P6_launch_email_has_no_subject",
         bool(em) and not re.search(r"Subject:", em.group(1), re.I),
         (em.group(1)[:120] if em else "no section"))
    note("P6_asset_sells_our_pack_not_their_product",
         bool(re.search(r"(?:opportunity pack|open the pack|this pack)", joined, re.I)),
         "buyer-facing copy refers to OUR pack", kind="heuristic")

    # P7 — an unpriced shelf life, printed as a promise
    m = _SHELF.search(joined)
    note("P7_prints_an_expiry_date", bool(m), m.group(1) if m else "")

    return {"id": pid, "checks": hits}


def main() -> int:
    api = os.environ.get("STORE_API_URL", pp.DEFAULT_API_URL)
    rows = pp.fetch_catalogue(api)
    print(f"catalogue: {len(rows)} packs on sale", file=sys.stderr)

    s3, bucket = pp._s3()
    ctx = {"api_url": api, "internal_key": os.environ.get("STORE_INTERNAL_API_KEY", ""),
           "s3": s3, "bucket": bucket}

    audited, skipped = [], []
    for i, row in enumerate(rows, 1):
        pid = row["id"]
        try:
            zf, where = pp.zip_for(pid, "r2", ctx)
        except Exception as exc:
            skipped.append({"id": pid, "why": f"{type(exc).__name__}: {exc}"})
            continue
        if zf is None:
            skipped.append({"id": pid, "why": where})
            continue
        rec = audit(pid, _text_of(zf), zf.namelist())
        rec["title"] = row.get("title") or pid
        rec["price"] = row.get("price")
        audited.append(rec)
        print(f"  [{i}/{len(rows)}] {pid} {rec['title'][:52]}", file=sys.stderr)

    keys = sorted({k for r in audited for k in r["checks"]})
    tally = {k: sum(1 for r in audited if r["checks"].get(k, {}).get("hit")) for k in keys}
    n = len(audited)

    print(f"\n{'defect':52s} {'packs':>9s}   verdict")
    print("-" * 90)
    for k in sorted(keys, key=lambda x: -tally[x]):
        c = tally[k]
        kind = next((r["checks"][k]["kind"] for r in audited if k in r["checks"]), "literal")
        verdict = ("GENERATOR CHANGE" if n and c >= 0.9 * n else
                   "WIDESPREAD" if n and c >= 0.5 * n else
                   "PARTIAL" if c else "clean")
        print(f"{k:52s} {c:4d}/{n:<4d}   {verdict}{'  (heuristic)' if kind == 'heuristic' else ''}")
    if skipped:
        print(f"\nnot audited: {len(skipped)} — {json.dumps(skipped[:5])}")

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps({
        "_meta": {"experiment": "pack_defect_census", "run_at_utc":
                  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "source": "r2", "catalogue": api},
        "verdict": (f"{n} packs audited; "
                    + "; ".join(f"{k}={tally[k]}/{n}" for k in sorted(keys, key=lambda x: -tally[x])[:4])),
        "n_audited": n, "tally": tally, "skipped": skipped, "packs": audited,
    }, indent=2))
    print(f"\nreceipt → {RECEIPT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
