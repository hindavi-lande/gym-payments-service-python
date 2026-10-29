def charge(client, **overrides):
    payload = {"memberId": 1, "amount": 49.99, **overrides}
    return client.post("/api/payments/charge", json=payload)


def pending_refund(client, **overrides):
    original = charge(client).get_json()
    payload = {
        "memberId": 1,
        "amount": 20,
        "relatedPaymentId": original["id"],
        "status": "PENDING",
        **overrides,
    }
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


def test_charge_with_failed_status_persists_the_charge_and_returns_402(client):
    response = charge(client, status="FAILED")

    assert response.status_code == 402
    body = response.get_json()
    assert body["type"] == "CHARGE"
    assert body["status"] == "FAILED"

    stored = client.get(f"/api/payments/{body['id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "FAILED"


def test_charge_accepts_an_explicit_success_status(client):
    response = charge(client, status="SUCCESS")

    assert response.status_code == 201
    assert response.get_json()["status"] == "SUCCESS"


def test_charge_rejects_an_unknown_status(client):
    response = charge(client, status="DECLINED")

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]
    assert client.get("/api/payments/member/1").get_json() == []


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


def test_refund_with_pending_status_is_stored_as_pending(client):
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
    body = response.get_json()
    assert body["type"] == "REFUND"
    assert body["status"] == "PENDING"

    stored = client.get(f"/api/payments/{body['id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "PENDING"


def test_refund_rejects_an_unknown_status(client):
    original = charge(client).get_json()

    response = client.post(
        "/api/payments/refund",
        json={
            "memberId": 1,
            "amount": 20,
            "relatedPaymentId": original["id"],
            "status": "DECLINED",
        },
    )

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]
    assert len(client.get("/api/payments/member/1").get_json()) == 1


def test_refund_rejects_an_over_refund_and_persists_nothing(client):
    original = charge(client).get_json()
    accepted = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    )
    assert accepted.status_code == 201
    accepted_refund = accepted.get_json()

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 30, "relatedPaymentId": original["id"]},
    )

    assert response.status_code == 422

    history = client.get("/api/payments/member/1").get_json()
    assert [payment["id"] for payment in history] == [accepted_refund["id"], original["id"]]

    stored_charge = client.get(f"/api/payments/{original['id']}").get_json()
    assert stored_charge["amount"] == 49.99
    stored_refund = client.get(f"/api/payments/{accepted_refund['id']}").get_json()
    assert stored_refund["amount"] == 20.0
    assert stored_refund["status"] == "SUCCESS"


def test_repeated_partial_refunds_are_allowed_until_the_charge_is_exhausted(client):
    original = charge(client).get_json()

    first = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    )
    second = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    )

    assert first.status_code == 201
    assert second.status_code == 201

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 10, "relatedPaymentId": original["id"]},
    )

    assert response.status_code == 422
    refunds = [
        payment
        for payment in client.get("/api/payments/member/1").get_json()
        if payment["type"] == "REFUND"
    ]
    assert len(refunds) == 2


def test_refund_rejects_a_second_full_refund_of_the_same_charge(client):
    original = charge(client).get_json()

    first = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 49.99, "relatedPaymentId": original["id"]},
    )
    assert first.status_code == 201

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 49.99, "relatedPaymentId": original["id"]},
    )

    assert response.status_code == 422
    refunds = [
        payment
        for payment in client.get("/api/payments/member/1").get_json()
        if payment["type"] == "REFUND"
    ]
    assert sum(payment["amount"] for payment in refunds) == 49.99


def test_failed_refund_does_not_consume_the_charge(client):
    original = charge(client).get_json()

    failed = client.post(
        "/api/payments/refund",
        json={
            "memberId": 1,
            "amount": 49.99,
            "relatedPaymentId": original["id"],
            "status": "FAILED",
        },
    )
    assert failed.status_code == 201
    assert failed.get_json()["status"] == "FAILED"

    response = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 49.99, "relatedPaymentId": original["id"]},
    )

    assert response.status_code == 201
    assert response.get_json()["status"] == "SUCCESS"


def test_patch_settles_a_pending_refund_to_success(client):
    refund = pending_refund(client).get_json()
    assert refund["status"] == "PENDING"

    response = client.patch(f"/api/payments/{refund['id']}", json={"status": "SUCCESS"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "SUCCESS"
    stored = client.get(f"/api/payments/{refund['id']}")
    assert stored.get_json()["status"] == "SUCCESS"


def test_patch_settles_a_pending_refund_to_failed(client):
    refund = pending_refund(client).get_json()
    assert refund["status"] == "PENDING"

    response = client.patch(f"/api/payments/{refund['id']}", json={"status": "FAILED"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "FAILED"
    stored = client.get(f"/api/payments/{refund['id']}")
    assert stored.get_json()["status"] == "FAILED"


def test_patch_rejects_settling_a_non_pending_refund(client):
    refund = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": None},
    ).get_json()
    assert refund["status"] == "SUCCESS"

    response = client.patch(f"/api/payments/{refund['id']}", json={"status": "FAILED"})

    assert response.status_code == 422
    stored = client.get(f"/api/payments/{refund['id']}")
    assert stored.get_json()["status"] == "SUCCESS"


def test_patch_rejects_settling_a_pending_charge(client):
    original = charge(client, status="PENDING").get_json()
    assert original["type"] == "CHARGE"
    assert original["status"] == "PENDING"

    response = client.patch(f"/api/payments/{original['id']}", json={"status": "SUCCESS"})

    assert response.status_code == 422
    stored = client.get(f"/api/payments/{original['id']}")
    assert stored.get_json()["status"] == "PENDING"


def test_patch_rejects_an_invalid_target_status(client):
    refund = pending_refund(client).get_json()

    for invalid in ("PENDING", "DECLINED"):
        response = client.patch(f"/api/payments/{refund['id']}", json={"status": invalid})

        assert response.status_code == 400
        assert "status" in response.get_json()["message"]

    stored = client.get(f"/api/payments/{refund['id']}")
    assert stored.get_json()["status"] == "PENDING"


def test_patch_returns_404_for_an_unknown_payment(client):
    response = client.patch("/api/payments/999999", json={"status": "SUCCESS"})

    assert response.status_code == 404
    assert "message" in response.get_json()


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
