from datetime import UTC, datetime, timedelta
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


def _add_payment(member_id, amount, payment_type, created_at, status="SUCCESS"):
    payment = Payment(
        member_id=member_id,
        amount=Decimal(amount),
        type=payment_type,
        status=status,
        created_at=created_at,
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def _naive_utc(value):
    return value.astimezone(UTC).replace(tzinfo=None)


def test_spend_returns_bare_integer_cents(client):
    original = charge(client).get_json()

    response = client.get("/api/payments/member/1/spend")

    assert response.status_code == 200
    assert response.get_json() == 4999

    client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    )

    response = client.get("/api/payments/member/1/spend")

    assert response.status_code == 200
    assert response.get_json() == 2999


def test_spend_ignores_non_success_payments(app, client):
    created_at = _naive_utc(datetime.now(UTC))
    _add_payment(1, "10.00", "CHARGE", created_at, status="SUCCESS")
    _add_payment(1, "5.00", "CHARGE", created_at, status="PENDING")
    _add_payment(1, "7.00", "CHARGE", created_at, status="FAILED")

    response = client.get("/api/payments/member/1/spend")

    assert response.status_code == 200
    assert response.get_json() == 1000


def test_spend_window_start_is_inclusive(app):
    now = datetime(2024, 5, 15, 12, 0, tzinfo=UTC)
    window_start = _naive_utc(payment_service._twelve_months_before(now))

    assert window_start == datetime(2023, 5, 15, 12, 0)
    _add_payment(1, "12.34", "CHARGE", window_start)
    _add_payment(2, "5.00", "CHARGE", window_start - timedelta(seconds=1))

    assert payment_service.get_member_spend(1, now=now) == 1234
    assert payment_service.get_member_spend(2, now=now) == 0


def test_spend_window_clamps_leap_day(app):
    now = datetime(2024, 2, 29, 10, 0, tzinfo=UTC)
    window_start = payment_service._twelve_months_before(now)

    assert window_start == datetime(2023, 2, 28, 10, 0, tzinfo=UTC)
    _add_payment(1, "20.00", "CHARGE", _naive_utc(window_start))

    assert payment_service.get_member_spend(1, now=now) == 2000


def test_spend_counts_refund_by_its_own_created_at(app):
    now = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
    refund_at = payment_service._twelve_months_before(now) - timedelta(seconds=1)

    _add_payment(1, "20.00", "CHARGE", _naive_utc(datetime(2023, 7, 1, 0, 0, tzinfo=UTC)))
    _add_payment(1, "5.00", "REFUND", _naive_utc(refund_at))

    assert payment_service.get_member_spend(1, now=now) == 2000


def test_spend_can_be_negative(client):
    response = client.post("/api/payments/refund", json={"memberId": 3, "amount": 15})

    assert response.status_code == 201

    response = client.get("/api/payments/member/3/spend")

    assert response.status_code == 200
    assert response.get_json() == -1500

    response = client.get("/api/payments/member/999999/spend")

    assert response.status_code == 200
    assert response.get_json() == 0


def test_spend_sums_whole_cents_without_float_error(client):
    charge(client, amount=0.10)
    charge(client, amount=0.20)

    response = client.get("/api/payments/member/1/spend")

    assert response.status_code == 200
    assert response.get_json() == 30
