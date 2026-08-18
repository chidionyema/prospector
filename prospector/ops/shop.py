"""The Shop screens: orders, revenue, and the delivery outbox.

Four reads, one per screen the console needs to answer "did the money arrive, and did the buyer
get the thing they paid for":

  * `orders_view`     — the order list, filtered.
  * `order_view`      — one order, with its entitlements, deliveries, siblings and sales audit.
  * `sales_view`      — revenue over a window, per currency and per pack.
  * `deliveries_view` — the delivery outbox, and what is stuck in it.

Three rules hold everywhere in this module, and each one exists to stop a specific wrong number
reaching a screen.

**Currencies are never summed.** The API answers revenue in per-currency buckets and this module
passes them through untouched. There is no "total" field, because a total across GBP and USD is
not money — it is two numbers added together and labelled with one of their symbols.

**An unreachable API is a state, not a datum.** Every fetch returns `{"reachable": False,
"error": ...}` on an exception or a shape this module does not recognise, exactly as
`money.py::_rail` does. It never returns a zero. A revenue figure of 0 that actually means "the
store API was down" is the defect this rule exists to prevent, and it is invisible on a screen.

**Nothing here computes what the API already computed.** Counts, splits, ages and totals come
from the endpoint. This module only reads them, and warns in plain words about the ones an
operator has to act on.
"""
from __future__ import annotations

from typing import Any, Callable, Optional
from urllib.parse import urlencode

#: Query parameters `GET /internal/ops/orders` accepts, keyed by the argument name the console
#: uses. Both the snake_case and the wire spelling are accepted so a caller does not have to know
#: which side of the fence it is on.
ORDER_FILTERS: dict[str, str] = {
    "q": "q",
    "status": "status",
    "pack_id": "packId",
    "packId": "packId",
    "from": "from",
    "date_from": "from",
    "to": "to",
    "date_to": "to",
    "limit": "limit",
    "offset": "offset",
}

#: The states `GET /internal/ops/deliveries` understands. `abandoned` is separate from `failed`
#: on purpose: the drain stops retrying at `Delivery:MaxAttempts`, so an abandoned row is a buyer
#: who paid, holds an entitlement, and will never be sent their link by any automatic process.
#: Counted as "failed" it reads as something still working.
DELIVERY_STATES = ("unsent", "pending", "failed", "abandoned", "sent", "all")


# --------------------------------------------------------------------------- #
# The four views
# --------------------------------------------------------------------------- #
def orders_view(cfg: Any, call: Callable[..., dict], **filters: Any) -> dict:
    """The order list. `call` is the gateway's own store-API caller, injected so this module
    stays testable without a network and without importing the gateway back."""
    query, ignored = _order_query(filters)
    fetched = _get(call, "/internal/ops/orders", query)
    if not fetched["reachable"]:
        return _unreachable(fetched, {"orders": None, "total": None, "returned": None,
                                      "limit": None, "offset": None},
                            "Could not read the orders: {error}. This is a failed measurement, "
                            "not an empty order book.")

    body = fetched["body"]
    orders = body.get("orders")
    orders = orders if isinstance(orders, list) else []

    warnings: list[str] = []
    if ignored:
        warnings.append("Ignored filters the orders endpoint does not accept: "
                        + ", ".join(sorted(ignored)) + ".")
    warnings.extend(_order_page_warnings(orders))

    return {
        "reachable": True,
        "error": None,
        "as_of_utc": body.get("asOfUtc"),
        "filters": query,
        "total": body.get("total"),
        "limit": body.get("limit"),
        "offset": body.get("offset"),
        "returned": body.get("returned"),
        "orders": orders,
        "warnings": warnings,
        "source": fetched["source"],
    }


