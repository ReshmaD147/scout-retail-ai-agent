"""Payment provider abstraction for deterministic Scout checkout.

This module deliberately never accepts card numbers or CVC. Mock mode stays
offline for tests; Stripe mode is test-only and uses PaymentIntents.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Protocol

from pydantic import BaseModel

from scout.config import get_settings


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


class PaymentIntentResult(BaseModel):
    provider: str
    provider_reference: str
    status: str
    amount: float
    currency: str
    client_secret: str
    publishable_key: str


class WebhookEvent(BaseModel):
    event_id: str
    event_type: str
    payment_intent_id: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    checkout_id: Optional[str] = None
    session_id: Optional[str] = None


class PaymentProvider(Protocol):
    def create_payment_intent(
        self,
        *,
        checkout_id: str,
        session_id: str,
        amount: float,
        currency: str,
        idempotency_key: str,
    ) -> PaymentIntentResult: ...

    def retrieve_payment_status(self, provider_reference: str) -> PaymentResult: ...

    def verify_webhook(self, payload: bytes, signature: Optional[str]) -> WebhookEvent: ...


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


def _amount_to_minor_units(amount: float) -> int:
    decimal_amount = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(decimal_amount * 100)


def _minor_units_to_amount(amount: int) -> float:
    return float((Decimal(amount) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _stripe_status(status: str) -> str:
    return {
        "requires_action": "payment_requires_action",
        "requires_confirmation": "payment_requires_action",
        "requires_payment_method": "payment_failed",
        "processing": "payment_processing",
        "succeeded": "payment_succeeded",
        "canceled": "payment_canceled",
    }.get(status, "payment_processing")


class StripeTestPaymentProvider:
    """Stripe PaymentIntent provider restricted to test-mode keys."""

    provider_name = "stripe_test"

    def __init__(
        self,
        *,
        secret_key: str,
        publishable_key: str,
        webhook_secret: Optional[str],
        stripe_module: Any = None,
    ) -> None:
        if not secret_key.startswith("sk_test_"):
            raise PaymentServiceError("stripe_configuration_error", "Stripe secret key must be a test key.")
        if not publishable_key.startswith("pk_test_"):
            raise PaymentServiceError("stripe_configuration_error", "Stripe publishable key must be a test key.")
        self.secret_key = secret_key
        self.publishable_key = publishable_key
        self.webhook_secret = webhook_secret
        if stripe_module is None:
            try:
                import stripe as stripe_module  # type: ignore[no-redef]
            except ImportError as exc:  # pragma: no cover - exercised only when dependency missing
                raise PaymentServiceError("stripe_unavailable", "Stripe SDK is not installed.") from exc
        self._stripe = stripe_module
        self._stripe.api_key = secret_key

    def create_payment_intent(
        self,
        *,
        checkout_id: str,
        session_id: str,
        amount: float,
        currency: str,
        idempotency_key: str,
    ) -> PaymentIntentResult:
        try:
            intent = self._stripe.PaymentIntent.create(
                amount=_amount_to_minor_units(amount),
                currency=currency.lower(),
                automatic_payment_methods={"enabled": True},
                metadata={"checkout_id": checkout_id, "session_id": session_id},
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001 - Stripe exceptions are provider-specific
            raise PaymentServiceError("payment_intent_failed", "Stripe could not create a test PaymentIntent.") from exc

        return PaymentIntentResult(
            provider=self.provider_name,
            provider_reference=str(intent["id"]),
            status=_stripe_status(str(intent["status"])),
            amount=amount,
            currency=currency.upper(),
            client_secret=str(intent["client_secret"]),
            publishable_key=self.publishable_key,
        )

    def retrieve_payment_status(self, provider_reference: str) -> PaymentResult:
        intent = self._stripe.PaymentIntent.retrieve(provider_reference)
        return PaymentResult(
            provider=self.provider_name,
            provider_reference=str(intent["id"]),
            status=str(intent["status"]),
            amount=_minor_units_to_amount(int(intent["amount"])),
            currency=str(intent["currency"]).upper(),
        )

    def verify_webhook(self, payload: bytes, signature: Optional[str]) -> WebhookEvent:
        if not self.webhook_secret:
            raise PaymentServiceError("stripe_configuration_error", "Stripe webhook secret is not configured.")
        if not signature:
            raise PaymentServiceError("invalid_webhook_signature", "Missing Stripe signature.")
        try:
            event = self._stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
        except Exception as exc:  # noqa: BLE001 - Stripe raises multiple signature/data errors
            raise PaymentServiceError("invalid_webhook_signature", "Invalid Stripe webhook signature.") from exc
        return _event_from_mapping(event)


def _event_from_mapping(event: Dict[str, Any]) -> WebhookEvent:
    data_object = event.get("data", {}).get("object", {})
    metadata = data_object.get("metadata") or {}
    return WebhookEvent(
        event_id=str(event.get("id", "")),
        event_type=str(event.get("type", "")),
        payment_intent_id=data_object.get("id"),
        status=data_object.get("status"),
        amount=_minor_units_to_amount(int(data_object["amount"])) if data_object.get("amount") is not None else None,
        currency=str(data_object.get("currency", "")).upper() if data_object.get("currency") else None,
        checkout_id=metadata.get("checkout_id"),
        session_id=metadata.get("session_id"),
    )


def get_payment_provider() -> PaymentProvider | MockPaymentAdapter:
    settings = get_settings()
    if settings.payment_provider == "stripe_test":
        return StripeTestPaymentProvider(
            secret_key=settings.stripe_secret_key or "",
            publishable_key=settings.stripe_publishable_key or "",
            webhook_secret=settings.stripe_webhook_secret,
        )
    return MockPaymentAdapter(settings.mock_payment_provider)
