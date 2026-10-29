from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.errors import ApiError
from app.extensions import db
from app.models import Payment

MAX_AMOUNT = Decimal("99999999.99")
CENT = Decimal("0.01")
PAYMENT_CHARGE_STATUSES: set[str] = {"SUCCESS", "FAILED"}


def charge(payload) -> Payment:
    data = _validate_payment_payload(payload)
    payment = Payment(
        member_id=data["member_id"],
        amount=data["amount"],
        reason=data["reason"],
        type="CHARGE",
        status=_parse_status(payload.get("status")),
    )
    return _save(payment)


def refund(payload):
    data = _validate_payment_payload(payload)
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

    payment = Payment(
        member_id=data["member_id"],
        amount=data["amount"],
        reason=data["reason"],
        related_payment_id=related_id,
        type="REFUND",
        status="SUCCESS",
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


def _parse_status(value) -> str:
    if value is None:
        return "SUCCESS"
    if not isinstance(value, str) or value not in PAYMENT_CHARGE_STATUSES:
        raise ApiError(400, "status must be one of: FAILED, SUCCESS")
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