def order_view(cfg: Any, call: Callable[..., dict], order_id: str) -> dict:
    """One order, and everything hanging off it."""
    oid = str(order_id or "").strip()
    if not oid:
        raise ValueError("order_view needs an order id")

    fetched = _get(call, f"/internal/ops/orders/{oid}")
    if not fetched["reachable"]:
        return _unreachable(fetched, {"id": oid, "order": None, "entitlements": None,
                                      "deliveries": None, "siblings": None, "sales_audit": None},
                            "Could not read order " + oid + ": {error}. This is a failed "
                            "measurement, not a missing order.")

    body = fetched["body"]
    order = body.get("order") if isinstance(body.get("order"), dict) else None
    entitlements = _list(body.get("entitlements"))
    deliveries = _list(body.get("deliveries"))

    warnings: list[str] = []
    if order is None:
        warnings.append("The store API answered without an order. Treat this as not found, "
                        "not as an order with no details.")
    else:
        warnings.extend(_order_status_warnings([order]))
    if order is not None and not entitlements:
        warnings.append("This order has no entitlement, so the buyer has nothing to download.")
    stuck = [d for d in deliveries if _delivery_state(d) in ("unsent", "pending")]
    failed = [d for d in deliveries if _delivery_state(d) == "failed"]
    abandoned = [d for d in deliveries if _delivery_state(d) == "abandoned"]
    if abandoned:
        warnings.append(f"{len(abandoned)} delivery on this order was abandoned. The drain has "
                        "given up. This buyer will not be sent the pack without a resend.")
    if failed:
        warnings.append(f"{len(failed)} delivery attempt(s) on this order failed. The buyer has "
                        "paid and has not been sent the pack.")
    elif stuck:
        warnings.append(f"{len(stuck)} delivery on this order has not been sent yet.")

    return {
        "reachable": True,
        "error": None,
        "as_of_utc": body.get("asOfUtc"),
        "id": oid,
        "order": order,
        "entitlements": entitlements,
        "deliveries": deliveries,
        "siblings": _list(body.get("siblings")),
        "sales_audit": _list(body.get("salesAudit")),
        "warnings": warnings,
        "source": fetched["source"],
    }


def sales_view(cfg: Any, call: Callable[..., dict], days: int = 30) -> dict:
    """Revenue over a window.

    Every money figure below is per currency, exactly as the API grouped it. Nothing on this
    screen adds two currencies together, and there is deliberately no combined total.
    """
    window = _int(days) or 30
    fetched = _get(call, "/internal/ops/sales", {"days": window})
    if not fetched["reachable"]:
        return _unreachable(fetched, {"days": window, "today": None, "by_currency": None,
                                      "by_day": None, "by_pack": None, "order_statuses": None,
                                      "order_count": None},
                            "Could not read sales: {error}. Revenue is unknown, which is not "
                            "the same as zero.")

    body = fetched["body"]
    today = _list(body.get("today"))
    by_currency = _list(body.get("byCurrency"))
    by_pack = _list(body.get("byPack"))
    statuses = _list(body.get("orderStatuses"))

    warnings: list[str] = []
    currencies = sorted({str(row.get("currency")) for row in by_currency
                         if isinstance(row, dict) and row.get("currency")})
    if len(currencies) > 1:
        warnings.append("Revenue is reported per currency (" + ", ".join(currencies)
                        + ") and is never added up. There is no combined total.")
    if by_currency and not today:
        warnings.append("Nothing has been taken today, though the window has takings.")

    refunded = [r for r in by_pack if isinstance(r, dict) and _int(r.get("refunded"))]
    disputed = [r for r in by_pack if isinstance(r, dict) and _int(r.get("disputed"))]
    if refunded:
        warnings.append(f"{len(refunded)} pack(s) in this window have refunded orders.")
    if disputed:
        warnings.append(f"{len(disputed)} pack(s) in this window have disputed orders. A dispute "
                        "answered late is money lost by default.")
    for row in statuses:
        if not isinstance(row, dict):
            continue
        state = str(row.get("status") or "").lower()
        count = _int(row.get("orders")) or 0
        if count and state in ("failed", "refunded", "disputed", "chargeback"):
            warnings.append(f"{count} order(s) in this window are {state}.")

    return {
        "reachable": True,
        "error": None,
        "as_of_utc": body.get("asOfUtc"),
        "days": body.get("days", window),
        "since_utc": body.get("sinceUtc"),
        "day_boundary": body.get("dayBoundary"),
        "note": body.get("note"),
        "today": today,
        "by_currency": by_currency,
        "by_day": _list(body.get("byDay")),
        "by_pack": by_pack,
        "order_statuses": statuses,
        "order_count": body.get("orderCount"),
        "currencies": currencies,
        "warnings": warnings,
        "source": fetched["source"],
    }


