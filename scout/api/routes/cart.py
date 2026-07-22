"""Cart API routes (Step 15).

Kept as thin as scout/api/routes/chat.py: every route validates its
request shape (Pydantic), calls exactly one scout.services.cart_service
function, and maps the result - or a raised CartServiceError - to an
HTTP response. No pricing, inventory, or validation rule lives here;
see that module for all of it. The one exception is the natural-
language `/command` endpoint, which additionally calls
scout.agents.cart_command_agent (parsing only) and
scout.services.product_reference_service (resolving "the first
product" to a real ID) before handing off to the exact same
cart_service functions every other route uses - a command never
bypasses any validation a button-driven request would have gone
through.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter

from scout.agents.cart_command_agent import CartCommand, parse_cart_command
from scout.api.exceptions import ScoutAppError
from scout.api.schemas.cart import (
    AddCartItemRequest,
    CartCommandRequest,
    CartCommandResponse,
    SetFulfillmentRequest,
    UpdateCartItemRequest,
)
from scout.mcp.store_tools import find_store_by_location
from scout.repositories.cart_repository import CartRepository
from scout.repositories.product_repository import ProductRepository
from scout.repositories.recommendation_reference_repository import RecommendationReferenceRepository
from scout.services import cart_service
from scout.services.cart_service import CartServiceError, CartView
from scout.services.product_reference_service import (
    NamedCandidate,
    ProductReferenceResolution,
    resolve_reference,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cart", tags=["cart"])

_ERROR_STATUS_CODES = {
    "product_not_found": 404,
    "cart_item_not_found": 404,
    "store_not_found": 404,
    "product_inactive": 400,
    "invalid_quantity": 400,
    "quantity_exceeds_maximum": 400,
    "insufficient_inventory": 400,
    "invalid_fulfillment_type": 400,
    "store_required": 400,
    "store_pickup_disabled": 400,
    "store_cannot_fulfill": 400,
}
"""Every scout.services.cart_service.CartServiceError.error_type this
API knows how to translate into an HTTP status code. Anything not
listed here (there should be nothing) falls back to 400 rather than
ever leaking a 500 for what is really a validation problem."""


def _as_app_error(exc: CartServiceError) -> ScoutAppError:
    status_code = _ERROR_STATUS_CODES.get(exc.error_type, 400)
    return ScoutAppError(exc.message, status_code=status_code, code=exc.error_type.upper())


@router.post("/items", response_model=CartView)
def add_cart_item(request: AddCartItemRequest) -> CartView:
    try:
        return cart_service.add_item(request.session_id, request.product_id, request.quantity)
    except CartServiceError as exc:
        raise _as_app_error(exc) from exc


@router.get("/{session_id}", response_model=CartView)
def get_cart(session_id: str) -> CartView:
    return cart_service.get_cart_view(session_id)


@router.patch("/items/{cart_item_id}", response_model=CartView)
def update_cart_item(cart_item_id: str, request: UpdateCartItemRequest) -> CartView:
    try:
        return cart_service.update_quantity(request.session_id, cart_item_id, request.quantity)
    except CartServiceError as exc:
        raise _as_app_error(exc) from exc


@router.delete("/items/{cart_item_id}", response_model=CartView)
def remove_cart_item(cart_item_id: str, session_id: str) -> CartView:
    """`session_id` is a required query parameter (not part of the
    path) purely so this DELETE, which has no body, still has a way to
    prove ownership - see scout.services.cart_service._get_owned_item
    for the isolation check itself."""
    try:
        return cart_service.remove_item(session_id, cart_item_id)
    except CartServiceError as exc:
        raise _as_app_error(exc) from exc


@router.delete("/{session_id}", response_model=CartView)
def clear_cart(session_id: str) -> CartView:
    return cart_service.clear_cart(session_id)


@router.put("/{session_id}/fulfillment", response_model=CartView)
def set_fulfillment(session_id: str, request: SetFulfillmentRequest) -> CartView:
    try:
        return cart_service.set_fulfillment(session_id, request.fulfillment_type, request.store_id)
    except CartServiceError as exc:
        raise _as_app_error(exc) from exc


@router.post("/{session_id}/validate", response_model=CartView)
def validate_cart(session_id: str) -> CartView:
    return cart_service.validate_cart(session_id)


def _resolve_recommendation_reference(session_id: str, reference_text: Optional[str]) -> ProductReferenceResolution:
    """Resolve an "add"-command's product reference against the
    session's last verified recommendation list - never against the
    current cart (see the module docstring for why these differ)."""
    snapshot = RecommendationReferenceRepository().get(session_id)
    candidates: List[NamedCandidate] = (
        [NamedCandidate(reference_id=entry["product_id"], name=entry["name"]) for entry in snapshot.products]
        if snapshot is not None
        else []
    )
    return resolve_reference(reference_text or "", candidates)


def _resolve_cart_item_reference(session_id: str, reference_text: Optional[str]) -> ProductReferenceResolution:
    """Resolve an "update"/"remove"-command's product reference against
    the session's current cart items - never the recommendation list."""
    cart = CartRepository().get_active_cart_by_session(session_id)
    items = CartRepository().list_items(cart.cart_id) if cart is not None else []

    if not items:
        return ProductReferenceResolution(clarification="Your cart is empty - there is nothing to change.")

    if not reference_text:
        if len(items) == 1:
            return ProductReferenceResolution(reference_id=items[0].cart_item_id)
        names = ", ".join(_product_name(item.product_id) for item in items)
        return ProductReferenceResolution(
            clarification=f"Your cart has more than one item ({names}). Which one did you mean?"
        )

    candidates = [
        NamedCandidate(reference_id=item.cart_item_id, name=_product_name(item.product_id)) for item in items
    ]
    return resolve_reference(reference_text, candidates)


