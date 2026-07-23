"""Read-only Order Agent node for Step 17.

The agent calls approved MCP tools only. It never queries SQLite and never
performs cancellation, return, exchange, or refund writes.
"""

from __future__ import annotations

from typing import Any, Dict

from scout.mcp.order_tools import lookup_latest_order, lookup_order
from scout.orchestration.limits import check_step_budget
from scout.orchestration.state import EvidenceEntry, RetailGraphState, ToolCallTrace, WorkflowError


def _customer_answer(order, requested_action: str) -> str:
    fulfillment = order.fulfillment
    if fulfillment.fulfillment_type == "pickup":
        destination = fulfillment.store_name or fulfillment.store_id or "the selected store"
        estimate = (
            f" Estimated pickup readiness: {fulfillment.estimated_ready_at}."
            if fulfillment.estimated_ready_at
            else ""
        )
        fulfillment_text = f"Pickup at {destination} is {fulfillment.status}.{estimate}"
    else:
        estimate = (
            f" Estimated delivery: {fulfillment.estimated_delivery_at}."
            if fulfillment.estimated_delivery_at
            else ""
        )
        fulfillment_text = f"Delivery status is {fulfillment.status}.{estimate}"

    tracking_text = (
        f" Tracking: {fulfillment.tracking.carrier_name} {fulfillment.tracking.tracking_number}."
        if fulfillment.tracking.available
        else f" {fulfillment.tracking.message}"
    )
    payment_text = f" Payment status: {order.payment.status}."

    eligibility = order.eligibility
    eligibility_text = ""
    if requested_action == "cancel_eligibility":
        eligibility_text = (
            f" Cancellation eligibility: {'eligible' if eligibility.cancellation.eligible else 'not eligible'} — "
            f"{eligibility.cancellation.reason} No cancellation was performed."
        )
    elif requested_action == "return_eligibility":
        eligibility_text = (
            f" Return eligibility: {'eligible' if eligibility.return_eligibility.eligible else 'not eligible'} — "
            f"{eligibility.return_eligibility.reason} No return was created."
        )
    elif requested_action == "exchange_eligibility":
        eligibility_text = (
            f" Exchange eligibility: {'eligible' if eligibility.exchange.eligible else 'not eligible'} — "
            f"{eligibility.exchange.reason} No exchange was created."
        )

    return (
        f"Order {order.order_id} is {order.order_status}. "
        f"{fulfillment_text}{tracking_text}{payment_text}{eligibility_text}"
    ).strip()


def order_agent_node(state: RetailGraphState) -> Dict[str, Any]:
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    intent = state.intent or {}
    order_id = intent.get("order_id")
    requested_action = intent.get("order_action") or "status"
    result = lookup_order(order_id, state.session_id) if order_id else lookup_latest_order(state.session_id)
    tool_name = "lookup_order" if order_id else "lookup_latest_order"

    base: Dict[str, Any] = {
        "step_count": state.step_count + 1,
        "active_agent": "order",
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
                "tool_results": [
                    ToolCallTrace(tool_name=tool_name, status="error", summary=result.error.message)
                ],
                "errors": [
                    WorkflowError(
                        error_type=error_type,
                        message=result.error.message,
                        agent="order",
                        step="lookup_order",
                    )
                ],
            }
        )
        return base

    assert result.order is not None
    order = result.order
    base.update(
        {
            "workflow_status": "completed",
            "order_context": order.model_dump(mode="json"),
            "final_response": _customer_answer(order, requested_action),
            "completed_steps": ["order_lookup"],
            "tool_results": [
                ToolCallTrace(
                    tool_name=tool_name,
                    status="success",
                    summary=f"found order {order.order_id} with {order.fulfillment.status} fulfillment",
                )
            ],
            "evidence": [
                EvidenceEntry(
                    source=tool_name,
                    claim=f"Order {order.order_id} has order status {order.order_status}",
                    data={"order_id": order.order_id, "order_status": order.order_status},
                ),
                EvidenceEntry(
                    source=tool_name,
                    claim=f"Payment status is {order.payment.status}",
                    data={"status": order.payment.status, "amount": order.payment.amount, "currency": order.payment.currency},
                ),
                EvidenceEntry(
                    source=tool_name,
                    claim=f"Fulfillment status is {order.fulfillment.status}",
                    data={
                        "fulfillment_type": order.fulfillment.fulfillment_type,
                        "status": order.fulfillment.status,
                        "estimated_ready_at": order.fulfillment.estimated_ready_at,
                        "estimated_delivery_at": order.fulfillment.estimated_delivery_at,
                        "tracking_available": order.fulfillment.tracking.available,
                    },
                ),
            ],
        }
    )
    return base
