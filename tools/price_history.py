"""Read the derivation behind a pack's price — the API's change log joined to the local record.

Why this exists
---------------
A price move leaves two artifacts, and until now neither could be read back:

* a `PackPriceHistory` row, written by `PATCH /internal/catalog/{id}/price` in the same
  transaction as the change. A grep for `PackPriceHistory` across `store_platform/src/`
  returned four hits — the class, the DbSet, the EF config, and one `.Add(`. No query, no
  endpoint, no test. `GET /internal/catalog/{id}/price-history` (added alongside this tool)
  is the read side.
* a rationale record under `store/pricing/rationale/`, written by
  `prospector.price_rationale.write_rationale`, holding the full `PriceDecision` and a
  snapshot of the ladder that was in force. The row points at it by `RationaleRef`.

Neither half answers "why is this pack £79" alone. The row says who and when and gives one
line of reason; the record says which segment, which rung, and which ladder — but is named
by a path nothing resolved. This joins them, and checks the join rather than assuming it:

  OK        the ref resolves and the record matches its own content digest
  MISSING   the row names a record that is not on disk (the write landed, the file did not,
            or it was never committed — records are deliberately NOT gitignored)
  TAMPERED  `read_rationale` refused it: the file no longer matches the digest in its path,
            so it is not provenance for anything

Exit codes follow the `verify_store.sh` convention that `storeops` is built on, because
collapsing them destroys the only property that makes a probe trustworthy:

  0  read, and coherent
  1  FAIL — checked and broken: the chain is discontinuous, or a record is MISSING/TAMPERED
  3  UNPROVEN — could not check: no internal key, API unreachable, or 401/404

Usage:
    python -m tools.price_history <pack_id>
    python -m tools.price_history <pack_id> --as-of 2026-07-01T12:00:00Z
    python -m tools.price_history <pack_id> --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

import requests

from prospector.price_rationale import read_rationale
from prospector.run import _load_dotenv

# The storefront (mumchimp.com) 404s on /catalog; the API is a separate host. Pointing this
# at the storefront returns HTML that json-decodes into an exception rather than a 404, so
# the default is the API and the failure mode of overriding it wrongly is loud.
DEFAULT_API_URL = os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}"


def fetch_history(api_url: str, pack_id: str, key: str, *,
                  as_of: Optional[str] = None, limit: Optional[int] = None,
                  timeout: int = 30) -> tuple[Optional[dict], str]:
    """GET the history. Returns (payload, error). Never raises on a network fault: the
    caller distinguishes "broken" from "could not check", and an exception collapses both
    into a traceback."""
    params: dict[str, Any] = {}
    if as_of:
        params["asOf"] = as_of
    if limit:
        params["limit"] = limit
    try:
        r = requests.get(f"{api_url.rstrip('/')}/internal/catalog/{pack_id}/price-history",
                         headers={"X-Internal-Key": key}, params=params, timeout=timeout)
    except requests.RequestException as e:
        return None, f"API unreachable: {e}"
    if r.status_code == 401:
        return None, "401 — STORE_INTERNAL_API_KEY is set but not the key this API expects"
    if r.status_code == 404:
        return None, f"404 — no pack '{pack_id}' in this catalogue"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    try:
        return r.json(), ""
    except ValueError:
        return None, f"response was not JSON (is {api_url} the API, not the storefront?)"


def resolve_rationale(ref: Optional[str]) -> tuple[str, Optional[dict], str]:
    """(status, record, detail) for one row's RationaleRef.

    Absent is not a fault: `RationaleRef` is optional, and a founder-applied price change
    legitimately has none. Only a ref that names something unreadable is a fault.
    """
    if not ref:
        return "none", None, ""
    try:
        return "ok", read_rationale(ref), ""
    except FileNotFoundError:
        return "missing", None, "no file at that path"
    except ValueError as e:
        return "tampered", None, str(e)
    except OSError as e:
        return "missing", None, str(e)


def _describe(record: dict) -> str:
    """One line of the derivation: what actually decided the number."""
    decision = record.get("decision") or {}
    segment = decision.get("segment") or {}
    ladder = record.get("ladder") or {}
    seg = "/".join(f"{k}={v}" for k, v in sorted(segment.items())) or "(no segment)"
    return (f"rung {decision.get('rung')} · {seg} · ladder "
            f"{ladder.get('version') or '?'} {ladder.get('fingerprint') or ''}")


def render(payload: dict, rows_resolved: list[tuple[dict, str, Optional[dict], str]]) -> None:
    print(f"pack {payload.get('packId')} — now {payload.get('currentPricePence')}p "
          f"(floor {payload.get('currentMinBillablePence')}p), published "
          f"{payload.get('publishedAt')}")
    print(f"origin {payload.get('originPricePence')}p · {payload.get('changeCount')} change(s) · "
          f"chain {'continuous' if payload.get('continuous') else 'BROKEN'}"
          + (" · response truncated" if payload.get("truncated") else ""))

    at = payload.get("asOf")
    if at:
        price = at.get("pricePence")
        print(f"\nas of {at.get('asOf')}: "
              + (f"{price}p" if price is not None else "not on sale")
              + f"  [{at.get('source')}]")

    if not rows_resolved:
        print("\nno recorded price changes — this pack has sold at its published price throughout.")
        return

    print()
    for row, status, record, detail in rows_resolved:
        print(f"{row.get('createdAt')}  {row.get('fromPence')}p -> {row.get('toPence')}p  "
              f"floor {row.get('minBillablePence')}p  by {row.get('actor')}")
        print(f"    reason: {row.get('reason')}")
        if status == "none":
            print("    rationale: (none recorded)")
        elif status == "ok" and record is not None:
            print(f"    rationale: OK  {row.get('rationaleRef')}")
            print(f"               {_describe(record)}")
        else:
            print(f"    rationale: {status.upper()}  {row.get('rationaleRef')}")
            print(f"               {detail}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack_id")
    ap.add_argument("--api-url", default=os.environ.get("STORE_API_URL") or DEFAULT_API_URL)
    ap.add_argument("--as-of", default=None,
                    help="ISO-8601 instant; resolves the price a buyer was shown then")
    ap.add_argument("--limit", type=int, default=None,
                    help="bound the rows returned (analysis is always over the whole chain)")
    ap.add_argument("--json", action="store_true", help="print the raw payload and exit 0")
    args = ap.parse_args(argv)

    _load_dotenv()
    key = os.environ.get("STORE_INTERNAL_API_KEY")
    if not key:
        print("UNPROVEN: STORE_INTERNAL_API_KEY unset — the history endpoint is key-gated.",
              file=sys.stderr)
        return 3

    payload, error = fetch_history(args.api_url, args.pack_id, key,
                                   as_of=args.as_of, limit=args.limit)
    if payload is None:
        print(f"UNPROVEN: {error}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    resolved = [(row, *resolve_rationale(row.get("rationaleRef")))
                for row in payload.get("history") or []]
    render(payload, resolved)

    broken = [s for _, s, _, _ in resolved if s in ("missing", "tampered")]
    if not payload.get("continuous"):
        print("\nFAIL: the price chain is discontinuous — a change was applied without a "
              "history row, so this record does not account for every price the pack has had.",
              file=sys.stderr)
        return 1
    if broken:
        print(f"\nFAIL: {len(broken)} change(s) name a rationale record that cannot be read.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
