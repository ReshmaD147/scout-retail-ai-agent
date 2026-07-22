"""Cart command agent: turn a natural-language cart instruction into a
structured, deterministic CartCommand (Step 15).

Like scout/agents/understand_request.py, this is deterministic,
regex/keyword-based extraction, not a real LLM/Ollama call - this
codebase has no LLM integration yet (Phase 5 was explicitly left as a
documented, deterministic placeholder for real NLU), so cart command
parsing follows that same established precedent rather than
introducing a new, unapproved dependency for one feature. If real NLU
is added later, it only needs to replace `parse_cart_command`'s
implementation - callers already treat its output as untrusted intent
that scout/services/cart_service.py independently validates.

This module only ever extracts *what the customer seems to be asking
for* - which product, how many, which fulfillment choice. It never
decides whether that request is valid (product exists, quantity in
range, store can fulfill); that is exactly scout/services/cart_service.py's
job, and it is called separately, after parsing, by
scout/api/routes/cart.py's command endpoint.
"""

import re
from typing import Literal, Optional

from pydantic import BaseModel

from scout.services.product_reference_service import parse_ordinal

_NUMBER_GROUP = r"\d+|one|two|three|four|five|six|seven|eight|nine|ten"

_CLEAR_PATTERN = re.compile(r"\b(?:clear|empty)\b.*\bcart\b", re.IGNORECASE)
_PICKUP_WITH_STORE_PATTERN = re.compile(
    r"\bpickup\b.*?\bat\s+(?P<store>.+?)[.!?]*$", re.IGNORECASE
)
_PICKUP_PATTERN = re.compile(r"\bpickup\b", re.IGNORECASE)
_DELIVERY_PATTERN = re.compile(r"\bdelivery\b", re.IGNORECASE)
_QUANTITY_PATTERN = re.compile(
    rf"quantity(?:\s+of\s+(?:the\s+)?(?P<ref>.+?))?\s+to\s+(?P<qty>{_NUMBER_GROUP})\b",
    re.IGNORECASE,
)
_REMOVE_PATTERN = re.compile(
    r"^(?:remove|delete)\s+(?:the\s+)?(?P<ref>.+?)(?:\s+from\s+(?:my\s+)?cart)?[.!?]*$",
    re.IGNORECASE,
)
_ADD_PATTERN = re.compile(
    rf"\badd\s+(?:(?P<qty>{_NUMBER_GROUP})\s+(?:of\s+)?)?(?:the\s+)?(?P<ref>.+?)"
    r"(?:\s+to\s+(?:my\s+)?cart)?[.!?]*$",
    re.IGNORECASE,
)

CartAction = Literal["add", "update_quantity", "remove", "clear", "set_fulfillment", "unknown"]


class CartCommand(BaseModel):
    """Structured, UNVALIDATED intent parsed from one natural-language
    cart instruction. Every field here is a caller's raw request, not a
    confirmed fact - scout/services/cart_service.py (via
    scout/services/product_reference_service.py for product_reference)
    is what actually validates and executes it."""

    action: CartAction
    product_reference: Optional[str] = None
    """Free text naming a product (e.g. "first product", "the
    backpack") - resolved to a real product_id or cart_item_id by
    scout.services.product_reference_service.resolve_reference, never
    by this module."""
    quantity: Optional[int] = None
    fulfillment_type: Optional[str] = None
    store_reference: Optional[str] = None
    """Free text naming a store (e.g. "Maple Grove") - resolved to a
    real store_id by scout.mcp.store_tools.find_store_by_location,
    never by this module."""


def _resolve_number(raw: str) -> Optional[int]:
    if raw.isdigit():
        return int(raw)
    return parse_ordinal(raw)


def parse_cart_command(message: str) -> CartCommand:
    """Parse one free-text cart instruction into a CartCommand.

    Returns:
        A CartCommand with action="unknown" (every other field None) if
        the message does not match any recognized cart-command pattern -
        never a guess at what the customer might have meant.
    """
    text = message.strip()

    if _CLEAR_PATTERN.search(text):
        return CartCommand(action="clear")

    store_match = _PICKUP_WITH_STORE_PATTERN.search(text)
    if store_match:
        return CartCommand(
            action="set_fulfillment",
            fulfillment_type="pickup",
            store_reference=store_match.group("store").strip(),
        )
    if _PICKUP_PATTERN.search(text):
        return CartCommand(action="set_fulfillment", fulfillment_type="pickup")
    if _DELIVERY_PATTERN.search(text):
        return CartCommand(action="set_fulfillment", fulfillment_type="delivery")

    quantity_match = _QUANTITY_PATTERN.search(text)
    if quantity_match:
        quantity = _resolve_number(quantity_match.group("qty"))
        ref = quantity_match.group("ref")
        return CartCommand(
            action="update_quantity",
            quantity=quantity,
            product_reference=ref.strip() if ref else None,
        )

    remove_match = _REMOVE_PATTERN.match(text)
    if remove_match:
        return CartCommand(action="remove", product_reference=remove_match.group("ref").strip())

    add_match = _ADD_PATTERN.match(text)
    if add_match:
        raw_qty = add_match.group("qty")
        quantity = _resolve_number(raw_qty) if raw_qty else 1
        return CartCommand(
            action="add",
            quantity=quantity or 1,
            product_reference=add_match.group("ref").strip(),
        )

    return CartCommand(action="unknown")
