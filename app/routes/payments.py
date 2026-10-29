from flask import Blueprint, jsonify, request

from app.services import payment_service

payments_bp = Blueprint("payments", __name__, url_prefix="/api")


@payments_bp.post("/payments/charge")
def charge():
    payment = payment_service.charge(_json_body())
    if payment.status == "FAILED":
        return jsonify(payment.to_dict()), 402
    return jsonify(payment.to_dict()), 201


@payments_bp.post("/payments/refund")
def refund():
    payment = payment_service.refund(_json_body())
    return jsonify(payment.to_dict()), 201


@payments_bp.get("/payments/member/<int:member_id>")
def get_history_for_member(member_id):
    history = payment_service.get_history_for_member(member_id)
    return jsonify([payment.to_dict() for payment in history])


@payments_bp.get("/payments/<int:payment_id>")
def get_payment(payment_id):
    payment = payment_service.get_payment(payment_id)
    return jsonify(payment.to_dict())


@payments_bp.patch("/payments/<int:payment_id>")
def settle_payment(payment_id):
    payment = payment_service.settle_refund(payment_id, _json_body())
    return jsonify(payment.to_dict()), 200


def _json_body():
    body = request.get_json(silent=True)
    return {} if body is None else body
