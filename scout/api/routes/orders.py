"""Thin, read-only REST routes for Step 17 order status."""

from fastapi import APIRouter, Query

from scout.api.exceptions import ScoutAppError
from scout.api.schemas.orders import (
    FulfillmentStatus,
    OrderEligibility,
    OrderStatusOnly,
    OrderStatusView,
    PaymentStatus,
)
from scout.services import order_service
from scout.services.order_service import OrderServiceError

router = APIRouter(prefix="/orders", tags=["orders"])


def _app_error(exc: OrderServiceError) -> ScoutAppError:
    status = 404 if exc.error_type in {"order_not_found", "payment_not_found", "order_items_not_found"} else 400
    return ScoutAppError(exc.message, status_code=status, code=exc.error_type.upper())


@router.get("/latest", response_model=OrderStatusView)
def latest_order(session_id: str = Query(min_length=1, max_length=128)) -> OrderStatusView:
    try:
        return order_service.lookup_latest_order(session_id)
    except OrderServiceError as exc:
        raise _app_error(exc) from exc


@router.get("/{order_id}", response_model=OrderStatusView)
def order_details(
    order_id: str,
    session_id: str = Query(min_length=1, max_length=128),
) -> OrderStatusView:
    try:
        return order_service.lookup_order(order_id, session_id)
    except OrderServiceError as exc:
        raise _app_error(exc) from exc


@router.get("/{order_id}/status", response_model=OrderStatusOnly)
def order_status(
    order_id: str,
    session_id: str = Query(min_length=1, max_length=128),
) -> OrderStatusOnly:
    order = order_details(order_id, session_id)
    return OrderStatusOnly(order_id=order.order_id, order_status=order.order_status)


@router.get("/{order_id}/payment", response_model=PaymentStatus)
def payment_status(
    order_id: str,
    session_id: str = Query(min_length=1, max_length=128),
) -> PaymentStatus:
    return order_details(order_id, session_id).payment


@router.get("/{order_id}/fulfillment", response_model=FulfillmentStatus)
def fulfillment_details(
    order_id: str,
    session_id: str = Query(min_length=1, max_length=128),
) -> FulfillmentStatus:
    return order_details(order_id, session_id).fulfillment


@router.get("/{order_id}/eligibility", response_model=OrderEligibility)
def order_eligibility(
    order_id: str,
    session_id: str = Query(min_length=1, max_length=128),
) -> OrderEligibility:
    return order_details(order_id, session_id).eligibility
