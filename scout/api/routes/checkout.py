"""Thin REST routes for checkout, payment, and order confirmation."""

from fastapi import APIRouter, Header, Request

from scout.api.exceptions import ScoutAppError
from scout.api.schemas.checkout import (
    CheckoutPaymentIntent,
    CheckoutPaymentStatus,
    CheckoutReview,
    ConfirmCheckoutRequest,
    CreateCheckoutSessionRequest,
    CreatePaymentIntentRequest,
    OrderConfirmation,
)
from scout.services import checkout_service
from scout.services.checkout_service import CheckoutServiceError
from scout.services.payment_service import PaymentServiceError, get_payment_provider

router = APIRouter(prefix="/checkout", tags=["checkout"])

_ERROR_STATUS_CODES = {
    "validation_error": 400,
    "cart_not_found": 404,
    "cart_empty": 400,
    "cart_invalid": 409,
    "fulfillment_required": 400,
    "shipping_address_required": 400,
    "store_required": 400,
    "store_pickup_disabled": 409,
    "product_not_found": 404,
    "product_inactive": 409,
    "insufficient_inventory": 409,
    "checkout_not_found": 404,
    "checkout_not_confirmable": 409,
    "checkout_completed": 409,
    "checkout_processing": 409,
    "checkout_changed": 409,
    "cart_changed": 409,
    "inventory_changed": 409,
    "confirmation_required": 400,
    "idempotency_key_required": 400,
    "idempotency_conflict": 409,
    "payment_declined": 402,
    "invalid_payment_method": 400,
    "payment_provider_unavailable": 400,
    "stripe_configuration_error": 500,
    "stripe_unavailable": 500,
    "payment_intent_failed": 502,
    "invalid_webhook_signature": 400,
    "invalid_webhook_event": 400,
    "payment_amount_mismatch": 409,
    "payment_currency_mismatch": 409,
    "payment_checkout_mismatch": 409,
    "payment_session_mismatch": 409,
    "order_not_found": 404,
    "checkout_persistence_conflict": 409,
}


def _as_app_error(exc: CheckoutServiceError) -> ScoutAppError:
    return ScoutAppError(
        exc.message,
        status_code=_ERROR_STATUS_CODES.get(exc.error_type, 400),
        code=exc.error_type.upper(),
    )


@router.post("/sessions", response_model=CheckoutReview)
def create_checkout_session(request: CreateCheckoutSessionRequest) -> CheckoutReview:
    try:
        return checkout_service.create_checkout_review(
            request.session_id, shipping_address=request.shipping_address
        )
    except CheckoutServiceError as exc:
        raise _as_app_error(exc) from exc


@router.get("/sessions/{checkout_id}", response_model=CheckoutReview)
def get_checkout_session(checkout_id: str, session_id: str) -> CheckoutReview:
    try:
        return checkout_service.get_checkout_review(checkout_id, session_id)
    except CheckoutServiceError as exc:
        raise _as_app_error(exc) from exc


@router.post("/sessions/{checkout_id}/confirm", response_model=OrderConfirmation)
def confirm_checkout(checkout_id: str, request: ConfirmCheckoutRequest) -> OrderConfirmation:
    try:
        return checkout_service.confirm_checkout(
            checkout_id=checkout_id,
            session_id=request.session_id,
            idempotency_key=request.idempotency_key,
            confirm_payment=request.confirm_payment,
            payment_method_token=request.payment_method_token,
        )
    except CheckoutServiceError as exc:
        raise _as_app_error(exc) from exc


@router.post("/sessions/{checkout_id}/payment-intents", response_model=CheckoutPaymentIntent)
def create_payment_intent(checkout_id: str, request: CreatePaymentIntentRequest) -> CheckoutPaymentIntent:
    try:
        return checkout_service.create_checkout_payment_intent(
            checkout_id=checkout_id,
            session_id=request.session_id,
            idempotency_key=request.idempotency_key,
        )
    except CheckoutServiceError as exc:
        raise _as_app_error(exc) from exc


@router.get("/sessions/{checkout_id}/payment-status", response_model=CheckoutPaymentStatus)
def checkout_payment_status(checkout_id: str, session_id: str) -> CheckoutPaymentStatus:
    try:
        return checkout_service.get_checkout_payment_status(checkout_id, session_id)
    except CheckoutServiceError as exc:
        raise _as_app_error(exc) from exc


@router.post("/stripe/webhook", response_model=CheckoutPaymentStatus)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> CheckoutPaymentStatus:
    payload = await request.body()
    try:
        provider = get_payment_provider()
        if not hasattr(provider, "verify_webhook"):
            raise CheckoutServiceError("payment_provider_unavailable", "Stripe test payments are not enabled.")
        event = provider.verify_webhook(payload, stripe_signature)
        return checkout_service.complete_stripe_checkout_from_event(event)
    except PaymentServiceError as exc:
        raise _as_app_error(CheckoutServiceError(exc.error_type, exc.message)) from exc
    except CheckoutServiceError as exc:
        raise _as_app_error(exc) from exc
