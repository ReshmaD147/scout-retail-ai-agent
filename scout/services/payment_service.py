"""Local mock payment adapter for Step 16.

This module deliberately does not accept card numbers or call a real payment
network. It provides a deterministic test-mode boundary that has the same
shape a future Stripe adapter would implement: the checkout service passes a
server-computed amount, currency, and idempotency key; the adapter returns a
provider result or a safe decline.
"""

from __future__ import annotations

import hashlib
from pydantic import BaseModel


class PaymentServiceError(Exception):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class PaymentResult(BaseModel):
    provider: str
    provider_reference: str
    status: str
    amount: float
    currency: str


class MockPaymentAdapter:
    """A deterministic success/decline adapter used only for local testing."""

    SUCCESS_TOKEN = "mock_success"
    DECLINE_TOKEN = "mock_decline"

    def __init__(self, provider_name: str = "mock") -> None:
        self.provider_name = provider_name

    def charge(
        self,
        *,
        checkout_id: str,
        amount: float,
        currency: str,
        payment_method_token: str,
        idempotency_key: str,
    ) -> PaymentResult:
        token = payment_method_token.strip()
        if token == self.DECLINE_TOKEN:
            raise PaymentServiceError(
                "payment_declined",
                "The test payment was declined. No order was created and no inventory was reserved.",
            )
        if token != self.SUCCESS_TOKEN:
            raise PaymentServiceError(
                "invalid_payment_method",
                "Use the supported test payment method token 'mock_success'.",
            )

        digest = hashlib.sha256(
            f"{checkout_id}|{idempotency_key}|{amount:.2f}|{currency}".encode("utf-8")
        ).hexdigest()[:24]
        return PaymentResult(
            provider=self.provider_name,
            provider_reference=f"mock_{digest}",
            status="succeeded",
            amount=round(amount, 2),
            currency=currency,
        )
