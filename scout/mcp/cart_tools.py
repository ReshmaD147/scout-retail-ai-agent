"""Scout's approved MCP cart tools (Step 15).

Mirrors scout/mcp/product_tools.py's rationale for why agents get
tools, not database or service access: every tool below validates its
own arguments, calls exactly one scout.services.cart_service function,
and returns a structured CartToolResult - never a raw exception. These
are the same cart_service functions scout/api/routes/cart.py calls for
the REST API a browser talks to, so an agent and a customer's browser
are always validated by identical rules; nothing here re-implements or
loosens what that service already enforces.
"""

from typing import Optional

from scout.mcp.schemas import CartToolResult, ToolError
from scout.mcp.server import mcp_server
from scout.services import cart_service
from scout.services.cart_service import CartServiceError


def _ok(cart) -> CartToolResult:
    return CartToolResult(cart=cart, error=None)


def _failed(error_type: str, message: str) -> CartToolResult:
    return CartToolResult(cart=None, error=ToolError(error_type=error_type, message=message))


def _blank(value: str) -> bool:
    return not value or not value.strip()


@mcp_server.tool()
def add_to_cart(session_id: str, product_id: str, quantity: int = 1) -> CartToolResult:
    """Add a product to a session's cart.

    Input schema:
        session_id: Required, non-empty. Identifies the customer's cart.
        product_id: Required, non-empty.
        quantity: How many units to add (default 1). Combined with any
            existing quantity already in the cart for this product
            (duplicate adds merge instead of creating a second line).

    Output schema: CartToolResult(cart, error). `cart` is the full,
    revalidated CartView after the add.

    Error responses: error.error_type is one of "validation_error"
    (blank session_id/product_id), "product_not_found",
    "product_inactive", "quantity_exceeds_maximum", or
    "insufficient_inventory" (fewer units sellable across the store
    network than the resulting combined quantity would need).

    Service called: scout.services.cart_service.add_item() - see that
    function for every validation rule.
    """
    if _blank(session_id):
        return _failed("validation_error", "session_id must not be empty")
    if _blank(product_id):
        return _failed("validation_error", "product_id must not be empty")
    try:
        return _ok(cart_service.add_item(session_id, product_id, quantity))
    except CartServiceError as exc:
        return _failed(exc.error_type, exc.message)


@mcp_server.tool()
def get_cart(session_id: str) -> CartToolResult:
    """Retrieve a session's cart, fully revalidated against current data.

    Input schema:
        session_id: Required, non-empty.

    Output schema: CartToolResult(cart, error). `cart.items` is empty
    and `cart.cart_id` is None when the session has no active cart yet -
    a normal state, never an error.

    Service called: scout.services.cart_service.get_cart_view().
    """
    if _blank(session_id):
        return _failed("validation_error", "session_id must not be empty")
    return _ok(cart_service.get_cart_view(session_id))


@mcp_server.tool()
def update_cart_quantity(session_id: str, cart_item_id: str, quantity: int) -> CartToolResult:
    """Overwrite one cart line's quantity.

    Input schema:
        session_id: Required, non-empty. Must own `cart_item_id` - see
            error responses.
        cart_item_id: Required, non-empty.
        quantity: The new quantity. Must be greater than zero and no
            more than the configured per-product maximum.

    Output schema: CartToolResult(cart, error).

    Error responses: "validation_error", "invalid_quantity",
    "quantity_exceeds_maximum", "cart_item_not_found" (missing, or not
    owned by this session_id - carts stay isolated by session),
    "insufficient_inventory".

    Service called: scout.services.cart_service.update_quantity().
    """
    if _blank(session_id):
        return _failed("validation_error", "session_id must not be empty")
    if _blank(cart_item_id):
        return _failed("validation_error", "cart_item_id must not be empty")
    try:
        return _ok(cart_service.update_quantity(session_id, cart_item_id, quantity))
    except CartServiceError as exc:
        return _failed(exc.error_type, exc.message)


@mcp_server.tool()
def remove_from_cart(session_id: str, cart_item_id: str) -> CartToolResult:
    """Remove one line item from a session's cart.

    Input schema:
        session_id: Required, non-empty. Must own `cart_item_id`.
        cart_item_id: Required, non-empty.

    Output schema: CartToolResult(cart, error).

    Error responses: "validation_error", "cart_item_not_found"
    (missing, or not owned by this session_id).

    Service called: scout.services.cart_service.remove_item().
    """
    if _blank(session_id):
        return _failed("validation_error", "session_id must not be empty")
    if _blank(cart_item_id):
        return _failed("validation_error", "cart_item_id must not be empty")
    try:
        return _ok(cart_service.remove_item(session_id, cart_item_id))
    except CartServiceError as exc:
        return _failed(exc.error_type, exc.message)


@mcp_server.tool()
def clear_cart(session_id: str) -> CartToolResult:
    """Remove every item from a session's cart.

    Input schema:
        session_id: Required, non-empty.

    Output schema: CartToolResult(cart, error). A session with no
    active cart simply gets back an empty cart - clearing nothing is
    not an error.

    Service called: scout.services.cart_service.clear_cart().
    """
    if _blank(session_id):
        return _failed("validation_error", "session_id must not be empty")
    return _ok(cart_service.clear_cart(session_id))


@mcp_server.tool()
def set_fulfillment_method(
    session_id: str, fulfillment_type: str, store_id: Optional[str] = None
) -> CartToolResult:
    """Record the customer's pickup-or-delivery choice for a cart.

    Input schema:
        session_id: Required, non-empty.
        fulfillment_type: "pickup" or "delivery".
        store_id: Required when fulfillment_type is "pickup"; ignored
            for "delivery".

    Output schema: CartToolResult(cart, error).

    Error responses: "validation_error", "invalid_fulfillment_type",
    "store_required", "store_not_found", "store_pickup_disabled",
    "store_cannot_fulfill" (the chosen store lacks enough sellable
    inventory for at least one current cart item - nothing is changed
    when this happens; the cart keeps its previous fulfillment choice).

    Service called: scout.services.cart_service.set_fulfillment().
    """
    if _blank(session_id):
        return _failed("validation_error", "session_id must not be empty")
    try:
        return _ok(cart_service.set_fulfillment(session_id, fulfillment_type, store_id))
    except CartServiceError as exc:
        return _failed(exc.error_type, exc.message)


@mcp_server.tool()
def validate_cart(session_id: str) -> CartToolResult:
    """Explicitly revalidate a session's cart before continuing (e.g. to checkout).

    Input schema:
        session_id: Required, non-empty.

    Output schema: CartToolResult(cart, error). `cart.validation_status`
    is "valid" or "invalid"; `cart.warnings` lists every reason, in
    customer-safe language (a changed price, a product no longer
    active, insufficient inventory at the selected store).

    Service called: scout.services.cart_service.validate_cart() - the
    same revalidation get_cart also performs; kept as its own tool so
    an agent has an explicit "confirm this cart is still good" step.
    """
    if _blank(session_id):
        return _failed("validation_error", "session_id must not be empty")
    return _ok(cart_service.validate_cart(session_id))
