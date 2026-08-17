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
MISSING_READS: list[dict[str, str]] = [
    {
        "id": "revenue-today",
        "what": "money taken today, and the orders behind it",
        "needs": "GET /internal/ops/sales-audit on Store.Api",
        "why": "no route serves orders; the console will not compute revenue from local files, "
               "which is how a dashboard invents a number the database disagrees with",
    },
    {
        "id": "disputes-refunds",
        "what": "open disputes and refunds (PAY-2)",
        "needs": "GET /internal/ops/disputes on Store.Api, backed by the Stripe dispute list",
        "why": "a dispute answered late is money lost by default, and nothing here can see one",
    },
    {
        "id": "canary-checkout",
        "what": "a real checkout, taken and refunded on a schedule",
        "needs": "an automation under ops/automations/ writing store/ops/canary_checkout.json",
        "why": "the rail reporting `live` proves the keys are live, not that a card clears",
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
    else:
        # Anything else is treated as test, which the console shows as a fault. There used to be
        # a "not-applicable" branch for a non-Stripe provider; the API can never send that mode,
        # because the startup gate refuses to boot on a provider it does not recognise.
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
