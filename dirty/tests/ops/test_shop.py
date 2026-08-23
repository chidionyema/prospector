"""The Shop reads report absence as absence, and never add two currencies together.

No network. The store-API caller is injected into every view, so these run against fixtures held
in this file. The cases pinned here are the ones that put a wrong number on a screen: an
unreachable API rendered as zero revenue, per-currency buckets quietly summed into one total, and
an undelivered order that nothing warns about.
"""
from __future__ import annotations

import pytest

from prospector.ops import console_api as api
from prospector.ops.shop import (
    DELIVERY_STATES,
    deliveries_view,
    order_view,
    orders_view,
    sales_view,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _caller(routes: dict):
    """A stand-in for the gateway's store-API caller. Routes are matched on the path WITHOUT its
    query string, so a test does not have to spell the encoding. A route mapped to an Exception
    raises it."""

    def call(method: str, path: str, **_kw):
        resp = routes[path.split("?", 1)[0]]
        if isinstance(resp, Exception):
            raise resp
        return resp

    return call


def _ok(url: str, body: dict) -> dict:
    return {"status": 200, "url": url, "body": body, "http_error": None}


ORDER = {
    "id": "ord_1", "createdAtUtc": "2026-08-17T09:00:00Z", "buyerEmail": "b@example.com",
    "packId": "pk_1", "packTitle": "A pack", "amountMinorUnits": 4900, "currency": "GBP",
    "country": "GB", "status": "paid", "paymentProvider": "stripe",
    "providerTransactionId": "pi_1", "entitlementCount": 1,
    "entitlement": {"id": "ent_1", "status": "active", "downloadCount": 0,
                    "lastDownloadedAtUtc": None, "expiresAtUtc": None},
    "delivery": {"id": "dlv_1", "sentAtUtc": "2026-08-17T09:01:00Z", "attempts": 1,
                 "lastError": None, "state": "sent"},
}

SALES = {
    "asOfUtc": "2026-08-18T10:00:00Z", "days": 30, "sinceUtc": "2026-07-19T00:00:00Z",
    "dayBoundary": "UTC", "note": "gross of fees",
    "today": [{"currency": "GBP", "grossMinorUnits": 4900, "transactions": 1}],
    "byCurrency": [{"currency": "GBP", "grossMinorUnits": 24500, "transactions": 5},
                   {"currency": "USD", "grossMinorUnits": 12000, "transactions": 2}],
    "byDay": [{"date": "2026-08-18", "currency": "GBP", "grossMinorUnits": 4900,
               "transactions": 1}],
    "byPack": [{"packId": "pk_1", "packTitle": "A pack", "currency": "GBP", "units": 5,
                "splitMinorUnits": 24500, "refunded": 0, "disputed": 0}],
    "orderStatuses": [{"status": "paid", "orders": 7}],
    "orderCount": 7,
}


# --------------------------------------------------------------------------- #
# An unreachable API is a state, never a zero
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("view, path", [
    (lambda call: orders_view(None, call), "/internal/ops/orders"),
    (lambda call: sales_view(None, call, days=30), "/internal/ops/sales"),
    (lambda call: deliveries_view(None, call, "all", None), "/internal/ops/deliveries"),
    (lambda call: order_view(None, call, "ord_1"), "/internal/ops/orders/ord_1"),
])
def test_an_unreachable_api_is_a_state_not_a_zero(view, path):
    out = view(_caller({path: ConnectionError("connection refused")}))
    assert out["reachable"] is False
    assert "connection refused" in out["error"]
    assert any("failed measurement" in w or "not the same as zero" in w or "cannot tell" in w
               for w in out["warnings"]), out["warnings"]
    # Nothing may come back as a number. A zero here reads on screen as "no money today".
    for key, value in out.items():
        if key in ("reachable", "error", "warnings", "source", "state", "days", "id"):
            continue
        assert value is None, f"{key} came back as {value!r} from an API that never answered"


def test_an_http_error_does_not_become_zero_revenue():
    out = sales_view(None, _caller({
        "/internal/ops/sales": {"status": 503, "url": "/internal/ops/sales", "body": None,
                                "http_error": "Service Unavailable"},
    }), days=30)
    assert out["reachable"] is False
    assert "503" in out["error"]
    assert out["by_currency"] is None
    assert out["order_count"] is None


# --------------------------------------------------------------------------- #
# Currencies are never summed
# --------------------------------------------------------------------------- #
def test_per_currency_buckets_survive_unchanged_and_are_never_summed():
    out = sales_view(None, _caller({"/internal/ops/sales": _ok("/internal/ops/sales", SALES)}),
                     days=30)
    assert out["by_currency"] == SALES["byCurrency"]
    assert out["today"] == SALES["today"]
    assert out["by_day"] == SALES["byDay"]
    assert out["by_pack"] == SALES["byPack"]
    assert out["currencies"] == ["GBP", "USD"]

    combined = 24500 + 12000
    for value in out.values():
        assert value != combined, "two currencies were added together"
    assert not any("total" in key for key in out), \
        "a combined total across currencies must not exist"
    assert any("per currency" in w for w in out["warnings"])


def test_sales_pass_through_what_the_api_already_computed():
    out = sales_view(None, _caller({"/internal/ops/sales": _ok("/internal/ops/sales", SALES)}),
                     days=30)
    assert out["order_count"] == 7
    assert out["since_utc"] == SALES["sinceUtc"]
    assert out["day_boundary"] == "UTC"
    assert out["note"] == "gross of fees"
    assert out["as_of_utc"] == "2026-08-18T10:00:00Z"


def test_refunds_and_disputes_in_the_window_are_warned_about():
    body = dict(SALES)
    body["byPack"] = [{"packId": "pk_1", "packTitle": "A pack", "currency": "GBP", "units": 5,
                       "splitMinorUnits": 24500, "refunded": 1, "disputed": 2}]
    body["orderStatuses"] = [{"status": "paid", "orders": 5}, {"status": "disputed", "orders": 2}]
    out = sales_view(None, _caller({"/internal/ops/sales": _ok("/internal/ops/sales", body)}),
                     days=30)
    assert any("refunded orders" in w for w in out["warnings"])
    assert any("disputed orders" in w for w in out["warnings"])
    assert any("2 order(s) in this window are disputed" in w for w in out["warnings"])


# --------------------------------------------------------------------------- #
# Deliveries
# --------------------------------------------------------------------------- #
def test_the_undelivered_warning_fires():
    out = deliveries_view(None, _caller({"/internal/ops/deliveries": _ok(
        "/internal/ops/deliveries", {
            "asOfUtc": "2026-08-18T10:00:00Z", "state": "all",
            "counts": {"sent": 40, "pending": 2, "failed": 3, "undelivered": 5},
            "deliveries": [{"id": "dlv_9", "entitlementId": "ent_9", "packId": "pk_1",
                            "packTitle": "A pack", "buyerEmail": "b@example.com",
                            "createdAtUtc": "2026-08-18T09:00:00Z", "sentAtUtc": None,
                            "ageMinutes": 60, "attempts": 3, "lastError": "smtp timeout",
                            "state": "failed"}],
        })}), "all", None)
    assert out["reachable"] is True
    assert any("5 paid order(s) have not been delivered" in w for w in out["warnings"])
    assert any("3 delivery(ies) failed" in w for w in out["warnings"])
    # The counts are the API's own; nothing is recomputed from the page.
    assert out["counts"] == {"sent": 40, "pending": 2, "failed": 3, "undelivered": 5}


def test_a_clean_outbox_warns_about_nothing():
    out = deliveries_view(None, _caller({"/internal/ops/deliveries": _ok(
        "/internal/ops/deliveries", {"asOfUtc": "x", "state": "all",
                                     "counts": {"sent": 40, "pending": 0, "failed": 0,
                                                "undelivered": 0},
                                     "deliveries": []})}), "all", None)
    assert out["warnings"] == []


def test_an_unknown_delivery_state_is_refused_rather_than_guessed():
    with pytest.raises(ValueError) as exc:
        deliveries_view(None, _caller({}), "nonsense", None)
    assert "nonsense" in str(exc.value)
    assert all(s in str(exc.value) for s in DELIVERY_STATES)


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #
def test_orders_pass_the_page_through_and_flag_undelivered_ones():
    undelivered = dict(ORDER, id="ord_2", delivery=None)
    out = orders_view(None, _caller({"/internal/ops/orders": _ok("/internal/ops/orders", {
        "asOfUtc": "2026-08-18T10:00:00Z", "total": 2, "limit": 50, "offset": 0, "returned": 2,
        "orders": [ORDER, undelivered]})}), status="paid", limit=50)
    assert out["reachable"] is True
    assert out["orders"] == [ORDER, undelivered]
    assert out["total"] == 2
    assert out["filters"] == {"status": "paid", "limit": 50}
    assert any("1 order(s) on this page have not been delivered" in w for w in out["warnings"])


def test_a_filter_the_endpoint_does_not_accept_is_dropped_and_named():
    out = orders_view(None, _caller({"/internal/ops/orders": _ok("/internal/ops/orders", {
        "asOfUtc": "x", "total": 0, "limit": 50, "offset": 0, "returned": 0, "orders": []})}),
        nonsense="x")
    assert out["filters"] == {}
    assert any("nonsense" in w for w in out["warnings"])


def test_one_order_carries_its_entitlements_deliveries_siblings_and_audit():
    out = order_view(None, _caller({"/internal/ops/orders/ord_1": _ok(
        "/internal/ops/orders/ord_1", {
            "asOfUtc": "2026-08-18T10:00:00Z", "order": ORDER,
            "entitlements": [ORDER["entitlement"]], "deliveries": [ORDER["delivery"]],
            "siblings": [{"id": "ord_9"}], "salesAudit": [{"event": "paid"}]})}), "ord_1")
    assert out["order"]["id"] == "ord_1"
    assert out["entitlements"] and out["deliveries"]
    assert out["siblings"] == [{"id": "ord_9"}]
    assert out["sales_audit"] == [{"event": "paid"}]
    assert out["warnings"] == []


def test_a_failed_delivery_on_one_order_says_the_buyer_paid_and_got_nothing():
    failed = dict(ORDER["delivery"], state="failed", sentAtUtc=None, lastError="smtp timeout")
    out = order_view(None, _caller({"/internal/ops/orders/ord_1": _ok(
        "/internal/ops/orders/ord_1", {"asOfUtc": "x", "order": ORDER,
                                       "entitlements": [ORDER["entitlement"]],
                                       "deliveries": [failed], "siblings": [],
                                       "salesAudit": []})}), "ord_1")
    assert any("has paid and has not been sent" in w for w in out["warnings"])


def test_an_order_with_no_entitlement_is_a_buyer_with_nothing_to_download():
    out = order_view(None, _caller({"/internal/ops/orders/ord_1": _ok(
        "/internal/ops/orders/ord_1", {"asOfUtc": "x", "order": dict(ORDER, entitlement=None),
                                       "entitlements": [], "deliveries": [], "siblings": [],
                                       "salesAudit": []})}), "ord_1")
    assert any("nothing to download" in w for w in out["warnings"])


def test_an_order_id_is_required():
    with pytest.raises(ValueError):
        order_view(None, _caller({}), "  ")


# --------------------------------------------------------------------------- #
# The gateway wiring
# --------------------------------------------------------------------------- #
def test_the_four_views_are_registered_and_listed():
    doc, code = api.dispatch(["views"])
    assert code == 0
    for name in ("orders", "order", "sales", "deliveries"):
        assert name in api.READS
        assert name in doc["data"]


def test_the_four_reads_dispatch_through_the_gateway(monkeypatch):
    """Each READ must reach its view module through the gateway's own store caller, with the
    argument convention the console uses."""
    seen: list[str] = []

    def fake_call(method: str, path: str, **_kw):
        seen.append(path)
        return {"status": 200, "url": path, "body": {"asOfUtc": "x"}, "http_error": None}

    monkeypatch.setattr(api, "_store_call", fake_call)

    for argv, expect in [
        (["read", "orders", "--arg", "status=paid"], "/internal/ops/orders?status=paid"),
        (["read", "order", "--arg", "order_id=ord_1"], "/internal/ops/orders/ord_1"),
        (["read", "sales", "--arg", "days=7"], "/internal/ops/sales?days=7"),
        (["read", "deliveries", "--arg", "state=failed", "--arg", "limit=5"],
         "/internal/ops/deliveries?state=failed&limit=5"),
    ]:
        seen.clear()
        doc, code = api.dispatch(argv)
        assert code == 0, doc
        assert seen == [expect], (argv, seen)
        assert doc["data"]["reachable"] is True


def test_read_order_without_an_id_is_a_bad_request_not_a_crash():
    doc, code = api.dispatch(["read", "order"])
    assert code == 1
    assert "order_id" in doc["error"]


def test_the_internal_key_header_is_what_these_routes_are_gated_on():
    """The four routes are gated by `X-Internal-Key`. The gateway's caller sets it only when
    `internal=True`, so every fetch in shop.py must pass that flag."""
    passed: list[bool] = []

    def call(method: str, path: str, **kw):
        passed.append(bool(kw.get("internal")))
        return {"status": 200, "url": path, "body": {"asOfUtc": "x"}, "http_error": None}

    orders_view(None, call)
    order_view(None, call, "ord_1")
    sales_view(None, call, days=1)
    deliveries_view(None, call, "all", None)
    assert passed == [True, True, True, True]
