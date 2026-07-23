"""Deterministic checkout and order creation for Scout Step 16.

The service owns every business decision: revalidating the active cart,
requiring fulfillment details, calculating money with Decimal, allocating
inventory, requiring explicit payment confirmation, and enforcing checkout
snapshot/idempotency rules. SQL remains in CheckoutRepository, and the mock
payment boundary remains in payment_service.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout.config import get_settings
from scout.repositories.cart_repository import CartRepository
from scout.repositories.checkout_repository import (
    CheckoutCommitPlan,
    CheckoutRepository,
    CheckoutRepositoryConflict,
    CheckoutSessionWrite,
    OrderItemWrite,
    PaymentWrite,
    ReservationWrite,
)
from scout.repositories.inventory_repository import InventoryRepository
from scout.repositories.product_repository import ProductRepository
from scout.repositories.promotion_repository import PromotionRepository
from scout.repositories.store_repository import StoreRepository
from scout.services import cart_service, promotion_service
from scout.services.inventory_service import evaluate_availability
from scout.services.payment_service import (
    MockPaymentAdapter,
    PaymentIntentResult,
    PaymentResult,
    PaymentServiceError,
    WebhookEvent,
    get_payment_provider,
)

_MONEY = Decimal("0.01")


class CheckoutServiceError(Exception):
    """Safe, structured checkout failure translated by API/MCP callers."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class ShippingAddress(BaseModel):
    """Delivery address accepted by the prototype checkout.

    The model intentionally contains no payment credential. All strings are
    trimmed, and extra fields are rejected so a client cannot smuggle card
    data or server-owned totals into the request.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=100)
    line1: str = Field(min_length=1, max_length=150)
    line2: Optional[str] = Field(default=None, max_length=150)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=2, max_length=50)
    postal_code: str = Field(min_length=3, max_length=20)
    country: str = Field(default="US", min_length=2, max_length=2)

    @field_validator("full_name", "line1", "city", "state", "postal_code", "country")
    @classmethod
    def _required_trimmed(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("line2")
    @classmethod
    def _optional_trimmed(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("country")
    @classmethod
    def _country_upper(cls, value: str) -> str:
        return value.upper()


class CheckoutLineReview(BaseModel):
    product_id: str
    product_name: str
    brand: str
    quantity: int
    catalog_unit_price: float
    charged_unit_price: float
    line_subtotal: float
    discount_total: float
    line_total: float
    promotion_id: Optional[str] = None
    promotion_label: Optional[str] = None


class CheckoutReview(BaseModel):
    checkout_id: str
    session_id: str
    cart_id: str
    cart_updated_at: Optional[str]
    status: str = "review"
    fulfillment_type: str
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    shipping_address: Optional[ShippingAddress] = None
    items: List[CheckoutLineReview]
    subtotal: float
    discount_total: float
    merchandise_total: float
    tax_rate: float
    tax_total: float
    shipping_total: float
    total: float
    currency: str
    payment_provider: str = "mock"
    warnings: List[str] = Field(default_factory=list)


class CheckoutPaymentIntent(BaseModel):
    checkout_id: str
    session_id: str
    status: str
    provider: str
    provider_reference: str
    client_secret: str
    publishable_key: str
    amount: float
    currency: str


class CheckoutPaymentStatus(BaseModel):
    checkout_id: str
    status: str
    order_id: Optional[str] = None


class InventoryReservationSummary(BaseModel):
    store_id: str
    store_name: Optional[str] = None
    quantity: int
    status: str


class OrderItemConfirmation(BaseModel):
    order_item_id: str
    product_id: str
    product_name: str
    brand: str
    quantity: int
    catalog_unit_price: float
    charged_unit_price: float
    line_subtotal: float
    discount_total: float
    line_total: float
    promotion_id: Optional[str] = None
    promotion_label: Optional[str] = None
    reservations: List[InventoryReservationSummary] = Field(default_factory=list)


class PaymentConfirmation(BaseModel):
    provider: str
    provider_reference: str
    status: str
    amount: float
    currency: str


class OrderConfirmation(BaseModel):
    order_id: str
    checkout_id: str
    session_id: str
    status: str
    fulfillment_type: str
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    shipping_address: Optional[ShippingAddress] = None
    items: List[OrderItemConfirmation]
    subtotal: float
    discount_total: float
    merchandise_total: float
    tax_total: float
    shipping_total: float
    total: float
    currency: str
    payment: PaymentConfirmation
    created_at: str


@dataclass(frozen=True)
class _Allocation:
    product_id: str
    store_id: str
    quantity: int


def _decimal(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _as_float(value: Decimal) -> float:
    return float(_money(value))


def _review_hash(review: CheckoutReview) -> str:
    """Hash only customer-confirmed facts, excluding generated checkout status."""
    payload = review.model_dump(mode="json", exclude={"checkout_id", "status"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plan_allocations(
    *,
    fulfillment_type: str,
    store_id: Optional[str],
    item_quantities: Dict[str, int],
    db_path: Optional[str],
) -> List[_Allocation]:
    inventory_repo = InventoryRepository(db_path)
    store_repo = StoreRepository(db_path)
    allocations: List[_Allocation] = []

    if fulfillment_type == "pickup":
        if not store_id:
            raise CheckoutServiceError("store_required", "A pickup store is required before checkout.")
        store = store_repo.get_by_id(store_id)
        if store is None or not store.active or not store.pickup_enabled:
            raise CheckoutServiceError(
                "store_pickup_disabled", "The selected store is not currently available for pickup."
            )
        for product_id, quantity in item_quantities.items():
            record = inventory_repo.get_for_product_and_store(product_id, store_id)
            sellable = evaluate_availability(record).sellable_quantity
            if sellable < quantity:
                raise CheckoutServiceError(
                    "insufficient_inventory",
                    "The selected pickup store no longer has enough inventory. Please review the cart.",
                )
            allocations.append(_Allocation(product_id=product_id, store_id=store_id, quantity=quantity))
        return allocations

    # Delivery may be split deterministically across active stores, ordered by
    # store_id (InventoryRepository.list_for_product already returns that order).
    for product_id, quantity in item_quantities.items():
        remaining = quantity
        for record in inventory_repo.list_for_product(product_id):
            store = store_repo.get_by_id(record.store_id)
            if store is None or not store.active:
                continue
            sellable = evaluate_availability(record).sellable_quantity
            take = min(sellable, remaining)
            if take > 0:
                allocations.append(
                    _Allocation(product_id=product_id, store_id=record.store_id, quantity=take)
                )
                remaining -= take
            if remaining == 0:
                break
        if remaining > 0:
            raise CheckoutServiceError(
                "insufficient_inventory",
                "The store network no longer has enough inventory for delivery. Please review the cart.",
            )
    return allocations


def _build_current_review(
    *,
    session_id: str,
    checkout_id: str,
    shipping_address: Optional[ShippingAddress],
    db_path: Optional[str],
) -> Tuple[CheckoutReview, List[_Allocation], str]:
    settings = get_settings()
    cart_repo = CartRepository(db_path)
    cart_record = cart_repo.get_active_cart_by_session(session_id)
    if cart_record is None:
        raise CheckoutServiceError("cart_not_found", "No active cart was found for this session.")

    cart = cart_service.validate_cart(session_id, db_path)
    if not cart.items:
        raise CheckoutServiceError("cart_empty", "Add at least one product before checkout.")
    if cart.validation_status != "valid":
        message = cart.warnings[0] if cart.warnings else "The cart is not valid for checkout."
        raise CheckoutServiceError("cart_invalid", message)
    if cart.fulfillment_type not in ("pickup", "delivery"):
        raise CheckoutServiceError(
            "fulfillment_required", "Choose pickup or delivery before checkout."
        )

    normalized_address: Optional[ShippingAddress]
    if cart.fulfillment_type == "delivery":
        if shipping_address is None:
            raise CheckoutServiceError(
                "shipping_address_required", "A shipping address is required for delivery."
            )
        normalized_address = shipping_address
    else:
        normalized_address = None

    product_repo = ProductRepository(db_path)
    promotion_repo = PromotionRepository(db_path)
    lines: List[CheckoutLineReview] = []
    subtotal = Decimal("0")
    merchandise_total = Decimal("0")
    item_quantities: Dict[str, int] = {}

    for cart_item in cart.items:
        product = product_repo.get_by_id(cart_item.product_id)
        if product is None:
            raise CheckoutServiceError(
                "product_not_found", "A product in the cart no longer exists in the catalog."
            )
        if not product.active:
            raise CheckoutServiceError(
                "product_inactive", f"{product.name} is no longer available for purchase."
            )
        promotions = promotion_repo.list_active(product_id=product.product_id)
        price_result = promotion_service.calculate_price(product, promotions)

        catalog_unit = _money(_decimal(product.price))
        charged_unit = _money(_decimal(price_result.final_price))
        line_subtotal = _money(catalog_unit * cart_item.quantity)
        line_total = _money(charged_unit * cart_item.quantity)
        line_discount = _money(max(line_subtotal - line_total, Decimal("0")))

        promotion_label: Optional[str] = None
        if price_result.applied_promotion_id:
            promotion = next(
                (p for p in promotions if p.promotion_id == price_result.applied_promotion_id), None
            )
            promotion_label = promotion.label if promotion else None

        lines.append(
            CheckoutLineReview(
                product_id=product.product_id,
                product_name=product.name,
                brand=product.brand,
                quantity=cart_item.quantity,
                catalog_unit_price=_as_float(catalog_unit),
                charged_unit_price=_as_float(charged_unit),
                line_subtotal=_as_float(line_subtotal),
                discount_total=_as_float(line_discount),
                line_total=_as_float(line_total),
                promotion_id=price_result.applied_promotion_id,
                promotion_label=promotion_label,
            )
        )
        subtotal += line_subtotal
        merchandise_total += line_total
        item_quantities[product.product_id] = cart_item.quantity

    subtotal = _money(subtotal)
    merchandise_total = _money(merchandise_total)
    discount_total = _money(max(subtotal - merchandise_total, Decimal("0")))

    if cart.fulfillment_type == "pickup":
        shipping_total = Decimal("0")
    elif merchandise_total >= _decimal(settings.free_shipping_threshold):
        shipping_total = Decimal("0")
    else:
        shipping_total = _money(_decimal(settings.flat_shipping_fee))

    tax_rate = _decimal(settings.checkout_tax_rate)
    # Prototype rule: tax applies to discounted merchandise, not shipping.
    tax_total = _money(merchandise_total * tax_rate)
    total = _money(merchandise_total + shipping_total + tax_total)

    allocations = _plan_allocations(
        fulfillment_type=cart.fulfillment_type,
        store_id=cart.store_id,
        item_quantities=item_quantities,
        db_path=db_path,
    )

    review = CheckoutReview(
        checkout_id=checkout_id,
        session_id=session_id,
        cart_id=cart_record.cart_id,
        cart_updated_at=cart.updated_at,
        fulfillment_type=cart.fulfillment_type,
        store_id=cart.store_id,
        store_name=cart.store_name,
        shipping_address=normalized_address,
        items=lines,
        subtotal=_as_float(subtotal),
        discount_total=_as_float(discount_total),
        merchandise_total=_as_float(merchandise_total),
        tax_rate=float(tax_rate),
        tax_total=_as_float(tax_total),
        shipping_total=_as_float(shipping_total),
        total=_as_float(total),
        currency=settings.checkout_currency,
        payment_provider=settings.payment_provider,
        warnings=list(cart.warnings),
    )
    return review, allocations, _review_hash(review)


def create_checkout_review(
    session_id: str,
    shipping_address: Optional[ShippingAddress] = None,
    db_path: Optional[str] = None,
) -> CheckoutReview:
    """Create and persist an immutable checkout review snapshot."""
    if not session_id or not session_id.strip():
        raise CheckoutServiceError("validation_error", "session_id must not be empty")

    checkout_id = str(uuid.uuid4())
    review, _allocations, review_hash = _build_current_review(
        session_id=session_id.strip(),
        checkout_id=checkout_id,
        shipping_address=shipping_address,
        db_path=db_path,
    )
    CheckoutRepository(db_path).create_session(
        CheckoutSessionWrite(
            checkout_id=review.checkout_id,
            session_id=review.session_id,
            cart_id=review.cart_id,
            fulfillment_type=review.fulfillment_type,
            store_id=review.store_id,
            shipping_address_json=(
                json.dumps(review.shipping_address.model_dump(mode="json"), sort_keys=True)
                if review.shipping_address is not None
                else None
            ),
            subtotal=review.subtotal,
            discount_total=review.discount_total,
            merchandise_total=review.merchandise_total,
            tax_total=review.tax_total,
            shipping_total=review.shipping_total,
            total=review.total,
            currency=review.currency,
            review_hash=review_hash,
            review_json=review.model_dump_json(),
        )
    )
    return review


def get_checkout_review(
    checkout_id: str, session_id: str, db_path: Optional[str] = None
) -> CheckoutReview:
    record = CheckoutRepository(db_path).get_session(checkout_id)
    if record is None or record.session_id != session_id:
        raise CheckoutServiceError(
            "checkout_not_found", "No checkout session was found for this customer session."
        )
    review = CheckoutReview.model_validate_json(record.review_json)
    return review.model_copy(update={"status": record.status})


def _build_order_confirmation(order_id: str, db_path: Optional[str]) -> OrderConfirmation:
    repo = CheckoutRepository(db_path)
    order = repo.get_order(order_id)
    payment = repo.get_payment_for_order(order_id)
    if order is None or payment is None:
        raise CheckoutServiceError("order_not_found", "The confirmed order could not be loaded.")

    reservations = repo.list_reservations(order_id)
    reservations_by_item: Dict[str, List[InventoryReservationSummary]] = {}
    store_repo = StoreRepository(db_path)
    for reservation in reservations:
        store = store_repo.get_by_id(reservation.store_id)
        reservations_by_item.setdefault(reservation.order_item_id, []).append(
            InventoryReservationSummary(
                store_id=reservation.store_id,
                store_name=store.store_name if store else None,
                quantity=reservation.quantity,
                status=reservation.status,
            )
        )

    items = [
        OrderItemConfirmation(
            order_item_id=item.order_item_id,
            product_id=item.product_id,
            product_name=item.product_name,
            brand=item.brand,
            quantity=item.quantity,
            catalog_unit_price=item.catalog_unit_price,
            charged_unit_price=item.charged_unit_price,
            line_subtotal=item.line_subtotal,
            discount_total=item.discount_total,
            line_total=item.line_total,
            promotion_id=item.promotion_id,
            promotion_label=item.promotion_label,
            reservations=reservations_by_item.get(item.order_item_id, []),
        )
        for item in repo.list_order_items(order_id)
    ]
    store = StoreRepository(db_path).get_by_id(order.store_id) if order.store_id else None
    return OrderConfirmation(
        order_id=order.order_id,
        checkout_id=order.checkout_id,
        session_id=order.session_id,
        status=order.status,
        fulfillment_type=order.fulfillment_type,
        store_id=order.store_id,
        store_name=store.store_name if store else None,
        shipping_address=(
            ShippingAddress.model_validate(order.shipping_address)
            if order.shipping_address is not None
            else None
        ),
        items=items,
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        merchandise_total=order.merchandise_total,
        tax_total=order.tax_total,
        shipping_total=order.shipping_total,
        total=order.total,
        currency=order.currency,
        payment=PaymentConfirmation(
            provider=payment.provider,
            provider_reference=payment.provider_reference,
            status=payment.status,
            amount=payment.amount,
            currency=payment.currency,
        ),
        created_at=order.created_at,
    )


def _build_commit_plan(
    *,
    checkout_id: str,
    session_id: str,
    idempotency_key: str,
    payment_result: PaymentResult,
    review: CheckoutReview,
    allocations: List[_Allocation],
) -> CheckoutCommitPlan:
    order_id = str(uuid.uuid4())
    payment_id = str(uuid.uuid4())
    order_item_writes: List[OrderItemWrite] = []
    item_id_by_product: Dict[str, str] = {}
    for line in review.items:
        order_item_id = str(uuid.uuid4())
        item_id_by_product[line.product_id] = order_item_id
        order_item_writes.append(
            OrderItemWrite(
                order_item_id=order_item_id,
                product_id=line.product_id,
                product_name=line.product_name,
                brand=line.brand,
                quantity=line.quantity,
                catalog_unit_price=line.catalog_unit_price,
                charged_unit_price=line.charged_unit_price,
                line_subtotal=line.line_subtotal,
                discount_total=line.discount_total,
                line_total=line.line_total,
                promotion_id=line.promotion_id,
                promotion_label=line.promotion_label,
            )
        )

    reservations = [
        ReservationWrite(
            reservation_id=str(uuid.uuid4()),
            order_item_id=item_id_by_product[allocation.product_id],
            product_id=allocation.product_id,
            store_id=allocation.store_id,
            quantity=allocation.quantity,
        )
        for allocation in allocations
    ]

    now = datetime.now(timezone.utc)
    estimated_ready_at: Optional[str] = None
    estimated_delivery_at: Optional[str] = None
    settings = get_settings()
    if review.fulfillment_type == "pickup":
        estimated_ready_at = (now + timedelta(minutes=settings.order_pickup_ready_minutes)).isoformat()
    else:
        estimated_delivery_at = (
            now + timedelta(days=settings.standard_delivery_max_days)
        ).isoformat()

    return CheckoutCommitPlan(
        checkout_id=checkout_id,
        session_id=session_id,
        cart_id=review.cart_id,
        idempotency_key=idempotency_key,
        order_id=order_id,
        payment=PaymentWrite(
            payment_id=payment_id,
            provider=payment_result.provider,
            provider_reference=payment_result.provider_reference,
            status=payment_result.status,
            amount=payment_result.amount,
            currency=payment_result.currency,
        ),
        fulfillment_type=review.fulfillment_type,
        store_id=review.store_id,
        shipping_address_json=(
            json.dumps(review.shipping_address.model_dump(mode="json"), sort_keys=True)
            if review.shipping_address is not None
            else None
        ),
        subtotal=review.subtotal,
        discount_total=review.discount_total,
        merchandise_total=review.merchandise_total,
        tax_total=review.tax_total,
        shipping_total=review.shipping_total,
        total=review.total,
        currency=review.currency,
        estimated_ready_at=estimated_ready_at,
        estimated_delivery_at=estimated_delivery_at,
        items=order_item_writes,
        reservations=reservations,
    )


def _current_review_for_record(record, db_path: Optional[str]) -> Tuple[CheckoutReview, List[_Allocation], str]:
    stored_review = CheckoutReview.model_validate_json(record.review_json)
    return _build_current_review(
        session_id=record.session_id,
        checkout_id=record.checkout_id,
        shipping_address=stored_review.shipping_address,
        db_path=db_path,
    )


def create_checkout_payment_intent(
    *,
    checkout_id: str,
    session_id: str,
    idempotency_key: str,
    db_path: Optional[str] = None,
) -> CheckoutPaymentIntent:
    """Create a Stripe test PaymentIntent from server-calculated checkout totals."""
    settings = get_settings()
    if settings.payment_provider != "stripe_test":
        raise CheckoutServiceError("payment_provider_unavailable", "Stripe test payments are not enabled.")
    if not checkout_id.strip() or not session_id.strip() or not idempotency_key.strip():
        raise CheckoutServiceError("validation_error", "checkout_id, session_id, and idempotency_key are required.")

    repo = CheckoutRepository(db_path)
    record = repo.get_session(checkout_id.strip())
    if record is None or record.session_id != session_id.strip():
        raise CheckoutServiceError("checkout_not_found", "No checkout session was found for this customer session.")
    if record.status == "completed":
        order = repo.get_order_by_checkout(record.checkout_id)
        return CheckoutPaymentIntent(
            checkout_id=record.checkout_id,
            session_id=record.session_id,
            status="order_created",
            provider=record.payment_provider or "stripe_test",
            provider_reference=record.payment_intent_id or "",
            client_secret="",
            publishable_key=settings.stripe_publishable_key or "",
            amount=record.total,
            currency=record.currency,
        )
    if record.status not in {"review", "processing"}:
        raise CheckoutServiceError("checkout_not_confirmable", "This checkout is not available for payment.")

    current_review, _allocations, current_hash = _current_review_for_record(record, db_path)
    if current_hash != record.review_hash:
        raise CheckoutServiceError("checkout_changed", "The cart price, items, or fulfillment details changed. Create a new order review before paying.")
    currency = settings.stripe_currency.upper()
    if currency != current_review.currency.upper():
        raise CheckoutServiceError("payment_currency_mismatch", "Stripe currency must match checkout currency.")

    provider = get_payment_provider()
    if not hasattr(provider, "create_payment_intent"):
        raise CheckoutServiceError("payment_provider_unavailable", "The configured payment provider cannot create PaymentIntents.")
    try:
        result = provider.create_payment_intent(
            checkout_id=record.checkout_id,
            session_id=record.session_id,
            amount=current_review.total,
            currency=currency,
            idempotency_key=idempotency_key.strip(),
        )
    except PaymentServiceError as exc:
        raise CheckoutServiceError(exc.error_type, exc.message) from exc

    repo.attach_payment_intent(
        checkout_id=record.checkout_id,
        session_id=record.session_id,
        provider=result.provider,
        payment_intent_id=result.provider_reference,
        payment_status=result.status,
        idempotency_key=idempotency_key.strip(),
    )
    return CheckoutPaymentIntent(
        checkout_id=record.checkout_id,
        session_id=record.session_id,
        status=result.status,
        provider=result.provider,
        provider_reference=result.provider_reference,
        client_secret=result.client_secret,
        publishable_key=result.publishable_key,
        amount=result.amount,
        currency=result.currency,
    )


def get_checkout_payment_status(checkout_id: str, session_id: str, db_path: Optional[str] = None) -> CheckoutPaymentStatus:
    repo = CheckoutRepository(db_path)
    record = repo.get_session(checkout_id)
    if record is None or record.session_id != session_id:
        raise CheckoutServiceError("checkout_not_found", "No checkout session was found for this customer session.")
    order = repo.get_order_by_checkout(checkout_id)
    return CheckoutPaymentStatus(
        checkout_id=checkout_id,
        status=record.payment_status or "checkout_created",
        order_id=order.order_id if order else None,
    )


def confirm_checkout(
    *,
    checkout_id: str,
    session_id: str,
    idempotency_key: str,
    confirm_payment: bool,
    payment_method_token: str = MockPaymentAdapter.SUCCESS_TOKEN,
    db_path: Optional[str] = None,
) -> OrderConfirmation:
    """Explicitly confirm payment, create an order, and reserve inventory."""
    if get_settings().payment_provider == "stripe_test":
        raise CheckoutServiceError(
            "payment_provider_unavailable",
            "Stripe checkout must be completed through PaymentIntent confirmation and webhook.",
        )
    if not confirm_payment:
        raise CheckoutServiceError(
            "confirmation_required", "Explicit payment confirmation is required before placing the order."
        )
    if not idempotency_key or not idempotency_key.strip():
        raise CheckoutServiceError("idempotency_key_required", "An idempotency key is required.")
    if not checkout_id or not checkout_id.strip() or not session_id or not session_id.strip():
        raise CheckoutServiceError("validation_error", "checkout_id and session_id must not be empty")

    checkout_id = checkout_id.strip()
    session_id = session_id.strip()
    idempotency_key = idempotency_key.strip()
    repo = CheckoutRepository(db_path)

    prior = repo.find_idempotency(session_id, idempotency_key)
    if prior is not None:
        if prior.checkout_id != checkout_id:
            raise CheckoutServiceError(
                "idempotency_conflict", "That confirmation key was already used for another checkout."
            )
        if prior.order_id is not None:
            return _build_order_confirmation(prior.order_id, db_path)
        raise CheckoutServiceError(
            "checkout_processing", "This checkout confirmation is already being processed."
        )

    record = repo.get_session(checkout_id)
    if record is None or record.session_id != session_id:
        raise CheckoutServiceError(
            "checkout_not_found", "No checkout session was found for this customer session."
        )
    if record.status == "completed":
        existing_order = repo.get_order_by_checkout(checkout_id)
        if existing_order is not None and record.confirm_idempotency_key == idempotency_key:
            return _build_order_confirmation(existing_order.order_id, db_path)
        raise CheckoutServiceError("checkout_completed", "This checkout has already been completed.")
    if record.status != "review":
        raise CheckoutServiceError(
            "checkout_not_confirmable", "This checkout is not available for confirmation."
        )

    current_review, allocations, current_hash = _current_review_for_record(record, db_path)
    if current_hash != record.review_hash:
        raise CheckoutServiceError(
            "checkout_changed",
            "The cart price, items, or fulfillment details changed. Create a new order review before paying.",
        )

    adapter = MockPaymentAdapter(get_settings().mock_payment_provider)
    try:
        payment_result = adapter.charge(
            checkout_id=checkout_id,
            amount=current_review.total,
            currency=current_review.currency,
            payment_method_token=payment_method_token,
            idempotency_key=idempotency_key,
        )
    except PaymentServiceError as exc:
        raise CheckoutServiceError(exc.error_type, exc.message) from exc

    plan = _build_commit_plan(
        checkout_id=checkout_id,
        session_id=session_id,
        idempotency_key=idempotency_key,
        payment_result=payment_result,
        review=current_review,
        allocations=allocations,
    )
    try:
        repo.commit_checkout(plan)
    except CheckoutRepositoryConflict as exc:
        # A second request with the same idempotency key may have raced
        # with the first one and reached the repository before the first
        # commit became visible to the service-level pre-check. Re-read
        # after the conflict and return the already-created order when it
        # belongs to this checkout; otherwise preserve the safe conflict.
        prior_after_conflict = repo.find_idempotency(session_id, idempotency_key)
        if (
            prior_after_conflict is not None
            and prior_after_conflict.checkout_id == checkout_id
            and prior_after_conflict.order_id is not None
        ):
            return _build_order_confirmation(prior_after_conflict.order_id, db_path)
        raise CheckoutServiceError(exc.error_type, exc.message) from exc

    return _build_order_confirmation(plan.order_id, db_path)


def complete_stripe_checkout_from_event(event: WebhookEvent, db_path: Optional[str] = None) -> CheckoutPaymentStatus:
    """Finalize a Stripe checkout from a verified webhook event."""
    repo = CheckoutRepository(db_path)
    if not event.event_id:
        raise CheckoutServiceError("invalid_webhook_event", "Stripe webhook event is missing an id.")
    if repo.has_processed_webhook_event(event.event_id):
        checkout_id = event.checkout_id or ""
        if checkout_id:
            return get_checkout_payment_status(checkout_id, event.session_id or "", db_path)
        return CheckoutPaymentStatus(checkout_id="", status="already_processed", order_id=None)

    if event.event_type in {"payment_intent.payment_failed", "payment_intent.canceled", "payment_intent.processing"}:
        payment_status = {
            "payment_intent.payment_failed": "payment_failed",
            "payment_intent.canceled": "payment_canceled",
            "payment_intent.processing": "payment_processing",
        }[event.event_type]
        checkout_id = event.checkout_id or ""
        if checkout_id:
            repo.update_payment_status(checkout_id, payment_status)
        repo.record_webhook_event(
            event_id=event.event_id,
            event_type=event.event_type,
            checkout_id=checkout_id or None,
            payment_intent_id=event.payment_intent_id,
        )
        return CheckoutPaymentStatus(checkout_id=checkout_id, status=payment_status, order_id=None)

    if event.event_type != "payment_intent.succeeded":
        repo.record_webhook_event(
            event_id=event.event_id,
            event_type=event.event_type,
            checkout_id=event.checkout_id,
            payment_intent_id=event.payment_intent_id,
        )
        return CheckoutPaymentStatus(checkout_id=event.checkout_id or "", status="ignored", order_id=None)

    if not event.payment_intent_id:
        raise CheckoutServiceError("invalid_webhook_event", "Stripe webhook is missing a PaymentIntent id.")
    payment_session = repo.get_by_payment_intent(event.payment_intent_id)
    if payment_session is None:
        raise CheckoutServiceError("checkout_not_found", "No checkout session matches this PaymentIntent.")
    if event.checkout_id and event.checkout_id != payment_session.checkout_id:
        raise CheckoutServiceError("payment_checkout_mismatch", "Stripe checkout metadata does not match Scout checkout.")
    if event.session_id and event.session_id != payment_session.session_id:
        raise CheckoutServiceError("payment_session_mismatch", "Stripe session metadata does not match Scout checkout.")
    if event.amount is None or round(event.amount, 2) != round(payment_session.total, 2):
        raise CheckoutServiceError("payment_amount_mismatch", "Stripe amount does not match Scout checkout total.")
    if event.currency is None or event.currency.upper() != payment_session.currency.upper():
        raise CheckoutServiceError("payment_currency_mismatch", "Stripe currency does not match Scout checkout currency.")

    existing_order = repo.get_order_by_checkout(payment_session.checkout_id)
    if existing_order is not None:
        repo.record_webhook_event(
            event_id=event.event_id,
            event_type=event.event_type,
            checkout_id=payment_session.checkout_id,
            payment_intent_id=event.payment_intent_id,
        )
        return CheckoutPaymentStatus(
            checkout_id=payment_session.checkout_id,
            status="order_created",
            order_id=existing_order.order_id,
        )

    record = repo.get_session(payment_session.checkout_id)
    if record is None:
        raise CheckoutServiceError("checkout_not_found", "No checkout session matches this PaymentIntent.")
    current_review, allocations, current_hash = _current_review_for_record(record, db_path)
    if current_hash != record.review_hash:
        repo.update_payment_status(payment_session.checkout_id, "order_creation_failed")
        raise CheckoutServiceError("checkout_changed", "The cart changed before order creation.")

    plan = _build_commit_plan(
        checkout_id=payment_session.checkout_id,
        session_id=payment_session.session_id,
        idempotency_key=record.confirm_idempotency_key or event.payment_intent_id,
        payment_result=PaymentResult(
            provider="stripe_test",
            provider_reference=event.payment_intent_id,
            status="succeeded",
            amount=payment_session.total,
            currency=payment_session.currency,
        ),
        review=current_review,
        allocations=allocations,
    )
    try:
        repo.commit_checkout(plan)
    except CheckoutRepositoryConflict as exc:
        repo.update_payment_status(payment_session.checkout_id, "order_creation_failed")
        raise CheckoutServiceError(exc.error_type, exc.message) from exc
    repo.record_webhook_event(
        event_id=event.event_id,
        event_type=event.event_type,
        checkout_id=payment_session.checkout_id,
        payment_intent_id=event.payment_intent_id,
    )
    return CheckoutPaymentStatus(
        checkout_id=payment_session.checkout_id,
        status="order_created",
        order_id=plan.order_id,
    )
