#!/usr/bin/env python3
"""Reconcile paid Stripe checkout sessions against what the store actually delivered.

Why this exists: PAID-WITHOUT-FULFILMENT and FULFILMENT-EMAIL-FAILED are ERROR log lines
inside the API (WebhookEndpoints.cs:71-75). Nobody reads logs. A webhook that never lands, or
lands and fails, means a buyer paid and got nothing — and the only trace is a line in a log
stream on a Fly machine. This turns that into a command with an exit code.

How it works: Stripe is the source of truth for "who paid". For every paid session, ask the
store's own /api/orders/by-session/{id} whether it can produce a download. That endpoint
answers "ready" only when an Order exists AND has at least one ACTIVE entitlement
(DeliveryEndpoints.cs:71-92), which is exactly the buyer-visible definition of delivered.

Two states are deliberately NOT failures:
  * Sessions paid within --grace-minutes (default 15). The webhook is normally in flight for
    seconds; alarming on that would make the probe cry wolf on every real sale.
  * Refunded / disputed charges. Revocation sets entitlements to Revoked by design
    (FulfilmentService.cs:151-154), so the endpoint correctly stops saying "ready". Counting
    those as failures would make every successful refund look like a delivery bug.

A third state is excused by ledger: store_platform/data/reconcile-exceptions.json lists sessions
that must not count as failures, each with a written reason. This exists because one known-bad
historical order otherwise red-lights the probe forever, and a permanently red probe hides the
real failure it was built to catch. Excuses are printed on every run, never silent, and they
apply ONLY to undelivered orders — an unreachable store can never be waved through.

Read-only. Exit 0 = every paid buyer can download what they bought.

    python3 store_platform/scripts/reconcile_orders.py
    python3 store_platform/scripts/reconcile_orders.py --days 30 --json
    python3 store_platform/scripts/reconcile_orders.py --no-exceptions   # audit the ledger
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = Path(os.environ.get("PROSPECTOR_ENV_PATH", REPO_ROOT / ".env"))
EXCEPTIONS_PATH = REPO_ROOT / "store_platform" / "data" / "reconcile-exceptions.json"
STRIPE_API = "https://api.stripe.com/v1"
DEFAULT_API_BASE = "https://api.mumchimp.com"


def load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def http_json(url: str, headers: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(url, method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": body}
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, {"error": str(e)}


def stripe_get(path: str, key: str, params: dict):
    auth = base64.b64encode(f"{key}:".encode()).decode()
    url = f"{STRIPE_API}/{path}?{urllib.parse.urlencode(params)}"
    status, body = http_json(url, {"Authorization": f"Basic {auth}"})
    if status >= 300:
        msg = (body or {}).get("error", {}).get("message", body)
        raise RuntimeError(f"Stripe {path} failed ({status}): {msg}")
    return body


def paid_sessions(key: str, since_ts: int):
    """Every checkout session created since `since_ts` whose payment_status is paid."""
    out, starting_after = [], None
    while True:
        params = {"limit": 100, "created[gte]": since_ts}
        if starting_after:
            params["starting_after"] = starting_after
        page = stripe_get("checkout/sessions", key, params)
        data = page.get("data", [])
        out.extend(s for s in data if s.get("payment_status") == "paid")
        if not page.get("has_more") or not data:
            return out
        starting_after = data[-1]["id"]


def is_reversed(key: str, session: dict) -> bool:
    """True if this session's payment was refunded or disputed.

    Revocation is the intended outcome there, so the store correctly stops reporting the
    download as available and it must not be counted as an undelivered sale.
    """
    pi_id = session.get("payment_intent")
    if not pi_id:
        return False
    try:
        pi = stripe_get(f"payment_intents/{pi_id}", key, {"expand[]": "latest_charge"})
    except RuntimeError:
        return False
    charge = pi.get("latest_charge") or {}
    if isinstance(charge, str):
        return False
    return bool(charge.get("refunded")) or bool(charge.get("disputed")) \
        or (charge.get("amount_refunded") or 0) > 0


def load_exceptions(path: Path) -> dict:
    """Sessions deliberately excused from the delivery check.

    Deliberately strict: a malformed file or a blank reason is a hard error rather than a
    silent "no exceptions". This file's whole job is to be the one sanctioned way to make the
    probe green, so a typo in it must never quietly widen or silently discard the excuse list.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{path} is not valid JSON ({e}). Refusing to guess whether an "
                           "order was excused.") from e

    entries = raw.get("exceptions", {})
    if not isinstance(entries, dict):
        raise RuntimeError(f"{path}: 'exceptions' must be an object keyed by session id.")

    for sid, meta in entries.items():
        reason = (meta or {}).get("reason", "").strip() if isinstance(meta, dict) else ""
        if not reason:
            raise RuntimeError(
                f"{path}: exception for {sid} has no reason. An excused delivery failure means "
                "a payer got nothing — that always needs a written justification.")
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7,
                    help="how far back to reconcile (default 7)")
    ap.add_argument("--grace-minutes", type=int, default=15,
                    help="ignore sessions paid this recently; the webhook is still in flight")
    ap.add_argument("--api-base", default=os.environ.get("STORE_API_BASE", DEFAULT_API_BASE))
    ap.add_argument("--stripe-key-var", default="STRIPE_API_KEY")
    ap.add_argument("--allow-test-mode", action="store_true",
                    help="permit reconciling with a TEST-mode Stripe key (see the mode check)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--exceptions", type=Path, default=EXCEPTIONS_PATH,
                    help="ledger of sessions excused from the delivery check "
                         f"(default {EXCEPTIONS_PATH})")
    ap.add_argument("--no-exceptions", action="store_true",
                    help="ignore the ledger and report every undelivered order, excused or not")
    args = ap.parse_args()

    try:
        excused = {} if args.no_exceptions else load_exceptions(args.exceptions)
    except RuntimeError as e:
        print(f"  FAIL  {e}", file=sys.stderr)
        return 2

    env = load_env(ENV_PATH)
    skey = os.environ.get(args.stripe_key_var) or env.get(args.stripe_key_var)
    if not skey:
        print(f"  FAIL  {args.stripe_key_var} not set (checked env and {ENV_PATH}).",
              file=sys.stderr)
        print("        Cannot reconcile without Stripe — refusing to report PASS on no data.",
              file=sys.stderr)
        return 2

    # A TEST-mode key lists TEST-mode sessions, which the live store can never resolve — every
    # one of them reports as undelivered, and the run looks like a catastrophic outage that is
    # really just the wrong Stripe account. The inverse is worse: a green run that certifies
    # nothing about the store that actually takes money. Refuse to guess which was meant.
    mode = "test" if "_test_" in skey else "live" if "_live_" in skey else "unknown"
    if mode != "live" and not args.allow_test_mode:
        print(f"  FAIL  {args.stripe_key_var} is a {mode.upper()}-mode Stripe key, but this "
              f"reconciles against {args.api_base}.", file=sys.stderr)
        print("        Test-mode sessions cannot resolve against a live store, so every result "
              "would be meaningless.", file=sys.stderr)
        print("        Use a live key, or pass --allow-test-mode to reconcile a test "
              "environment on purpose.", file=sys.stderr)
        return 2

    now = int(time.time())
    since = now - args.days * 86400
    cutoff = now - args.grace_minutes * 60
    api_base = args.api_base.rstrip("/")

    try:
        sessions = paid_sessions(skey, since)
    except RuntimeError as e:
        print(f"  FAIL  {e}", file=sys.stderr)
        return 2

    mature = [s for s in sessions if (s.get("created") or 0) <= cutoff]
    in_flight = len(sessions) - len(mature)

    undelivered, unreachable, excused_hits, refunded, delivered = [], [], [], 0, 0

    for s in mature:
        sid = s["id"]
        status, body = http_json(f"{api_base}/api/orders/by-session/{urllib.parse.quote(sid)}")
        if status == 0 or status >= 500:
            # NOTE: deliberately checked BEFORE the exception ledger. An excused session still
            # has to be reachable — "the store is down" is never something the ledger may hide.
            unreachable.append((sid, status, body.get("error") or body))
            continue
        if body.get("status") == "ready" and body.get("items"):
            delivered += 1
            continue
        # Not deliverable right now. A refund explains that legitimately; nothing else does.
        if is_reversed(skey, s):
            refunded += 1
            continue
        if sid in excused:
            excused_hits.append({"session": sid, "reason": excused[sid]["reason"]})
            continue
        undelivered.append({
            "session": sid,
            "amount": s.get("amount_total"),
            "currency": (s.get("currency") or "").upper(),
            "email": (s.get("customer_details") or {}).get("email"),
            "created": s.get("created"),
            "store_status": body.get("status"),
            "http": status,
        })

    result = {
        "stripe_mode": mode,
        "window_days": args.days,
        "paid_sessions": len(sessions),
        "in_flight_skipped": in_flight,
        "delivered": delivered,
        "refunded_or_disputed": refunded,
        "excused": excused_hits,
        "undelivered": undelivered,
        "unreachable": [{"session": a, "http": b} for a, b, _ in unreachable],
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        line = "-" * 60
        print(line)
        print(f"RECONCILE  last {args.days}d against {api_base}  [Stripe {mode.upper()} mode]")
        print(line)
        print(f"  ....  {len(sessions)} paid session(s); {in_flight} within grace, not yet due")
        print(f"  PASS  {delivered} delivered (order + active entitlement)")
        if refunded:
            print(f"  ....  {refunded} refunded/disputed — revocation is expected, not a fault")
        # Printed, never silent: an excused failure is still a payer who got nothing, and the
        # moment it stops being visible it stops being reviewed.
        for x in excused_hits:
            print(f"  EXCUSED  {x['session']}")
            print(f"           {x['reason'][:150]}")
        for u in undelivered:
            amt = f"{(u['amount'] or 0) / 100:.2f} {u['currency']}"
            print(f"  FAIL  PAID-WITHOUT-DELIVERY  {u['session']}  {amt}  "
                  f"{u['email'] or 'no-email'}  (store said '{u['store_status']}')")
        for sid, code, err in unreachable:
            print(f"  FAIL  store unreachable for {sid} (HTTP {code}) — {err}")
        print(line)
        if undelivered or unreachable:
            print(f"RECONCILE: FAIL — {len(undelivered)} buyer(s) paid without delivery, "
                  f"{len(unreachable)} unverifiable")
        elif excused_hits:
            print(f"RECONCILE: OK — every paid buyer can download what they bought "
                  f"({len(excused_hits)} excused, see {args.exceptions.name})")
        else:
            print("RECONCILE: OK — every paid buyer can download what they bought")
        print(line)

    return 1 if (undelivered or unreachable) else 0


if __name__ == "__main__":
    sys.exit(main())
