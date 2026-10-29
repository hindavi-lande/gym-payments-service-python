def charge(client, **overrides):
    payload = {"memberId": 1, "amount": 49.99, **overrides}
    return client.post("/api/payments/charge", json=payload)


def refund(client, **overrides):
    payload = {"memberId": 1, "amount": 20, **overrides}
    return client.post("/api/payments/refund", json=payload)


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


def test_refund_accepts_a_pending_status(client):
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
    assert response.get_json()["status"] == "PENDING"

    history = client.get("/api/payments/member/1")
    assert history.status_code == 200
    assert [payment["status"] for payment in history.get_json()] == ["PENDING", "SUCCESS"]


def test_refund_rejects_a_status_outside_success_and_pending(client):
    original = charge(client).get_json()

    response = client.post(
        "/api/payments/refund",
        json={
            "memberId": 1,
            "amount": 20,
            "relatedPaymentId": original["id"],
            "status": "FAILED",
        },
    )

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]

    history = client.get("/api/payments/member/1")
    assert history.status_code == 200
    assert [payment["type"] for payment in history.get_json()] == ["CHARGE"]


def test_refund_rejects_a_related_charge_with_status_failed(client):
    failed = charge(client, status="FAILED").get_json()

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": failed["id"]},
    )

    assert response.status_code == 422

    history = client.get("/api/payments/member/1")
    assert history.status_code == 200
    assert [payment["type"] for payment in history.get_json()] == ["CHARGE"]


def test_refund_rejects_an_over_refund(client):
    original = charge(client).get_json()
    first = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 40, "relatedPaymentId": original["id"]},
    )
    assert first.status_code == 201

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    )

    assert response.status_code == 422

    history = client.get("/api/payments/member/1")
    assert history.status_code == 200
    assert len(history.get_json()) == 2


def test_settle_marks_a_pending_refund_success(client):
    original = charge(client).get_json()
    pending = refund(
        client, relatedPaymentId=original["id"], status="PENDING"
    ).get_json()

    response = client.post(
        f"/api/payments/refund/{pending['id']}/settle", json={"status": "SUCCESS"}
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "SUCCESS"

    stored = client.get(f"/api/payments/{pending['id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "SUCCESS"


def test_settle_marks_a_pending_refund_failed(client):
    original = charge(client).get_json()
    pending = refund(
        client, relatedPaymentId=original["id"], status="PENDING"
    ).get_json()

    response = client.post(
        f"/api/payments/refund/{pending['id']}/settle", json={"status": "FAILED"}
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "FAILED"

    stored = client.get(f"/api/payments/{pending['id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "FAILED"


def test_settle_rejects_a_refund_that_is_not_pending(client):
    original = charge(client).get_json()
    settled = refund(client, relatedPaymentId=original["id"]).get_json()

    response = client.post(
        f"/api/payments/refund/{settled['id']}/settle", json={"status": "FAILED"}
    )

    assert response.status_code == 422

    stored = client.get(f"/api/payments/{settled['id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "SUCCESS"


def test_settle_rejects_a_charge(client):
    original = charge(client).get_json()

    response = client.post(
        f"/api/payments/refund/{original['id']}/settle", json={"status": "SUCCESS"}
    )

    assert response.status_code == 422

    stored = client.get(f"/api/payments/{original['id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "SUCCESS"


def test_settle_returns_404_for_an_unknown_id(client):
    response = client.post(
        "/api/payments/refund/999999/settle", json={"status": "SUCCESS"}
    )

    assert response.status_code == 404


def test_settle_rejects_a_status_outside_success_and_failed(client):
    original = charge(client).get_json()
    pending = refund(
        client, relatedPaymentId=original["id"], status="PENDING"
    ).get_json()

    response = client.post(
        f"/api/payments/refund/{pending['id']}/settle", json={"status": "PENDING"}
    )

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]

    stored = client.get(f"/api/payments/{pending['id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "PENDING"


def test_refund_rejects_a_double_refund(client):
    original = charge(client).get_json()
    first = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 49.99, "relatedPaymentId": original["id"]},
    )
    assert first.status_code == 201

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 1, "relatedPaymentId": original["id"]},
    )

    assert response.status_code == 422

    history = client.get("/api/payments/member/1")
    assert history.status_code == 200
    assert len(history.get_json()) == 2
    assert history.get_json()[0]["id"] == first.get_json()["id"]
