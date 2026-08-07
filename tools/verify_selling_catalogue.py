#!/usr/bin/env python3
"""Does every pack a buyer can purchase right now still have a PASS behind it?

Nothing in the engine walks the selling catalogue after a re-vet. That gap is not
hypothetical: `467187f2c95cb3b5` ("The Brief Winnow") was found SELLING with only a KILL
dossier on disk — 1 of 57 — and it took a bundle backfill to notice. `decay.py:52-56`
records the same class from the other direction: four candidates re-vetted to KILL "kept
selling live on mumchimp.com because store/listings/{cid}.json and Store.Api's IsListed both
outlive the kill".

The check itself is trivial and always was. What makes it worth a file is the DENOMINATOR,
which is the part that has produced wrong answers twice (§25 of the readiness programme):

  * `store/listings/*.json` is NOT the catalogue — it is a local receipt, and receipts
    outlive listings. 21 of 77 receipt files have no live listing at all.
  * `store_platform/.../store.db` is NOT the catalogue — it is a DEV database containing
    `demo-pack-001`. Querying it says a live, selling product is absent.
  * The catalogue is the production API: `GET https://api.mumchimp.com/catalog`.

So this reads the production catalogue and asks one question per row. Read-only, zero LLM,
one HTTP GET. Exit 1 when any selling pack lacks a PASS, so it can be wired into the estate
probe or a scheduled tick and FAIL rather than merely print.

Usage:
    .venv/bin/python tools/verify_selling_catalogue.py
    .venv/bin/python tools/verify_selling_catalogue.py --catalogue /tmp/cat.json   # offline
    .venv/bin/python tools/verify_selling_catalogue.py --json                      # receipts
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospector.paths import repo_path  # noqa: E402

DEFAULT_CATALOGUE_URL = "https://api.mumchimp.com/catalog"


def fetch_catalogue(url: str, timeout: int = 30) -> list[dict]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    # The endpoint has returned both a bare list and an envelope over its life. Accept both
    # rather than reporting an empty catalogue — "0 packs selling" is the most dangerous
    # false PASS this probe could produce, because it looks like nothing is wrong.
    if isinstance(payload, dict):
        for key in ("items", "packs", "catalog", "data", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
        raise ValueError(f"unrecognised catalogue envelope, keys={sorted(payload)}")
    if not isinstance(payload, list):
        raise ValueError(f"unrecognised catalogue payload of type {type(payload).__name__}")
    return payload


def pack_id_of(row: dict) -> str:
    for key in ("candidateId", "candidate_id", "id", "packId", "pack_id", "slug"):
        val = row.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def dossier_state(candidate_id: str) -> tuple[str, str]:
    """Return (state, path). State is one of pass / kill / defer / missing."""
    base = repo_path("store", "dossiers")
    for suffix, state in ((".pass.json", "pass"), (".kill.json", "kill"),
                          (".defer.json", "defer")):
        p = base / f"{candidate_id}{suffix}"
        if p.exists():
            return state, str(p)
    return "missing", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", help="Offline catalogue JSON instead of the live GET")
    ap.add_argument("--url", default=DEFAULT_CATALOGUE_URL)
    ap.add_argument("--json", action="store_true", help="Emit a JSON receipt on stdout")
    args = ap.parse_args()

    try:
        if args.catalogue:
            rows = json.loads(Path(args.catalogue).read_text())
            rows = rows if isinstance(rows, list) else rows.get("items", [])
        else:
            rows = fetch_catalogue(args.url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # An unreachable catalogue is UNKNOWN, never PASS. A probe that reports green when
        # it could not look is worse than no probe.
        print(f"FATAL: could not read the catalogue: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    findings, ok = [], 0
    for row in rows:
        cid = pack_id_of(row)
        if not cid:
            findings.append({"id": None, "state": "unidentifiable", "row_keys": sorted(row)})
            continue
        state, path = dossier_state(cid)
        if state == "pass":
            ok += 1
        else:
            findings.append({
                "id": cid,
                "state": state,
                "path": path,
                "title": row.get("title") or row.get("name"),
                "price": row.get("price") or row.get("priceGbp"),
            })

    print(f"selling packs checked : {len(rows)}")
    print(f"backed by a PASS      : {ok}")
    print(f"PROBLEMS              : {len(findings)}")
    for f in findings:
        print(f"  [{f['state'].upper()}] {f.get('id')} {f.get('title') or ''} "
              f"{f.get('price') or ''}")

    if args.json:
        print(json.dumps({"checked": len(rows), "ok": ok, "findings": findings}, indent=2))

    if findings:
        print("\nA pack selling without a PASS dossier must be unlisted or re-vetted. "
              "'Publish only on PASS' is the rule; this is the shelf-side check of it.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
