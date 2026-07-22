"""Request schemas for Step 16 checkout endpoints."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout.services.checkout_service import (
    CheckoutReview,
    OrderConfirmation,
    ShippingAddress,
)


def _trimmed(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty or whitespace-only")
    return stripped


class CreateCheckoutSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    shipping_address: ShippingAddress | None = None

    @field_validator("session_id")
    @classmethod
    def _session_not_blank(cls, value: str) -> str:
        return _trimmed(value)


class ConfirmCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=200)
    confirm_payment: bool
    payment_method_token: str = Field(default="mock_success", min_length=1, max_length=100)

    @field_validator("session_id", "idempotency_key", "payment_method_token")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _trimmed(value)


__all__ = [
    "CheckoutReview",
    "OrderConfirmation",
    "ShippingAddress",
    "CreateCheckoutSessionRequest",
    "ConfirmCheckoutRequest",
]
