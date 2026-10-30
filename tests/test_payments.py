from decimal import Decimal

from app.extensions import db
from app.models import Payment


def charge(client, **overrides):
    payload = {"memberId": 1, "amount": 49.99, **overrides}
    return client.post("/api/payments/charge", json=payload)


def test_health_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_charge_records_a_successful_charge(client):
    response = charge(client, reason="PREMIUM plan renewal")

    assert response.status_code == 201
    body = response.get_json()
    assert body["memberId"] == 1
    assert body["type"] == "CHARGE"
    assert body["status"] == "SUCCESS"
    assert body["reason"] == "PREMIUM plan renewal"
    assert body["amount"] == 49.99


def test_charge_rejects_an_amount_of_zero_or_below(client):
    response = client.post("/api/payments/charge", json={"memberId": 1, "amount": 0})

    assert response.status_code == 400
    assert "amount" in response.get_json()["message"]


def test_charge_rejects_a_missing_member_id(client):
    response = client.post("/api/payments/charge", json={"amount": 10})

    assert response.status_code == 400
    assert "memberId" in response.get_json()["message"]


def test_refund_records_against_a_valid_prior_charge(client):
    original = charge(client).get_json()

    response = client.post(
        "/api/payments/refund",
        json={
            "memberId": 1,
            "amount": 20,
            "reason": "early cancellation",
            "relatedPaymentId": original["id"],
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["memberId"] == 1
    assert body["type"] == "REFUND"
    assert body["status"] == "SUCCESS"
    assert body["relatedPaymentId"] == original["id"]


def test_refund_can_have_no_related_payment(client):
    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 15},
    )

    assert response.status_code == 201
    assert response.get_json()["relatedPaymentId"] is None


def test_refund_rejects_a_related_payment_that_does_not_exist(client):
    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": 999999},
    )

    assert response.status_code == 422


def test_refund_rejects_a_related_payment_for_another_member(client):
    original = charge(client, memberId=1).get_json()

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 2, "amount": 20, "relatedPaymentId": original["id"]},
    )

    assert response.status_code == 422


def test_refund_rejects_a_related_payment_that_is_itself_a_refund(client):
    original = charge(client).get_json()
    refund = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    ).get_json()

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 5, "relatedPaymentId": refund["id"]},
    )

    assert response.status_code == 422


def test_history_is_ordered_most_recent_first(client):
    original = charge(client).get_json()
    refund = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    ).get_json()

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body) == 2
    assert body[0]["id"] == refund["id"]
    assert body[1]["id"] == original["id"]


def test_history_is_empty_for_a_member_with_no_payments(client):
    response = client.get("/api/payments/member/999999")

    assert response.status_code == 200
    assert response.get_json() == []


def test_get_payment_by_id(client):
    original = charge(client).get_json()

    response = client.get(f"/api/payments/{original['id']}")

    assert response.status_code == 200
    assert response.get_json()["id"] == original["id"]


def test_get_payment_returns_404_for_unknown_id(client):
    response = client.get("/api/payments/999999")

    assert response.status_code == 404


def test_unknown_route_returns_404(client):
    response = client.get("/api/not-a-real-route")

    assert response.status_code == 404
    assert "message" in response.get_json()


def test_charge_with_failed_status_returns_402_and_persists(client):
    response = charge(client, status="FAILED")

    assert response.status_code == 402
    body = response.get_json()
    assert body["status"] == "FAILED"
    assert isinstance(body["id"], int)

    stored = client.get(f"/api/payments/{body['id']}")

    assert stored.status_code == 200
    assert stored.get_json()["status"] == "FAILED"


def test_charge_defaults_status_to_success(client):
    response = charge(client)

    assert response.status_code == 201
    assert response.get_json()["status"] == "SUCCESS"


def test_charge_rejects_an_unsupported_status(client):
    response = charge(client, status="PENDING")

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]

    history = client.get("/api/payments/member/1")

    assert history.status_code == 200
    assert history.get_json() == []


def test_history_annotates_a_charge_with_refunded_amount_in_cents(client):
    original = charge(client).get_json()
    refund = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    ).get_json()

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.get_json()}
    assert isinstance(rows[original["id"]]["refundedAmount"], int)
    assert rows[original["id"]]["refundedAmount"] == 2000
    assert rows[refund["id"]]["refundedAmount"] == 0


def test_history_sums_multiple_successful_refunds(client):
    original = charge(client).get_json()
    for amount in (20, 5.5):
        client.post(
            "/api/payments/refund",
            json={"memberId": 1, "amount": amount, "relatedPaymentId": original["id"]},
        )

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    charge_row = next(row for row in response.get_json() if row["id"] == original["id"])
    assert charge_row["refundedAmount"] == 2550


def test_history_gives_a_failed_charge_zero_refunded_amount(client):
    failed = charge(client, status="FAILED").get_json()
    refund = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": failed["id"]},
    ).get_json()

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.get_json()}
    assert rows[failed["id"]]["status"] == "FAILED"
    assert rows[failed["id"]]["refundedAmount"] == 0
    assert rows[refund["id"]]["refundedAmount"] == 0


def test_history_lists_a_pending_refund_but_counts_zero(app, client):
    original = charge(client).get_json()
    client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    )

    pending = Payment(
        member_id=1,
        amount=Decimal("7.00"),
        type="REFUND",
        status="PENDING",
        related_payment_id=original["id"],
    )
    db.session.add(pending)
    db.session.commit()

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.get_json()}
    assert rows[pending.id]["status"] == "PENDING"
    assert rows[pending.id]["refundedAmount"] == 0
    assert rows[original["id"]]["refundedAmount"] == 2000


def test_history_gives_non_charge_rows_zero_refunded_amount(client):
    original = charge(client).get_json()
    client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    )

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    rows = response.get_json()
    assert any(row["type"] == "REFUND" for row in rows)
    for row in rows:
        assert isinstance(row["refundedAmount"], int)
        if row["type"] != "CHARGE":
            assert row["refundedAmount"] == 0
