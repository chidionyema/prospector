#!/usr/bin/env python3
"""Bake one grounded PASS dossier into a static JSON for the free "Report #00" page.

The storefront on Fly has no endpoint that serves a full verification dossier (the detail
DTO only carries a few sample lines). The free sample needs the WHOLE thing: every check,
its verdict, its rationale, and its clickable sources. Rather than add an API surface, we
bake the chosen dossier into src/data/sample-report.json at build time. It is one fixed,
real report, so static is correct and reproducible.

Source-or-die: only real dossier content is emitted. Nothing is invented.

Usage:  python tools/make_sample_report.py <pack_id>
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlparse

OUT = "store_platform/src/Store.Web/src/data/sample-report.json"

# Human, refutational framing for each gate (matches the storefront's voice).
CHECK_LABELS = {
    "buyer_intent": "Is anyone actually trying to buy this?",
    "pain_reality": "Is the pain real, or imagined?",
    "pain_acuity": "Is the pain real, or imagined?",
    "value_durability": "Will the value last, or evaporate?",
    "incumbency": "Do incumbents already own the space?",
    "incumbent": "Do incumbents already own the space?",
    "payer_solvency": "Can the payer actually pay?",
    "distribution": "Is there a route to reach the market?",
    "route_to_market": "Can it actually reach buyers?",
    "currency": "Is real money flowing here today?",
    "claims_verifiable": "Do its own claims hold up to checking?",
    "legality": "Is there a legal landmine?",
    "moat": "Is there anything to defend?",
}


def nodash(s: str) -> str:
    if not s:
        return ""
    s = s.replace("—", ", ").replace("–", ", ")
    s = re.sub(r"\s+-\s+", ", ", s)
    return re.sub(r"\s+", " ", s).strip()


def source_label(src: dict) -> str:
    url = src.get("url", "")
    host = urlparse(url).netloc.replace("www.", "")
    # Prefer the first non-empty line of the fetched text as a title, else the host.
    text = (src.get("text") or "").strip()
    first = next((ln.strip(" #") for ln in text.splitlines() if ln.strip(" #")), "")
    if first and len(first) <= 90:
        return first
    return host or "source"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: make_sample_report.py <pack_id>", file=sys.stderr)
        return 2
    pid = sys.argv[1]
    d = json.load(open(f"store/dossiers/{pid}.pass.json", encoding="utf-8"))
    c = d["candidate"]
    tags = c.get("tags", {}) or {}
    pm = tags.get("commodity_premortem")
    pm = pm if isinstance(pm, dict) else {}

    checks_out = []
    supported = 0
    total_sources = 0
    for ch in d.get("checks", []):
        v = ch.get("verdict")
        if v == "supported":
            supported += 1
        srcs, seen = [], set()  # dedup WITHIN a check so each gate shows its own citation
        for s in ch.get("sources") or []:
            url = s.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            srcs.append({"url": url, "label": nodash(source_label(s))})
        total_sources += len(srcs)
        name = ch.get("check_name", "")
        checks_out.append({
            "name": CHECK_LABELS.get(name, name.replace("_", " ").capitalize()),
            "key": name,
            "verdict": v,
            "confidence": round(float(ch.get("confidence") or 0), 2),
            "rationale": nodash(ch.get("rationale", "")),
            "sources": srcs,
        })

    adv = d.get("adversarial") or {}
    report = {
        "id": pid,
        "title": c.get("title"),
        "oneLiner": nodash(c.get("one_liner", "")),
        "whoPays": nodash(c.get("who_pays", "")),
        "whyNow": nodash(c.get("why_now", "")),
        "verifiedAt": d.get("created_at"),
        "supported": supported,
        "total": len(d.get("checks", [])),
        "sourceCount": total_sources,
        "scores": d.get("score", {}).get("scores", {}),
        "premortem": {
            "strongestAlternative": nodash(pm.get("strongest_free_or_commodity_alternative", "")),
            "whyDurable": nodash(pm.get("why_durable_anyway", "") or pm.get("why_durable", "")),
        },
        "adversarial": {
            "killCase": nodash(adv.get("kill_case", "")),
            "decisive": bool(adv.get("decisive")),
        },
        "checks": checks_out,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"wrote {OUT}: {report['title']!r}  {supported}/{report['total']} supported, "
          f"{total_sources} sources across {len(checks_out)} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
