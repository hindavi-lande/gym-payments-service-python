import pytest


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


def test_merge_moves_every_payment_and_preserves_all_fields(client):
    original = charge(client, memberId=1, reason="PREMIUM plan renewal").get_json()
    refund = client.post(
        "/api/payments/refund",
        json={
            "memberId": 1,
            "amount": 20,
            "reason": "early cancellation",
            "relatedPaymentId": original["id"],
        },
    ).get_json()
    charge(client, memberId=2)

    snapshots = {
        payment["id"]: payment
        for payment in (
            client.get("/api/payments/member/1").get_json()
            + client.get("/api/payments/member/2").get_json()
        )
    }

    response = client.post(
        "/api/payments/merge",
        json={"fromMemberId": 1, "toMemberId": 2},
    )

    assert response.status_code == 200
    assert response.get_json() == {"moved": 2}

    assert client.get("/api/payments/member/1").get_json() == []

    kept_history = client.get("/api/payments/member/2").get_json()
    assert {payment["id"] for payment in kept_history} == set(snapshots)
    for payment in kept_history:
        snapshot = snapshots[payment["id"]]
        assert payment["memberId"] == 2
        for field in (
            "type",
            "amount",
            "status",
            "reason",
            "relatedPaymentId",
            "createdAt",
            "updatedAt",
        ):
            assert payment[field] == snapshot[field]

    moved_refund = next(payment for payment in kept_history if payment["id"] == refund["id"])
    assert moved_refund["relatedPaymentId"] == original["id"]


def test_merge_is_idempotent(client):
    charge(client, memberId=1, reason="first")
    charge(client, memberId=1, reason="second")

    first = client.post(
        "/api/payments/merge",
        json={"fromMemberId": 1, "toMemberId": 2},
    )

    assert first.status_code == 200
    assert first.get_json() == {"moved": 2}

    kept_history = client.get("/api/payments/member/2").get_json()

    second = client.post(
        "/api/payments/merge",
        json={"fromMemberId": 1, "toMemberId": 2},
    )

    assert second.status_code == 200
    assert second.get_json() == {"moved": 0}
    assert client.get("/api/payments/member/2").get_json() == kept_history
    assert client.get("/api/payments/member/1").get_json() == []


def test_merge_rejects_equal_member_ids(client):
    charge(client, memberId=3)

    response = client.post(
        "/api/payments/merge",
        json={"fromMemberId": 3, "toMemberId": 3},
    )

    assert response.status_code == 400
    assert "must be different" in response.get_json()["message"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fromMemberId", None),
        ("fromMemberId", 0),
        ("fromMemberId", -1),
        ("fromMemberId", True),
        ("toMemberId", None),
        ("toMemberId", 0),
        ("toMemberId", -1),
        ("toMemberId", True),
    ],
)
def test_merge_rejects_invalid_member_ids(client, field, value):
    payload = {"fromMemberId": 1, "toMemberId": 2}
    if value is None:
        del payload[field]
    else:
        payload[field] = value

    response = client.post("/api/payments/merge", json=payload)

    assert response.status_code == 400
    assert field in response.get_json()["message"]


def test_history_after_merge_is_ordered_most_recent_first(client):
    original = charge(client, memberId=1).get_json()
    refund = client.post(
        "/api/payments/refund",
        json={"memberId": 1, "amount": 20, "relatedPaymentId": original["id"]},
    ).get_json()
    kept_charge = charge(client, memberId=2, reason="kept charge").get_json()
    kept_refund = client.post(
        "/api/payments/refund",
        json={"memberId": 2, "amount": 5, "relatedPaymentId": kept_charge["id"]},
    ).get_json()

    merge = client.post(
        "/api/payments/merge",
        json={"fromMemberId": 1, "toMemberId": 2},
    )

    assert merge.status_code == 200
    assert merge.get_json() == {"moved": 2}

    response = client.get("/api/payments/member/2")

    assert response.status_code == 200
    body = response.get_json()
    assert {payment["id"] for payment in body} == {
        original["id"],
        refund["id"],
        kept_charge["id"],
        kept_refund["id"],
    }
    assert len(body) == 4
    assert [payment["id"] for payment in body] == [
        payment["id"]
        for payment in sorted(
            body,
            key=lambda payment: (payment["createdAt"], payment["id"]),
            reverse=True,
        )
    ]


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
