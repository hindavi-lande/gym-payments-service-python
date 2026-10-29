from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Payment
from app.models.payment import _utcnow
from app.services import payment_service

FROZEN_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def record_payment(app, *, member_id, type, amount, status="SUCCESS", created_at=None):
    timestamp = created_at or _utcnow()
    payment = Payment(
        member_id=member_id,
        type=type,
        amount=Decimal(str(amount)),
        status=status,
        created_at=timestamp,
        updated_at=timestamp,
    )

    db.session.add(payment)
    db.session.commit()

    return payment


def freeze_now(monkeypatch):
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return FROZEN_NOW.replace(tzinfo=None)
            return FROZEN_NOW.astimezone(tz)

    monkeypatch.setattr(payment_service, "datetime", _FrozenDatetime)


def test_spend_nets_charges_and_refunds(client):
    charge = client.post("/api/payments/charge", json={"memberId": 1, "amount": 100})
    assert charge.status_code == 201
    refund = client.post("/api/payments/refund", json={"memberId": 1, "amount": 30})
    assert refund.status_code == 201

    response = client.get("/api/payments/member/1/spend")

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"memberId", "spend"}
    assert body["memberId"] == 1
    assert body["spend"] == 70.0


def test_spend_ignores_non_success_statuses(app, client):
    record_payment(app, member_id=2, type="CHARGE", amount=100, status="FAILED")
    record_payment(app, member_id=2, type="CHARGE", amount=50, status="PENDING")
    record_payment(app, member_id=2, type="REFUND", amount=25, status="FAILED")
    record_payment(app, member_id=2, type="CHARGE", amount=10)

    response = client.get("/api/payments/member/2/spend")

    assert response.status_code == 200
    assert response.get_json()["spend"] == 10.0


def test_spend_window_is_rolling_365_days_inclusive(app, client, monkeypatch):
    freeze_now(monkeypatch)

    record_payment(
        app,
        member_id=7,
        type="CHARGE",
        amount=20,
        created_at=FROZEN_NOW - timedelta(days=365),
    )
    record_payment(
        app,
        member_id=7,
        type="CHARGE",
        amount=5,
        created_at=FROZEN_NOW - timedelta(days=366),
    )

    response = client.get("/api/payments/member/7/spend")

    assert response.status_code == 200
    assert response.get_json()["spend"] == 20.0


def test_spend_can_be_negative(app, client):
    record_payment(app, member_id=3, type="CHARGE", amount=10)
    record_payment(app, member_id=3, type="REFUND", amount=35.5)

    response = client.get("/api/payments/member/3/spend")

    assert response.status_code == 200
    assert response.get_json()["spend"] == -25.5


def test_spend_rounds_to_cents(app, client):
    record_payment(app, member_id=4, type="CHARGE", amount=10.015)

    response = client.get("/api/payments/member/4/spend")

    assert response.status_code == 200
    assert response.get_json()["spend"] == 10.02


def test_spend_is_zero_for_member_without_payments(client):
    response = client.get("/api/payments/member/999999/spend")

    assert response.status_code == 200
    body = response.get_json()
    assert body["memberId"] == 999999
    assert body["spend"] == 0.0
