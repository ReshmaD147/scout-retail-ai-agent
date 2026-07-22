"""Approved MCP tools for Step 16 checkout.

Tools expose the same deterministic checkout_service functions used by the
REST API. They never accept client-calculated totals and never expose raw SQL
or payment credentials to an agent.
"""

from typing import Any, Dict, Optional

from pydantic import ValidationError

from scout.mcp.schemas import CheckoutToolResult, ToolError
from scout.mcp.server import mcp_server
from scout.services import checkout_service
from scout.services.checkout_service import CheckoutServiceError, ShippingAddress


def _failed(error_type: str, message: str) -> CheckoutToolResult:
    return CheckoutToolResult(error=ToolError(error_type=error_type, message=message))


@mcp_server.tool()
def create_checkout_review(
    session_id: str, shipping_address: Optional[Dict[str, Any]] = None
) -> CheckoutToolResult:
    """Create a server-calculated checkout review for a cart.

    `shipping_address` is required only when the cart uses delivery. Totals
    come from current catalog, promotion, and inventory facts; an agent cannot
    supply or override them.
    """
    if not session_id or not session_id.strip():
        return _failed("validation_error", "session_id must not be empty")
    try:
        address = ShippingAddress.model_validate(shipping_address) if shipping_address else None
        review = checkout_service.create_checkout_review(session_id, address)
        return CheckoutToolResult(review=review)
    except ValidationError:
        return _failed("validation_error", "shipping_address is invalid")
    except CheckoutServiceError as exc:
        return _failed(exc.error_type, exc.message)


@mcp_server.tool()
def confirm_checkout(
    checkout_id: str,
    session_id: str,
    idempotency_key: str,
    confirm_payment: bool,
    payment_method_token: str = "mock_success",
) -> CheckoutToolResult:
    """Explicitly confirm a reviewed checkout and create one idempotent order."""
    if not checkout_id or not checkout_id.strip():
        return _failed("validation_error", "checkout_id must not be empty")
    if not session_id or not session_id.strip():
        return _failed("validation_error", "session_id must not be empty")
    try:
        order = checkout_service.confirm_checkout(
            checkout_id=checkout_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            confirm_payment=confirm_payment,
            payment_method_token=payment_method_token,
        )
        return CheckoutToolResult(order=order)
    except CheckoutServiceError as exc:
        return _failed(exc.error_type, exc.message)
