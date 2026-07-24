"""Read-only Order & Customer Support Agent.

The agent authenticates by requiring the active session_id and verifies
ownership by using approved session-scoped MCP order tools. It never
performs cancellation, return, exchange, refund, or complaint mutations.
"""

from __future__ import annotations

from typing import Any, Dict

from scout.mcp.order_tools import lookup_latest_order, lookup_order
from scout.orchestration.limits import check_step_budget
from scout.orchestration.state import EvidenceEntry, PendingConfirmation, RetailGraphState, ToolCallTrace, WorkflowError
from scout.services.protected_action_service import ProtectedActionError, ProtectedActionProposalRequest, propose_action
from scout.services.support_logging_service import create_support_case_if_needed

_POLICY_NEEDED_ACTIONS = {"missing_package", "return_eligibility", "refund_status", "return_request_status"}
_PROTECTED_ACTIONS = {
    "cancel_order",
    "create_return_request",
    "create_exchange_request",
    "change_order_address",
    "create_refund_request",
}


def _tracking_text(order) -> str:
    tracking = order.fulfillment.tracking
    return (
        f"Tracking: {tracking.carrier_name} {tracking.tracking_number}."
        if tracking.available
        else tracking.message
    )


def _eligibility_text(order, requested_action: str) -> str:
    eligibility = order.eligibility
    if requested_action == "cancel_eligibility":
        return (
            f"Cancellation eligibility: {'eligible' if eligibility.cancellation.eligible else 'not eligible'} — "
            f"{eligibility.cancellation.reason} No cancellation was performed."
        )
    if requested_action == "return_eligibility":
        return (
            f"Return eligibility: {'eligible' if eligibility.return_eligibility.eligible else 'not eligible'} — "
            f"{eligibility.return_eligibility.reason} No return was created."
        )
    if requested_action == "exchange_eligibility":
        return (
            f"Exchange eligibility: {'eligible' if eligibility.exchange.eligible else 'not eligible'} — "
            f"{eligibility.exchange.reason} No exchange was created."
        )
    return ""


def _policy_query_for_action(requested_action: str) -> str | None:
    if requested_action == "missing_package":
        return "What happens when a package is marked delivered but is missing?"
    if requested_action in {"return_eligibility", "return_request_status"}:
        return "What is the return window?"
    if requested_action == "refund_status":
        return "How long do refunds normally take?"
    return None


def _customer_answer(order, requested_action: str) -> str:
    fulfillment = order.fulfillment
    if fulfillment.fulfillment_type == "pickup":
        destination = fulfillment.store_name or fulfillment.store_id or "the selected store"
        estimate = f" Estimated pickup readiness: {fulfillment.estimated_ready_at}." if fulfillment.estimated_ready_at else ""
        fulfillment_text = f"Pickup at {destination} is {fulfillment.status}.{estimate}"
    else:
        estimate = f" Estimated delivery: {fulfillment.estimated_delivery_at}." if fulfillment.estimated_delivery_at else ""
        fulfillment_text = f"Delivery status is {fulfillment.status}.{estimate}"

    base = f"Order {order.order_id} is {order.order_status}. {fulfillment_text} {_tracking_text(order)} Payment status: {order.payment.status}."
    eligibility = _eligibility_text(order, requested_action)
    if eligibility:
        return f"{base} {eligibility}".strip()
    if requested_action == "shipment_status":
        return f"{base} Shipment status: {fulfillment.status}.".strip()
    if requested_action == "refund_status":
        return (
            f"{base} I do not see a verified refund record in the current read-only order evidence. "
            "No refund was created or changed."
        ).strip()
    if requested_action == "return_request_status":
        return (
            f"{base} I do not see a verified return-request record in the current read-only order evidence. "
            "No return request was created or changed."
        ).strip()
    if requested_action == "missing_package":
        return (
            f"{base} For a missing-package concern, I verified the order and shipment evidence first. "
            "No replacement, refund, or investigation was opened."
        ).strip()
    if requested_action == "complaint_investigation":
        return (
            f"{base} I can summarize the current order evidence, but I do not see a verified complaint investigation record in this read-only flow. "
            "No complaint investigation was opened or changed."
        ).strip()
    return base.strip()


