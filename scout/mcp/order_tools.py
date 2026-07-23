"""Approved, deterministic, read-only Order Agent tools (Step 17)."""

from __future__ import annotations

from scout.mcp.schemas import (
    FulfillmentStatusToolResult,
    OrderEligibilityToolResult,
    OrderStatusToolResult,
    OrderToolResult,
    PaymentStatusToolResult,
    ToolError,
)
from scout.mcp.server import mcp_server
from scout.services import order_service
from scout.services.order_service import OrderServiceError


def _error(error_type: str, message: str) -> ToolError:
    return ToolError(error_type=error_type, message=message)


@mcp_server.tool()
def lookup_order(order_id: str, session_id: str) -> OrderToolResult:
    """Return the complete grounded status for one session-owned order."""
    try:
        return OrderToolResult(order=order_service.lookup_order(order_id, session_id))
    except OrderServiceError as exc:
        return OrderToolResult(error=_error(exc.error_type, exc.message))


@mcp_server.tool()
def lookup_latest_order(session_id: str) -> OrderToolResult:
    """Return the newest order created by the current shopping session."""
    try:
        return OrderToolResult(order=order_service.lookup_latest_order(session_id))
    except OrderServiceError as exc:
        return OrderToolResult(error=_error(exc.error_type, exc.message))


@mcp_server.tool()
def get_order_status(order_id: str, session_id: str) -> OrderStatusToolResult:
    """Return only the immutable order status."""
    result = lookup_order(order_id, session_id)
    if result.error:
        return OrderStatusToolResult(error=result.error)
    assert result.order is not None
    return OrderStatusToolResult(order_id=result.order.order_id, order_status=result.order.order_status)


@mcp_server.tool()
def get_payment_status(order_id: str, session_id: str) -> PaymentStatusToolResult:
    """Return the persisted mock-payment status for an order."""
    result = lookup_order(order_id, session_id)
    if result.error:
        return PaymentStatusToolResult(error=result.error)
    assert result.order is not None
    return PaymentStatusToolResult(order_id=result.order.order_id, payment=result.order.payment)


@mcp_server.tool()
def get_fulfillment_details(order_id: str, session_id: str) -> FulfillmentStatusToolResult:
    """Return pickup/delivery status, estimate, and available tracking facts."""
    result = lookup_order(order_id, session_id)
    if result.error:
        return FulfillmentStatusToolResult(error=result.error)
    assert result.order is not None
    return FulfillmentStatusToolResult(
        order_id=result.order.order_id,
        fulfillment=result.order.fulfillment,
    )


@mcp_server.tool()
def check_order_eligibility(order_id: str, session_id: str) -> OrderEligibilityToolResult:
    """Report cancellation/return/exchange eligibility without executing any action."""
    result = lookup_order(order_id, session_id)
    if result.error:
        return OrderEligibilityToolResult(error=result.error)
    assert result.order is not None
    return OrderEligibilityToolResult(
        order_id=result.order.order_id,
        eligibility=result.order.eligibility,
    )
