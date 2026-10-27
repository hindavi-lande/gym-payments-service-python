from datetime import UTC, datetime

from app.extensions import db


def _utcnow():
    return datetime.now(UTC)


def _iso_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_id = db.Column(db.Integer, nullable=False, index=True)
    type = db.Column(
        db.Enum("CHARGE", "REFUND", name="payment_type"),
        nullable=False,
    )
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(
        db.Enum("SUCCESS", "FAILED", "PENDING", name="payment_status"),
        nullable=False,
        default="SUCCESS",
    )
    reason = db.Column(db.String(255), nullable=True)
    related_payment_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "memberId": self.member_id,
            "type": self.type,
            "amount": float(self.amount),
            "status": self.status,
            "reason": self.reason,
            "relatedPaymentId": self.related_payment_id,
            "createdAt": _iso_datetime(self.created_at),
            "updatedAt": _iso_datetime(self.updated_at),
        }
