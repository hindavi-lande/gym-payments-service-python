import pytest


def charge(client, **overrides):
    payload = {"memberId": 1, "amount": 49.99, **overrides}
    return client.post("/api/payments/charge", json=payload)


def pending_refund(client) -> dict:
    original = charge(client).get_json()
    response = client.post(
        "/api/payments/refund",
        json={
            "memberId": 1,
            "amount": 20,
            "relatedPaymentId": original["id"],
            "status": "PENDING",
        },
    )

    assert response.status_code == 201
    return response.get_json()


def test_settle_marks_a_pending_refund_successful(client) -> None:
    payment = pending_refund(client)

    response = client.post(
        f"/api/payments/{payment['id']}/settle",
        json={"status": "SUCCESS"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "SUCCESS"

    stored = client.get(f"/api/payments/{payment['id']}")

    assert stored.status_code == 200
    assert stored.get_json()["status"] == "SUCCESS"


def test_settle_marks_a_pending_refund_failed(client) -> None:
    payment = pending_refund(client)

    response = client.post(
        f"/api/payments/{payment['id']}/settle",
        json={"status": "FAILED"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "FAILED"

    stored = client.get(f"/api/payments/{payment['id']}")

    assert stored.status_code == 200
    assert stored.get_json()["status"] == "FAILED"


def test_settle_rejects_a_refund_that_is_not_pending(client) -> None:
    original = charge(client).get_json()
    refund = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    ).get_json()

    assert refund["status"] == "SUCCESS"

    response = client.post(
        f"/api/payments/{refund['id']}/settle",
        json={"status": "FAILED"},
    )

    assert response.status_code == 409
    assert "message" in response.get_json()

    stored = client.get(f"/api/payments/{refund['id']}")

    assert stored.status_code == 200
    assert stored.get_json()["status"] == "SUCCESS"


def test_settle_rejects_a_charge(client) -> None:
    original = charge(client).get_json()

    response = client.post(
        f"/api/payments/{original['id']}/settle",
        json={"status": "SUCCESS"},
    )

    assert response.status_code == 409
    assert "message" in response.get_json()

    stored = client.get(f"/api/payments/{original['id']}")

    assert stored.status_code == 200
    assert stored.get_json()["type"] == "CHARGE"
    assert stored.get_json()["status"] == "SUCCESS"


def test_settle_returns_404_for_an_unknown_payment(client) -> None:
    response = client.post(
        "/api/payments/999999/settle",
        json={"status": "SUCCESS"},
    )

    assert response.status_code == 404
    assert "message" in response.get_json()


@pytest.mark.parametrize(
    "body",
    [{}, {"status": "PENDING"}, {"status": "REFUNDED"}, {"status": 1}],
    ids=["missing", "not-settleable", "unknown", "not-a-string"],
)
def test_settle_rejects_an_unsupported_status(client, body) -> None:
    payment = pending_refund(client)

    response = client.post(
        f"/api/payments/{payment['id']}/settle",
        json=body,
    )

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]

    stored = client.get(f"/api/payments/{payment['id']}")

    assert stored.status_code == 200
    assert stored.get_json()["status"] == "PENDING"
