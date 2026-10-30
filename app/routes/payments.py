from flask import Blueprint, jsonify, request

from app.services import payment_service

payments_bp = Blueprint("payments", __name__, url_prefix="/api")


@payments_bp.post("/payments/charge")
def charge():
    payment = payment_service.charge(_json_body())
    status_code = 402 if payment.status == "FAILED" else 201
    return jsonify(payment.to_dict()), status_code


@payments_bp.post("/payments/refund")
def refund():
    payment = payment_service.refund(_json_body())
    return jsonify(payment.to_dict()), 201


@payments_bp.get("/payments/member/<int:member_id>")
def get_history_for_member(member_id):
    return jsonify(payment_service.payment_history(member_id))


@payments_bp.get("/payments/<int:payment_id>")
def get_payment(payment_id):
    payment = payment_service.get_payment(payment_id)
    return jsonify(payment.to_dict())


def _json_body():
    body = request.get_json(silent=True)
    return {} if body is None else body
