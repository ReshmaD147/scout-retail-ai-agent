"""Deterministic, read-only order status and eligibility service (Step 17).

The service combines the immutable Step 16 order/payment/item snapshots with
optional fulfillment/tracking facts. It never performs cancellation, return,
exchange, or refund writes; it only reports eligibility using configured,
testable rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel

from scout.config import get_settings
from scout.repositories.order_repository import OrderRepository
from scout.repositories.store_repository import StoreRepository
from scout.services.checkout_service import ShippingAddress


class OrderServiceError(Exception):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class OrderItemStatus(BaseModel):
    order_item_id: str
    product_id: str
    product_name: str
    brand: str
    quantity: int
    charged_unit_price: float
    line_total: float


class PaymentStatus(BaseModel):
    status: str
    provider: str
    provider_reference: str
    amount: float
    currency: str
    paid_at: str


class TrackingInformation(BaseModel):
    available: bool
    carrier_name: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    message: str


class FulfillmentStatus(BaseModel):
    fulfillment_type: Literal["pickup", "delivery"]
    status: str
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    shipping_address: Optional[ShippingAddress] = None
    estimated_ready_at: Optional[str] = None
    estimated_delivery_at: Optional[str] = None
    estimate_source: Literal["configured_policy", "persisted_tracking"]
    tracking: TrackingInformation


class EligibilityCheck(BaseModel):
    eligible: bool
    reason: str
    deadline: Optional[str] = None


class OrderEligibility(BaseModel):
    cancellation: EligibilityCheck
    return_eligibility: EligibilityCheck
    exchange: EligibilityCheck


class OrderStatusView(BaseModel):
    order_id: str
    session_id: str
    order_status: str
    created_at: str
    items: List[OrderItemStatus]
    subtotal: float
    discount_total: float
    tax_total: float
    shipping_total: float
    total: float
    currency: str
    payment: PaymentStatus
    fulfillment: FulfillmentStatus
    eligibility: OrderEligibility


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _default_fulfillment(order, now: datetime) -> FulfillmentStatus:
    settings = get_settings()
    created = _parse_datetime(order.created_at)
    if order.fulfillment_type == "pickup":
        estimate = created + timedelta(minutes=settings.order_pickup_ready_minutes)
        return FulfillmentStatus(
            fulfillment_type="pickup",
            status="processing",
            store_id=order.store_id,
            shipping_address=None,
            estimated_ready_at=_iso(estimate),
            estimated_delivery_at=None,
            estimate_source="configured_policy",
            tracking=TrackingInformation(
                available=False,
                message="Tracking is not used for pickup orders.",
            ),
        )
    estimate = created + timedelta(days=settings.standard_delivery_max_days)
    return FulfillmentStatus(
        fulfillment_type="delivery",
        status="processing",
        store_id=None,
        shipping_address=order.shipping_address,
        estimated_ready_at=None,
        estimated_delivery_at=_iso(estimate),
        estimate_source="configured_policy",
        tracking=TrackingInformation(
            available=False,
            message="A carrier tracking number has not been assigned yet.",
        ),
    )


def _build_fulfillment(order, repository: OrderRepository, db_path: Optional[str], now: datetime) -> FulfillmentStatus:
    record = repository.get_fulfillment(order.order_id)
    if record is None:
        view = _default_fulfillment(order, now)
    else:
        tracking_available = bool(record.carrier_name and record.tracking_number)
        view = FulfillmentStatus(
            fulfillment_type=order.fulfillment_type,
            status=record.fulfillment_status,
            store_id=order.store_id if order.fulfillment_type == "pickup" else None,
            shipping_address=order.shipping_address if order.fulfillment_type == "delivery" else None,
            estimated_ready_at=record.estimated_ready_at,
            estimated_delivery_at=record.estimated_delivery_at,
            estimate_source=(
                "persisted_tracking"
                if record.tracking_number or record.shipped_at or record.delivered_at
                else "configured_policy"
            ),
            tracking=TrackingInformation(
                available=tracking_available,
                carrier_name=record.carrier_name,
                tracking_number=record.tracking_number,
                tracking_url=record.tracking_url,
                message=(
                    "Carrier tracking is available."
                    if tracking_available
                    else (
                        "Tracking is not used for pickup orders."
                        if order.fulfillment_type == "pickup"
                        else "A carrier tracking number has not been assigned yet."
                    )
                ),
            ),
        )
    if view.store_id:
        store = StoreRepository(db_path).get_by_id(view.store_id)
        view.store_name = store.store_name if store is not None else None
    return view


def _eligibility(order, fulfillment: FulfillmentStatus, now: datetime, completion_at: Optional[str]) -> OrderEligibility:
    settings = get_settings()
    created = _parse_datetime(order.created_at)
    cancel_deadline = created + timedelta(minutes=settings.order_cancellation_window_minutes)
    cancelable_status = fulfillment.status == "processing"
    cancel_eligible = cancelable_status and now <= cancel_deadline
    if cancel_eligible:
        cancel_reason = "The order is still processing and is within the cancellation review window."
    elif not cancelable_status:
        cancel_reason = "The order has progressed too far for cancellation through the current policy."
    else:
        cancel_reason = "The cancellation review window has passed."

    completed = _parse_datetime(completion_at) if completion_at else None
    return_deadline = completed + timedelta(days=settings.order_return_window_days) if completed else None
    exchange_deadline = completed + timedelta(days=settings.order_exchange_window_days) if completed else None
    completed_status = fulfillment.status in {"delivered", "picked_up"}
    return_eligible = bool(completed_status and return_deadline and now <= return_deadline)
    exchange_eligible = bool(completed_status and exchange_deadline and now <= exchange_deadline)

    return OrderEligibility(
        cancellation=EligibilityCheck(
            eligible=cancel_eligible,
            reason=cancel_reason,
            deadline=_iso(cancel_deadline),
        ),
        return_eligibility=EligibilityCheck(
            eligible=return_eligible,
            reason=(
                "The completed order is within the return eligibility window."
                if return_eligible
                else (
                    "The return eligibility window has passed."
                    if completed_status and return_deadline and now > return_deadline
                    else "Returns become eligible after delivery or pickup."
                )
            ),
            deadline=_iso(return_deadline) if return_deadline else None,
        ),
        exchange=EligibilityCheck(
            eligible=exchange_eligible,
            reason=(
                "The completed order is within the exchange eligibility window."
                if exchange_eligible
                else (
                    "The exchange eligibility window has passed."
                    if completed_status and exchange_deadline and now > exchange_deadline
                    else "Exchanges become eligible after delivery or pickup."
                )
            ),
            deadline=_iso(exchange_deadline) if exchange_deadline else None,
        ),
    )


def _build_view(order, db_path: Optional[str], as_of: Optional[datetime]) -> OrderStatusView:
    repository = OrderRepository(db_path)
    payment = repository.get_payment(order.order_id)
    if payment is None:
        raise OrderServiceError("payment_not_found", "Payment status could not be found for this order.")
    items = repository.list_items(order.order_id)
    if not items:
        raise OrderServiceError("order_items_not_found", "No order items could be found for this order.")

    now = as_of or datetime.now(timezone.utc)
    fulfillment_record = repository.get_fulfillment(order.order_id)
    fulfillment = _build_fulfillment(order, repository, db_path, now)
    completion_at = None
    if fulfillment_record is not None:
        completion_at = fulfillment_record.delivered_at or fulfillment_record.picked_up_at

    return OrderStatusView(
        order_id=order.order_id,
        session_id=order.session_id,
        order_status=order.status,
        created_at=order.created_at,
        items=[
            OrderItemStatus(
                order_item_id=item.order_item_id,
                product_id=item.product_id,
                product_name=item.product_name,
                brand=item.brand,
                quantity=item.quantity,
                charged_unit_price=item.charged_unit_price,
                line_total=item.line_total,
            )
            for item in items
        ],
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        tax_total=order.tax_total,
        shipping_total=order.shipping_total,
        total=order.total,
        currency=order.currency,
        payment=PaymentStatus(
            status=payment.status,
            provider=payment.provider,
            provider_reference=payment.provider_reference,
            amount=payment.amount,
            currency=payment.currency,
            paid_at=payment.created_at,
        ),
        fulfillment=fulfillment,
        eligibility=_eligibility(order, fulfillment, now, completion_at),
    )


def lookup_order(
    order_id: str,
    session_id: str,
    db_path: Optional[str] = None,
    as_of: Optional[datetime] = None,
) -> OrderStatusView:
    if not order_id or not order_id.strip():
        raise OrderServiceError("validation_error", "order_id must not be empty")
    if not session_id or not session_id.strip():
        raise OrderServiceError("validation_error", "session_id must not be empty")
    order = OrderRepository(db_path).get_by_id_for_session(order_id.strip(), session_id.strip())
    if order is None:
        raise OrderServiceError("order_not_found", "No order was found for that order number and session.")
    return _build_view(order, db_path, as_of)


def lookup_latest_order(
    session_id: str,
    db_path: Optional[str] = None,
    as_of: Optional[datetime] = None,
) -> OrderStatusView:
    if not session_id or not session_id.strip():
        raise OrderServiceError("validation_error", "session_id must not be empty")
    order = OrderRepository(db_path).get_latest_for_session(session_id.strip())
    if order is None:
        raise OrderServiceError("order_not_found", "No order was found for this shopping session.")
    return _build_view(order, db_path, as_of)
