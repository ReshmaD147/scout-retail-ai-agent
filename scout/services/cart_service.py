"""Deterministic cart business logic (Step 15).

Every cart mutation, price check, inventory check, and subtotal
calculation happens here, in plain Python re-reading the repositories -
never in an agent, never in the API layer, and never left to an LLM to
compute (CLAUDE.md section 3: "Scout must never invent... prices" and
"must never modify... inventory directly through an LLM"). Callers -
scout/api/routes/cart.py (REST) and scout/mcp/cart_tools.py (agent
tools) - both call these same functions and translate `CartServiceError`
into their own transport shape (an HTTP error body, or a structured
`ToolError`), so the validation rules exist exactly once.

Why every read recomputes price and inventory from scratch
------------------------------------------------------------
A cart_items row's `unit_price_snapshot` is the price at the moment a
product was added - kept only so a customer can be told "the price
changed since you added this." It is never the number shown as the
current unit price or used in the subtotal: every function below that
returns a `CartView` re-fetches the product's current price (via
scout.services.promotion_service.calculate_price, the same function the
rest of the codebase already trusts) and current inventory, exactly per
this phase's "always revalidate the current database price before
checkout" requirement. There is no separate cache to go stale - SQLite,
read fresh every call, is the only source of truth.

Two different inventory checks, on purpose
----------------------------------------------
- add_item/update_quantity check *network-wide* sellable inventory
  (scout.services.fulfillment_service.aggregate_network_availability) -
  a soft "does this even exist in enough quantity anywhere" ceiling,
  since a cart usually has no pickup store chosen yet.
- set_fulfillment (pickup) and get_cart_view/validate_cart (once a
  pickup store IS chosen) check that *specific store's* sellable
  inventory instead - the real, authoritative answer to "can I actually
  pick this up here."
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from scout.config import get_settings
from scout.repositories.cart_repository import CartRepository
from scout.repositories.inventory_repository import InventoryRepository
from scout.repositories.models import Cart, CartItem
from scout.repositories.product_repository import ProductRepository
from scout.repositories.promotion_repository import PromotionRepository
from scout.repositories.store_repository import StoreRepository
from scout.services import fulfillment_service, promotion_service
from scout.services.inventory_service import evaluate_availability


class CartServiceError(Exception):
    """Raised for exactly one invalid cart operation, always caught by
    the caller (an API route or an MCP tool) and translated into that
    layer's own structured error - never allowed to surface as a raw
    Python exception (mirrors scout/mcp/errors.py's ToolValidationError
    pattern, one layer lower, so both REST and MCP callers can reuse it).
    """

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        """A short, stable, machine-readable category, e.g.
        "product_not_found", "quantity_exceeds_maximum",
        "insufficient_inventory", "store_pickup_disabled",
        "store_cannot_fulfill", "cart_item_not_found"."""
        self.message = message


class CartItemView(BaseModel):
    """One cart line, with every value already revalidated against the
    current database - never the stale add-time snapshot."""

    cart_item_id: str
    product_id: str
    product_name: str
    brand: str
    quantity: int
    unit_price: float
    """The product's CURRENT verified price (after any currently-valid
    promotion) - always what the customer would actually pay right
    now, distinct from `unit_price_snapshot`."""
    unit_price_snapshot: float
    """The price recorded when this line was added - audit only, see
    the module docstring."""
    line_total: float
    promotion_id: Optional[str] = None
    promotion_label: Optional[str] = None
    active: bool
    warnings: List[str] = Field(default_factory=list)


class CartView(BaseModel):
    """The full, revalidated state of a session's cart.

    `cart_id` is None and `items` is empty when the session has no
    active cart yet - a normal state (nothing has been added), not an
    error; every mutation call creates a cart on first use.
    """

    cart_id: Optional[str] = None
    session_id: str
    items: List[CartItemView] = Field(default_factory=list)
    subtotal: float = 0.0
    fulfillment_type: Optional[str] = None
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    status: str = "active"
    validation_status: Literal["valid", "invalid"] = "valid"
    warnings: List[str] = Field(default_factory=list)
    updated_at: Optional[str] = None


def _build_view(cart: Cart, items: List[CartItem], db_path: Optional[str]) -> CartView:
    product_repo = ProductRepository(db_path)
    promotion_repo = PromotionRepository(db_path)
    inventory_repo = InventoryRepository(db_path)
    store_repo = StoreRepository(db_path)

    store = store_repo.get_by_id(cart.store_id) if cart.store_id else None

    item_views: List[CartItemView] = []
    cart_warnings: List[str] = []
    is_valid = True

    for item in items:
        product = product_repo.get_by_id(item.product_id)
        if product is None:
            # The product was removed from the catalog entirely after
            # being added - an extreme edge case, but still never
            # invented: report it plainly instead of guessing a price.
            item_views.append(
                CartItemView(
                    cart_item_id=item.cart_item_id,
                    product_id=item.product_id,
                    product_name="(no longer in catalog)",
                    brand="",
                    quantity=item.quantity,
                    unit_price=item.unit_price_snapshot,
                    unit_price_snapshot=item.unit_price_snapshot,
                    line_total=round(item.unit_price_snapshot * item.quantity, 2),
                    active=False,
                    warnings=["This product no longer exists in the catalog."],
                )
            )
            cart_warnings.append(f"{item.product_id} is no longer in the catalog.")
            is_valid = False
            continue

        promotions = promotion_repo.list_active(product_id=product.product_id)
        price_result = promotion_service.calculate_price(product, promotions)
        line_total = round(price_result.final_price * item.quantity, 2)

        warnings: List[str] = []
        if not product.active:
            warnings.append(f"{product.name} is no longer available for purchase.")
            is_valid = False
        if round(price_result.final_price, 2) != round(item.unit_price_snapshot, 2):
            warnings.append(
                f"The price for {product.name} has changed since it was added to your cart "
                f"(was ${item.unit_price_snapshot:.2f}, now ${price_result.final_price:.2f})."
            )

        if cart.fulfillment_type == "pickup" and cart.store_id:
            record = inventory_repo.get_for_product_and_store(product.product_id, cart.store_id)
            sellable = evaluate_availability(record).sellable_quantity
            if sellable < item.quantity:
                store_label = store.store_name if store else cart.store_id
                warnings.append(
                    f"Only {sellable} unit(s) of {product.name} available for pickup at "
                    f"{store_label}; your cart has {item.quantity}."
                )
                is_valid = False
        else:
            records = inventory_repo.list_for_product(product.product_id)
            network = fulfillment_service.aggregate_network_availability(records)
            if network.total_sellable_quantity < item.quantity:
                warnings.append(
                    f"Only {network.total_sellable_quantity} unit(s) of {product.name} available "
                    f"across Scout's store network; your cart has {item.quantity}."
                )
                is_valid = False

        promotion_label: Optional[str] = None
        if price_result.applied_promotion_id:
            matching = next(
                (p for p in promotions if p.promotion_id == price_result.applied_promotion_id), None
            )
            promotion_label = matching.label if matching else None

        item_views.append(
            CartItemView(
                cart_item_id=item.cart_item_id,
                product_id=product.product_id,
                product_name=product.name,
                brand=product.brand,
                quantity=item.quantity,
                unit_price=price_result.final_price,
                unit_price_snapshot=item.unit_price_snapshot,
                line_total=line_total,
                promotion_id=price_result.applied_promotion_id,
                promotion_label=promotion_label,
                active=product.active,
                warnings=warnings,
            )
        )
        cart_warnings.extend(warnings)

    if cart.fulfillment_type == "pickup" and cart.store_id:
        if store is None or not store.active or not store.pickup_enabled:
            cart_warnings.append("The selected pickup store is no longer available for pickup.")
            is_valid = False

    subtotal = round(sum(view.line_total for view in item_views), 2)

    return CartView(
        cart_id=cart.cart_id,
        session_id=cart.session_id,
        items=item_views,
        subtotal=subtotal,
        fulfillment_type=cart.fulfillment_type,
        store_id=cart.store_id,
        store_name=store.store_name if store else None,
        status=cart.status,
        validation_status="valid" if is_valid else "invalid",
        warnings=cart_warnings,
        updated_at=cart.updated_at,
    )


def get_cart_view(session_id: str, db_path: Optional[str] = None) -> CartView:
    """Return the session's cart, fully revalidated against current data.

    Never creates a cart as a side effect of reading - a session with
    no active cart yet gets back an empty CartView (cart_id=None), not
    a new row in the database.
    """
    cart = CartRepository(db_path).get_active_cart_by_session(session_id)
    if cart is None:
        return CartView(session_id=session_id)
    items = CartRepository(db_path).list_items(cart.cart_id)
    return _build_view(cart, items, db_path)


def validate_cart(session_id: str, db_path: Optional[str] = None) -> CartView:
    """An explicit revalidation pass before continuing (e.g. to checkout).

    Returns exactly what get_cart_view already computes fresh from the
    database on every call - there is no separate cache for this to
    invalidate. Kept as its own function (and its own endpoint/tool) so
    a caller preparing to check out has one explicit, self-documenting
    step to call, per this phase's own requirement, rather than having
    to know that GET already does the same work.
    """
    return get_cart_view(session_id, db_path)


def add_item(session_id: str, product_id: str, quantity: int, db_path: Optional[str] = None) -> CartView:
    """Add a product to the session's cart, merging into an existing
    line for the same product instead of creating a duplicate one.

    Raises:
        CartServiceError: "invalid_quantity" (quantity <= 0),
            "quantity_exceeds_maximum" (this add, combined with any
            existing quantity for the same product, exceeds
            settings.max_cart_item_quantity), "product_not_found",
            "product_inactive", or "insufficient_inventory" (fewer
            units are sellable across the store network than the
            resulting combined quantity would need).
    """
    if quantity <= 0:
        raise CartServiceError("invalid_quantity", "quantity must be greater than zero")

    settings = get_settings()
    product = ProductRepository(db_path).get_by_id(product_id)
    if product is None:
        raise CartServiceError("product_not_found", f"No product found with product_id={product_id!r}")
    if not product.active:
        raise CartServiceError("product_inactive", f"{product.name} is not currently available.")

    cart_repo = CartRepository(db_path)
    cart = cart_repo.get_active_cart_by_session(session_id) or cart_repo.create_cart(session_id)

    existing = cart_repo.get_item_by_product(cart.cart_id, product_id)
    combined_quantity = quantity + (existing.quantity if existing else 0)
    if combined_quantity > settings.max_cart_item_quantity:
        raise CartServiceError(
            "quantity_exceeds_maximum",
            f"quantity must not exceed {settings.max_cart_item_quantity} per product",
        )

    records = InventoryRepository(db_path).list_for_product(product_id)
    network = fulfillment_service.aggregate_network_availability(records)
    if network.total_sellable_quantity < combined_quantity:
        raise CartServiceError(
            "insufficient_inventory",
            f"Only {network.total_sellable_quantity} unit(s) of {product.name} are available.",
        )

    promotions = PromotionRepository(db_path).list_active(product_id=product_id)
    price_result = promotion_service.calculate_price(product, promotions)

    if existing is not None:
        cart_repo.update_item_quantity(existing.cart_item_id, combined_quantity)
    else:
        cart_repo.insert_item(
            cart.cart_id, product_id, quantity, price_result.final_price, price_result.applied_promotion_id
        )
    cart_repo.touch_cart(cart.cart_id)

    return get_cart_view(session_id, db_path)


def _get_owned_item(cart_repo: CartRepository, session_id: str, cart_item_id: str) -> CartItem:
    """Look up a cart item and confirm it belongs to this session's
    active cart, or raise "cart_item_not_found" for both "does not
    exist" and "belongs to a different session" - carts must stay
    isolated by session, and a caller must not be able to tell the
    difference between the two by probing IDs."""
    item = cart_repo.get_item(cart_item_id)
    if item is None:
        raise CartServiceError("cart_item_not_found", "No cart item found for this session.")
    cart = cart_repo.get_cart_by_id(item.cart_id)
    if cart is None or cart.session_id != session_id or cart.status != "active":
        raise CartServiceError("cart_item_not_found", "No cart item found for this session.")
    return item


def update_quantity(
    session_id: str, cart_item_id: str, quantity: int, db_path: Optional[str] = None
) -> CartView:
    """Overwrite a line item's quantity.

    Raises:
        CartServiceError: "invalid_quantity", "quantity_exceeds_maximum",
            "cart_item_not_found" (missing, or not owned by this
            session), or "insufficient_inventory".
    """
    if quantity <= 0:
        raise CartServiceError("invalid_quantity", "quantity must be greater than zero")

    settings = get_settings()
    if quantity > settings.max_cart_item_quantity:
        raise CartServiceError(
            "quantity_exceeds_maximum",
            f"quantity must not exceed {settings.max_cart_item_quantity} per product",
        )

    cart_repo = CartRepository(db_path)
    item = _get_owned_item(cart_repo, session_id, cart_item_id)

    product = ProductRepository(db_path).get_by_id(item.product_id)
    if product is None:
        raise CartServiceError("product_not_found", f"No product found with product_id={item.product_id!r}")

    records = InventoryRepository(db_path).list_for_product(item.product_id)
    network = fulfillment_service.aggregate_network_availability(records)
    if network.total_sellable_quantity < quantity:
        raise CartServiceError(
            "insufficient_inventory",
            f"Only {network.total_sellable_quantity} unit(s) of {product.name} are available.",
        )

    cart_repo.update_item_quantity(cart_item_id, quantity)
    cart_repo.touch_cart(item.cart_id)
    return get_cart_view(session_id, db_path)


def remove_item(session_id: str, cart_item_id: str, db_path: Optional[str] = None) -> CartView:
    """Remove one line item from the session's cart.

    Raises:
        CartServiceError: "cart_item_not_found" (missing, or not owned
            by this session).
    """
    cart_repo = CartRepository(db_path)
    item = _get_owned_item(cart_repo, session_id, cart_item_id)
    cart_repo.delete_item(cart_item_id)
    cart_repo.touch_cart(item.cart_id)
    return get_cart_view(session_id, db_path)


def clear_cart(session_id: str, db_path: Optional[str] = None) -> CartView:
    """Remove every item from the session's cart. A session with no
    active cart simply gets back an empty CartView - clearing nothing
    is not an error."""
    cart_repo = CartRepository(db_path)
    cart = cart_repo.get_active_cart_by_session(session_id)
    if cart is not None:
        cart_repo.delete_all_items(cart.cart_id)
        cart_repo.touch_cart(cart.cart_id)
    return get_cart_view(session_id, db_path)


def set_fulfillment(
    session_id: str,
    fulfillment_type: str,
    store_id: Optional[str],
    db_path: Optional[str] = None,
) -> CartView:
    """Record the customer's pickup-or-delivery choice.

    For "delivery": stores the preference only - no address is
    collected and no shipping total is calculated yet (Step 16's job).

    For "pickup": requires a store_id, and rejects the choice outright
    (raising, changing nothing) unless the store is active, pickup-
    enabled, AND has enough sellable inventory for every current cart
    item - "reject pickup when one item is unavailable" is enforced
    here, before the cart's fulfillment fields are ever written.

    Raises:
        CartServiceError: "invalid_fulfillment_type", "store_required",
            "store_not_found", "store_pickup_disabled", or
            "store_cannot_fulfill".
    """
    if fulfillment_type not in ("pickup", "delivery"):
        raise CartServiceError(
            "invalid_fulfillment_type", "fulfillment_type must be 'pickup' or 'delivery'"
        )

    cart_repo = CartRepository(db_path)
    cart = cart_repo.get_active_cart_by_session(session_id) or cart_repo.create_cart(session_id)

    if fulfillment_type == "delivery":
        cart_repo.set_fulfillment(cart.cart_id, "delivery", None)
        return get_cart_view(session_id, db_path)

    if not store_id:
        raise CartServiceError("store_required", "A store is required for pickup.")

    store = StoreRepository(db_path).get_by_id(store_id)
    if store is None:
        raise CartServiceError("store_not_found", f"No store found with store_id={store_id!r}")
    if not store.active or not store.pickup_enabled:
        raise CartServiceError(
            "store_pickup_disabled", f"{store.store_name} is not currently available for pickup."
        )

    inventory_repo = InventoryRepository(db_path)
    product_repo = ProductRepository(db_path)
    unavailable_names: List[str] = []
    for item in cart_repo.list_items(cart.cart_id):
        record = inventory_repo.get_for_product_and_store(item.product_id, store_id)
        sellable = evaluate_availability(record).sellable_quantity
        if sellable < item.quantity:
            product = product_repo.get_by_id(item.product_id)
            unavailable_names.append(product.name if product else item.product_id)

    if unavailable_names:
        raise CartServiceError(
            "store_cannot_fulfill",
            f"{store.store_name} cannot fulfill: {', '.join(unavailable_names)}.",
        )

    cart_repo.set_fulfillment(cart.cart_id, "pickup", store_id)
    return get_cart_view(session_id, db_path)
