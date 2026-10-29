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


def insert_refund(member_id: int, amount, related_payment_id, status: str) -> Payment:
    payment = Payment(
        member_id=member_id,
        type="REFUND",
        amount=Decimal(amount),
        related_payment_id=related_payment_id,
        status=status,
    )
    db.session.add(payment)
    db.session.commit()
    db.session.refresh(payment)
    return payment


def test_history_annotates_charge_with_refunded_amount(app, client):
    original = charge(client, amount=100).get_json()
    insert_refund(1, "0.10", original["id"], "SUCCESS")
    insert_refund(1, "0.20", original["id"], "SUCCESS")

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    body = response.get_json()
    charge_row = next(row for row in body if row["id"] == original["id"])
    assert charge_row["refundedAmount"] == 0.3
    refund_rows = [row for row in body if row["type"] == "REFUND"]
    assert len(refund_rows) == 2
    assert all("refundedAmount" not in row for row in refund_rows)


def test_history_ignores_pending_and_failed_refunds(app, client):
    original = charge(client, amount=100).get_json()
    insert_refund(1, "10.00", original["id"], "SUCCESS")
    insert_refund(1, "5.00", original["id"], "PENDING")
    insert_refund(1, "5.00", original["id"], "FAILED")

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body) == 4
    charge_row = next(row for row in body if row["id"] == original["id"])
    assert charge_row["refundedAmount"] == 10.0
    refund_statuses = sorted(row["status"] for row in body if row["type"] == "REFUND")
    assert refund_statuses == ["FAILED", "PENDING", "SUCCESS"]


def test_history_charge_without_refunds_has_zero_refunded_amount(client):
    successful = charge(client, amount=100).get_json()
    failed = charge(client, status="FAILED").get_json()

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    refunded_by_id = {row["id"]: row["refundedAmount"] for row in response.get_json()}
    assert refunded_by_id[successful["id"]] == 0.0
    assert refunded_by_id[failed["id"]] == 0.0


def test_history_refund_without_related_payment_does_not_affect_charges(client):
    original = charge(client, amount=100).get_json()
    refund = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 15},
    ).get_json()
    assert refund["relatedPaymentId"] is None

    response = client.get("/api/payments/member/1")

    assert response.status_code == 200
    body = response.get_json()
    charge_row = next(row for row in body if row["id"] == original["id"])
    assert charge_row["refundedAmount"] == 0.0
    refund_row = next(row for row in body if row["id"] == refund["id"])
    assert "refundedAmount" not in refund_row


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


def test_charge_with_status_failed_persists_and_returns_402(client):
    response = charge(client, status="FAILED")

    assert response.status_code == 402
    body = response.get_json()
    assert body["type"] == "CHARGE"
    assert body["status"] == "FAILED"

    history = client.get("/api/payments/member/1")
    assert history.status_code == 200
    assert [payment["status"] for payment in history.get_json()] == ["FAILED"]


def test_charge_with_status_success_returns_201(client):
    response = charge(client, status="SUCCESS")

    assert response.status_code == 201
    assert response.get_json()["status"] == "SUCCESS"


def test_charge_rejects_a_status_outside_success_and_failed(client):
    response = charge(client, status="PENDING")

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]

    history = client.get("/api/payments/member/1")
    assert history.status_code == 200
    assert history.get_json() == []
