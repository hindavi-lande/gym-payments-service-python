from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.errors import ApiError
from app.extensions import db
from app.models import Payment

MAX_AMOUNT = Decimal("99999999.99")
CENT = Decimal("0.01")
PAYMENT_CHARGE_STATUSES = {"SUCCESS", "FAILED"}
REFUND_STATUSES = {"SUCCESS", "PENDING"}
SETTLE_STATUSES = {"SUCCESS", "FAILED"}


def charge(payload):
    data = _validate_payment_payload(payload)
    status = _parse_payment_status(payload.get("status"))
    payment = Payment(
        member_id=data["member_id"],
        amount=data["amount"],
        reason=data["reason"],
        type="CHARGE",
        status=status,
    )
    return _save(payment)


def refund(payload: dict) -> Payment:
    data = _validate_payment_payload(payload)
    status = _parse_refund_status(payload.get("status"))
    related_id = data["related_payment_id"]

    if related_id is not None:
        original = db.session.get(Payment, related_id)
        if (
            original is None
            or original.member_id != data["member_id"]
            or original.type != "CHARGE"
        ):
            raise ApiError(
                422,
                f"relatedPaymentId {related_id} is not a valid charge "
                f"for member {data['member_id']}",
            )
        if _refunded_total(related_id) + data["amount"] > original.amount:
            raise ApiError(
                409,
                f"Refund of {data['amount']} exceeds the amount still "
                f"refundable for relatedPaymentId {related_id}",
            )

    payment = Payment(
        member_id=data["member_id"],
        amount=data["amount"],
        reason=data["reason"],
        related_payment_id=related_id,
        type="REFUND",
        status=status,
    )
    return _save(payment)


def get_payment(payment_id):
    payment = db.session.get(Payment, payment_id)
    if payment is None:
        raise ApiError(404, f"Payment with id {payment_id} not found")
    return payment


def get_history_for_member(member_id):
    statement = (
        db.select(Payment)
        .where(Payment.member_id == member_id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
    )
    return db.session.scalars(statement).all()


def _refunded_total(charge_id: int) -> Decimal:
    total = db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(Payment.amount), 0)).where(
            Payment.related_payment_id == charge_id,
            Payment.type == "REFUND",
            Payment.status.in_(REFUND_STATUSES),
        )
    )
    if total is None or isinstance(total, int):
        return Decimal("0.00")
    return Decimal(str(total))


def settle_refund(payment_id: int, payload: dict) -> Payment:
    payment = get_payment(payment_id)

    if not isinstance(payload, dict):
        raise ApiError(400, "Request body must be a JSON object")

    status = payload.get("status")
    if not isinstance(status, str) or status not in SETTLE_STATUSES:
        raise ApiError(400, "status must be one of: FAILED, SUCCESS")

    if payment.type != "REFUND" or payment.status != "PENDING":
        raise ApiError(409, f"Payment with id {payment_id} is not a pending refund")

    payment.status = status
    db.session.commit()
    db.session.refresh(payment)
    return payment


def _save(payment):
    db.session.add(payment)
    db.session.commit()
    db.session.refresh(payment)
    return payment


def _validate_payment_payload(payload):
    if not isinstance(payload, dict):
        raise ApiError(400, "Request body must be a JSON object")

    return {
        "member_id": _parse_positive_int(payload.get("memberId"), "memberId"),
        "amount": _parse_amount(payload.get("amount")),
        "reason": _optional_string(payload.get("reason"), "reason"),
        "related_payment_id": _optional_positive_int(
            payload.get("relatedPaymentId"), "relatedPaymentId"
        ),
    }


def _parse_amount(value):
    if isinstance(value, bool) or value is None:
        raise ApiError(400, "amount must be greater than 0")

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ApiError(400, "amount must be greater than 0") from exc

    if not amount.is_finite() or amount <= 0:
        raise ApiError(400, "amount must be greater than 0")
    if amount > MAX_AMOUNT:
        raise ApiError(400, "amount must be at most 99999999.99")

    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _parse_payment_status(value):
    if value is None:
        return "SUCCESS"
    if not isinstance(value, str) or value not in PAYMENT_CHARGE_STATUSES:
        raise ApiError(400, "status must be one of: FAILED, SUCCESS")
    return value


def _parse_refund_status(value: object) -> str:
    if value is None:
        return "SUCCESS"
    if not isinstance(value, str) or value not in REFUND_STATUSES:
        raise ApiError(400, "status must be one of: PENDING, SUCCESS")
    return value


def _parse_positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ApiError(400, f"{field} must be a positive integer")
    return value


def _optional_positive_int(value, field):
    if value is None:
        return None
    return _parse_positive_int(value, field)


def _optional_string(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, f"{field} must be a string")
    return value