def _product_name(product_id: str) -> str:
    product = ProductRepository().get_by_id(product_id)
    return product.name if product is not None else product_id


def _resolve_pickup_store(session_id: str, command: CartCommand) -> ProductReferenceResolution:
    """Resolve a set-fulfillment command's store reference. Reuses
    find_store_by_location (scout/mcp/store_tools.py) - the same
    grounded lookup understand_request_node already trusts - rather
    than a second, independent store-matching implementation."""
    if command.store_reference:
        result = find_store_by_location(command.store_reference)
        if result.error is not None or result.store_id is None:
            return ProductReferenceResolution(
                clarification=f"I couldn't find a store matching {command.store_reference!r}."
            )
        return ProductReferenceResolution(reference_id=result.store_id)

    existing = cart_service.get_cart_view(session_id)
    if existing.store_id:
        return ProductReferenceResolution(reference_id=existing.store_id)
    return ProductReferenceResolution(clarification="Which store would you like to pick up from?")


@router.post("/{session_id}/command", response_model=CartCommandResponse)
def cart_command(session_id: str, request: CartCommandRequest) -> CartCommandResponse:
    """Understand one natural-language cart instruction and execute it.

    See scout/agents/cart_command_agent.py for parsing (deterministic,
    not an LLM call - see that module's docstring) and
    scout/services/product_reference_service.py for how a phrase like
    "the first product" or "the backpack" resolves to a real ID, or
    produces a clarification instead of a guess.
    """
    command = parse_cart_command(request.message)

    if command.action == "unknown":
        return CartCommandResponse(
            clarification=(
                'I couldn\'t understand that cart instruction. Try things like "add the '
                'first product to my cart", "remove the backpack", "change the quantity '
                'to three", or "switch to delivery".'
            ),
            cart=cart_service.get_cart_view(session_id),
        )

    try:
        if command.action == "add":
            resolution = _resolve_recommendation_reference(session_id, command.product_reference)
            if resolution.clarification or resolution.reference_id is None:
                return CartCommandResponse(
                    clarification=resolution.clarification, cart=cart_service.get_cart_view(session_id)
                )
            quantity = command.quantity or 1
            cart = cart_service.add_item(session_id, resolution.reference_id, quantity)
            return CartCommandResponse(interpreted_action=f"add {quantity} x {resolution.reference_id}", cart=cart)

        if command.action in ("update_quantity", "remove"):
            resolution = _resolve_cart_item_reference(session_id, command.product_reference)
            if resolution.clarification or resolution.reference_id is None:
                return CartCommandResponse(
                    clarification=resolution.clarification, cart=cart_service.get_cart_view(session_id)
                )
            if command.action == "update_quantity":
                quantity = command.quantity or 1
                cart = cart_service.update_quantity(session_id, resolution.reference_id, quantity)
                return CartCommandResponse(interpreted_action=f"update quantity to {quantity}", cart=cart)
            cart = cart_service.remove_item(session_id, resolution.reference_id)
            return CartCommandResponse(interpreted_action="remove item", cart=cart)

        if command.action == "clear":
            cart = cart_service.clear_cart(session_id)
            return CartCommandResponse(interpreted_action="clear cart", cart=cart)

        # command.action == "set_fulfillment"
        if command.fulfillment_type == "delivery":
            cart = cart_service.set_fulfillment(session_id, "delivery", None)
            return CartCommandResponse(interpreted_action="set fulfillment to delivery", cart=cart)

        store_resolution = _resolve_pickup_store(session_id, command)
        if store_resolution.clarification or store_resolution.reference_id is None:
            return CartCommandResponse(
                clarification=store_resolution.clarification, cart=cart_service.get_cart_view(session_id)
            )
        cart = cart_service.set_fulfillment(session_id, "pickup", store_resolution.reference_id)
        return CartCommandResponse(interpreted_action="set fulfillment to pickup", cart=cart)

    except CartServiceError as exc:
        raise _as_app_error(exc) from exc
