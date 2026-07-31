#!/usr/bin/env python3
"""Backfill truthful per-pack telemetry into the store from the grounded dossiers.

The storefront DTO (/catalog and /catalog/{id}) already projects WhoPays, SourceCount,
VerifiedAt, QaVerdictSummary, WhatYouGet, SampleExtract, FinancialSnapshot, etc. Those
columns were shipped empty, so every card rendered as an identical hardcoded-looking block.
This reads each pack's PASS dossier and fills those columns with REAL data only:

  * source counts + supported-gate counts straight off the verification checks
  * the verified-on date (the heartbeat, no fabricated scarcity)
  * who pays + market size from the candidate
  * the 6-axis opportunity scorecard from the real score axes
  * the FAILURE VECTOR: the actual refuted check, or the commodity premortem (honest cons)
  * the "what's inside the box" anatomy: the four artifacts + the dossier sections

Source-or-die: nothing is invented. A pack with no grounded dossier (0 sources) is NOT
listed; its "stress-tested" claim would be a lie. IsListed is set to 1 only for packs that
are BOTH grounded (>= MIN_SUPPORTED supported checks AND >= MIN_SOURCES sources) AND have a
ContentKey (a real delivered file). Everything else is delisted.

Usage:  python backfill_pack_telemetry.py --db /path/to/store.db [--dossiers store/dossiers]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys

MIN_SUPPORTED = 2
MIN_SOURCES = 8

AXIS_LABELS = {
    "pain_acuity": "Pain acuity",
    "money_provability": "Money provability",
    "defensibility": "Defensibility",
    "distribution": "Distribution",
    "build_feasibility": "Build feasibility",
    "automatability": "Automatable vs hands on",
}


def nodash(s: str | None) -> str:
    """House rule: no dashes as punctuation in customer-facing copy."""
    if not s:
        return ""
    s = s.replace("—", ", ").replace("–", ", ")
    s = re.sub(r"\s+-\s+", ", ", s)
    return re.sub(r"\s+", " ", s).strip()


_ABBR = ["approx.", "e.g.", "i.e.", "etc.", "vs.", "Inc.", "Ltd.", "No.", "U.K.", "U.S."]


def first_sentence(s: str, maxlen: int = 180) -> str:
    s = nodash(s)
    if not s:
        return ""
    prot = s
    for a in _ABBR:  # shield abbreviation dots so they don't read as sentence ends
        prot = prot.replace(a, a.replace(".", "\x00"))
    # A real sentence end: . ! ? followed by space + capital/paren, or end of string.
    m = re.search(r"(.+?[.!?])(\s+[A-Z(\"']|\s*$)", prot)
    out = (m.group(1) if m else prot).replace("\x00", ".")
    if len(out) > maxlen:
        out = out[:maxlen].rsplit(" ", 1)[0].rstrip(",.;: ") + "."
    return out


def telemetry(d: dict) -> dict:
    c = d.get("candidate", {})
    checks = d.get("checks", [])
    supported = [x for x in checks if x.get("verdict") == "supported"]
    refuted = [x for x in checks if x.get("verdict") == "refuted"]
    src = sum(len(x.get("sources") or []) for x in checks) + len(d.get("sources") or [])
    tot = len(checks)
    scores = (d.get("score") or {}).get("scores", {}) or {}
    tags = c.get("tags", {}) or {}
    premortem = tags.get("commodity_premortem") or {}
    if not isinstance(premortem, dict):  # some dossiers store it as a bare string
        premortem = {}

    # Failure vector: the real refuted check first; else the strongest free alternative
    # (the honest "why this might not work"). Never empty for a grounded pack.
    if refuted:
        fv = first_sentence(refuted[0].get("rationale", ""), 220)
    else:
        fv = first_sentence(premortem.get("strongest_free_or_commodity_alternative", ""), 220)

    qa = (f"{len(supported)} of {tot} verification gates supported by {src} cited sources. "
          "Survived adversarial review.")
    if fv:
        qa += f" Main risk surfaced: {fv}"

    autom = scores.get("automatability")
    effort = ("Hands on service" if autom is not None and autom <= 1
              else "Part automatable" if autom is not None and autom <= 3
              else "Highly automatable" if autom is not None else None)

    whatyouget = [
        f"The grounded opportunity dossier: {tot} verification checks with {src} cited "
        "sources you can re check yourself",
        "Build spec: the exact service and how to ship it as a solo operator",
        "Go to market plan: who to reach first and the opening move",
        "Operations playbook: how to run it week to week",
        "Unit economics: the money model and what it costs to start",
        "Commodity premortem: your strongest free competitor and why it cannot capture this",
    ]
    if refuted:
        whatyouget.append("Failure vectors: every check that pushed back, in full")

    sample = []
    if c.get("who_pays"):
        sample.append("Who pays. " + nodash(c["who_pays"])[:240])
    if premortem.get("strongest_free_or_commodity_alternative"):
        sample.append("Strongest free alternative. "
                      + first_sentence(premortem["strongest_free_or_commodity_alternative"], 240))
    if refuted:
        sample.append("Where it pushed back. " + first_sentence(refuted[0].get("rationale", ""), 240))
    if not sample and supported:  # always give a real, grounded taste
        sample.append("From the evidence. " + first_sentence(supported[0].get("rationale", ""), 240))

    snapshot = {lab: f"{scores[k]} of 5" for k, lab in AXIS_LABELS.items() if k in scores}

    return {
        "supported": len(supported),
        "total": tot,
        "sources": src,
        "grounded": len(supported) >= MIN_SUPPORTED and src >= MIN_SOURCES,
        # Headline/Subhead deliberately NOT auto-filled: the hypothesis field is internal
        # reasoning scaffolding ("First-principles reframe:") and why_now carries ungrounded
        # generation-stage numbers. The oneLine is the headline; everything else below is
        # derived from the VERIFICATION (grounded) so it is safe to print.
        "Headline": None,
        "Subhead": None,
        "WhoPays": nodash(c.get("who_pays", ""))[:220] or None,
        "EffortTag": effort,
        "ProofPoint": (f"Grounded in {src} cited sources. {len(supported)} of {tot} checks "
                       "supported by evidence."),
        "QaVerdictSummary": qa,
        "SourceCount": src,
        "VerifiedAt": d.get("created_at"),
        "WhatYouGetJson": json.dumps(whatyouget),
        "SampleExtractJson": json.dumps(sample),
        "FinancialSnapshotJson": json.dumps(snapshot),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--dossiers", default="store/dossiers")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT Id, Title, ContentKey FROM Packs").fetchall()

    listed, delisted = [], []
    for r in rows:
        path = os.path.join(args.dossiers, f"{r['Id']}.pass.json")
        if not os.path.exists(path):
            t = {"grounded": False, "sources": 0, "supported": 0, "total": 0}
            con.execute("UPDATE Packs SET IsListed=0 WHERE Id=?", (r["Id"],))
            delisted.append((r["Title"], "no dossier"))
            continue
        t = telemetry(json.load(open(path, encoding="utf-8")))
        do_list = bool(t["grounded"] and r["ContentKey"])
        con.execute(
            """UPDATE Packs SET Headline=?, Subhead=?, WhoPays=?, EffortTag=?, ProofPoint=?,
                 QaVerdictSummary=?, SourceCount=?, VerifiedAt=?, WhatYouGetJson=?,
                 SampleExtractJson=?, FinancialSnapshotJson=?, IsListed=? WHERE Id=?""",
            (t["Headline"], t["Subhead"], t["WhoPays"], t["EffortTag"], t["ProofPoint"],
             t["QaVerdictSummary"], t["SourceCount"], t["VerifiedAt"], t["WhatYouGetJson"],
             t["SampleExtractJson"], t["FinancialSnapshotJson"], 1 if do_list else 0, r["Id"]),
        )
        (listed if do_list else delisted).append(
            (r["Title"], f"{t['supported']}/{t['total']} sup, {t['sources']} src"))

    if args.apply:
        con.commit()
    con.close()

    print(f"{'APPLIED' if args.apply else 'DRY RUN'} against {args.db}\n")
    print(f"LISTED ({len(listed)}):")
    for t, why in listed:
        print(f"  + {t[:46]:46} {why}")
    print(f"\nDELISTED ({len(delisted)}):")
    for t, why in delisted:
        print(f"  - {t[:46]:46} {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
