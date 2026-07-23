"""Public Step 17 order-status response schemas."""

from pydantic import BaseModel

from scout.services.order_service import (
    FulfillmentStatus,
    OrderEligibility,
    OrderStatusView,
    PaymentStatus,
)

class OrderStatusOnly(BaseModel):
    order_id: str
    order_status: str


__all__ = [
    "OrderStatusOnly",
    "OrderStatusView",
    "PaymentStatus",
    "FulfillmentStatus",
    "OrderEligibility",
]
