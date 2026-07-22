"""Request/response schemas for Scout's cart endpoints (Step 15).

`CartView`/`CartItemView` (scout/services/cart_service.py) are reused
directly as the response shape here - the same precedent
scout/api/schemas/chat.py already set by reusing `ProductSummary`
(scout/mcp/schemas.py) rather than re-declaring an identical model.
Only the *request* shapes are new: everything a client is allowed to
send for each cart mutation, with `extra="forbid"` so no request can
smuggle in a field like `unit_price` or `validation_status` that only
the server is ever allowed to decide.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout.services.cart_service import CartView  # noqa: F401  (re-exported for route type hints)

_MAX_MESSAGE_LENGTH = 500


def _non_blank(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty or whitespace-only")
    return stripped


class AddCartItemRequest(BaseModel):
    """Body for POST /cart/items."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    quantity: int = Field(default=1, ge=1)

    @field_validator("session_id", "product_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _non_blank(value)


class UpdateCartItemRequest(BaseModel):
    """Body for PATCH /cart/items/{cart_item_id}."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)

    @field_validator("session_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _non_blank(value)


class SetFulfillmentRequest(BaseModel):
    """Body for PUT /cart/{session_id}/fulfillment."""

    model_config = ConfigDict(extra="forbid")

    fulfillment_type: str = Field(min_length=1)
    """"pickup" or "delivery" - re-validated by cart_service, never
    trusted from request shape alone."""
    store_id: Optional[str] = Field(default=None)

    @field_validator("fulfillment_type")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("store_id")
    @classmethod
    def _optional_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return _non_blank(value)


class CartCommandRequest(BaseModel):
    """Body for POST /cart/{session_id}/command - the natural-language
    cart-command entry point (see scout/agents/cart_command_agent.py)."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_LENGTH)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _non_blank(value)


class CartCommandResponse(BaseModel):
    """Response for POST /cart/{session_id}/command."""

    interpreted_action: Optional[str] = None
    """A short, safe description of what Scout understood (e.g. "add 2
    x FTW-004") - never the raw command text echoed back as if it were
    an internal field, and never chain-of-thought."""
    clarification: Optional[str] = None
    """Set instead of mutating anything when the command could not be
    safely understood or the product reference was ambiguous."""
    cart: CartView
