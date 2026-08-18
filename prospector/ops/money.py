"""The Money screen's reader.

One question: can the shop take money right now, and would we know if it could not.

The rail's own answer is `GET /healthz/money-rail`, served by `Store.Api/Program.cs:404` from
the decision `MoneyRailConfigGate` made at startup. Three states matter and they are not the
same thing:

  * `live`      — the gate ran and the rail is on live keys.
  * `test`      — the gate ran and the rail is on test keys. A buyer's card is never charged.
  * never ran   — `decidedAtUtc` is null. Nothing checked the money rail at all, which is worse
                  than `test`, because `test` at least means a check happened.

An unreachable API is the END of a measurement, not a datum. It is reported as `unreachable`
with the error, never as a mode, because a screen that renders a missing answer as "test" or
as blank is how a dead rail reads as a healthy one.

Two things this screen does NOT show, and says so on the screen rather than leaving a blank:
today's revenue, and disputes and refunds (PAY-2). Neither has a route on the store API — the
whole `/internal/ops/*` family in `docs/OPS_CONSOLE_PROGRAM.md` 7.6 is recon, not code. A gap
named with the route that would close it is a work item; a blank panel is a lie.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

#: What has to be built before this screen can answer the other half of PAY-1..PAY-3. Each entry
#: names the route, so the gap is a ticket rather than an observation.
#:
#: Two of the original three are now built and are no longer listed here. `revenue-today` is
#: `GET /internal/ops/sales`, rendered on the console's `/revenue`. `disputes-refunds` is
#: `GET /internal/ops/disputes`, which reads our own reversed orders rather than calling Stripe,
#: because `FulfilmentService.RevokeAsync` has already recorded every inbound reversal. Both are
#: in `store_platform/src/Store.Api/Endpoints/OpsEndpoints.cs`.
MISSING_READS: list[dict[str, str]] = [
    {
        "id": "dispute-clock",
        "what": "when a dispute actually arrived, not when the sale happened",
        "needs": "a persisted reversal row (provider, kind, event id, received at) and the "
                 "migration for it; RevokeAsync currently changes two status fields and drops "
                 "the PaymentReversal record",
        "why": "the evidence window on a chargeback is days. /internal/ops/disputes can only "
               "show the ORIGINAL SALE date, so an operator sorting by it is sorting by the "
               "wrong clock and will answer the oldest dispute last",
    },
    {
        "id": "canary-checkout",
        "what": "a real checkout, taken and refunded on a schedule",
        "needs": "an automation under ops/automations/ writing store/ops/canary_checkout.json",
        "why": "the rail reporting `live` proves the keys are live, not that a card clears",
    },
]

# Writes the console cannot do, declared for the same reason as MISSING_READS: a money screen that
# simply has no refund button reads as "refunds are handled elsewhere", and nobody can tell whether
# that is true. Named here, it is a gap with an owner.
MISSING_ACTIONS: list[dict[str, str]] = [
    {
        "id": "issue-refund",
        "what": "refund a buyer from the console",
        "needs": "a refund method on IPaymentProvider (IPaymentProvider.cs:5-35 has none) and the "
                 "Stripe implementation behind it; the console can only SEE reversals Stripe has "
                 "already told us about, via the webhook that calls FulfilmentService.RevokeAsync",
        "why": "an operator who agrees to refund a buyer today has to do it in the Stripe "
               "dashboard, and the revocation only reaches our database when the webhook lands",
    },
]


def money_view(cfg: Any, call: Callable[..., dict]) -> dict:
    """Assemble the screen. `call` is the gateway's own store-API caller, injected so this
    module stays testable without a network and without importing the gateway back."""
    rail = _rail(call)
    shelf = _shelf(call)

    warnings: list[str] = []
    if rail["state"] == "test":
        warnings.append(
            "The money rail is on TEST keys. Every checkout completes and no card is charged.")
    elif rail["state"] == "never-ran":
        warnings.append(
            "The startup gate never recorded a decision, so nothing has checked the money rail. "
            "Treat the mode as unknown, not as live.")
    elif rail["state"] == "unreachable":
        warnings.append(f"Could not reach the money rail: {rail['error']}. "
                        "This is a failed measurement, not a healthy rail.")
    if shelf.get("listed") == 0 and shelf.get("reachable"):
        warnings.append("Nothing on the shelf is listed, so there is nothing to buy.")

    return {
        "rail": rail,
        "shelf": shelf,
        "missing": MISSING_READS,
        "missing_actions": MISSING_ACTIONS,
        "warnings": warnings,
    }


def _rail(call: Callable[..., dict]) -> dict:
    try:
        resp = call("GET", "/healthz/money-rail")
    except Exception as exc:  # noqa: BLE001 — an outage is a state, and it is reported as one
        return {"state": "unreachable", "error": str(exc), "mode": None, "provider": None,
                "environment": None, "decided_at": None}

    body = resp.get("body")
    if resp.get("http_error") or not isinstance(body, dict):
        return {"state": "unreachable", "mode": None, "provider": None, "environment": None,
                "decided_at": None,
                "error": f"HTTP {resp.get('status')} from {resp.get('url')}"}

    decided = body.get("decidedAtUtc")
    mode = body.get("mode")
    if not decided:
        state = "never-ran"
    elif mode == "live":
        state = "live"
    elif mode == "not-applicable":
        state = "not-applicable"
    else:
        state = "test"

    return {
        "state": state,
        "mode": mode,
        "provider": body.get("provider"),
        "environment": body.get("environment"),
        "decided_at": decided,
        "error": None,
        "source": resp.get("url"),
    }


def _shelf(call: Callable[..., dict]) -> dict:
    """How much of the catalogue can actually be bought.

    `registered` counts packs the API knows; `listed` counts the ones on offer. The gap is
    revenue that exists and cannot be taken, which is why it sits on the Money screen and not
    only on the Shelf screen.
    """
    try:
        resp = call("GET", "/catalog/stats")
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": str(exc), "listed": None, "registered": None,
                "unsellable": None}

    body = resp.get("body")
    if resp.get("http_error") or not isinstance(body, dict):
        return {"reachable": False, "listed": None, "registered": None, "unsellable": None,
                "error": f"HTTP {resp.get('status')} from {resp.get('url')}"}

    listed = _int(body.get("listed"))
    registered = _int(body.get("registered"))
    unsellable = None if listed is None or registered is None else max(0, registered - listed)
    return {"reachable": True, "listed": listed, "registered": registered,
            "unsellable": unsellable, "error": None, "source": resp.get("url")}


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
