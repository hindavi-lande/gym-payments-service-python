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


def test_charge_with_status_failed_returns_402_and_persists_the_charge(client):
    response = charge(client, status="FAILED")

    assert response.status_code == 402
    history = client.get("/api/payments/member/1").get_json()
    assert len(history) == 1
    assert history[0]["status"] == "FAILED"


def test_charge_defaults_status_to_success(client):
    response = client.post("/api/payments/charge", json={"memberId": 1, "amount": 10})

    assert response.status_code == 201
    assert response.get_json()["status"] == "SUCCESS"


def test_charge_rejects_an_unknown_status(client):
    pending = charge(client, status="PENDING")
    wrong_case = charge(client, status="failed")
    not_a_string = charge(client, status=123)

    assert pending.status_code == 400
    assert wrong_case.status_code == 400
    assert not_a_string.status_code == 400
    assert client.get("/api/payments/member/1").get_json() == []


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
