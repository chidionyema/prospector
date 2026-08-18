"""The one write on the shop's operator surface: put a delivery back in front of the drain.

Separate from `test_console_api.py` because these tests exist for a specific reason. Resending a
link that has ALREADY been delivered is not a free retry. `PendingDeliveries.EntitlementId` is
UNIQUE (`store_platform/src/Store.Catalog/Persistence/StoreDbContext.cs:61`), so there is exactly
one outbox row per entitlement and a resend must reset it. Resetting it clears `SentAt`, which is
the only row-level proof that a link was ever emailed.
"""

import pytest

from prospector.ops import console_api as api


def test_resend_preview_warns_when_the_link_has_already_been_sent(monkeypatch):
    """A resend on a delivered link emails the buyer twice AND clears the row's SentAt. The
    preview has to say both, or an operator clicking "resend" to be helpful destroys the record
    they would need an hour later."""
    def fake_call(method, path, *, body=None, internal=False, timeout=20.0):
        assert method == "GET", "a preview must not write"
        return {"status": 200, "url": path, "body": {"deliveries": [
            {"id": 7, "orderId": 3, "buyerEmail": "b@example.com", "packId": "pack-alpha",
             "state": "sent", "attempts": 1, "sentAtUtc": "2026-08-18T09:00:00Z"},
        ]}}

    monkeypatch.setattr(api, "_store_call", fake_call)
    preview = api._act_delivery_resend(api._cfg(None), {"id": "7"}, True)

    assert preview["will"] == "requeued", "there is no second row; the unique index forbids it"
    assert "ALREADY SENT" in preview["effect"]
    assert "second email" in preview["effect"]
    assert preview["sends_email_directly"] is False, "DeliveryDrain stays the only sender"


def test_resend_preview_does_not_claim_an_unseen_id_is_missing(monkeypatch):
    """The preview reads the most recent 200 rows. An older id is absent from that window, which
    is a fact about the window and not about the id. Saying "no such delivery" here would be a
    claim the read cannot support."""
    def fake_call(method, path, *, body=None, internal=False, timeout=20.0):
        return {"status": 200, "url": path, "body": {"deliveries": []}}

    monkeypatch.setattr(api, "_store_call", fake_call)
    preview = api._act_delivery_resend(api._cfg(None), {"id": "9999"}, True)

    assert preview["found"] is False
    assert "not proof the id is wrong" in preview["found_note"]


def test_resend_receipt_keeps_the_send_time_the_row_is_losing(monkeypatch, tmp_path):
    """The API clears SentAt to requeue and hands the old value back as previousSentAt. This
    receipt is where that timestamp lives from then on."""
    monkeypatch.setattr(api, "_store_ops_dir", lambda cfg: tmp_path)

    def fake_call(method, path, *, body=None, internal=False, timeout=20.0):
        return {"status": 200, "url": path, "body": {
            "action": "requeued", "deliveryId": 7, "originalDeliveryId": 7,
            "buyerEmail": "b@example.com", "packId": "pack-alpha",
            "previousSentAt": "2026-08-18T09:00:00Z"}}

    monkeypatch.setattr(api, "_store_call", fake_call)
    receipt = api._act_delivery_resend(api._cfg(None), {"id": "7", "actor": "ops"}, False)

    assert receipt["applied"] is True
    assert receipt["previous_sent_at"] == "2026-08-18T09:00:00Z"


def test_resend_refuses_an_id_that_is_not_a_number():
    """The route is /internal/ops/deliveries/{id:long}/resend. A non-numeric id would 404 as a
    missing route, which reads as "no such delivery" rather than "you passed an email address"."""
    with pytest.raises(ValueError, match="numeric"):
        api._act_delivery_resend(api._cfg(None), {"id": "b@example.com"}, True)


def test_resend_refuses_an_empty_id():
    with pytest.raises(ValueError, match="delivery id"):
        api._act_delivery_resend(api._cfg(None), {}, True)