def deliveries_view(cfg: Any, call: Callable[..., dict], state: str = "all",
                    limit: Optional[int] = None) -> dict:
    """The delivery outbox: what has been sent, and what a buyer is still waiting for."""
    want = str(state or "all").strip().lower() or "all"
    if want not in DELIVERY_STATES:
        raise ValueError(f"unknown delivery state {want!r}; expected one of "
                         f"{', '.join(DELIVERY_STATES)}")
    query: dict[str, Any] = {"state": want}
    cap = _int(limit)
    if cap:
        query["limit"] = cap

    fetched = _get(call, "/internal/ops/deliveries", query)
    if not fetched["reachable"]:
        return _unreachable(fetched, {"state": want, "counts": None, "deliveries": None},
                            "Could not read the delivery outbox: {error}. Nothing here says a "
                            "buyer was served; it says we cannot tell.")

    body = fetched["body"]
    counts = body.get("counts") if isinstance(body.get("counts"), dict) else {}
    deliveries = _list(body.get("deliveries"))

    warnings: list[str] = []
    undelivered = _int(counts.get("undelivered"))
    failed = _int(counts.get("failed"))
    pending = _int(counts.get("pending"))
    if undelivered:
        warnings.append(f"{undelivered} paid order(s) have not been delivered.")
    abandoned = _int(counts.get("abandoned"))
    if abandoned:
        warnings.append(f"{abandoned} delivery(ies) were abandoned. The drain has given up on "
                        "these. Nothing will retry them without a resend.")
    if failed:
        warnings.append(f"{failed} delivery(ies) failed. Each one is a buyer who paid and got "
                        "nothing.")
    if pending and not undelivered:
        warnings.append(f"{pending} delivery(ies) are still pending.")

    return {
        "reachable": True,
        "error": None,
        "as_of_utc": body.get("asOfUtc"),
        "state": body.get("state", want),
        "counts": counts,
        "deliveries": deliveries,
        "warnings": warnings,
        "source": fetched["source"],
    }