def _order_claims(order, requested_action: str, session_id: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = [
        {"type": "order_ownership", "order_id": order.order_id, "session_id": session_id},
        {"type": "order_status", "order_id": order.order_id, "session_id": session_id, "order_status": order.order_status},
        {"type": "payment_status", "order_id": order.order_id, "session_id": session_id, "payment_status": order.payment.status},
        {"type": "tracking_status", "order_id": order.order_id, "session_id": session_id, "tracking_status": order.fulfillment.tracking.message},
    ]
    eligibility_map = {
        "cancel_eligibility": ("cancellation", order.eligibility.cancellation.eligible),
        "return_eligibility": ("return", order.eligibility.return_eligibility.eligible),
        "exchange_eligibility": ("exchange", order.eligibility.exchange.eligible),
    }
    if requested_action in eligibility_map:
        eligibility_type, eligible = eligibility_map[requested_action]
        claims.append(
            {
                "type": "eligibility",
                "order_id": order.order_id,
                "session_id": session_id,
                "eligibility_type": eligibility_type,
                "eligible": eligible,
            }
        )
    return claims


def order_agent_node(state: RetailGraphState) -> Dict[str, Any]:
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    if not state.session_id:
        return {
            "step_count": state.step_count + 1,
            "workflow_status": "failed",
            "active_agent": "order",
            "current_agent": "order_agent",
            "final_response": "Please start an authenticated shopping session before asking about private order details.",
            "errors": [WorkflowError(error_type="unauthorized", message="session authentication is required", agent="order", step="authenticate_session")],
            "tool_results": [ToolCallTrace(tool_name="authenticate_session", status="error", summary="session authentication is required")],
        }

    intent = state.intent or {}
    order_id = intent.get("order_id")
    requested_action = intent.get("order_action") or "status"
    result = lookup_order(order_id, state.session_id) if order_id else lookup_latest_order(state.session_id)
    tool_name = "lookup_order" if order_id else "lookup_latest_order"

    base: Dict[str, Any] = {
        "step_count": state.step_count + 1,
        "active_agent": "order",
        "current_agent": "order_agent",
        "next_agent": None,
        "pending_steps": [],
    }

    if result.error is not None:
        error_type = "not_found" if result.error.error_type == "order_not_found" else "validation_error"
        base.update(
            {
                "workflow_status": "completed",
                "order_context": None,
                "final_response": result.error.message,
                "tool_results": [ToolCallTrace(tool_name=tool_name, status="error", summary=result.error.message)],
                "errors": [WorkflowError(error_type=error_type, message=result.error.message, agent="order", step="verify_order_ownership")],
            }
        )
        return base

    assert result.order is not None
    order = result.order
    if requested_action in _PROTECTED_ACTIONS:
        try:
            proposal = propose_action(
                ProtectedActionProposalRequest(
                    session_id=state.session_id,
                    customer_id=state.user_id or state.session_id,
                    workflow_id=state.workflow_id,
                    action_type=requested_action,
                    order_id=order.order_id,
                )
            )
        except ProtectedActionError as exc:
            base.update(
                {
                    "workflow_status": "completed",
                    "order_context": order.model_dump(mode="json"),
                    "final_response": exc.message,
                    "tool_results": [ToolCallTrace(tool_name="create_protected_action_proposal", status="error", summary=exc.message)],
                    "errors": [WorkflowError(error_type="validation_error", message=exc.message, agent="order", step="protected_action_proposal")],
                }
            )
            return base
        return {
            **base,
            "workflow_status": "awaiting_confirmation",
            "order_context": order.model_dump(mode="json"),
            "final_response": proposal.proposal_summary,
            "pending_confirmation": PendingConfirmation(
                confirmation_id=proposal.confirmation_id,
                workflow_id=proposal.workflow_id,
                request_id=proposal.request_id,
                action_type=proposal.action_type,
                description=proposal.proposal_summary,
                target_id=proposal.resource_id,
                resource_type=proposal.resource_type,
                customer_effects=proposal.customer_effects,
                financial_effects=proposal.financial_effects,
                eligibility_status=proposal.eligibility_status,
                eligibility_reason_code=proposal.eligibility_reason_code,
                expires_at=proposal.expires_at,
                requested_at=proposal.created_at,
            ),
            "tool_results": [
                ToolCallTrace(
                    tool_name="create_protected_action_proposal",
                    status="success",
                    summary=f"created confirmation proposal for {requested_action}",
                    validated_arguments={"session_id": state.session_id, "order_id": order.order_id},
                )
            ],
        }
    final_response = _customer_answer(order, requested_action)
    updated_intent = dict(intent)
    policy_query = _policy_query_for_action(requested_action)
    if policy_query:
        updated_intent["policy_query"] = policy_query
        updated_intent["needs_policy"] = True

    support_case = create_support_case_if_needed(
        session_id=state.session_id,
        workflow_id=state.workflow_id,
        query=state.customer_query,
        order_id=order.order_id,
        order_action=requested_action,
    )
    response_with_case = (
        f"{final_response} I created support case {support_case['case_reference']} for follow-up."
        if support_case is not None
        else final_response
    )

    base.update(
        {
            "workflow_status": "in_progress",
            "intent": updated_intent,
            "order_context": order.model_dump(mode="json"),
            "final_response": response_with_case,
            "completed_steps": ["order_lookup"],
            "proposed_claims": _order_claims(order, requested_action, state.session_id),
            "tool_results": [
                ToolCallTrace(
                    tool_name=tool_name,
                    status="success",
                    summary=f"verified session ownership for order {order.order_id} with {order.fulfillment.status} fulfillment",
                    validated_arguments={"session_id": state.session_id, "order_id": order_id} if order_id else {"session_id": state.session_id},
                )
            ],
            "evidence": [
                EvidenceEntry(source=tool_name, claim=f"Order {order.order_id} belongs to this authenticated session", data={"order_id": order.order_id, "session_id": state.session_id}),
                EvidenceEntry(source=tool_name, claim=f"Order {order.order_id} has order status {order.order_status}", data={"order_id": order.order_id, "order_status": order.order_status}),
                EvidenceEntry(source=tool_name, claim=f"Payment status is {order.payment.status}", data={"status": order.payment.status, "amount": order.payment.amount, "currency": order.payment.currency}),
                EvidenceEntry(source=tool_name, claim=f"Fulfillment status is {order.fulfillment.status}", data={"fulfillment_type": order.fulfillment.fulfillment_type, "status": order.fulfillment.status, "estimated_ready_at": order.fulfillment.estimated_ready_at, "estimated_delivery_at": order.fulfillment.estimated_delivery_at, "tracking_available": order.fulfillment.tracking.available}),
                *([EvidenceEntry(source="create_support_case", claim=f"Support case {support_case['case_reference']} was created for controlled follow-up", data=support_case)] if support_case is not None else []),
            ],
        }
    )
    return base
