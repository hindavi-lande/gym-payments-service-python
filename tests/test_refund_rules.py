def charge(client, **overrides):
    payload = {"memberId": 1, "amount": 49.99, **overrides}
    return client.post("/api/payments/charge", json=payload)


def refund(client, **overrides):
    payload = {"memberId": 1, "amount": 20, **overrides}
    return client.post("/api/payments/refund", json=payload)


def test_refund_defaults_status_to_success(client) -> None:
    response = refund(client)

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "SUCCESS"

    stored = client.get(f"/api/payments/{body['id']}")

    assert stored.status_code == 200
    assert stored.get_json()["status"] == "SUCCESS"


def test_refund_accepts_pending_status(client) -> None:
    original = charge(client).get_json()

    response = refund(client, status="PENDING", relatedPaymentId=original["id"])

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "PENDING"

    stored = client.get(f"/api/payments/{body['id']}")

    assert stored.status_code == 200
    assert stored.get_json()["status"] == "PENDING"


def test_refund_rejects_a_status_that_is_not_refundable(client) -> None:
    original = charge(client).get_json()

    response = refund(client, status="FAILED", relatedPaymentId=original["id"])

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]

    history = client.get("/api/payments/member/1")

    assert history.status_code == 200
    body = history.get_json()
    assert len(body) == 1
    assert body[0]["id"] == original["id"]


def test_refund_rejects_an_amount_above_the_unrefunded_charge(client) -> None:
    original = charge(client).get_json()
    first = refund(client, amount=30, relatedPaymentId=original["id"])

    assert first.status_code == 201

    response = refund(client, amount=20, relatedPaymentId=original["id"])

    assert response.status_code == 409

    history = client.get("/api/payments/member/1")

    assert history.status_code == 200
    body = history.get_json()
    assert len(body) == 2
    assert body[0]["id"] == first.get_json()["id"]
    assert body[1]["id"] == original["id"]


def test_refund_allows_a_refund_of_exactly_the_remaining_amount(client) -> None:
    original = charge(client).get_json()

    response = refund(client, amount=49.99, relatedPaymentId=original["id"])

    assert response.status_code == 201
    body = response.get_json()
    assert body["type"] == "REFUND"
    assert body["amount"] == 49.99
    assert body["relatedPaymentId"] == original["id"]
