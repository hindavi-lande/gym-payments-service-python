from datetime import UTC, datetime
from decimal import Decimal

from app.extensions import db
from app.models import Payment
from app.services import payment_service


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


def _create_payment(
    member_id=1,
    payment_type="CHARGE",
    amount="49.99",
    status="SUCCESS",
    created_at=None,
    related_payment_id=None,
):
    moment = created_at or datetime.now(UTC)
    payment = Payment(
        member_id=member_id,
        type=payment_type,
        amount=Decimal(str(amount)),
        status=status,
        related_payment_id=related_payment_id,
        created_at=moment,
        updated_at=moment,
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def test_spend_is_zero_for_a_member_with_no_payments(client):
    response = client.get("/api/payments/spend/1")

    assert response.status_code == 200
    assert response.get_json() == {"memberId": 1, "spend": 0.0}


def test_spend_ignores_failed_and_pending_payments(client):
    _create_payment(member_id=1, amount="10.00", status="SUCCESS")
    _create_payment(member_id=1, amount="100.00", status="FAILED")
    _create_payment(member_id=1, amount="100.00", status="PENDING")

    body = client.get("/api/payments/spend/1").get_json()

    assert body["spend"] == 10.0


def test_spend_sums_in_whole_cents(client):
    _create_payment(member_id=1, amount="0.10")
    _create_payment(member_id=1, amount="0.20")

    body = client.get("/api/payments/spend/1").get_json()

    assert body["spend"] == 0.30
    assert repr(body["spend"]) == "0.3"


def test_spend_allows_negative_totals(client):
    original = _create_payment(member_id=1, amount="200.00")
    _create_payment(
        member_id=1,
        payment_type="REFUND",
        amount="250.00",
        related_payment_id=original.id,
    )

    body = client.get("/api/payments/spend/1").get_json()

    assert body["spend"] == -50.0


def test_spend_window_start_is_inclusive(client, monkeypatch):
    monkeypatch.setattr(
        payment_service,
        "_now",
        lambda: datetime(2024, 5, 15, 10, 0, tzinfo=UTC),
    )
    _create_payment(
        member_id=1,
        amount="10.00",
        created_at=datetime(2023, 5, 15, 10, 0, tzinfo=UTC),
    )
    _create_payment(
        member_id=1,
        amount="100.00",
        created_at=datetime(2023, 5, 15, 9, 59, 59, tzinfo=UTC),
    )

    body = client.get("/api/payments/spend/1").get_json()

    assert body["spend"] == 10.0


def test_spend_window_clamps_february_29_to_28(client, monkeypatch):
    monkeypatch.setattr(
        payment_service,
        "_now",
        lambda: datetime(2024, 2, 29, 12, 0, tzinfo=UTC),
    )
    _create_payment(
        member_id=1,
        amount="10.00",
        created_at=datetime(2023, 2, 28, 12, 0, tzinfo=UTC),
    )
    _create_payment(
        member_id=1,
        amount="100.00",
        created_at=datetime(2023, 2, 28, 11, 59, 59, tzinfo=UTC),
    )

    body = client.get("/api/payments/spend/1").get_json()

    assert body["spend"] == 10.0


def test_spend_windows_refunds_by_their_own_created_at(client, monkeypatch):
    monkeypatch.setattr(
        payment_service,
        "_now",
        lambda: datetime(2024, 5, 15, 10, 0, tzinfo=UTC),
    )
    old_charge = _create_payment(
        member_id=1,
        amount="300.00",
        created_at=datetime(2023, 1, 1, tzinfo=UTC),
    )
    _create_payment(
        member_id=1,
        payment_type="REFUND",
        amount="50.00",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        related_payment_id=old_charge.id,
    )
    new_charge = _create_payment(
        member_id=2,
        amount="300.00",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    _create_payment(
        member_id=2,
        payment_type="REFUND",
        amount="50.00",
        created_at=datetime(2023, 1, 1, tzinfo=UTC),
        related_payment_id=new_charge.id,
    )

    refund_inside_window = client.get("/api/payments/spend/1").get_json()
    refund_outside_window = client.get("/api/payments/spend/2").get_json()

    assert refund_inside_window == {"memberId": 1, "spend": -50.0}
    assert refund_outside_window == {"memberId": 2, "spend": 300.0}