def disputes_view(cfg: Any, call: Callable[..., dict], days: int = 90) -> dict:
    """Money that came back out: refunds and chargebacks.

    This reads our own reversed orders, not Stripe. The webhook already applied every reversal —
    `FulfilmentService.RevokeAsync` revokes the entitlement and moves the order to Refunded or
    Disputed — so the shop's own rows already know, and calling Stripe here would add a second
    version of the truth.

    The dates are SALE dates. The reversal itself is not persisted anywhere, so there is no
    "disputed at" timestamp to sort by. That is carried through to the operator rather than
    hidden, because a dispute clock the operator cannot see is worse than no clock at all: the
    evidence window is days, and sorting by sale date answers the oldest dispute last.
    """
    window = _int(days) or 90
    fetched = _get(call, "/internal/ops/disputes", {"days": window})
    if not fetched["reachable"]:
        return _unreachable(fetched,
                            {"days": window, "counts": None, "by_currency": None, "orders": None},
                            "Could not read refunds and disputes: {error}. This says we cannot "
                            "tell, not that nothing has been reversed.")

    body = fetched["body"]
    counts = _list(body.get("counts"))
    by_currency = _list(body.get("byCurrency"))
    orders = _list(body.get("orders"))

    warnings: list[str] = []
    for row in counts:
        if not isinstance(row, dict):
            continue
        n = _int(row.get("orders"))
        state = str(row.get("status") or "").lower()
        if n and state == "disputed":
            warnings.append(f"{n} order(s) are disputed. A dispute answered late is lost by "
                            "default.")
        elif n and state in ("refunded", "partiallyrefunded"):
            warnings.append(f"{n} order(s) were {state}.")
    if orders:
        warnings.append("Every date on this screen is the date of the SALE. The reversal is not "
                        "timestamped, so this cannot be sorted by how urgent a dispute is.")

    return {
        "reachable": True,
        "error": None,
        "as_of_utc": body.get("asOfUtc"),
        "days": _int(body.get("days")) or window,
        "date_basis": body.get("dateBasis"),
        "counts": counts,
        "order_count": _int(body.get("orderCount")),
        "by_currency": by_currency,
        "entitlements_revoked": _int(body.get("entitlementsRevoked")),
        "orders": orders,
        "warnings": warnings,
        "source": fetched["source"],
    }


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def _get(call: Callable[..., dict], path: str, query: Optional[dict] = None) -> dict:
    """One internal GET. An outage comes back as a state, never as empty data.

    This is `money.py::_rail`'s contract, kept identical on purpose: on an exception or a body
    that is not a dict, the answer is `reachable: False` with the error, and no numbers at all.
    """
    url = path
    if query:
        pairs = [(k, str(v)) for k, v in query.items() if v not in (None, "")]
        if pairs:
            url = f"{path}?{urlencode(pairs)}"
    try:
        resp = call("GET", url, internal=True)
    except Exception as exc:  # noqa: BLE001 — an outage is a state, and it is reported as one
        return {"reachable": False, "error": str(exc), "body": None, "source": url}

    if not isinstance(resp, dict):
        return {"reachable": False, "body": None, "source": url,
                "error": f"the store API answered a shape this console does not recognise "
                         f"from {url}"}
    body = resp.get("body")
    if resp.get("http_error") or not isinstance(body, dict):
        return {"reachable": False, "body": None, "source": resp.get("url") or url,
                "error": f"HTTP {resp.get('status')} from {resp.get('url') or url}"}
    return {"reachable": True, "error": None, "body": body,
            "source": resp.get("url") or url}


def _unreachable(fetched: dict, blanks: dict, template: str) -> dict:
    """The shape every view returns when the API could not answer. Every datum is None — never a
    zero — and the warning says the measurement failed."""
    error = fetched["error"]
    out: dict[str, Any] = {"reachable": False, "error": error, "as_of_utc": None}
    out.update(blanks)
    out["warnings"] = [template.format(error=error)]
    out["source"] = fetched.get("source")
    return out


# --------------------------------------------------------------------------- #
# Reading what came back
# --------------------------------------------------------------------------- #
def _order_query(filters: dict) -> tuple[dict, list[str]]:
    query: dict[str, Any] = {}
    ignored: list[str] = []
    for key, value in filters.items():
        if value in (None, ""):
            continue
        wire = ORDER_FILTERS.get(key)
        if wire is None:
            ignored.append(str(key))
            continue
        query[wire] = value
    return query, ignored


def _order_page_warnings(orders: list) -> list[str]:
    warnings = _order_status_warnings(orders)
    undelivered = [o for o in orders if _order_delivery_state(o) in (None, "unsent", "pending")]
    failed = [o for o in orders if _order_delivery_state(o) == "failed"]
    if failed:
        warnings.append(f"{len(failed)} order(s) on this page have a failed delivery.")
    if undelivered:
        warnings.append(f"{len(undelivered)} order(s) on this page have not been delivered.")
    return warnings


def _order_status_warnings(orders: list) -> list[str]:
    flagged: dict[str, int] = {}
    for order in orders:
        if not isinstance(order, dict):
            continue
        state = str(order.get("status") or "").lower()
        if state in ("refunded", "disputed", "chargeback", "failed"):
            flagged[state] = flagged.get(state, 0) + 1
    return [f"{count} order(s) here are {state}." for state, count in sorted(flagged.items())]


def _order_delivery_state(order: Any) -> Optional[str]:
    if not isinstance(order, dict):
        return None
    return _delivery_state(order.get("delivery"))


def _delivery_state(delivery: Any) -> Optional[str]:
    if not isinstance(delivery, dict):
        return None
    state = delivery.get("state")
    return str(state).lower() if state else None


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
