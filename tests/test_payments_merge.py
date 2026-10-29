def charge(client, member_id=1, amount=49.99, **overrides):
    payload = {"memberId": member_id, "amount": amount, **overrides}
    return client.post("/api/payments/charge", json=payload).get_json()


def refund(client, member_id=1, amount=20, related_payment_id=None):
    payload = {"memberId": member_id, "amount": amount}
    if related_payment_id is not None:
        payload["relatedPaymentId"] = related_payment_id
    return client.post("/api/payments/refund", json=payload).get_json()


def merge(client, from_member_id, to_member_id):
    return client.post(
        "/api/payments/merge",
        json={"fromMemberId": from_member_id, "toMemberId": to_member_id},
    )


def get_payment(client, payment_id):
    return client.get(f"/api/payments/{payment_id}").get_json()


def test_merge_moves_every_payment_and_reports_the_count(client):
    charge(client, member_id=1, amount=10)
    charge(client, member_id=1, amount=15.5)
    charge(client, member_id=2, amount=99)

    response = merge(client, 1, 2)

    assert response.status_code == 200
    assert response.get_json() == {"moved": 2}
    assert client.get("/api/payments/member/1").get_json() == []
    assert len(client.get("/api/payments/member/2").get_json()) == 3


def test_merge_preserves_every_field_including_related_payment_id(client):
    original_charge = charge(client, member_id=1, amount=49.99, reason="PREMIUM plan renewal")
    original_refund = refund(
        client,
        member_id=1,
        amount=20,
        related_payment_id=original_charge["id"],
    )
    before_charge = get_payment(client, original_charge["id"])
    before_refund = get_payment(client, original_refund["id"])
    assert before_refund["relatedPaymentId"] == before_charge["id"]

    response = merge(client, 1, 2)

    assert response.status_code == 200
    assert response.get_json() == {"moved": 2}

    after_charge = get_payment(client, before_charge["id"])
    after_refund = get_payment(client, before_refund["id"])

    assert after_charge == {**before_charge, "memberId": 2}
    assert after_refund == {**before_refund, "memberId": 2}
    assert after_charge["createdAt"] == before_charge["createdAt"]
    assert after_charge["updatedAt"] == before_charge["updatedAt"]
    assert after_refund["createdAt"] == before_refund["createdAt"]
    assert after_refund["updatedAt"] == before_refund["updatedAt"]
    assert after_refund["relatedPaymentId"] == before_charge["id"]
    assert after_refund["type"] == "REFUND"
    assert after_charge["type"] == "CHARGE"


def test_merge_keeps_destination_history_order(client):
    first = charge(client, member_id=1, amount=10)
    second = charge(client, member_id=1, amount=20)
    third = charge(client, member_id=1, amount=30)
    before = client.get("/api/payments/member/1").get_json()
    assert [payment["id"] for payment in before] == [third["id"], second["id"], first["id"]]

    response = merge(client, 1, 2)

    assert response.status_code == 200
    assert response.get_json() == {"moved": 3}
    after = client.get("/api/payments/member/2").get_json()
    assert [payment["id"] for payment in after] == [payment["id"] for payment in before]
    assert [payment["createdAt"] for payment in after] == [
        payment["createdAt"] for payment in before
    ]


def test_repeat_merge_returns_moved_zero_and_changes_nothing(client):
    original_charge = charge(client, member_id=1, amount=49.99, reason="PREMIUM plan renewal")
    original_refund = refund(
        client,
        member_id=1,
        amount=20,
        related_payment_id=original_charge["id"],
    )
    payment_ids = [original_charge["id"], original_refund["id"]]

    first_response = merge(client, 1, 2)
    assert first_response.status_code == 200
    assert first_response.get_json() == {"moved": 2}
    after_first_merge = {pid: get_payment(client, pid) for pid in payment_ids}

    second_response = merge(client, 1, 2)

    assert second_response.status_code == 200
    assert second_response.get_json() == {"moved": 0}
    assert {pid: get_payment(client, pid) for pid in payment_ids} == after_first_merge
    assert len(client.get("/api/payments/member/2").get_json()) == 2


def test_merge_from_a_member_with_no_payments_returns_moved_zero(client):
    response = merge(client, 999999, 2)

    assert response.status_code == 200
    assert response.get_json() == {"moved": 0}


def test_merge_rejects_equal_ids_and_invalid_ids(client):
    payment = charge(client, member_id=1)
    before = client.get(f"/api/payments/{payment['id']}").data

    self_merge = merge(client, 1, 1)
    assert self_merge.status_code == 400
    assert "fromMemberId" in self_merge.get_json()["message"]
    assert client.get(f"/api/payments/{payment['id']}").data == before

    invalid_bodies = [
        ({"toMemberId": 2}, "fromMemberId"),
        ({"fromMemberId": 1}, "toMemberId"),
        ({"fromMemberId": 0, "toMemberId": 2}, "fromMemberId"),
        ({"fromMemberId": -1, "toMemberId": 2}, "fromMemberId"),
        ({"fromMemberId": 1.5, "toMemberId": 2}, "fromMemberId"),
        ({"fromMemberId": "1", "toMemberId": 2}, "fromMemberId"),
        ({"fromMemberId": True, "toMemberId": 2}, "fromMemberId"),
        ({"fromMemberId": 1, "toMemberId": 0}, "toMemberId"),
        ({"fromMemberId": 1, "toMemberId": "2"}, "toMemberId"),
    ]

    for body, field in invalid_bodies:
        response = client.post("/api/payments/merge", json=body)

        assert response.status_code == 400
        assert field in response.get_json()["message"]
        assert client.get(f"/api/payments/{payment['id']}").data == before
