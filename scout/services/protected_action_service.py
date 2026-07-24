"""Deterministic protected-action proposal, confirmation, and execution."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout.repositories.order_repository import OrderRepository
from scout.repositories.protected_action_repository import ProtectedActionRepository
from scout.services import checkout_service, order_service
from scout.services.checkout_service import ShippingAddress

ActionType = Literal[
    "cancel_order",
    "create_return_request",
    "create_exchange_request",
    "change_order_address",
    "create_refund_request",
    "start_protected_payment_handoff",
]
ConfirmationStatus = Literal[
    "requested",
    "proposed",
    "awaiting_confirmation",
    "approved",
    "rejected",
    "executing",
    "executed",
    "verified",
    "failed",
    "expired",
]


class ProtectedActionError(Exception):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class ProtectedActionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    customer_id: str = Field(min_length=1, max_length=200)
    action_type: ActionType
    order_id: Optional[str] = Field(default=None, max_length=128)
    checkout_id: Optional[str] = Field(default=None, max_length=128)
    workflow_id: Optional[str] = Field(default=None, max_length=128)
    reason: Optional[str] = Field(default=None, max_length=500)
    order_item_id: Optional[str] = Field(default=None, max_length=128)
    replacement_product_id: Optional[str] = Field(default=None, max_length=128)
    shipping_address: Optional[ShippingAddress] = None

    @field_validator("session_id", "customer_id")
    @classmethod
    def _required_trimmed(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("order_id", "checkout_id", "workflow_id", "reason", "order_item_id", "replacement_product_id")
    @classmethod
    def _optional_trimmed(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ProtectedActionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=200)
    customer_id: str = Field(min_length=1, max_length=200)
    decision: Literal["approve", "reject"]
    payload_hash: Optional[str] = Field(default=None, min_length=64, max_length=64)


class ProtectedActionProposal(BaseModel):
    confirmation_id: str
    workflow_id: str
    request_id: str
    session_id: str
    customer_id: str
    action_type: ActionType
    resource_type: str
    resource_id: str
    proposal_summary: str
    customer_effects: List[str]
    financial_effects: List[str]
    eligibility_status: Literal["eligible", "ineligible"]
    eligibility_reason_code: str
    policy_ids: List[str]
    evidence_ids: List[str]
    payload_hash: str
    idempotency_key: str
    status: ConfirmationStatus
    created_at: str
    expires_at: str


class ProtectedActionResult(BaseModel):
    confirmation_id: str
    action_type: ActionType
    execution_status: Literal["verified", "rejected", "expired", "failed"]
    resource_id: str
    result_state: str
    request_id: Optional[str] = None
    verified_at: str
    evidence_ids: List[str] = Field(default_factory=list)
    message: str
    payment_handoff: Optional[Dict[str, Any]] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _payload_hash(payload: Dict[str, Any]) -> str:
    safe_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(safe_payload.encode("utf-8")).hexdigest()


def _stable_idempotency_key(payload_hash: str, action_type: str, resource_id: str, customer_id: str) -> str:
    digest = hashlib.sha256(f"{payload_hash}|{action_type}|{resource_id}|{customer_id}".encode("utf-8")).hexdigest()
    return f"pa_{digest}"


def _from_record(record) -> ProtectedActionProposal:
    return ProtectedActionProposal(
        confirmation_id=record.confirmation_id,
        workflow_id=record.workflow_id,
        request_id=record.request_id,
        session_id=record.session_id,
        customer_id=record.customer_id,
        action_type=record.action_type,
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        proposal_summary=record.proposal_summary,
        customer_effects=record.customer_effects,
        financial_effects=record.financial_effects,
        eligibility_status=record.eligibility_status,
        eligibility_reason_code=record.eligibility_reason_code,
        policy_ids=record.policy_ids,
        evidence_ids=record.evidence_ids,
        payload_hash=record.payload_hash,
        idempotency_key=record.idempotency_key,
        status=record.status,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


def _lookup_order(order_id: Optional[str], session_id: str, db_path: Optional[str]):
    if not order_id:
        raise ProtectedActionError("validation_error", "An order number is required for this protected action.")
    try:
        return order_service.lookup_order(order_id, session_id, db_path)
    except order_service.OrderServiceError as exc:
        raise ProtectedActionError(exc.error_type, exc.message) from exc


def _eligibility_for(action_type: str, order) -> tuple[bool, str, str, List[str], List[str]]:
    if action_type == "cancel_order":
        check = order.eligibility.cancellation
        return check.eligible, ("not_fulfilled" if check.eligible else "not_cancelable"), check.reason, ["order_cancellation"], []
    if action_type == "create_return_request":
        check = order.eligibility.return_eligibility
        return check.eligible, ("within_return_window" if check.eligible else "return_not_eligible"), check.reason, ["returns"], [
            "No refund is issued automatically."
        ]
    if action_type == "create_exchange_request":
        check = order.eligibility.exchange
        return check.eligible, ("within_exchange_window" if check.eligible else "exchange_not_eligible"), check.reason, ["exchanges"], [
            "Price differences may require separate review."
        ]
    if action_type == "create_refund_request":
        paid = order.payment.status in {"succeeded", "paid", "payment_succeeded"}
        return paid, ("payment_captured" if paid else "payment_not_captured"), (
            "A paid order can be submitted for refund review." if paid else "A captured payment is required before refund review."
        ), ["refunds"], ["This submits a refund review request; it does not issue a refund."]
    if action_type == "change_order_address":
        eligible = order.fulfillment.fulfillment_type == "delivery" and order.fulfillment.status == "processing"
        return eligible, ("delivery_processing" if eligible else "address_locked"), (
            "The delivery order is still processing." if eligible else "The order is no longer eligible for address changes."
        ), ["shipping_delivery"], []
    return True, "payment_handoff_available", "Secure payment handoff can be started from the checkout session.", [], []


def propose_action(request: ProtectedActionProposalRequest, db_path: Optional[str] = None) -> ProtectedActionProposal:
    repo = ProtectedActionRepository(db_path)
    workflow_id = request.workflow_id or f"wf-{uuid.uuid4()}"
    confirmation_id = f"conf-{uuid.uuid4()}"
    request_id = f"req-{uuid.uuid4()}"
    resource_id = request.checkout_id if request.action_type == "start_protected_payment_handoff" else request.order_id
    if not resource_id:
        raise ProtectedActionError("validation_error", "A protected action resource identifier is required.")

    evidence_ids: List[str] = []
    policy_ids: List[str] = []
    financial_effects: List[str] = []
    customer_effects: List[str] = []
    eligibility_status: Literal["eligible", "ineligible"] = "eligible"
    reason_code = "eligible"

    if request.action_type == "start_protected_payment_handoff":
        try:
            review = checkout_service.get_checkout_review(resource_id, request.session_id, db_path)
        except checkout_service.CheckoutServiceError as exc:
            raise ProtectedActionError(exc.error_type, exc.message) from exc
        proposal_summary = f"Continue to secure test payment for checkout {review.checkout_id}"
        customer_effects = ["You will continue through the existing protected Stripe test checkout workflow."]
        financial_effects = [f"Payment amount to authorize: {review.currency} {review.total:.2f}."]
    else:
        order = _lookup_order(request.order_id, request.session_id, db_path)
        eligible, reason_code, reason, policy_ids, extra_financial = _eligibility_for(request.action_type, order)
        eligibility_status = "eligible" if eligible else "ineligible"
        if not eligible:
            repo.record_audit_event(
                confirmation_id=None,
                workflow_id=workflow_id,
                session_id=request.session_id,
                customer_id=request.customer_id,
                event_type="eligibility_result",
                detail={"action_type": request.action_type, "eligible": False, "reason_code": reason_code},
            )
            raise ProtectedActionError("ineligible_action", reason)
        evidence_ids = [f"order:{order.order_id}", f"eligibility:{request.action_type}:{reason_code}"]
        proposal_summary = {
            "cancel_order": f"Cancel order {order.order_id} before fulfillment completes",
            "create_return_request": f"Submit a return request for order {order.order_id}",
            "create_exchange_request": f"Submit an exchange request for order {order.order_id}",
            "change_order_address": f"Change the delivery address for order {order.order_id}",
            "create_refund_request": f"Submit a refund review request for order {order.order_id}",
        }[request.action_type]
        customer_effects = [reason]
        financial_effects = extra_financial or [f"Order total on record: {order.currency} {order.total:.2f}."]

    payload = request.model_dump(mode="json", exclude_none=True)
    payload.update({"resource_id": resource_id, "workflow_id": workflow_id, "request_id": request_id})
    hashed = _payload_hash(payload)
    idempotency_key = _stable_idempotency_key(hashed, request.action_type, resource_id, request.customer_id)
    existing = repo.find_by_idempotency_key(idempotency_key)
    if existing is not None:
        repo.record_audit_event(
            confirmation_id=existing.confirmation_id,
            workflow_id=existing.workflow_id,
            session_id=existing.session_id,
            customer_id=existing.customer_id,
            event_type="idempotent_replay",
            detail={"phase": "proposal"},
        )
        return _from_record(existing)

    expires_at = _iso(_now() + timedelta(minutes=15))
    record = repo.create_confirmation(
        confirmation_id=confirmation_id,
        workflow_id=workflow_id,
        request_id=request_id,
        session_id=request.session_id,
        customer_id=request.customer_id,
        action_type=request.action_type,
        resource_type="checkout" if request.action_type == "start_protected_payment_handoff" else "order",
        resource_id=resource_id,
        proposal_summary=proposal_summary,
        customer_effects=customer_effects,
        financial_effects=financial_effects,
        eligibility_status=eligibility_status,
        eligibility_reason_code=reason_code,
        policy_ids=policy_ids,
        evidence_ids=evidence_ids,
        payload_hash=hashed,
        idempotency_key=idempotency_key,
        status="awaiting_confirmation",
        expires_at=expires_at,
    )
    for event_type in ("proposal_created", "authentication_result", "authorization_result", "ownership_result", "confirmation_shown"):
        repo.record_audit_event(
            confirmation_id=confirmation_id,
            workflow_id=workflow_id,
            session_id=request.session_id,
            customer_id=request.customer_id,
            event_type=event_type,
            detail={"action_type": request.action_type, "resource_id": resource_id, "success": True},
        )
    return _from_record(record)


def _result(
    *,
    confirmation_id: str,
    action_type: str,
    execution_status: Literal["verified", "rejected", "expired", "failed"],
    resource_id: str,
    result_state: str,
    message: str,
    request_id: Optional[str] = None,
    evidence_ids: Optional[List[str]] = None,
    payment_handoff: Optional[Dict[str, Any]] = None,
) -> ProtectedActionResult:
    return ProtectedActionResult(
        confirmation_id=confirmation_id,
        action_type=action_type,
        execution_status=execution_status,
        resource_id=resource_id,
        result_state=result_state,
        request_id=request_id,
        verified_at=_iso(_now()),
        evidence_ids=evidence_ids or [],
        message=message,
        payment_handoff=payment_handoff,
    )


def decide_confirmation(request: ProtectedActionDecisionRequest, db_path: Optional[str] = None) -> ProtectedActionResult:
    repo = ProtectedActionRepository(db_path)
    record = repo.get_confirmation(request.confirmation_id)
    if record is None:
        raise ProtectedActionError("confirmation_not_found", "No matching confirmation was found.")
    if record.session_id != request.session_id or record.customer_id != request.customer_id:
        repo.record_audit_event(
            confirmation_id=record.confirmation_id,
            workflow_id=record.workflow_id,
            session_id=request.session_id,
            customer_id=request.customer_id,
            event_type="authorization_result",
            detail={"success": False, "reason": "session_or_customer_mismatch"},
        )
        raise ProtectedActionError("authorization_failed", "This confirmation does not belong to this customer session.")
    if record.status in {"verified", "executed"} and record.result:
        repo.record_audit_event(
            confirmation_id=record.confirmation_id,
            workflow_id=record.workflow_id,
            session_id=record.session_id,
            customer_id=record.customer_id,
            event_type="idempotent_replay",
            detail={"phase": "decision"},
        )
        return ProtectedActionResult.model_validate(record.result)
    if record.status != "awaiting_confirmation":
        raise ProtectedActionError("confirmation_consumed", "This confirmation has already been used.")
    if request.payload_hash is not None and request.payload_hash != record.payload_hash:
        repo.record_audit_event(
            confirmation_id=record.confirmation_id,
            workflow_id=record.workflow_id,
            session_id=record.session_id,
            customer_id=record.customer_id,
            event_type="payload_hash_rejected",
            detail={"success": False},
        )
        raise ProtectedActionError("payload_hash_mismatch", "The confirmation payload changed. Please review the action again.")
    if datetime.fromisoformat(record.expires_at.replace("Z", "+00:00")) <= _now():
        repo.update_status(record.confirmation_id, status="expired")
        repo.record_audit_event(
            confirmation_id=record.confirmation_id,
            workflow_id=record.workflow_id,
            session_id=record.session_id,
            customer_id=record.customer_id,
            event_type="confirmation_expired",
            detail={},
        )
        return _result(
            confirmation_id=record.confirmation_id,
            action_type=record.action_type,
            execution_status="expired",
            resource_id=record.resource_id,
            result_state="expired",
            message="This confirmation expired before it was approved.",
        )
    if request.decision == "reject":
        result = _result(
            confirmation_id=record.confirmation_id,
            action_type=record.action_type,
            execution_status="rejected",
            resource_id=record.resource_id,
            result_state="rejected",
            message="The protected action was canceled. No changes were made.",
        )
        repo.update_status(record.confirmation_id, status="rejected", result=result.model_dump(mode="json"), consume=True)
        repo.record_audit_event(
            confirmation_id=record.confirmation_id,
            workflow_id=record.workflow_id,
            session_id=record.session_id,
            customer_id=record.customer_id,
            event_type="confirmation_rejected",
            detail={},
        )
        return result

    repo.record_audit_event(
        confirmation_id=record.confirmation_id,
        workflow_id=record.workflow_id,
        session_id=record.session_id,
        customer_id=record.customer_id,
        event_type="confirmation_approved",
        detail={"action_type": record.action_type},
    )
    repo.update_status(record.confirmation_id, status="executing")

    if record.action_type == "cancel_order":
        order = _lookup_order(record.resource_id, record.session_id, db_path)
        if not order.eligibility.cancellation.eligible:
            failed = _result(
                confirmation_id=record.confirmation_id,
                action_type=record.action_type,
                execution_status="failed",
                resource_id=record.resource_id,
                result_state="eligibility_changed",
                message="The order is no longer eligible for cancellation.",
            )
            repo.update_status(record.confirmation_id, status="failed", result=failed.model_dump(mode="json"), consume=True)
            return failed
        if not OrderRepository(db_path).update_status_for_session(record.resource_id, record.session_id, "canceled"):
            raise ProtectedActionError("execution_failed", "Scout could not cancel this order safely.")
        verified = order_service.lookup_order(record.resource_id, record.session_id, db_path)
        result = _result(
            confirmation_id=record.confirmation_id,
            action_type=record.action_type,
            execution_status="verified",
            resource_id=record.resource_id,
            result_state=verified.order_status,
            message=f"Order {record.resource_id} was canceled successfully.",
            evidence_ids=[f"order:{record.resource_id}:status:{verified.order_status}"],
        )
    elif record.action_type == "start_protected_payment_handoff":
        try:
            intent = checkout_service.create_checkout_payment_intent(
                checkout_id=record.resource_id,
                session_id=record.session_id,
                idempotency_key=record.idempotency_key,
                db_path=db_path,
            )
        except checkout_service.CheckoutServiceError as exc:
            raise ProtectedActionError(exc.error_type, exc.message) from exc
        result = _result(
            confirmation_id=record.confirmation_id,
            action_type=record.action_type,
            execution_status="verified",
            resource_id=record.resource_id,
            result_state=intent.status,
            message="Continue through the secure Stripe test payment handoff.",
            payment_handoff=intent.model_dump(mode="json"),
        )
    else:
        action_request = repo.create_action_request(
            request_id=record.request_id,
            confirmation_id=record.confirmation_id,
            action_type=record.action_type,
            order_id=record.resource_id,
            order_item_id=None,
            status="submitted_for_review",
            reason=None,
            payload={"payload_hash": record.payload_hash},
        )
        result = _result(
            confirmation_id=record.confirmation_id,
            action_type=record.action_type,
            execution_status="verified",
            resource_id=record.resource_id,
            result_state="request_submitted",
            request_id=action_request.request_id,
            message={
                "create_return_request": f"Return request {action_request.request_id} was submitted for review.",
                "create_exchange_request": f"Exchange request {action_request.request_id} was submitted for review.",
                "change_order_address": f"Address change request {action_request.request_id} was submitted for review.",
                "create_refund_request": f"Refund request {action_request.request_id} was submitted. This does not mean the refund has been approved or issued.",
            }[record.action_type],
        )

    repo.update_status(record.confirmation_id, status="verified", result=result.model_dump(mode="json"), consume=True)
    for event_type in ("execution_completed", "verification_result"):
        repo.record_audit_event(
            confirmation_id=record.confirmation_id,
            workflow_id=record.workflow_id,
            session_id=record.session_id,
            customer_id=record.customer_id,
            event_type=event_type,
            detail=result.model_dump(mode="json"),
        )
    return result
